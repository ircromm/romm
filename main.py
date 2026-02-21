#!/usr/bin/env python3
"""
ROM Collection Manager
A tool for organizing ROM collections using DAT files.

Usage:
    GUI Mode:  python main.py
    Web Mode:  python main.py --web
    CLI Mode:  python main.py --dat <file> --roms <folder> --output <folder>

For CLI help: python main.py --help
"""

import os
import sys

# Add package to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rommanager import __version__


def main():
    """Main entry point"""
    if "--web" in sys.argv:
        host = "127.0.0.1"
        port = 5000

        for i, arg in enumerate(sys.argv):
            if arg == "--host" and i + 1 < len(sys.argv):
                host = sys.argv[i + 1]
            elif arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])

        try:
            from rommanager.web import run_server

            run_server(host, port)
        except ImportError as exc:
            print("Error: Flask is required for web interface")
            print("Install it with: pip install flask")
            print(f"\nDetails: {exc}")
            sys.exit(1)
        return

    if len(sys.argv) > 1 and sys.argv[1] not in ("-h", "--help"):
        from rommanager.cli import run_cli

        sys.exit(run_cli())
    elif len(sys.argv) == 1:
        try:
            from rommanager.gui_flet import run_gui

            sys.exit(run_gui())
        except ImportError as exc:
            print(f"ROM Collection Manager v{__version__}")
            print("=" * 40)
            print("\nGUI not available (flet not installed)")
            print("\nOptions:")
            print("  Web mode: python main.py --web")
            print("  CLI mode: python main.py --dat <file> --roms <folder> --output <folder>")
            print("\nFor help: python main.py --help")
            print(f"\nDetails: {exc}")
            sys.exit(0)
    else:
        from rommanager.cli import run_cli

        sys.exit(run_cli())


if __name__ == "__main__":
    main()
