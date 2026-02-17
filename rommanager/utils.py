"""
Utility functions for ROM Manager
"""


def format_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.
    
    Args:
        size_bytes: Size in bytes
    
    Returns:
        Formatted string (e.g., "1.5 MB")
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            if unit == 'B':
                return f"{size_bytes} {unit}"
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def truncate_string(s: str, max_length: int, suffix: str = '...') -> str:
    """
    Truncate a string to max length.
    
    Args:
        s: String to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated
    
    Returns:
        Truncated string
    """
    if len(s) <= max_length:
        return s
    return s[:max_length - len(suffix)] + suffix


def safe_filename(name: str) -> str:
    """
    Make a filename safe for all operating systems.
    
    Args:
        name: Original filename
    
    Returns:
        Safe filename
    """
    # Characters not allowed in filenames on various systems
    invalid_chars = '<>:"/\\|?*'
    
    for char in invalid_chars:
        name = name.replace(char, '_')
    
    # Remove leading/trailing spaces and dots
    name = name.strip(' .')
    
    # Ensure not empty
    if not name:
        name = 'unnamed'
    
    return name
