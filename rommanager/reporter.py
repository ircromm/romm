"""
Missing ROM report generation and export.
"""

import csv
import json
import os
from typing import Dict, List

from .models import DATInfo, ROMInfo, ScannedFile
from .utils import format_size


class MissingROMReporter:
    """Generates missing ROM reports in various formats."""

    def generate_report(self, dat_info: DATInfo, all_roms: List[ROMInfo],
                       identified: List[ScannedFile]) -> Dict:
        """Generate a comprehensive missing ROM report for a single DAT."""
        found_keys = set()
        for f in identified:
            if f.matched_rom:
                key = (f.matched_rom.crc32.lower(), f.matched_rom.size)
                found_keys.add(key)

        missing = []
        for rom in all_roms:
            key = (rom.crc32.lower(), rom.size)
            if key not in found_keys:
                missing.append({
                    'name': rom.name,
                    'game_name': rom.game_name,
                    'region': rom.region,
                    'size': rom.size,
                    'size_formatted': format_size(rom.size),
                    'crc32': rom.crc32.upper(),
                    'md5': rom.md5.upper() if rom.md5 else '',
                    'sha1': rom.sha1.upper() if rom.sha1 else '',
                })

        total = len(all_roms)
        found = total - len(missing)
        percentage = (found / total * 100) if total > 0 else 0

        # Region breakdown of missing ROMs
        regions = {}
        for m in missing:
            r = m['region'] or 'Unknown'
            regions[r] = regions.get(r, 0) + 1

        return {
            'dat_name': dat_info.name,
            'system_name': dat_info.system_name,
            'total_in_dat': total,
            'found': found,
            'missing_count': len(missing),
            'percentage': percentage,
            'missing_by_region': regions,
            'missing': missing,
        }

    def generate_multi_report(self, dat_infos: Dict[str, DATInfo],
                             all_roms_by_dat: Dict[str, List[ROMInfo]],
                             identified: List[ScannedFile]) -> Dict:
        """Generate a combined report for multiple DATs."""
        reports = {}
        for dat_id, dat_info in dat_infos.items():
            roms = all_roms_by_dat.get(dat_id, [])
            dat_identified = [f for f in identified
                            if f.matched_rom and f.matched_rom.dat_id == dat_id]
            reports[dat_id] = self.generate_report(dat_info, roms, dat_identified)

        total_in_all = sum(r['total_in_dat'] for r in reports.values())
        found_in_all = sum(r['found'] for r in reports.values())
        missing_in_all = sum(r['missing_count'] for r in reports.values())

        return {
            'total_dats': len(reports),
            'total_in_all_dats': total_in_all,
            'found_in_all': found_in_all,
            'missing_in_all': missing_in_all,
            'overall_percentage': (found_in_all / total_in_all * 100) if total_in_all > 0 else 0,
            'by_dat': reports,
        }

    def export_txt(self, report: Dict, filepath: str) -> None:
        """Export report as plain text."""
        with open(filepath, 'w', encoding='utf-8') as f:
            if 'by_dat' in report:
                f.write("=== ROM Collection Missing Report ===\n\n")
                f.write(f"Total DATs: {report['total_dats']}\n")
                f.write(f"Overall: {report['found_in_all']}/{report['total_in_all_dats']} "
                       f"({report['overall_percentage']:.1f}%)\n")
                f.write(f"Missing: {report['missing_in_all']}\n\n")

                for dat_id, dat_report in report['by_dat'].items():
                    self._write_dat_report_txt(f, dat_report)
            else:
                self._write_dat_report_txt(f, report)

    def _write_dat_report_txt(self, f, report: Dict) -> None:
        """Write a single DAT report section to text file."""
        f.write(f"--- {report['dat_name']} ---\n")
        f.write(f"System: {report['system_name']}\n")
        f.write(f"Found: {report['found']}/{report['total_in_dat']} "
               f"({report['percentage']:.1f}%)\n")
        f.write(f"Missing: {report['missing_count']}\n")

        if report['missing_by_region']:
            f.write("Missing by region:\n")
            for region, count in sorted(report['missing_by_region'].items()):
                f.write(f"  {region}: {count}\n")

        f.write("\nMissing ROMs:\n")
        for m in report['missing']:
            f.write(f"  {m['name']} [{m['region']}] ({m['size_formatted']})\n")
        f.write("\n")

    def export_csv(self, report: Dict, filepath: str) -> None:
        """Export report as CSV."""
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['System', 'ROM Name', 'Game', 'Region',
                           'Size', 'CRC32', 'MD5', 'SHA1'])

            if 'by_dat' in report:
                for dat_report in report['by_dat'].values():
                    for m in dat_report['missing']:
                        writer.writerow([
                            dat_report['system_name'],
                            m['name'], m['game_name'], m['region'],
                            m['size'], m['crc32'], m['md5'], m['sha1'],
                        ])
            else:
                for m in report['missing']:
                    writer.writerow([
                        report.get('system_name', ''),
                        m['name'], m['game_name'], m['region'],
                        m['size'], m['crc32'], m['md5'], m['sha1'],
                    ])

    def export_json(self, report: Dict, filepath: str) -> None:
        """Export report as JSON."""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
