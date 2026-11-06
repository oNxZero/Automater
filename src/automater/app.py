import argparse
import json
import sys

from . import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(description="Automater input recorder and visual editor")
    parser.add_argument("--version", action="version", version=f"Automater {__version__}")
    parser.add_argument(
        "--demo", action="store_true", help="Load an example with input-free test mode"
    )
    parser.add_argument(
        "--doctor", action="store_true", help="Print Linux device diagnostics as JSON"
    )
    parser.add_argument(
        "--check-portal",
        action="store_true",
        help="With --doctor, check pointer portal interfaces without asking for permission",
    )
    commands = parser.add_subparsers(dest="command", title="commands")
    run = commands.add_parser("run", help="Run a saved workflow without opening the editor")
    run.add_argument("workflow", help="Path to a workflow JSON file")
    run.add_argument("--test", action="store_true", help="Preview timing without sending input")
    run.add_argument("--speed", type=float, default=1.0, help="Playback speed, 0.1–10 (default: 1)")
    run.add_argument("--repeat", type=int, default=1, help="Runs, or 0 until stopped (default: 1)")
    run.add_argument(
        "--countdown", type=float, default=0, help="Lead-in seconds, 0–30 (default: 0)"
    )
    run.add_argument(
        "--loop-gap", type=float, default=0.25, help="Seconds between runs (default: 0.25)"
    )
    run.add_argument("--no-start-position", action="store_true", help="Skip the saved cursor reset")
    run.add_argument("--quiet", action="store_true", help="Only print errors and warnings")
    commands.add_parser("stop", help="Stop the current CLI workflow and release held inputs")
    status = commands.add_parser("status", help="Show the current CLI workflow")
    status.add_argument("--json", action="store_true", help="Print status as JSON")
    pointer = commands.add_parser(
        "pointer", help="Set up or forget remembered Wayland pointer access"
    )
    pointer.add_argument("action", choices=("setup", "forget"))
    args = parser.parse_args(argv)
    if not sys.platform.startswith("linux"):
        parser.error("Automater supports Linux only.")
    if args.check_portal and not args.doctor:
        parser.error("--check-portal must be used with --doctor")
    if args.command:
        if args.demo or args.doctor or args.check_portal:
            parser.error("--demo and --doctor cannot be combined with a CLI command")
        from .cli import dispatch

        return dispatch(args)
    if args.doctor:
        from .linux_input import diagnostics

        report = diagnostics()
        if args.check_portal:
            from .portal_probe import probe

            report["pointer_portal"] = probe()
        print(json.dumps(report, indent=2))
        return 0
    from .compatibility import configure_qt_platform

    try:
        configure_qt_platform()
    except RuntimeError as exc:
        parser.error(str(exc))
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .desktop import APP_ID
    from .window import MainWindow

    app = QApplication([APP_ID])
    app.setApplicationName("Automater")
    app.setOrganizationName("oNxZero")
    app.setDesktopFileName("io.github.onxzero.Automater")
    window = MainWindow(demo=args.demo)
    window.show()
    QTimer.singleShot(0, window.offer_tutorial)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
