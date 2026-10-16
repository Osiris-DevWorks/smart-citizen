"""scripts/generate_enhancements_ini.py writes every output in one step.

A generation cut off by a close or a crash used to leave the INI it was
writing truncated (``path.write_text`` truncates first), and the next load
read half a category as the whole thing. A lookup pickle cut off the same
way was rebuilt with no word in the Log tab, though a rebuild can take a
minute and a half. Every file the script writes now goes through
``src/utils/atomic_io.py``. These tests pin:

* ``write_ini``'s bytes are what the old in-place writer wrote,
* a failed ``write_ini`` (mid-write or at the swap) keeps the old INI whole,
* the real ``main()`` failing on its last INI leaves every INI whole, the
  ones before it new and the failed one old,
* a truncated lookup pickle is rebuilt with an INFO line, and a pickle
  write that fails keeps the old pickle,
* an AST guard: no write in the script bypasses the atomic writer, outside
  the module-level ``except ImportError`` fallbacks that run only when
  ``src/`` is missing,
* closing stops a generation between jobs: ``main()`` raises
  ``GenerationStopped`` at each of its stop points with every INI untouched,
  the last one just before the write phase, and never looks at a stop once
  it has begun writing.
"""
from __future__ import annotations

import ast
import errno
import importlib.util
import logging
import os
import pickle
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("lxml")

from src.utils import atomic_io  # noqa: E402
from src.utils.pak_extractor import DATAFORGE_LOOKUPS_SUBPATH  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "generate_enhancements_ini.py"

OLD_SHIPS = b"vehicle_Desc_Old=old ship text\r\n"
OLD_MEDICAL = b"item_Desc_Old=old pen text\r\nitem_Desc_Old2=second line\r\n"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_writes_test", SCRIPT
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


@pytest.fixture
def forge_layout(tmp_path):
    """A base.ini plus a minimal, empty DataForge cache tree, as in
    test_single_job_skips_threadpool.py. main() writes beside the base.ini."""
    base_ini = tmp_path / "base.ini"
    shutil.copy(REPO_ROOT / "tests" / "fixtures" / "kraken_global_latest.ini", base_ini)
    forge_dir = tmp_path / "forge"
    (forge_dir / "raw" / "libs" / "foundry" / "records").mkdir(parents=True)
    return base_ini, forge_dir


def _temps(folder: Path) -> list[str]:
    return sorted(p.name for p in Path(folder).glob(".sc-*.tmp"))


def _disk_full(source, destination):
    raise OSError(errno.ENOSPC, "No space left on device")


# ── write_ini ───────────────────────────────────────────────────────────────

def test_write_ini_bytes_match_the_old_writer(gen, tmp_path):
    entries = {
        "item_Desc_b": "Aspirum™ Shield — Mk. II",
        "item_Desc_a": "Sebastián Muñoz\\nsecond line",
        "item_Desc_c": "",
        "item_Desc_d": "a=b",
    }
    path = tmp_path / "out" / "components_desc_enhancements.ini"

    gen.write_ini(path, entries)

    old = tmp_path / "old_writer.ini"
    old.write_text(
        "".join(f"{k}={v}\n" for k, v in sorted(entries.items())), encoding="utf-8"
    )
    assert path.read_bytes() == old.read_bytes()
    assert gen.parse_ini(path) == entries
    assert _temps(path.parent) == []


@pytest.mark.parametrize("failure", ["while_writing", "at_the_swap"])
def test_write_ini_failure_keeps_the_old_ini(gen, tmp_path, monkeypatch, failure):
    path = tmp_path / "ships_desc_enhancements.ini"
    path.write_bytes(OLD_SHIPS)
    entries = {"vehicle_Desc_New": "new ship text"}
    if failure == "while_writing":
        # Any failure part-way through the write. A lone surrogate cannot
        # be encoded as UTF-8, so the text layer raises mid-write.
        entries["vehicle_Desc_Zed"] = "broken \ud800 text"
        expected = UnicodeEncodeError
    else:
        monkeypatch.setattr(atomic_io.os, "replace", _disk_full)
        expected = OSError

    with pytest.raises(expected):
        gen.write_ini(path, entries)

    assert path.read_bytes() == OLD_SHIPS
    assert _temps(tmp_path) == []


def test_a_failure_on_the_last_ini_leaves_every_ini_whole(gen, forge_layout, monkeypatch):
    """The real main(), two categories. The medical consumables INI is
    written last, and its swap fails: the ships INI written before it is
    new, the medical INI is the old one, and both parse in full."""
    base_ini, forge_dir = forge_layout
    out = base_ini.parent
    ships = out / "ships_desc_enhancements.ini"
    medical = out / "medical_consumables_enhancements.ini"
    ships.write_bytes(OLD_SHIPS)
    medical.write_bytes(OLD_MEDICAL)
    real_replace = os.replace

    def medical_disk_full(source, destination):
        if Path(destination).name == medical.name:
            _disk_full(source, destination)
        real_replace(source, destination)

    monkeypatch.setattr(atomic_io.os, "replace", medical_disk_full)
    new_ships = {"vehicle_Desc_New": "new ship text", "vehicle_Desc_New2": "more"}
    with patch.object(gen, "_run_gen_ships", return_value=dict(new_ships)), \
         patch.object(gen, "build_controller_lookup", return_value={}), \
         patch.object(gen, "build_armor_lookup", return_value={}):
        with pytest.raises(OSError) as raised:
            gen.main(
                base_ini_path=base_ini,
                forge_dir=forge_dir,
                categories={"medical_consumables", "ship_descs"},
                max_workers=1,
            )

    assert raised.value.errno == errno.ENOSPC
    assert gen.parse_ini(ships) == new_ships
    assert medical.read_bytes() == OLD_MEDICAL
    assert gen.parse_ini(medical) == {
        "item_Desc_Old": "old pen text", "item_Desc_Old2": "second line",
    }
    assert _temps(out) == []


# ── Stop points ─────────────────────────────────────────────────────────────

NEW_SHIPS = {"vehicle_Desc_New": "new ship text"}


def _run_main(gen, forge_layout, should_cancel, max_workers=1):
    """The real main(), ships (stubbed, with its two lookups) and medical
    consumables, on the serial path the GUI always takes."""
    base_ini, forge_dir = forge_layout
    with patch.object(gen, "_run_gen_ships", return_value=dict(NEW_SHIPS)), \
         patch.object(gen, "build_controller_lookup", return_value={}), \
         patch.object(gen, "build_armor_lookup", return_value={}):
        gen.main(
            base_ini_path=base_ini,
            forge_dir=forge_dir,
            categories={"medical_consumables", "ship_descs"},
            max_workers=max_workers,
            should_cancel=should_cancel,
        )


def _outputs(forge_layout) -> tuple[Path, Path]:
    out = forge_layout[0].parent
    return out / "ships_desc_enhancements.ini", out / "medical_consumables_enhancements.ini"


def _stops(gen, forge_layout, checks: int, max_workers=1) -> list[str]:
    """Stop at each of a clean run's *checks* in turn, with old INIs on
    disk, and return where each run stopped. Every stopped run must leave
    both INIs byte for byte as they were, and no temp file."""
    ships, medical = _outputs(forge_layout)
    wheres = []
    for stop_at in range(1, checks + 1):
        ships.write_bytes(OLD_SHIPS)
        medical.write_bytes(OLD_MEDICAL)
        asked = []

        def should_cancel():
            asked.append(1)
            return len(asked) == stop_at

        with pytest.raises(gen.GenerationStopped) as stopped:
            _run_main(gen, forge_layout, should_cancel, max_workers)
        assert len(asked) == stop_at
        assert ships.read_bytes() == OLD_SHIPS
        assert medical.read_bytes() == OLD_MEDICAL
        assert _temps(ships.parent) == []
        wheres.append(str(stopped.value))
    return wheres


def test_main_stops_at_every_checkpoint_before_writing(gen, forge_layout):
    """Closing stops a generation at its next job boundary. Each one is a
    point where main() has written no INI yet, the last being just before
    the write phase."""
    ships, medical = _outputs(forge_layout)
    asked = []
    _run_main(gen, forge_layout, lambda: asked.append(1) or False)
    assert gen.parse_ini(ships) == NEW_SHIPS
    assert gen.parse_ini(medical)

    wheres = _stops(gen, forge_layout, len(asked))

    # One per parse, the XML path index, each lookup and each generator, and
    # the last one before the write phase.
    assert wheres == [
        "after parsing base.ini",
        "after parsing the English base.ini",
        "after the xml_path_index",
        "before the controller lookup",
        "before the armor lookup",
        "before the ships generator",
        "before the medical_consumables generator",
        "before writing",
    ]


def test_the_pool_path_still_stops_before_writing(gen, forge_layout):
    """With a pool (CLI and tests only, never the GUI) the lookups and the
    generators are not checked one by one, but the check before the write
    phase still holds."""
    asked = []
    _run_main(gen, forge_layout, lambda: asked.append(1) or False, max_workers=6)

    wheres = _stops(gen, forge_layout, len(asked), max_workers=6)

    assert wheres == [
        "after parsing base.ini",
        "after parsing the English base.ini",
        "after the xml_path_index",
        "before writing",
    ]


def test_a_stop_during_the_write_phase_is_ignored(gen, forge_layout):
    """A stop that lands once the first INI is written is not even looked
    at: every INI is written, nothing raises, and the run can certify the
    whole set."""
    ships, medical = _outputs(forge_layout)
    ships.write_bytes(OLD_SHIPS)
    medical.write_bytes(OLD_MEDICAL)
    real_write_ini = gen.write_ini
    written, asked_while_writing = [], []

    def write_ini(path, entries):
        real_write_ini(path, entries)
        written.append(Path(path).name)

    def should_cancel():
        if written:
            asked_while_writing.append(written[-1])
        return bool(written)

    with patch.object(gen, "write_ini", write_ini):
        _run_main(gen, forge_layout, should_cancel)

    assert written == [ships.name, medical.name]
    assert asked_while_writing == []
    assert gen.parse_ini(ships) == NEW_SHIPS
    assert medical.read_bytes() != OLD_MEDICAL
    assert gen.parse_ini(medical)


# ── Lookup pickles ──────────────────────────────────────────────────────────

def _lookup_cache(tmp_path: Path, stamp: str) -> tuple[Path, Path]:
    forge_dir = tmp_path / "forge"
    (forge_dir / DATAFORGE_LOOKUPS_SUBPATH).mkdir(parents=True)
    (forge_dir / ".p4k_mtime").write_text(stamp, encoding="utf-8")
    return forge_dir, forge_dir / DATAFORGE_LOOKUPS_SUBPATH / "standings.pkl"


def test_a_truncated_lookup_pickle_is_rebuilt_and_logged(gen, tmp_path, caplog):
    forge_dir, cache_file = _lookup_cache(tmp_path, "stamp-1")
    key = f"{gen._LOOKUP_VERSIONS['standings']}:stamp-1"
    whole = pickle.dumps(
        (key, {"faction": list(range(5000))}), protocol=pickle.HIGHEST_PROTOCOL
    )
    cache_file.write_bytes(whole[: len(whole) // 2])
    builds = []

    def builder():
        builds.append(1)
        return {"faction": [1, 2, 3]}

    caplog.set_level(logging.INFO, logger=gen.logger.name)
    assert gen._cached_lookup(forge_dir, "standings", builder) == {"faction": [1, 2, 3]}

    assert builds == [1]
    assert [
        r for r in caplog.records
        if r.levelno == logging.INFO
        and "unreadable" in r.getMessage() and "standings" in r.getMessage()
    ]
    # The rebuilt pickle is whole: the next call is a cache hit.
    assert gen._cached_lookup(forge_dir, "standings", builder) == {"faction": [1, 2, 3]}
    assert builds == [1]


class _Unpicklable:
    def __reduce__(self):
        raise pickle.PicklingError("this value cannot be pickled")


def test_a_failed_pickle_write_keeps_the_old_pickle(gen, tmp_path):
    """The dump fails part-way (the first value is already written when the
    second refuses to pickle). An in-place write would already have
    truncated the old pickle."""
    forge_dir, cache_file = _lookup_cache(tmp_path, "stamp-new")
    old_bytes = pickle.dumps(("v0:stamp-old", {"old": 1}), protocol=pickle.HIGHEST_PROTOCOL)
    cache_file.write_bytes(old_bytes)
    value = {"big": list(range(100_000)), "bad": _Unpicklable()}

    assert gen._cached_lookup(forge_dir, "standings", lambda: value) is value

    assert cache_file.read_bytes() == old_bytes
    assert _temps(cache_file.parent) == []


# ── No write bypasses the atomic writer ─────────────────────────────────────

_WRITE_METHODS = {"write_text", "write_bytes"}
# Module-style open() calls take the path first and the mode second, like the
# builtin. Any other .open() is a Path.open(), whose mode comes first.
_MODULE_OPENERS = {"io", "codecs", "gzip", "bz2", "lzma", "builtins"}


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    elts = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(
        isinstance(e, ast.Name) and e.id in ("ImportError", "ModuleNotFoundError")
        for e in elts
    )


def _fallback_node_ids(tree: ast.Module) -> set[int]:
    """Every node inside a module-level ``except ImportError`` handler."""
    ids: set[int] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Try):
            for handler in stmt.handlers:
                if _catches_import_error(handler):
                    for node in handler.body:
                        ids.update(id(n) for n in ast.walk(node))
    return ids


def _open_mode(call: ast.Call):
    for kw in call.keywords:
        if kw.arg == "mode":
            return kw.value
    func = call.func
    module_style = isinstance(func, ast.Name) or (
        isinstance(func.value, ast.Name) and func.value.id in _MODULE_OPENERS
    )
    position = 1 if module_style else 0
    return call.args[position] if len(call.args) > position else None


def _in_place_writes(source: str, skip_fallbacks: bool = True) -> list[str]:
    tree = ast.parse(source)
    skipped = _fallback_node_ids(tree) if skip_fallbacks else set()
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in skipped:
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _WRITE_METHODS:
            found.append(f"line {node.lineno}: .{func.attr}(")
            continue
        is_open = (isinstance(func, ast.Name) and func.id == "open") or (
            isinstance(func, ast.Attribute) and func.attr == "open"
        )
        if not is_open:
            continue
        mode = _open_mode(node)
        if mode is None:
            continue   # the default mode reads
        if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
            found.append(f"line {node.lineno}: open() with a mode the guard cannot read")
        elif set(mode.value) & set("wax+"):
            found.append(f"line {node.lineno}: open(..., {mode.value!r})")
    return found


def test_every_generator_write_goes_through_the_atomic_writer():
    source = SCRIPT.read_text(encoding="utf-8")
    assert _in_place_writes(source) == [], (
        "write generator output with atomic_writer() or atomic_write_text() "
        "(src/utils/atomic_io.py), never in place"
    )
    # The guard reads something: the fallbacks it skips really write in
    # place, and it finds those writes when it is told not to skip them.
    fallback_writes = _in_place_writes(source, skip_fallbacks=False)
    assert len(fallback_writes) >= 2, fallback_writes


@pytest.mark.parametrize("snippet", [
    "p.write_text('x')",
    "p.write_bytes(b'x')",
    "open(p, 'w')",
    "open(p, 'a', encoding='utf-8')",
    "open(p, mode='wb')",
    "open(p, 'r+')",
    "open(p, mode)",
    "p.open('w')",
    "p.open(mode='xb')",
    "io.open(p, 'w')",
    "def f():\n    try:\n        import x\n    except ImportError:\n        p.write_text('x')\n",
])
def test_the_guard_catches_each_in_place_write(snippet):
    assert _in_place_writes(snippet)


@pytest.mark.parametrize("snippet", [
    "open(p)",
    "open(p, 'rb')",
    "p.open('rb')",
    "p.open(encoding='utf-8')",
    "io.open(p)",
    "f.write('x')",
    "try:\n    import x\nexcept ImportError:\n    p.write_text('x')\n    open(p, 'wb')\n",
    "try:\n    import x\nexcept (OSError, ImportError):\n    open(p, mode)\n",
])
def test_the_guard_passes_reads_and_the_fallbacks(snippet):
    assert _in_place_writes(snippet) == []
