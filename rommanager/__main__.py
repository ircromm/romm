"""Entry point for running as module: python -m rommanager"""

import sys

from .monitor import setup_runtime_monitor, monitor_action


def main():
    """Always open visual mode selector for module execution."""
    logger = setup_runtime_monitor()
    monitor_action("startup: module entry", logger=logger)
    monitor_action("mode selected: launcher (forced for python -m rommanager)", logger=logger)

    try:
        from .launcher import run_launcher
        run_launcher()
    except ImportError as exc:
        print(f"Launcher unavailable: {exc}")
        print("Use python main.py --help for CLI usage.")
        sys.exit(1)


if __name__ == '__main__':
    main()
