"""
R0MM - A tool for organizing ROM collections using DAT files

Supports No-Intro, Redump, TOSEC, and any XML-based DAT format.
"""

__version__ = '2.1.0'
__author__ = 'R0MM'

from .models import (
    ROMInfo, ScannedFile, OrganizationAction, DATInfo,
    Collection, PlannedAction, OrganizationPlan,
)
from .parser import DATParser
from .scanner import FileScanner
from .matcher import ROMMatcher, MultiROMMatcher
from .organizer import Organizer, build_strategy
from .utils import format_size, truncate_string, safe_filename
from .collection import CollectionManager
from .reporter import MissingROMReporter


__all__ = [
    'ROMInfo',
    'ScannedFile',
    'OrganizationAction',
    'DATInfo',
    'Collection',
    'PlannedAction',
    'OrganizationPlan',
    'DATParser',
    'FileScanner',
    'ROMMatcher',
    'MultiROMMatcher',
    'Organizer',
    'build_strategy',
    'CollectionManager',
    'MissingROMReporter',
    'format_size',
    'truncate_string',
    'safe_filename',
]

def run_web(host='127.0.0.1', port=5000):
    """Run the web interface"""
    from .web import run_server
    run_server(host, port)
