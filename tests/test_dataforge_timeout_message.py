"""unforge timing out must say so, and say what to do about it (#370).

A user's DataForge extraction died after exactly 1800 seconds and all the app
told them was "DataForge extraction failed". The traceback ended in
subprocess._communicate with no exception type, their log carried nothing from
unforge, and they spent the next stretch chasing a memory reading that turned
out to be a symptom.

The cause was a Data.p4k that did not match its own build_manifest.id: a
114 MB Game.dcb where a healthy install of the identical build (verified
byte-for-byte on BuildId) carries a 330 MB Game2.dcb. Measured, that healthy
file converts in about 40 seconds against a 1800 second budget, so a timeout
here is a mismatched install rather than a slow machine, and the fix is Verify
Files in the RSI launcher.

Three things have to hold for the next person to get that without a
maintainer reading their log:

* the timeout is caught and turned into DataForgeTimeoutError, which the
  worker recognises the way it already recognises P4kLockedError;
* the message names the database and its size, because "Game.dcb (114 MB)"
  versus "Game2.dcb (330 MB)" is the entire diagnosis;
* unforge's partial output, which subprocess.run attaches to the exception on
  Windows and the old code discarded, reaches the log.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.pak_extractor import (  # noqa: E402
    DataForgeTimeoutError, _unforge_timeout_error,
)

# english_ui (tests/conftest.py): the English asserts below would otherwise
# depend on which language an earlier test module left active.
pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.usefixtures("english_ui")]

# The p4k the extraction was pointed at. Named in the message because #370's
# root cause was Smart Citizen reading a leftover install, so "which folder"
# is the first thing a user needs to check.
_P4K = Path(r"D:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Data.p4k")


def _timeout(stdout=None, stderr=None, secs: float = 1800.0):
    """A TimeoutExpired shaped like the one subprocess.run raises on Windows,
    where it kills the child and re-collects its output onto the exception."""
    exc = subprocess.TimeoutExpired(cmd=["unforge.exe", "Game.dcb"], timeout=secs)
    exc.stdout, exc.stderr = stdout, stderr
    return exc


def _dcb(tmp_path: Path, name: str = "Game.dcb") -> Path:
    p = tmp_path / name
    p.write_bytes(b"\0")
    return p


def test_raises_the_recognisable_type_not_a_bare_timeout(tmp_path):
    """The worker tells this apart from an unexpected crash by isinstance, so
    that a friendly dialog is not doubled up by the global error handler."""
    with pytest.raises(DataForgeTimeoutError):
        raise _unforge_timeout_error(_timeout(), _dcb(tmp_path), 114.0, _P4K)


def test_it_is_still_a_runtimeerror(tmp_path):
    """Same contract as P4kLockedError: any caller with a plain
    ``except RuntimeError`` keeps working."""
    with pytest.raises(RuntimeError):
        raise _unforge_timeout_error(_timeout(), _dcb(tmp_path), 114.0, _P4K)


def test_message_names_the_database_and_its_size(tmp_path):
    """The whole diagnosis is which file it was chewing on. Without both, a
    mismatched install and a slow machine look identical, and they need
    opposite advice."""
    msg = str(_unforge_timeout_error(
        _timeout(), _dcb(tmp_path, "Game.dcb"), 114.0, _P4K))
    assert "Game.dcb" in msg
    assert "114" in msg


def test_message_leads_with_the_install_path_not_verify_files(tmp_path):
    """The actionable half, in the order #370 proved correct."""
    msg = str(_unforge_timeout_error(_timeout(), _dcb(tmp_path), 114.0, _P4K))
    # The install path comes FIRST and Verify Files second. That ordering is
    # the lesson of #370: the reporter was sent to Verify Files, it changed
    # nothing, and the real cause was Smart Citizen reading a leftover folder.
    assert str(_P4K) in msg
    assert "Config tab" in msg
    assert "Verify Files" in msg
    assert msg.index("Config tab") < msg.index("Verify Files")


def test_partial_unforge_output_reaches_the_log(tmp_path, caplog):
    """subprocess.run attaches what the child managed to emit before the kill.
    The old code let the exception propagate untouched, so the one failure
    that most needs diagnostics produced none."""
    with caplog.at_level(logging.WARNING):
        with pytest.raises(DataForgeTimeoutError):
            raise _unforge_timeout_error(
                _timeout(stdout="wrote 12 files", stderr="unexpected node"),
                _dcb(tmp_path), 114.0, _P4K,
            )
    logged = "\n".join(r.message for r in caplog.records)
    assert "wrote 12 files" in logged
    assert "unexpected node" in logged


def test_bytes_output_is_decoded_not_crashed_on(tmp_path, caplog):
    """capture_output without text= yields bytes. A decode error here would
    replace the timeout with a UnicodeDecodeError and lose the diagnosis."""
    with caplog.at_level(logging.WARNING):
        with pytest.raises(DataForgeTimeoutError):
            raise _unforge_timeout_error(
                _timeout(stdout=b"binary \xff\xfe noise"), _dcb(tmp_path), 114.0, _P4K,
            )
    assert "binary" in "\n".join(r.message for r in caplog.records)


def test_logs_at_warning_not_error(tmp_path, caplog):
    """ERROR-level records trip MainWindow's global ErrorDialogHandler
    app-wide, which would stack a second dialog on the friendly one. Same
    reasoning as P4kLockedError."""
    with caplog.at_level(logging.WARNING):
        with pytest.raises(DataForgeTimeoutError):
            raise _unforge_timeout_error(_timeout(), _dcb(tmp_path), 114.0, _P4K)
    assert caplog.records
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_log_records_the_size_for_a_maintainer(tmp_path, caplog):
    """The user-facing string is translated; the log is not. A maintainer
    reading a German user's log still needs the two numbers."""
    with caplog.at_level(logging.WARNING):
        with pytest.raises(DataForgeTimeoutError):
            raise _unforge_timeout_error(_timeout(), _dcb(tmp_path, "Game.dcb"), 114.0, _P4K)
    logged = "\n".join(r.message for r in caplog.records)
    assert "Game.dcb" in logged and "114" in logged and "1800" in logged
