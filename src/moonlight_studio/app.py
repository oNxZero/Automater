import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Moonlight Studio input recorder and visual editor"
    )
    parser.add_argument(
        "--demo", action="store_true", help="Load an example with input-free test mode"
    )
    parser.add_argument(
        "--doctor", action="store_true", help="Print Linux device diagnostics as JSON"
    )
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("This release supports Linux. Windows and macOS backends are planned.")
    if args.doctor:
        from .linux_input import diagnostics

        print(json.dumps(diagnostics(), indent=2))
        return 0
    from PySide6.QtWidgets import QApplication

    from .window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Moonlight Studio")
    app.setOrganizationName("Moonlight")
    window = MainWindow(demo=args.demo)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
