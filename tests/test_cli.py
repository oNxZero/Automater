import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from automater import cli_control
from automater.app import main
from automater.models import Script, Step
from automater.storage import save


@pytest.fixture
def cli_environment(monkeypatch, tmp_path):
    with tempfile.TemporaryDirectory(prefix="automater-cli-test-") as runtime:
        monkeypatch.setenv("XDG_RUNTIME_DIR", runtime)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("QT_QPA_PLATFORM", "does-not-exist")
        yield dict(os.environ)


def command(*args, env=None, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "automater", *args],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
    )


def workflow(tmp_path, delay=20):
    path = tmp_path / "My workflow.json"
    save(
        Script("Example", steps=[Step(0, "key_down", "KEY_A"), Step(delay, "key_up", "KEY_A")]),
        path,
    )
    return path


def wait_for_run(process, phase=None):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if process.poll() is not None:
            pytest.fail(str(process.communicate()))
        status = cli_control.request("status")
        if status and (phase is None or status["phase"] == phase):
            return status
        time.sleep(0.01)
    pytest.fail("CLI runner did not become ready")


def test_test_mode_needs_no_qt_display_devices_or_preferences(cli_environment, tmp_path):
    path = workflow(tmp_path)
    before = path.read_bytes()
    code = """
import sys
from automater.app import main
result = main(sys.argv[1:])
assert not any(name.startswith('PySide6') for name in sys.modules)
raise SystemExit(result)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            "run",
            str(path),
            "--test",
            "--repeat",
            "2",
            "--loop-gap",
            "0",
        ],
        env=cli_environment,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert "Finished" in result.stdout
    assert path.read_bytes() == before
    assert not Path(cli_environment["XDG_CONFIG_HOME"]).exists()
    assert not (cli_control.runtime_directory() / "run.sock").exists()


@pytest.mark.parametrize(
    "arguments,code",
    [
        (["--speed", "0"], 1),
        (["--speed", "nan"], 1),
        (["--countdown", "31"], 1),
        (["--repeat", "-1"], 1),
        (["--loop-gap", "-1"], 1),
        (["--repeat", "many"], 2),
    ],
)
def test_bad_options_fail_without_starting(cli_environment, tmp_path, arguments, code):
    result = command("run", str(workflow(tmp_path)), "--test", *arguments, env=cli_environment)
    assert result.returncode == code
    assert "Traceback" not in result.stderr
    assert not (cli_control.runtime_directory() / "run.sock").exists()


@pytest.mark.parametrize(
    "content", ["{broken", '{"version":99}', '{"version":1,"name":"Empty","steps":[]}']
)
def test_invalid_or_empty_workflow_has_a_useful_error(cli_environment, tmp_path, content):
    path = tmp_path / "broken.json"
    path.write_text(content)
    result = command("run", str(path), "--test", env=cli_environment)
    assert result.returncode == 1
    assert result.stderr.startswith("Automater:")
    assert "Traceback" not in result.stderr
    assert not (cli_control.runtime_directory() / "run.sock").exists()


def test_missing_file_and_idle_control(cli_environment, tmp_path):
    assert (
        command("run", str(tmp_path / "missing.json"), "--test", env=cli_environment).returncode
        == 1
    )
    status = command("status", "--json", env=cli_environment)
    assert status.returncode == 0 and json.loads(status.stdout) == {"running": False}
    assert command("stop", env=cli_environment).returncode == 0


def test_status_stop_duplicate_run_and_restart(cli_environment, tmp_path):
    path = workflow(tmp_path, delay=3_600_000)
    process = subprocess.Popen(
        [sys.executable, "-m", "automater", "run", str(path), "--test", "--quiet"],
        env=cli_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        status = wait_for_run(process)
        assert status["pid"] == process.pid and status["workflow"] == str(path)
        report = command("status", "--json", env=cli_environment)
        assert json.loads(report.stdout)["test_mode"]
        duplicate = command("run", str(path), "--test", env=cli_environment)
        assert duplicate.returncode == 3
        assert "already running" in duplicate.stderr
        stopped = command("stop", env=cli_environment)
        assert stopped.returncode == 0, stopped.stderr
        assert process.wait(timeout=3) == 130
        assert cli_control.request("status") is None
        workflow(tmp_path, delay=0)
        assert command("run", str(path), "--test", env=cli_environment).returncode == 0
    finally:
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=5)


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_signals_cancel_countdown_and_remove_control_socket(cli_environment, tmp_path, signum):
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "automater",
            "run",
            str(workflow(tmp_path)),
            "--test",
            "--countdown",
            "30",
        ],
        env=cli_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for_run(process, "countdown")
        process.send_signal(signum)
        assert process.wait(timeout=3) == 128 + signum
        assert cli_control.request("status") is None
    finally:
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=5)


def test_cli_stop_releases_held_inputs_and_closes_backend(cli_environment, tmp_path, monkeypatch):
    from automater import linux_input

    events = []
    pressed = threading.Event()
    closed = []

    class Backend:
        def check(self):
            pass

        def send(self, step):
            events.append(step.action)
            if step.action == "key_down":
                pressed.set()

        def close(self):
            closed.append(True)

    monkeypatch.setattr(linux_input, "UInputBackend", Backend)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)

    def stop():
        assert pressed.wait(3)
        cli_control.request("stop")

    stopper = threading.Thread(target=stop)
    stopper.start()
    try:
        assert main(["run", str(workflow(tmp_path, delay=3_600_000)), "--quiet"]) == 130
    finally:
        stopper.join(3)
    assert events == ["key_down", "key_up"]
    assert closed == [True]


def test_backend_failure_is_reported_and_releases_run_lock(
    cli_environment, tmp_path, monkeypatch, capsys
):
    from automater import linux_input

    def denied():
        raise RuntimeError("Cannot write /dev/uinput")

    monkeypatch.setattr(linux_input, "UInputBackend", denied)
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    path = workflow(tmp_path)
    assert main(["run", str(path)]) == 1
    assert "Cannot write /dev/uinput" in capsys.readouterr().err
    assert cli_control.request("status") is None
    assert main(["run", str(path), "--test", "--quiet"]) == 0


def test_no_start_position_does_not_rewrite_workflow(cli_environment, tmp_path):
    path = workflow(tmp_path)
    content = json.loads(path.read_text())
    content.update(version=2, start={"x": 0, "y": 0, "settle_ms": 0, "space": "window"})
    path.write_text(json.dumps(content))
    before = path.read_bytes()
    result = command("run", str(path), "--test", "--no-start-position", env=cli_environment)
    assert result.returncode == 0, result.stderr
    assert path.read_bytes() == before


def test_installed_command_keeps_working_directory_and_quotes_paths(cli_environment, tmp_path):
    from automater.desktop import install_cli

    checkout = tmp_path / "User's apps = 100% $dollar `literal`"
    (checkout / ".venv/bin").mkdir(parents=True)
    (checkout / ".venv/bin/python").write_text(
        "#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' "$@"\n'
    )
    (checkout / ".venv/bin/python").chmod(0o755)
    (checkout / "scripts").mkdir()
    (checkout / "scripts/launch.sh").write_text("unused")
    (checkout / "src/automater/assets").mkdir(parents=True)
    (checkout / "src/automater/assets/automater.svg").write_text("<svg/>")
    launcher = install_cli(checkout, tmp_path / "bin")
    cwd = tmp_path / "Working directory"
    cwd.mkdir()
    path = workflow(cwd)
    result = subprocess.run(
        [str(launcher), "run", path.name, "--test", "--quiet"],
        cwd=cwd,
        env=cli_environment,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert launcher.stat().st_mode & 0o777 == 0o755
