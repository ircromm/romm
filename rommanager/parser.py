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
from typing import Dict, List, Tuple, Any

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
        root = DATParser._parse_xml(content)

        header = DATParser._extract_header(root)
        roms = DATParser._extract_roms(root)

        return header, roms

    @staticmethod
    def parse_with_info(filepath: str) -> Tuple[DATInfo, List[ROMInfo]]:
        """
        Parse a DAT file and return a DATInfo object and ROM list.
        Each ROM is stamped with dat_id and system_name.
        """
        content = DATParser._read_file(filepath)
        content = DATParser._clean_content(content)
        root = DATParser._parse_xml(content)

        header = DATParser._extract_header(root)
        roms = DATParser._extract_roms(root)

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
