import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="Automater input recorder and visual editor")
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
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("Automater supports Linux only.")
    if args.check_portal and not args.doctor:
        parser.error("--check-portal must be used with --doctor")
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
