import importlib.util
import os
import pwd
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def input_setup(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/setup_input.py"
    spec = importlib.util.spec_from_file_location("setup_input", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=1000, pw_name=name)
    )
    return module


def test_setup_preserves_other_groups_and_configuration(input_setup, tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(input_setup, "run", lambda args, **kwargs: commands.append(args))
    existing = tmp_path / "etc/udev/rules.d/99-moonlight.rules"
    existing.parent.mkdir(parents=True)
    existing.write_text("existing Moonlight rules\n")

    input_setup.configure_input("desktop-user", root=tmp_path)
    input_setup.configure_input("desktop-user", root=tmp_path)

    assert existing.read_text() == "existing Moonlight rules\n"
    rules = tmp_path / "etc/udev/rules.d/99-automater.rules"
    assert rules.read_text() == input_setup.RULES
    assert rules.stat().st_mode & 0o777 == 0o644
    assert 'MODE="0660"' in rules.read_text() and 'MODE="0666"' not in rules.read_text()
    assert (tmp_path / "etc/modules-load.d/automater.conf").read_text() == "uinput\n"
    assert ["usermod", "-aG", "input", "--", "desktop-user"] in commands
    assert ["modprobe", "uinput"] in commands
    triggers = [args for args in commands if args[:2] == ["udevadm", "trigger"]]
    assert triggers
    assert all(any(arg.startswith("--subsystem-match=") for arg in args) for args in triggers)
    assert not list(tmp_path.rglob(".automater-*"))


def test_root_account_is_rejected_before_changes(input_setup, tmp_path, monkeypatch):
    monkeypatch.setattr(
        input_setup.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=0, pw_name=name)
    )
    monkeypatch.setattr(input_setup, "run", lambda *args, **kwargs: pytest.fail("system change"))
    with pytest.raises(ValueError, match="regular desktop account"):
        input_setup.configure_input("root", root=tmp_path)
    assert not list(tmp_path.iterdir())


def test_unknown_account_is_rejected_before_changes(input_setup, tmp_path, monkeypatch):
    def missing(name):
        raise KeyError(name)

    monkeypatch.setattr(input_setup.pwd, "getpwnam", missing)
    monkeypatch.setattr(input_setup, "run", lambda *args, **kwargs: pytest.fail("system change"))
    with pytest.raises(KeyError):
        input_setup.configure_input("missing-user", root=tmp_path)
    assert not list(tmp_path.iterdir())


def test_failed_config_replace_keeps_previous_file(input_setup, tmp_path, monkeypatch):
    target = tmp_path / "99-automater.rules"
    target.write_text("previous rules\n")

    def fail(*args):
        raise OSError("Read-only filesystem")

    monkeypatch.setattr(input_setup.os, "replace", fail)
    with pytest.raises(OSError, match="Read-only"):
        input_setup.write_config(target, "replacement rules\n")
    assert target.read_text() == "previous rules\n"
    assert list(tmp_path.iterdir()) == [target]


def test_module_failure_stops_before_udev_reload(input_setup, tmp_path, monkeypatch):
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        if args[0] == "modprobe":
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(input_setup, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        input_setup.configure_input("desktop-user", root=tmp_path)
    assert not any(args[0] == "udevadm" for args in commands)


def test_helper_requires_root_before_changes(input_setup, monkeypatch, capsys):
    monkeypatch.setattr(input_setup.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(sys, "argv", ["setup_input.py", "desktop-user"])
    monkeypatch.setattr(input_setup, "configure_input", lambda *args: pytest.fail("system change"))
    with pytest.raises(SystemExit) as exc:
        input_setup.main()
    assert exc.value.code == 1
    assert "Run ./install.sh as your regular user" in capsys.readouterr().err


def test_helper_reports_failure_without_claiming_success(input_setup, monkeypatch, capsys):
    monkeypatch.setattr(input_setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["setup_input.py", "desktop-user"])

    def fail(*args):
        raise subprocess.CalledProcessError(1, ["modprobe", "uinput"])

    monkeypatch.setattr(input_setup, "configure_input", fail)
    with pytest.raises(SystemExit) as exc:
        input_setup.main()
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert "Input setup failed" in output.err
    assert "--no-input-permissions" in output.err
    assert "Input access configured" not in output.out


@pytest.mark.parametrize("permission_result", [0, 42])
def test_installer_configures_current_user_before_menu_registration(tmp_path, permission_result):
    if os.geteuid() == 0:
        pytest.skip("The installer runs as a desktop user")
    root = Path(__file__).resolve().parents[1]
    checkout = tmp_path / "Automater install"
    (checkout / ".venv/bin").mkdir(parents=True)
    shutil.copy(root / "install.sh", checkout / "install.sh")
    shutil.copytree(root / "src/automater/assets", checkout / "src/automater/assets")
    (checkout / "scripts").mkdir()
    shutil.copy(root / "scripts/launch.sh", checkout / "scripts/launch.sh")
    interpreter = checkout / ".venv/bin/python"
    interpreter.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' "$@"\n')
    interpreter.chmod(0o755)
    (checkout / "start.sh").write_text("#!/bin/sh\nexit 0\n")
    (checkout / "start.sh").chmod(0o755)
    tools = tmp_path / "bin"
    tools.mkdir()
    sudo = tools / "sudo"
    sudo.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" > "$AUTOMATER_SUDO_LOG"\nexit {permission_result}\n'
    )
    sudo.chmod(0o755)
    log = tmp_path / "sudo.log"
    result = subprocess.run(
        ["bash", str(checkout / "install.sh"), "--no-system-packages"],
        env={
            **os.environ,
            "PATH": str(tools) + os.pathsep + os.environ["PATH"],
            "AUTOMATER_SUDO_LOG": str(log),
            "XDG_DATA_HOME": str(tmp_path / "xdg"),
            "USER": "root",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert log.read_text().splitlines() == [
        "python3",
        "scripts/setup_input.py",
        pwd.getpwuid(os.geteuid()).pw_name,
    ]
    assert result.returncode == permission_result, result.stdout + result.stderr
    entry = tmp_path / "xdg/applications/io.github.onxzero.Automater.desktop"
    assert entry.exists() == (permission_result == 0)
    if permission_result == 0:
        assert "Automater is installed" in result.stdout
    else:
        assert "Automater is installed" not in result.stdout
