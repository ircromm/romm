#!/usr/bin/env python3
"""
ROM Collection Manager
A tool for organizing ROM collections using DAT files.

Usage:
    Launcher:  python main.py
    Web Mode:  python main.py --web
    CLI Mode:  python main.py --dat <file> --roms <folder> --output <folder>

For CLI help: python main.py --help
"""

import os
import sys

# Add package to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    """Main entry point."""
    if len(sys.argv) == 1:
        from rommanager.launcher import run_launcher

        sys.exit(run_launcher())

    from rommanager.cli import run_cli

    sys.exit(run_cli())


if __name__ == "__main__":
    main()
