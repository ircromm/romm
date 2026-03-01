"""
DAT file parser for various formats (No-Intro, Redump, TOSEC, etc.)
"""

import os
import uuid
import xml.etree.ElementTree as ET
import zipfile
import gzip
import re
from datetime import datetime
from typing import Any, Dict, Iterator, List, Set, Tuple

from .models import ROMInfo, DATInfo


class DATParser:
    """Parser for various DAT file formats"""

    @staticmethod
    def parse(filepath: str) -> Tuple[Dict[str, Any], List[ROMInfo]]:
        """
        Parse a DAT file and return header info and ROM list.

        Supports:
        - Plain XML/DAT files
        - Gzipped DAT files (.gz)
        - Zipped DAT files (.zip)
        """
        content = DATParser._read_file(filepath)
        content = DATParser._clean_content(content)
        if DATParser._looks_like_clrmamepro(content):
            return DATParser._parse_clrmamepro(content)

        try:
            root = DATParser._parse_xml(content)
            header = DATParser._extract_header(root)
            roms = DATParser._extract_roms(root)
            return header, roms
        except Exception as xml_exc:
            # Fallback for DAT files that are plain clrmamepro text.
            try:
                return DATParser._parse_clrmamepro(content)
            except Exception:
                raise xml_exc

    @staticmethod
    def parse_with_info(filepath: str) -> Tuple[DATInfo, List[ROMInfo]]:
        """
        Parse a DAT file and return a DATInfo object and ROM list.
        Each ROM is stamped with dat_id and system_name.
        """
        header, roms = DATParser.parse(filepath)

        dat_id = uuid.uuid4().hex[:8]
        name = header.get('name', header.get('description', os.path.basename(filepath)))
        system_name = name

        dat_info = DATInfo(
            id=dat_id,
            filepath=filepath,
            name=name,
            description=header.get('description', ''),
            version=header.get('version', ''),
            system_name=system_name,
            rom_count=len(roms),
            loaded_at=datetime.now().isoformat(),
        )

        for rom in roms:
            rom.dat_id = dat_id
            rom.system_name = system_name

        return dat_info, roms

    @staticmethod
    def _looks_like_clrmamepro(content: str) -> bool:
        """Best-effort detection for clrmamepro DAT text files."""
        probe = (content or "").lstrip()
        if not probe:
            return False
        if probe.startswith("<"):
            return False
        return probe.lower().startswith("clrmamepro") or "\ngame (" in probe.lower()

    @staticmethod
    def _skip_ws(text: str, idx: int) -> int:
        size = len(text)
        i = idx
        while i < size and text[i].isspace():
            i += 1
        return i

    @staticmethod
    def _read_word(text: str, idx: int) -> Tuple[str, int]:
        size = len(text)
        i = idx
        while i < size and not text[i].isspace() and text[i] not in "()":
            i += 1
        return text[idx:i], i

    @staticmethod
    def _read_quoted(text: str, idx: int) -> Tuple[str, int]:
        if idx >= len(text) or text[idx] != '"':
            return "", idx
        i = idx + 1
        buf: List[str] = []
        size = len(text)
        while i < size:
            ch = text[i]
            if ch == "\\" and i + 1 < size:
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                return "".join(buf), i + 1
            buf.append(ch)
            i += 1
        return "".join(buf), i

    @staticmethod
    def _extract_parenthesized(text: str, open_idx: int) -> Tuple[str, int]:
        """Extract content inside (...) starting at open_idx."""
        if open_idx >= len(text) or text[open_idx] != "(":
            raise ValueError("Expected '(' while parsing DAT")
        depth = 1
        i = open_idx + 1
        size = len(text)
        in_quote = False
        while i < size:
            ch = text[i]
            if ch == "\\" and in_quote:
                i += 2
                continue
            if ch == '"':
                in_quote = not in_quote
                i += 1
                continue
            if not in_quote:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        return text[open_idx + 1:i], i + 1
            i += 1
        raise ValueError("Unbalanced DAT parentheses")

    @staticmethod
    def _iter_named_blocks(text: str, names: Set[str]) -> Iterator[Tuple[str, str]]:
        """Yield (name, block_text) for entries like `name ( ... )`."""
        wanted = {str(n).lower() for n in names}
        i = 0
        size = len(text)
        while i < size:
            i = DATParser._skip_ws(text, i)
            if i >= size:
                break
            ch = text[i]
            if ch == '"':
                _, i = DATParser._read_quoted(text, i)
                continue
            if ch in "()":
                i += 1
                continue
            word, nxt = DATParser._read_word(text, i)
            if not word:
                i += 1
                continue
            j = DATParser._skip_ws(text, nxt)
            if j < size and text[j] == "(":
                block_text, after = DATParser._extract_parenthesized(text, j)
                key = word.lower()
                if key in wanted:
                    yield key, block_text
                i = after
                continue
            i = nxt

    @staticmethod
    def _parse_block_pairs(block_text: str) -> Dict[str, str]:
        """
        Parse top-level key/value pairs from a block, skipping nested (...) entries.
        Example: name "SNES" version "2026.01.17"
        """
        pairs: Dict[str, str] = {}
        i = 0
        size = len(block_text)
        while i < size:
            i = DATParser._skip_ws(block_text, i)
            if i >= size:
                break
            ch = block_text[i]
            if ch == '"':
                _, i = DATParser._read_quoted(block_text, i)
                continue
            if ch in "()":
                i += 1
                continue

            key, nxt = DATParser._read_word(block_text, i)
            if not key:
                i += 1
                continue

            i = DATParser._skip_ws(block_text, nxt)
            if i >= size:
                break
            if block_text[i] == "(":
                # Nested child block (e.g. rom (...)) -> skip entirely.
                _, i = DATParser._extract_parenthesized(block_text, i)
                continue

            if block_text[i] == '"':
                value, i = DATParser._read_quoted(block_text, i)
            else:
                value, i = DATParser._read_word(block_text, i)
            pairs[key.lower()] = value
        return pairs

    @staticmethod
    def _parse_clrmamepro(content: str) -> Tuple[Dict[str, Any], List[ROMInfo]]:
        """Parse plain text clrmamepro DAT format."""
        header: Dict[str, Any] = {}
        roms: List[ROMInfo] = []
        found_any = False

        for entry_name, entry_block in DATParser._iter_named_blocks(
            content, {"clrmamepro", "game", "machine"}
        ):
            found_any = True
            if entry_name == "clrmamepro":
                header = DATParser._parse_block_pairs(entry_block)
                continue

            game_pairs = DATParser._parse_block_pairs(entry_block)
            game_name = str(game_pairs.get("name", "") or "").strip()
            description = str(game_pairs.get("description", "") or "").strip() or game_name
            region = str(game_pairs.get("region", "") or "").strip() or DATParser._extract_region(game_name)
            languages = str(game_pairs.get("languages", "") or "").strip() or DATParser._extract_languages(game_name)

            for rom_tag, rom_block in DATParser._iter_named_blocks(entry_block, {"rom", "disk"}):
                rom_pairs = DATParser._parse_block_pairs(rom_block)
                rom_name = str(rom_pairs.get("name", "") or "").strip() or game_name
                size_raw = str(rom_pairs.get("size", "0") or "0")
                try:
                    size = int(size_raw)
                except Exception:
                    size = 0

                status = str(rom_pairs.get("status", "") or "").strip()
                if not status:
                    status = "verified"
                if rom_tag == "disk" and status == "verified":
                    # Disk entries usually carry hashes but no size/status in many DATs.
                    status = "disk"

                roms.append(
                    ROMInfo(
                        name=rom_name,
                        size=size,
                        crc32=str(rom_pairs.get("crc", "") or "").lower(),
                        md5=str(rom_pairs.get("md5", "") or "").lower(),
                        sha1=str(rom_pairs.get("sha1", "") or "").lower(),
                        description=description,
                        game_name=game_name,
                        region=region,
                        languages=languages,
                        status=status,
                    )
                )

        if not found_any:
            raise ValueError("Invalid DAT structure: expected XML or clrmamepro blocks")
        return header, roms

    @staticmethod
    def _read_file(filepath: str) -> str:
        """Read file content, handling compression"""
        if filepath.endswith('.gz'):
            with gzip.open(filepath, 'rt', encoding='utf-8', errors='ignore') as f:
                return f.read()

        elif filepath.endswith('.zip') or zipfile.is_zipfile(filepath):
            with zipfile.ZipFile(filepath, 'r') as zf:
                # Find XML/DAT file inside
                xml_files = [n for n in zf.namelist()
                           if n.endswith('.dat') or n.endswith('.xml')]
                if not xml_files:
                    raise ValueError("No DAT/XML file found in ZIP archive")
                with zf.open(xml_files[0]) as f:
                    return f.read().decode('utf-8', errors='ignore')

        else:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()

    @staticmethod
    def _clean_content(content: str) -> str:
        """Clean XML content of problematic characters"""
        # Remove BOM
        content = content.lstrip('\ufeff')
        # Remove control characters
        content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', content)
        return content

    @staticmethod
    def _parse_xml(content: str) -> ET.Element:
        """Parse XML content"""
        try:
            return ET.fromstring(content)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML in DAT file: {e}")

    @staticmethod
    def _extract_header(root: ET.Element) -> Dict[str, str]:
        """Extract header information from DAT"""
        header = {}
        header_elem = root.find('header')

        if header_elem is not None:
            for child in header_elem:
                header[child.tag] = child.text or ""

        return header

    @staticmethod
    def _extract_roms(root: ET.Element) -> List[ROMInfo]:
        """Extract ROM information from DAT"""
        roms = []

        # Handle different DAT formats (game/machine elements)
        for game in root.findall('.//game') + root.findall('.//machine'):
            game_name = game.get('name', '')

            # Get description
            desc_elem = game.find('description')
            description = desc_elem.text if desc_elem is not None and desc_elem.text else game_name

            # Extract region and language
            region = DATParser._extract_region(game_name)
            languages = DATParser._extract_languages(game_name)

            # Process each ROM in the game
            for rom in game.findall('rom'):
                rom_info = DATParser._parse_rom_element(
                    rom, game_name, description, region, languages
                )
                roms.append(rom_info)

        return roms

    @staticmethod
    def _parse_rom_element(rom: ET.Element, game_name: str,
                          description: str, region: str,
                          languages: str) -> ROMInfo:
        """Parse a single ROM element"""
        try:
            size = int(rom.get('size', 0))
        except (ValueError, TypeError):
            size = 0

        return ROMInfo(
            name=rom.get('name', ''),
            size=size,
            crc32=rom.get('crc', '').lower(),
            md5=rom.get('md5', '').lower(),
            sha1=rom.get('sha1', '').lower(),
            description=description,
            game_name=game_name,
            region=region,
            languages=languages,
            status=rom.get('status', 'verified')
        )

    @staticmethod
    def _extract_region(name: str) -> str:
        """Extract region from ROM name"""
        regions = {
            '(USA)': 'USA', '(U)': 'USA', '(America)': 'USA',
            '(Europe)': 'Europe', '(E)': 'Europe', '(EU)': 'Europe',
            '(Japan)': 'Japan', '(J)': 'Japan', '(JP)': 'Japan',
            '(World)': 'World', '(W)': 'World',
            '(Brazil)': 'Brazil', '(B)': 'Brazil', '(BR)': 'Brazil',
            '(Korea)': 'Korea', '(K)': 'Korea', '(KR)': 'Korea',
            '(China)': 'China', '(C)': 'China', '(CN)': 'China',
            '(Germany)': 'Germany', '(G)': 'Germany', '(De)': 'Germany',
            '(France)': 'France', '(F)': 'France', '(Fr)': 'France',
            '(Spain)': 'Spain', '(S)': 'Spain', '(Es)': 'Spain',
            '(Italy)': 'Italy', '(I)': 'Italy', '(It)': 'Italy',
            '(Australia)': 'Australia', '(A)': 'Australia', '(Au)': 'Australia',
            '(Asia)': 'Asia', '(As)': 'Asia',
            '(Netherlands)': 'Netherlands', '(Nl)': 'Netherlands',
            '(Sweden)': 'Sweden', '(Sw)': 'Sweden',
            '(Russia)': 'Russia', '(Ru)': 'Russia',
        }

        for pattern, region in regions.items():
            if pattern in name:
                return region

        return 'Unknown'

    @staticmethod
    def _extract_languages(name: str) -> str:
        """Extract languages from ROM name"""
        lang_match = re.search(r'\(([A-Z][a-z](?:,[A-Z][a-z])*)\)', name)
        if lang_match:
            return lang_match.group(1)
        return ''
