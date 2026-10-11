"""Download utilities for fetching source files from remote URLs."""
import datetime
import email.utils
import logging
import shutil
import socket
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.utils.version import get_version

logger = logging.getLogger(__name__)


def download_file(url: str, output_path: str | Path) -> Path:
    """Download a file from a URL and save to disk.

    Args:
        url: URL to download from
        output_path: Path to save the downloaded file

    Returns:
        Path to saved file

    Raises:
        Exception if download fails
    """
    output_path = Path(output_path)

    try:
        logger.info(f"Downloading from {url}")

        with urlopen(url, timeout=60) as response:
            chunks = []
            chunk_size = 65536  # 64KB chunks

            while True:
                try:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    chunks.append(chunk)
                except socket.timeout:
                    logger.warning("Download timeout, retrying...")
                    raise

            file_data = b''.join(chunks)

        # Write to output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(file_data)

        logger.info(f"Downloaded to {output_path} ({len(file_data)} bytes)")
        return output_path

    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        raise


def download_file_if_changed(url: str, output_path: str | Path) -> bool:
    """Download a file only if it has changed since the cached version.

    Uses an If-Modified-Since conditional GET based on the local file's mtime.
    Falls back to a full download if the local file does not exist.

    Args:
        url: Raw URL to download from
        output_path: Path to save/overwrite the downloaded file

    Returns:
        True if the file was downloaded (new or updated), False if already current (304).

    Raises:
        Exception on non-304 HTTP errors, timeouts, or write failures.
    """
    output_path = Path(output_path)
    # Some source hosts (e.g. ini.42kit.com) reject requests carrying
    # urllib's default "Python-urllib/x.y" User-Agent with a 403, even though
    # the same request succeeds with any explicit UA. GitHub raw content
    # doesn't care either way, so this was latent until a non-GitHub source
    # was added.
    headers: dict[str, str] = {"User-Agent": f"SmartCitizen/{get_version()}"}

    if output_path.exists():
        mtime = output_path.stat().st_mtime
        dt = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)
        headers["If-Modified-Since"] = email.utils.format_datetime(dt, usegmt=True)

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=60) as response:
            data = response.read()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        logger.info(f"Downloaded updated {output_path.name} ({len(data):,} bytes) from {url}")
        return True

    except HTTPError as e:
        if e.code == 304:
            logger.info(f"{output_path.name} is up to date (304 Not Modified)")
            return False
        logger.error(f"HTTP {e.code} downloading {url}: {e}")
        raise


def fetch_language_base(source: str, dest_path: str | Path) -> bool:
    """Fetch a language's global.ini to *dest_path* from *source* (#367).

    *source* is either an ``http(s)://`` URL (downloaded via
    :func:`download_file_if_changed`) or a local file path — a language whose
    community source can't be redistributed (e.g. Korean) is mapped to a file
    the user already has on disk, so it's copied instead of fetched.

    Returns True if *dest_path* is present and usable afterward. Raises
    on a failed download or a missing/unreadable local source, same as
    :func:`download_file_if_changed` and :func:`shutil.copy2`.
    """
    dest_path = Path(dest_path)
    if source.startswith(("http://", "https://")):
        return download_file_if_changed(source, dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest_path)
    return True
