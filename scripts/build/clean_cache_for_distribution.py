"""
Clean DataForge cache before distributing to remove the raw/ directory.

Usage:
    python clean_cache_for_distribution.py

This removes the 'raw/' subdirectory from the DataForge cache to reduce
distribution size. The filtered 'libs/' directory contains all necessary
files for enhancements generation. Users can regenerate the raw cache if needed
by re-extracting from P4K.
"""

import shutil
from pathlib import Path

def get_documents_dir():
    """Get Documents directory path."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        )
        docs = Path(winreg.QueryValueEx(key, "Personal")[0])
        winreg.CloseKey(key)
        return docs
    except Exception:
        return Path.home() / "Documents"

def main():
    cache_dir = get_documents_dir() / "Smart Citizen" / "cache" / "dataforge"
    raw_dir = cache_dir / "raw"

    if not raw_dir.exists():
        print(f"Raw DataForge directory not found at {raw_dir}")
        print("Cache may already be cleaned.")
        return

    size_mb = sum(f.stat().st_size for f in raw_dir.rglob("*") if f.is_file()) / 1_048_576

    print(f"Found raw DataForge extraction: {raw_dir}")
    print(f"Size: {size_mb:.1f} MB")
    print()

    response = input("Delete raw/ directory? (y/N): ").strip().lower()
    if response != 'y':
        print("Cancelled.")
        return

    try:
        shutil.rmtree(raw_dir)
        print(f"✓ Deleted {raw_dir}")
        print()
        print("Cache cleaned for distribution. The filtered 'libs/' directory")
        print("contains all necessary files for enhancements generation.")
    except Exception as e:
        print(f"✗ Error deleting directory: {e}")
        return False

if __name__ == "__main__":
    main()
