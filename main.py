#!/usr/bin/env python3
"""
ROM Collection Manager
A tool for organizing ROM collections using DAT files.

Usage:
    Launcher: python main.py           (default)
    Flet GUI: python main.py --flet
    Tkinter:  python main.py --gui
    Web Mode: python main.py --web
    CLI Mode: python main.py --dat <file> --roms <folder> --output <folder>

For CLI help: python main.py --help
"""

import sys
import os

# Add package to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rommanager import __version__
from rommanager.monitor import setup_runtime_monitor, monitor_action


def main():
    """Main entry point"""
    logger = setup_runtime_monitor()
    monitor_action("startup: main.py entry", logger=logger)
    # Check for --web flag
    if '--web' in sys.argv:
        monitor_action('mode selected: web', logger=logger)
        # Get optional host and port
        host = '127.0.0.1'
        port = 5000

        for i, arg in enumerate(sys.argv):
            if arg == '--host' and i + 1 < len(sys.argv):
                host = sys.argv[i + 1]
            elif arg == '--port' and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])

        try:
            from rommanager.web import run_server
            run_server(host, port)
        except ImportError as e:
            print("Error: Flask is required for web interface")
            print("Install it with: pip install flask")
            print(f"\nDetails: {e}")
            sys.exit(1)
        return

    # Check for --gui flag (legacy tkinter)
    if '--gui' in sys.argv:
        monitor_action('mode selected: tkinter', logger=logger)
        from rommanager.gui import run_gui, GUI_AVAILABLE
        if GUI_AVAILABLE:
            sys.exit(run_gui())
        else:
            print("tkinter not available. Use --flet or --web instead.")
            sys.exit(1)
        return

    # Check for --flet flag
    if '--flet' in sys.argv:
        monitor_action('mode selected: flet', logger=logger)
        try:
            from rommanager.gui_flet import run_flet_gui
            sys.exit(run_flet_gui())
        except ImportError as e:
            print(f"Error: Flet is required for the desktop interface")
            print("Install it with: pip install flet")
            print(f"\nDetails: {e}")
            sys.exit(1)
        return

    if len(sys.argv) == 1:
        monitor_action('mode selected: launcher', logger=logger)
        try:
            from rommanager.launcher import run_launcher
            run_launcher()
            return
        except Exception as e:
            print(f"Warning: launcher failed ({e}). Falling back to CLI help.")

    if len(sys.argv) > 1 and sys.argv[1] not in ('-h', '--help'):
        monitor_action('mode selected: cli', logger=logger)
        # CLI mode
        from rommanager.cli import run_cli
        sys.exit(run_cli())
    else:
        # Show help
        from rommanager.cli import run_cli
        sys.exit(run_cli())


if __name__ == '__main__':
    main()
