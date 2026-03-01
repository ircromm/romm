"""
File scanner for ROM files
"""

import os
import hashlib
import binascii
import zipfile
from pathlib import Path
from typing import List, Callable, Optional

from .models import ScannedFile


class FileScanner:
    """Scans files and calculates checksums"""
    
    BUFFER_SIZE = 65536  # 64KB chunks for efficient hashing
    
    # Common ROM extensions
    ROM_EXTENSIONS = {
        '.bin', '.rom', '.nes', '.sfc', '.smc', '.gba', '.gbc', '.gb',
        '.nds', '.3ds', '.n64', '.z64', '.v64', '.md', '.gen', '.smd',
        '.gg', '.sms', '.pce', '.iso', '.cue', '.cdi', '.gdi', '.chd',
        '.a26', '.a78', '.lnx', '.ngp', '.ngc', '.ws', '.wsc', '.vb',
        '.vec', '.col', '.int', '.jag', '.j64', '.ndd', '.fds', '.nsf',
        '.32x', '.cso', '.pbp', '.vpk', '.xci', '.nsp', '.wad', '.wbfs',
        '.gcm', '.rvz', '.wia', '.dol', '.elf', '.prg', '.d64', '.t64',
        '.tap', '.tzx', '.crt', '.adf', '.ipf', '.st', '.stx', '.msa'
    }

    # Obvious non-ROM/document/media/source extensions to skip by default.
    NON_ROM_EXTENSIONS = {
        '.txt', '.md', '.rtf', '.pdf',
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico',
        '.mp3', '.wav', '.flac', '.ogg', '.mp4', '.mkv', '.avi', '.mov',
        '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.json', '.yaml', '.yml', '.xml', '.html', '.htm', '.css', '.js', '.ts',
        '.ini', '.cfg', '.conf', '.log', '.csv',
        '.py', '.pyw', '.pyc', '.c', '.cpp', '.h', '.hpp', '.java', '.cs', '.go', '.rs',
        '.exe', '.dll', '.bat', '.cmd', '.ps1', '.msi', '.lnk',
        '.db', '.sqlite', '.sqlite3',
    }
    
    @staticmethod
    def scan_file(filepath: str, need_md5: bool = False, 
                  need_sha1: bool = False) -> ScannedFile:
        """
        Scan a single file and calculate checksums.
        
        CRC32 is always calculated. MD5 and SHA1 are optional for performance.
        """
        path = Path(filepath)
        size = path.stat().st_size
        
        crc = 0
        md5_hash = hashlib.md5() if need_md5 else None
        sha1_hash = hashlib.sha1() if need_sha1 else None
        
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(FileScanner.BUFFER_SIZE)
                if not data:
                    break
                crc = binascii.crc32(data, crc)
                if md5_hash:
                    md5_hash.update(data)
                if sha1_hash:
                    sha1_hash.update(data)
        
        return ScannedFile(
            path=str(filepath),
            filename=path.name,
            size=size,
            crc32=format(crc & 0xffffffff, '08x'),
            md5=md5_hash.hexdigest() if md5_hash else "",
            sha1=sha1_hash.hexdigest() if sha1_hash else ""
        )
    
    @staticmethod
    def scan_archive_contents(filepath: str) -> List[ScannedFile]:
        """
        Scan contents of a ZIP archive.
        
        Uses CRC from ZIP header for instant identification (no need to decompress).
        """
        results = []
        
        try:
            with zipfile.ZipFile(filepath, 'r') as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    
                    # Get CRC directly from ZIP header (instant!)
                    crc = format(info.CRC & 0xffffffff, '08x')
                    
                    results.append(ScannedFile(
                        path=f"{filepath}|{info.filename}",
                        filename=info.filename,
                        size=info.file_size,
                        crc32=crc,
                        md5="",
                        sha1=""
                    ))
        except zipfile.BadZipFile:
            pass
        except Exception:
            pass
        
        return results
    
    @staticmethod
    def collect_files(folder: str, recursive: bool = True, 
                     scan_archives: bool = True) -> List[str]:
        """
        Collect all scannable files from a folder.
        
        Args:
            folder: Root folder to scan
            recursive: Whether to scan subdirectories
            scan_archives: Whether to include ZIP files
        
        Returns:
            List of file paths
        """
        files = []
        
        if recursive:
            for root, dirs, filenames in os.walk(folder):
                for filename in filenames:
                    filepath = os.path.join(root, filename)
                    if FileScanner._is_scannable(filepath, scan_archives):
                        files.append(filepath)
        else:
            for filename in os.listdir(folder):
                filepath = os.path.join(folder, filename)
                if os.path.isfile(filepath) and FileScanner._is_scannable(filepath, scan_archives):
                    files.append(filepath)
        
        return files

    @staticmethod
    def _iter_scannable_files(folder: str, recursive: bool, scan_archives: bool):
        """Yield scannable file paths without building a full in-memory list first."""
        if recursive:
            for root, _dirs, filenames in os.walk(folder):
                for filename in filenames:
                    filepath = os.path.join(root, filename)
                    if FileScanner._is_scannable(filepath, scan_archives):
                        yield filepath
            return

        for filename in os.listdir(folder):
            filepath = os.path.join(folder, filename)
            if os.path.isfile(filepath) and FileScanner._is_scannable(filepath, scan_archives):
                yield filepath
    
    @staticmethod
    def _is_scannable(filepath: str, include_archives: bool) -> bool:
        """Check if a file should be scanned"""
        ext = os.path.splitext(filepath)[1].lower()

        if ext == '.zip' and include_archives:
            return True

        if ext in FileScanner.ROM_EXTENSIONS:
            return True

        if ext in FileScanner.NON_ROM_EXTENSIONS:
            return False

        # Keep compatibility for ROMs dumped without extension.
        if not ext:
            return True

        # Unknown extension fallback: keep scanning for compatibility.
        return True
    
    @staticmethod
    def scan_folder(folder: str, recursive: bool = True,
                   scan_archives: bool = True,
                   progress_callback: Optional[Callable[[int, int], None]] = None
                   ) -> List[ScannedFile]:
        """
        Scan all files in a folder.
        
        Args:
            folder: Folder to scan
            recursive: Scan subdirectories
            scan_archives: Scan inside ZIP files
            progress_callback: Optional callback(current, total)
        
        Returns:
            List of ScannedFile objects
        """
        results = []
        processed = 0
        discovered = 0

        for filepath in FileScanner._iter_scannable_files(folder, recursive, scan_archives):
            discovered += 1
            try:
                ext = os.path.splitext(filepath)[1].lower()
                
                if ext == '.zip' and scan_archives:
                    # Scan archive contents
                    archive_files = FileScanner.scan_archive_contents(filepath)
                    results.extend(archive_files)
                else:
                    # Scan regular file
                    scanned = FileScanner.scan_file(filepath)
                    results.append(scanned)
                    
            except Exception as e:
                # Skip files that can't be read
                pass

            processed += 1
            if progress_callback:
                progress_callback(processed, discovered)

        if progress_callback and discovered == 0:
            progress_callback(0, 0)
        
        return results
