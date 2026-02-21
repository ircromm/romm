"""Entry point for running as module: python -m rommanager."""

import sys


def main():
    """Main entry point."""
    if len(sys.argv) == 1:
        from .launcher import run_launcher

        sys.exit(run_launcher())

    from .cli import run_cli

    sys.exit(run_cli())


if __name__ == "__main__":
    main()
