"""Entry point for running as module: python -m rommanager."""

import sys


def main():
    """Main entry point."""
    if "--web" in sys.argv:
        from .web import run_server

        run_server()
        return

    if "--gui" in sys.argv:
        from .gui_flet import run_gui

        run_gui()
        return

    has_args = len(sys.argv) > 1

    if has_args:
        from .cli import run_cli

        sys.exit(run_cli())

    from .gui_flet import run_gui

    run_gui()


if __name__ == "__main__":
    main()
