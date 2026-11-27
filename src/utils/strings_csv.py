"""CSV export and import of the String Editor's rows (#565).

Export writes the rows the table shows, in its order, with the table's
text columns. Import reads back the Key and Custom Value columns. Both
are Qt-free; ``MainWindow._export_csv`` and ``_handle_import_csv`` own the
dialogs.

The file is UTF-8 with a BOM, so Excel shows accents and other scripts
right when it opens it. The header names are fixed English, whatever the
app's language, so a file exported in one language imports in any other.
Line breaks stay as the game writes them, a literal backslash-n.

``plan_override_import`` is the one rule both Import CSV and Import INI
follow: a value that is empty, or the same as the row's default or current
text, is skipped, so a re-imported full export only adds what was really
changed and an enhanced row keeps updating after a game patch.
"""
from __future__ import annotations

import csv
import io
import locale
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.utils.atomic_io import atomic_writer

# The columns written, in order. Key and Custom Value are what import reads.
COL_KEY = "Key"
COL_CATEGORY = "Category"
COL_DEFAULT = "Default Value"
COL_CURRENT = "Current Value"
COL_CUSTOM = "Custom Value"
COL_STATUS = "Status"
CSV_COLUMNS = (COL_KEY, COL_CATEGORY, COL_DEFAULT, COL_CURRENT, COL_CUSTOM, COL_STATUS)

# Header spellings import accepts for the two columns it reads (compared
# lower case, spaces and underscores ignored).
_KEY_HEADERS = {"key"}
_CUSTOM_HEADERS = {"customvalue", "custom"}

# Excel saves "CSV" with the list separator of the user's region, which is
# ";" across most of Europe, so the reader sniffs among these.
_DELIMITERS = ",;\t"

CSV_SUFFIX = ".csv"


class CsvColumnsMissing(ValueError):
    """The file has no Key column or no Custom Value column."""


@dataclass(frozen=True)
class CsvRow:
    key: str
    category: str
    default_value: str
    current_value: str
    custom_value: str
    status: str

    def cells(self) -> Tuple[str, ...]:
        return (self.key, self.category, self.default_value, self.current_value,
                self.custom_value, self.status)


def strings_csv_text(rows: Iterable[CsvRow]) -> str:
    """The CSV text for ``rows`` (no BOM; ``write_strings_csv`` adds it)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(row.cells())
    return out.getvalue()


def write_strings_csv(path: "str | Path", rows: Iterable[CsvRow]) -> int:
    """Write ``rows`` to ``path`` in one step; return how many were written."""
    rows = list(rows)
    # Bytes, not text mode: text mode on Windows turns the CSV's own "\r\n"
    # into "\r\r\n", a blank row after every row.
    data = ("\ufeff" + strings_csv_text(rows)).encode("utf-8")
    with atomic_writer(Path(path), "wb") as f:
        f.write(data)
    return len(rows)


def _decode(data: bytes) -> str:
    """UTF-8 (with or without a BOM), else the system's own code page, which
    is what Excel's plain "CSV" save uses."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode(locale.getpreferredencoding(False) or "cp1252", errors="replace")


def _header_name(cell: str) -> str:
    return cell.strip().lower().replace(" ", "").replace("_", "")


def _find_column(header: Sequence[str], names: set) -> Optional[int]:
    for i, cell in enumerate(header):
        if _header_name(cell) in names:
            return i
    return None


def parse_strings_csv_text(text: str) -> Dict[str, str]:
    """Each row's key and Custom Value, in file order.

    Rows with no key are skipped. A key listed twice keeps its last value.
    Raises ``CsvColumnsMissing`` when the header has no Key or no Custom
    Value column.
    """
    first_line = text.split("\n", 1)[0]
    try:
        dialect = csv.Sniffer().sniff(first_line, delimiters=_DELIMITERS)
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    header = next(reader, None) or []
    key_col = _find_column(header, _KEY_HEADERS)
    custom_col = _find_column(header, _CUSTOM_HEADERS)
    if key_col is None or custom_col is None:
        raise CsvColumnsMissing(header)
    values: Dict[str, str] = {}
    for row in reader:
        if len(row) <= key_col:
            continue
        key = row[key_col].strip()
        if not key:
            continue
        values[key] = row[custom_col] if len(row) > custom_col else ""
    return values


def read_strings_csv(path: "str | Path") -> Dict[str, str]:
    """``parse_strings_csv_text`` over the file at ``path``."""
    return parse_strings_csv_text(_decode(Path(path).read_bytes()))


@dataclass
class ImportPlan:
    """What an import of override values would do (``plan_override_import``)."""

    auto_add: Dict[str, str] = field(default_factory=dict)
    """Keys with no override yet, added as they are."""
    conflicts: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    """Keys whose override differs: (current override, imported value)."""
    unchanged: int = 0
    """Values skipped: empty, the same as the row's default or current text,
    or the same as the override already there."""
    unknown: int = 0
    """Keys skipped because base.ini does not have them."""

    @property
    def has_work(self) -> bool:
        return bool(self.auto_add or self.conflicts)


def plan_override_import(
    imported: Mapping[str, str],
    default_values: Mapping[str, str],
    current_values: Mapping[str, str],
    current_overrides: Mapping[str, str],
) -> ImportPlan:
    """Sort imported values into what an import adds, asks about and skips.

    ``default_values`` is base.ini (the Default Value column; a key it lacks
    is unknown), ``current_values`` each row's merged text before any
    override (the Current Value column, enhancements included), and
    ``current_overrides`` what user.ini holds now.
    """
    plan = ImportPlan()
    for key, value in imported.items():
        if key not in default_values:
            plan.unknown += 1
            continue
        if not value or value == default_values[key] or value == current_values.get(key):
            plan.unchanged += 1
            continue
        current = current_overrides.get(key)
        if current is None:
            plan.auto_add[key] = value
        elif current != value:
            plan.conflicts[key] = (current, value)
        else:
            plan.unchanged += 1
    return plan


def default_csv_filename(channel: str, today: Optional[datetime] = None) -> str:
    """``SmartCitizen-Strings-{channel}-{YYYYMMDD}.csv``, as the loc-pack's name."""
    when = today or datetime.now()
    return f"SmartCitizen-Strings-{channel}-{when.strftime('%Y%m%d')}{CSV_SUFFIX}"


__all__: List[str] = [
    "CSV_COLUMNS", "CsvColumnsMissing", "CsvRow", "ImportPlan",
    "default_csv_filename", "parse_strings_csv_text", "plan_override_import",
    "read_strings_csv", "strings_csv_text", "write_strings_csv",
]
