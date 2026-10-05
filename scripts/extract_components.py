#!/usr/bin/env python3
"""Extract modified/added strings from base.ini into a components.ini file.

Compares the current base.ini (cached MrKraken-modified file) against BeltaKoda's
stock-global.ini (vanilla Star Citizen strings) and writes the delta — keys that are
new or have different values in base.ini — to an output file.

The output file can then be configured as the 'Components' source in SC Localization
Editor so the hierarchy is: stock global → components (mods) → contracts → user.

Usage:
    python scripts/extract_components.py [options]

Options:
    --stock PATH     Path to stock-global.ini (downloaded if omitted)
    --base PATH      Path to base.ini (defaults to Documents cache)
    --output PATH    Output path for extracted components (defaults to cache/components.ini)
    --stock-url URL  Override the stock-global.ini download URL
    --dry-run        Print stats without writing output file
"""
import argparse
import sys
from pathlib import Path
from urllib.request import urlopen

STOCK_URL = "https://raw.githubusercontent.com/BeltaKoda/ScCompLangPackRemix/main/LIVE/stock-global.ini"


def get_documents_dir() -> Path:
    """Resolve the real Documents folder (handles OneDrive redirection on Windows)."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        )
        docs, _ = winreg.QueryValueEx(key, "Personal")
        winreg.CloseKey(key)
        return Path(docs)
    except Exception:
        return Path.home() / "Documents"


def get_default_cache_dir() -> Path:
    return get_documents_dir() / "Smart Citizen" / "cache"


def parse_ini(path: Path) -> dict[str, str]:
    """Parse a key=value INI file, skipping blank lines and ; comments."""
    result = {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line.strip() or line.strip().startswith(";"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key:
                    result[key] = value.strip()
    except Exception as e:
        print(f"ERROR: Could not parse {path}: {e}", file=sys.stderr)
        sys.exit(1)
    return result


def download_stock(url: str, dest: Path) -> None:
    print(f"Downloading stock-global.ini from {url} ...")
    try:
        with urlopen(url, timeout=60) as resp:
            data = resp.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        print(f"  Saved to {dest} ({len(data):,} bytes)")
    except Exception as e:
        print(f"ERROR: Download failed: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stock", metavar="PATH", help="Path to stock-global.ini (downloaded if omitted)")
    parser.add_argument("--base", metavar="PATH", help="Path to base.ini (defaults to Documents cache/base.ini)")
    parser.add_argument("--output", metavar="PATH", help="Output path (defaults to Documents cache/components.ini)")
    parser.add_argument("--stock-url", metavar="URL", default=STOCK_URL, help="Override stock-global.ini download URL")
    parser.add_argument("--dry-run", action="store_true", help="Print stats without writing output file")
    args = parser.parse_args()

    cache_dir = get_default_cache_dir()

    # Resolve stock file
    if args.stock:
        stock_path = Path(args.stock)
        if not stock_path.exists():
            print(f"ERROR: --stock file not found: {stock_path}", file=sys.stderr)
            sys.exit(1)
    else:
        stock_path = cache_dir / "stock-global.ini"
        if not stock_path.exists():
            download_stock(args.stock_url, stock_path)

    # Resolve base file
    base_path = Path(args.base) if args.base else cache_dir / "base.ini"
    if not base_path.exists():
        print(f"ERROR: base.ini not found at {base_path}", file=sys.stderr)
        print("  Run SC Localization Editor first to download the base file, or pass --base <path>.")
        sys.exit(1)

    # Resolve output path
    output_path = Path(args.output) if args.output else cache_dir / "components.ini"

    # Parse both files
    print(f"Parsing stock : {stock_path}")
    stock = parse_ini(stock_path)
    print(f"  {len(stock):,} keys")

    print(f"Parsing base  : {base_path}")
    base = parse_ini(base_path)
    print(f"  {len(base):,} keys")

    # Find delta: keys in base that are absent from or differ vs stock
    added = {}
    modified = {}
    for key, value in base.items():
        if key not in stock:
            added[key] = value
        elif value != stock[key]:
            modified[key] = value

    delta = {**added, **modified}

    print("\nDelta summary:")
    print(f"  Keys only in base (new)      : {len(added):,}")
    print(f"  Keys in both but modified    : {len(modified):,}")
    print(f"  Total delta keys             : {len(delta):,}")

    if not delta:
        print("\nNo differences found. base.ini matches stock-global.ini exactly.")
        return

    if args.dry_run:
        print("\n--dry-run: skipping file write.")
        return

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("; SC Localization Editor - extracted components\n")
        f.write("; Delta between base.ini and stock-global.ini\n")
        f.write("; Generated by scripts/extract_components.py\n")
        f.write(f"; Keys: {len(added)} new, {len(modified)} modified\n\n")

        if added:
            f.write("; === Keys not present in stock-global.ini ===\n")
            for key, value in sorted(added.items()):
                f.write(f"{key}={value}\n")
            f.write("\n")

        if modified:
            f.write("; === Keys with different values from stock-global.ini ===\n")
            for key, value in sorted(modified.items()):
                f.write(f"{key}={value}\n")

    print(f"\nWrote {len(delta):,} keys to: {output_path}")
    print("\nNext steps:")
    print("  1. In SC Localization Editor > Config tab, set the Components source to:")
    print(f"     {output_path}")
    print("  2. Enable the Components source and add it to your merge hierarchy.")
    print("  3. Set the Global source URL to BeltaKoda stock-global.ini:")
    print(f"     {STOCK_URL}")
    print("  4. Save Configuration & Merge.")


if __name__ == "__main__":
    main()
