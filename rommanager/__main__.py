"""
Entry point for running as module: python -m rommanager
"""

import sys
import argparse

def main():
    """Main entry point"""
    
    # 1. Check for explicit flags first (before parsing full CLI args)
    if '--flet' in sys.argv:
        from .gui_flet import run_flet_gui
        run_flet_gui()
        return

    if '--web' in sys.argv:
        from .web import run_server
        run_server()
        return

    if '--gui' in sys.argv:
        from .gui import run_gui
        run_gui()
        return

    # 2. Check if we have CLI arguments (like --dat, --roms, etc.)
    # We look for arguments that start with '-' but aren't the mode flags
    has_args = len(sys.argv) > 1
    
    if has_args:
        # If arguments exist, pass to CLI handler
        from .cli import run_cli
        sys.exit(run_cli())
    else:
        # 3. No arguments provided: Open the Launcher
        try:
            from .launcher import run_launcher
            run_launcher()
        except ImportError:
            # Fallback if launcher fails (e.g. missing deps), try GUI directly
            from .gui import run_gui, GUI_AVAILABLE
            if GUI_AVAILABLE:
                run_gui()
            else:
                # Fallback to CLI help
                print("GUI not available. Use --help for CLI usage.")

if __name__ == '__main__':
    main()
