"""Entry point for running as module: python -m rommanager."""

import sys


def _run_gui_or_fallback() -> None:
    """Run Flet GUI when available, with graceful fallback messaging."""
    try:
        from .gui_flet import run_gui

        run_gui()
    except ImportError as exc:
        print("GUI not available (flet not installed).")
        print("Install it with: pip install flet")
        print(f"Details: {exc}")
        print("Use --help for CLI usage or --web for web interface.")


def main():
    """Main entry point."""
    if "--web" in sys.argv:
        from .web import run_server

        run_server()
        return

    if "--gui" in sys.argv:
        _run_gui_or_fallback()
        return

    has_args = len(sys.argv) > 1

    if has_args:
        from .cli import run_cli

        sys.exit(run_cli())

    _run_gui_or_fallback()


if __name__ == "__main__":
    main()
