"""
Command-line interface for ROM Manager
"""

import argparse
import sys
import os
import logging

from .parser import DATParser
from .scanner import FileScanner
from .matcher import ROMMatcher, MultiROMMatcher
from .organizer import Organizer
from .collection import CollectionManager
from .reporter import MissingROMReporter
from .utils import format_size
from .monitor import setup_monitoring, log_event, tail_events


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser"""
    parser = argparse.ArgumentParser(
        prog='rommanager',
        description='ROM Collection Manager - Organize your ROMs using DAT files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Modes:
  %(prog)s              Launch the GUI Mode Selector (Launcher)
  %(prog)s --web        Start the Web Interface directly
  %(prog)s --gui        Start the Desktop App directly

Examples:
  %(prog)s --dat nointro.dat --roms ./roms --output ./organized
  %(prog)s --dat gba.dat --dat snes.dat --roms ./mixed --output ./sorted --strategy system+region
  %(prog)s --dat nointro.dat --roms ./roms --report missing --report-output missing.csv
  %(prog)s --dat nointro.dat --roms ./roms --output ./out --strategy 1g1r --dry-run
        '''
    )

    # Mode flags
    parser.add_argument('--web', action='store_true', help='Launch Web Interface')
    parser.add_argument('--gui', action='store_true', help='Launch Desktop GUI')

    # CLI Arguments group
    cli_group = parser.add_argument_group('CLI Operations')

    cli_group.add_argument(
        '--dat', '-d',
        type=str,
        action='append',
        help='Path to DAT file (can be specified multiple times for multi-DAT)'
    )

    cli_group.add_argument(
        '--roms', '-r',
        type=str,
        help='Path to ROMs folder to scan'
    )

    cli_group.add_argument(
        '--output', '-o',
        type=str,
        help='Path to output folder'
    )

    cli_group.add_argument(
        '--strategy', '-s',
        type=str,
        default='flat',
        help='Organization strategy. Options: system, 1g1r, region, alphabetical, '
             'emulationstation, flat. Use + for composites (e.g. system+region). Default: flat'
    )

    cli_group.add_argument(
        '--action', '-a',
        type=str,
        default='copy',
        choices=['copy', 'move'],
        help='Copy or move files (default: copy)'
    )

    cli_group.add_argument(
        '--no-archives',
        action='store_true',
        help='Do not scan inside ZIP archives'
    )

    cli_group.add_argument(
        '--no-recursive',
        action='store_true',
        help='Do not scan subdirectories'
    )

    cli_group.add_argument(
        '--download-delay', '-dd',
        type=int,
        default=0,
        help='Seconds to wait between downloads (0-60, default: 0)'
    )

    cli_group.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress progress output'
    )

    cli_group.add_argument(
        '--monitor',
        action='store_true',
        help='Enable realtime monitoring output while the app runs'
    )

    cli_group.add_argument(
        '--monitor-file',
        type=str,
        help='Custom monitor log file path (default: ~/.rommanager/events.log)'
    )

    cli_group.add_argument(
        '--monitor-tail',
        action='store_true',
        help='Tail monitor logs in realtime (no scan/organize action)'
    )

    cli_group.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview what organization would do without executing'
    )

    # Report options
    report_group = parser.add_argument_group('Report')

    report_group.add_argument(
        '--report',
        type=str,
        choices=['missing'],
        help='Generate a report (requires --dat and --roms)'
    )

    report_group.add_argument(
        '--report-output',
        type=str,
        help='Output file for report (.txt, .csv, or .json)'
    )

    # Collection options
    coll_group = parser.add_argument_group('Collections')

    coll_group.add_argument(
        '--save-collection',
        type=str,
        metavar='NAME',
        help='Save the current session as a named collection'
    )

    coll_group.add_argument(
        '--load-collection',
        type=str,
        metavar='PATH',
        help='Load a saved collection (.romcol.json) and display its info'
    )

    parser.add_argument(
        '--version', '-v',
        action='version',
        version='%(prog)s 2.0.0'
    )

    return parser


def run_cli(args=None):
    """Run the CLI"""
    parser = create_parser()
    args = parser.parse_args(args)

    setup_monitoring(log_file=args.monitor_file, echo=args.monitor)

    if args.monitor_tail:
        tail_events(log_file=args.monitor_file)
        return 0

    log_event('cli.start', 'CLI execution started')

    # Handle load-collection mode
    if args.load_collection:
        return _load_collection_mode(args)

    # Check if user tried to run CLI mode without required args
    if not (args.web or args.gui):
        if not args.dat or not args.roms:
            log_event('cli.error', 'Missing required arguments: --dat and --roms', logging.ERROR)
            parser.print_help()
            print("\nError: --dat and --roms are required for CLI mode.")
            return 1
        # --output is required unless just doing --report
        if not args.output and not args.report:
            log_event('cli.error', 'Missing required argument: --output', logging.ERROR)
            parser.print_help()
            print("\nError: --output is required for organizing (or use --report).")
            return 1

    quiet = args.quiet

    def log(msg):
        if not quiet:
            print(msg)

    log("ROM Collection Manager")
    log("=" * 50)

    # Load DAT(s)
    multi_matcher = MultiROMMatcher()
    all_dat_infos = []

    for dat_path in args.dat:
        log(f"\nLoading DAT: {dat_path}")
        log_event('dat.load.start', f'Loading DAT: {dat_path}')
        if not os.path.exists(dat_path):
            log_event('dat.load.error', f'DAT file not found: {dat_path}', logging.ERROR)
            print(f"Error: DAT file not found: {dat_path}", file=sys.stderr)
            return 1

        try:
            dat_info, roms = DATParser.parse_with_info(dat_path)
            multi_matcher.add_dat(dat_info, roms)
            all_dat_infos.append(dat_info)
            log_event('dat.load.done', f'Loaded DAT {dat_info.system_name} ({dat_info.rom_count} ROMs)')
            log(f"   System: {dat_info.system_name}")
            log(f"   ROMs in database: {dat_info.rom_count:,}")
        except Exception as e:
            log_event('dat.load.error', f'Failed to load DAT {dat_path}: {e}', logging.ERROR)
            print(f"Error: Failed to load DAT file: {e}", file=sys.stderr)
            return 1

    total_roms = sum(di.rom_count for di in all_dat_infos)
    if len(all_dat_infos) > 1:
        log(f"\nTotal DATs loaded: {len(all_dat_infos)} ({total_roms:,} ROMs)")

    # Scan files
    log(f"\nScanning: {args.roms}")
    if not os.path.exists(args.roms):
        log_event('scan.error', f'ROM folder not found: {args.roms}', logging.ERROR)
        print(f"Error: ROM folder not found: {args.roms}", file=sys.stderr)
        return 1

    scan_archives = not args.no_archives
    recursive = not args.no_recursive

    def progress_callback(current, total):
        if not quiet:
            print(f"   Scanning: {current:,} / {total:,}...", end='\r')

    log_event('scan.start', f'Scanning folder: {args.roms}')
    scanned_files = FileScanner.scan_folder(
        args.roms,
        recursive=recursive,
        scan_archives=scan_archives,
        progress_callback=progress_callback if not quiet else None
    )

    if not quiet:
        print()

    log(f"   Found {len(scanned_files):,} files")
    log_event('scan.done', f'Found {len(scanned_files)} files')

    # Match files
    identified, unidentified = multi_matcher.match_all(scanned_files)
    log_event('match.done', f'Identified={len(identified)} Unidentified={len(unidentified)}')

    total = len(identified) + len(unidentified)
    percent = (len(identified) / total * 100) if total > 0 else 0

    log(f"\nResults:")
    log(f"   Identified: {len(identified):,} ({percent:.1f}%)")
    log(f"   Unidentified: {len(unidentified):,}")

    # Per-system breakdown if multi-DAT
    if len(all_dat_infos) > 1:
        completeness = multi_matcher.get_completeness_by_dat(identified)
        log("\n   Per-system:")
        for dat_id, stats in completeness.items():
            log(f"     {stats['system_name']}: "
                f"{stats['found']}/{stats['total_in_dat']} "
                f"({stats['percentage']:.1f}%)")

    # Handle report mode
    if args.report == 'missing':
        return _generate_report(args, multi_matcher, all_dat_infos, identified, log)

    # Save collection if requested
    if args.save_collection:
        _save_collection(args, all_dat_infos, identified, unidentified, log)

    if not args.output:
        return 0

    if not identified:
        log("\nNo ROMs identified. Nothing to organize.")
        return 0

    total_size = sum(f.size for f in identified)
    log(f"   Total size: {format_size(total_size)}")

    # Dry-run mode
    if args.dry_run:
        log_event('organize.dry_run', 'Dry-run preview requested')
        return _dry_run(args, identified, log)

    # Organize
    log(f"\nOrganizing:")
    log(f"   Strategy: {args.strategy}")
    log(f"   Action: {args.action}")
    log(f"   Output: {args.output}")

    organizer = Organizer()
    log_event('organize.start', f'Strategy={args.strategy} Action={args.action} Output={args.output}')

    def org_progress(current, total):
        if not quiet:
            print(f"   Processing: {current:,} / {total:,}...", end='\r')

    actions = organizer.organize(
        identified,
        args.output,
        args.strategy,
        args.action,
        progress_callback=org_progress if not quiet else None
    )

    if not quiet:
        print()

    log(f"\nDone! Organized {len(actions):,} ROMs")
    log_event('organize.done', f'Organized {len(actions)} ROMs')

    # Save collection if requested
    if args.save_collection:
        _save_collection(args, all_dat_infos, identified, unidentified, log)

    return 0


def _generate_report(args, multi_matcher, all_dat_infos, identified, log):
    """Generate missing ROM report."""
    reporter = MissingROMReporter()

    if len(all_dat_infos) == 1:
        dat_info = all_dat_infos[0]
        roms = list(multi_matcher.all_roms.values())[0]
        report = reporter.generate_report(dat_info, roms, identified)
    else:
        report = reporter.generate_multi_report(
            multi_matcher.dat_infos,
            multi_matcher.all_roms,
            identified
        )

    # Output report
    if args.report_output:
        ext = os.path.splitext(args.report_output)[1].lower()
        if ext == '.csv':
            reporter.export_csv(report, args.report_output)
        elif ext == '.json':
            reporter.export_json(report, args.report_output)
        else:
            reporter.export_txt(report, args.report_output)
        log(f"\nReport saved to: {args.report_output}")
    else:
        # Print to stdout
        if 'by_dat' in report:
            print(f"\n=== Missing ROM Report ===")
            print(f"Overall: {report['found_in_all']}/{report['total_in_all_dats']} "
                  f"({report['overall_percentage']:.1f}%)")
            print(f"Missing: {report['missing_in_all']}")
            for dat_report in report['by_dat'].values():
                print(f"\n--- {dat_report['dat_name']} ---")
                print(f"Found: {dat_report['found']}/{dat_report['total_in_dat']} "
                      f"({dat_report['percentage']:.1f}%)")
                for m in dat_report['missing'][:20]:
                    print(f"  {m['name']} [{m['region']}]")
                if len(dat_report['missing']) > 20:
                    print(f"  ... and {len(dat_report['missing']) - 20} more")
        else:
            print(f"\n=== Missing ROM Report: {report['dat_name']} ===")
            print(f"Found: {report['found']}/{report['total_in_dat']} "
                  f"({report['percentage']:.1f}%)")
            print(f"Missing: {report['missing_count']}")
            for m in report['missing'][:50]:
                print(f"  {m['name']} [{m['region']}]")
            if len(report['missing']) > 50:
                print(f"  ... and {len(report['missing']) - 50} more")

    return 0


def _dry_run(args, identified, log):
    """Preview what organization would do."""
    organizer = Organizer()
    plan = organizer.preview(identified, args.output, args.strategy, args.action)

    log(f"\n=== Dry Run Preview ===")
    log(f"Strategy: {plan.strategy_description}")
    log(f"Files: {plan.total_files:,}")
    log(f"Total size: {format_size(plan.total_size)}")
    log(f"\nPlanned actions:")

    for action in plan.actions[:30]:
        src = os.path.basename(action.source)
        dst = os.path.relpath(action.destination, args.output)
        log(f"  [{action.action_type}] {src} -> {dst}")

    if len(plan.actions) > 30:
        log(f"  ... and {len(plan.actions) - 30} more")

    return 0


def _save_collection(args, dat_infos, identified, unidentified, log):
    """Save current session as a collection."""
    from .models import Collection
    from datetime import datetime

    collection = Collection(
        name=args.save_collection,
        created_at=datetime.now().isoformat(),
        dat_infos=dat_infos,
        dat_filepaths=[d.filepath for d in dat_infos],
        scan_folder=args.roms,
        scan_options={
            'recursive': not args.no_recursive,
            'scan_archives': not args.no_archives,
        },
        identified=[f.to_dict() for f in identified],
        unidentified=[f.to_dict() for f in unidentified],
        settings={
            'strategy': args.strategy,
            'action': args.action,
            'output': args.output or '',
        },
    )

    manager = CollectionManager()
    filepath = manager.save(collection)
    log(f"\nCollection saved: {filepath}")


def _load_collection_mode(args):
    """Load and display a saved collection."""
    manager = CollectionManager()
    try:
        collection = manager.load(args.load_collection)
        print(f"Collection: {collection.name}")
        print(f"Created: {collection.created_at}")
        print(f"Updated: {collection.updated_at}")
        print(f"DATs: {len(collection.dat_infos)}")
        for di in collection.dat_infos:
            print(f"  - {di.name} ({di.rom_count:,} ROMs)")
        print(f"Scan folder: {collection.scan_folder}")
        print(f"Identified: {len(collection.identified):,}")
        print(f"Unidentified: {len(collection.unidentified):,}")
        return 0
    except Exception as e:
        print(f"Error loading collection: {e}", file=sys.stderr)
        return 1


def main():
    """Entry point"""
    sys.exit(run_cli())


if __name__ == '__main__':
    main()
