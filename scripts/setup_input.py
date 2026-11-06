"""Configure Linux input access for the desktop user during installation."""

import argparse
import os
import pwd
import tempfile
from pathlib import Path
from subprocess import CalledProcessError, run

RULES = """SUBSYSTEM=="misc", KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"
SUBSYSTEM=="input", KERNEL=="event*", GROUP="input", MODE="0660"
"""


def write_config(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".automater-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def configure_input(username, root=Path("/")):
    account = pwd.getpwnam(username)
    if account.pw_uid == 0:
        raise ValueError("Choose your regular desktop account, not root")

    run(["groupadd", "-f", "input"], check=True)
    run(["usermod", "-aG", "input", "--", account.pw_name], check=True)
    write_config(root / "etc/udev/rules.d/99-automater.rules", RULES)
    write_config(root / "etc/modules-load.d/automater.conf", "uinput\n")
    run(["modprobe", "uinput"], check=True)
    run(["udevadm", "control", "--reload-rules"], check=True)
    run(["udevadm", "trigger", "--action=add", "--subsystem-match=input"], check=True)
    run(
        ["udevadm", "trigger", "--action=add", "--subsystem-match=misc", "--sysname-match=uinput"],
        check=True,
    )
    run(["udevadm", "settle", "--timeout=10"], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user", help="The desktop account that will run Automater")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(1, "Run ./install.sh as your regular user; it uses sudo for input setup.\n")
    try:
        configure_input(args.user)
    except (KeyError, ValueError, OSError, CalledProcessError) as exc:
        parser.exit(
            1,
            f"Input setup failed: {exc}\n"
            "Fix the error and rerun ./install.sh, or use --no-input-permissions "
            "for editing and Test mode.\n",
        )
    print(f"Input access configured for {args.user}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
