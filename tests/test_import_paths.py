"""#510: tests import Smart Citizen's modules through ``src.`` only.

Production code imports everything as ``src.<package>.<module>``. A test that
imported the same file by a shorter name (``from utils.pak_extractor import
...``) loaded a second copy of the module, with its own globals, so a fake or
a patch set on one copy never reached code that used the other. Osiris's
review of #481 found that in ``test_pak_extraction.py``, and ``conftest.py``
had to stub install detection on two copies of ``settings``.

``pytest.ini`` now puts only the repo root on the path, so a short import
fails at once. These checks say why, and catch what would not fail: a patch
target or logger name given as a string, and any module from ``src/``
loaded under a short name, for example after a test file put ``src`` back on
the path. A ``sys.path`` line on its own is not checked: it does no harm
while nothing imports by the short name.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TESTS = ROOT / "tests"
# The packages under src/ (utils, parser, models, merger, gui), read from disk
# so a new one is covered without touching this file.
SHORT_NAMES = frozenset(p.name for p in SRC.iterdir() if (p / "__init__.py").is_file())
_SHORT_STRING = re.compile(rf"^(?:{'|'.join(sorted(SHORT_NAMES))})\.[A-Za-z_]")


def _offenders(source: str) -> list:
    """Each import of a ``src/`` package by its short name, and each string
    passed to a call (a patch target, a logger name, a sys.modules key) that
    names one by its short name. Docstrings and other strings are not calls'
    arguments, so they pass."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.split(".")[0] in SHORT_NAMES:
                found.append(f"line {node.lineno}: from {node.module} import")
        elif isinstance(node, ast.Import):
            found.extend(f"line {node.lineno}: import {alias.name}" for alias in node.names
                         if alias.name.split(".")[0] in SHORT_NAMES)
        elif isinstance(node, ast.Call):
            values = list(node.args) + [keyword.value for keyword in node.keywords]
            found.extend(f"line {value.lineno}: {value.value!r}" for value in values
                         if isinstance(value, ast.Constant) and isinstance(value.value, str)
                         and _SHORT_STRING.match(value.value))
    return found


def _short_name_copies(modules: dict) -> list:
    """The names in ``modules`` (a copy of ``sys.modules``) under which a
    file from ``src/`` is loaded without ``src.``, each one a second copy."""
    found = []
    for name, module in modules.items():
        file = getattr(module, "__file__", None)
        if not file or name == "src" or name.startswith("src."):
            continue
        try:
            Path(file).resolve().relative_to(SRC)
        except ValueError:
            continue
        found.append(name)
    return found


class TestTheGuard:
    def test_it_knows_the_packages(self):
        assert {"utils", "parser", "models", "merger", "gui"} <= SHORT_NAMES

    @pytest.mark.parametrize("source", [
        "from utils.settings import AppSettings\n",
        "from utils import build_mode\n",
        "def f():\n    from gui.config_tab import X\n",
        "import parser.ini_parser\n",
        "import models.string_model as sm\n",
        "patch('utils.pak_extractor._win_long_path')\n",
        "monkeypatch.setattr('merger.ini_merger.merge_ini_files', None)\n",
        "caplog.at_level(10, logger='utils.pak_extractor')\n",
        "sys.modules.get('utils.settings')\n",
        "patch(target='utils.win_paths.win_long_path')\n",
    ])
    def test_it_sees_each_short_spelling(self, source):
        assert _offenders(source)

    @pytest.mark.parametrize("source", [
        "from src.utils.settings import AppSettings\n",
        "import src.utils.pak_extractor as pe\n",
        "from . import helper\n",
        "from .utils import helper\n",
        "patch('src.utils.pak_extractor._win_long_path')\n",
        "caplog.at_level(10, logger='src.utils.pak_extractor')\n",
        '"""The legacy utils.pak_extractor path would load a second copy."""\n',
        "x = 'utils.pak_extractor is a module'\n",
        "tr('config.data_folder_label')\n",
        "pytest.param(\"@patch('utils.pak_extractor.subprocess.run')\\n\")\n",
    ])
    def test_it_passes_the_full_names_and_other_strings(self, source):
        assert _offenders(source) == []

    def test_it_sees_a_second_copy_loaded(self):
        i18n = SimpleNamespace(__file__=str(SRC / "utils" / "i18n.py"))
        assert _short_name_copies({"src.utils.i18n": i18n, "utils.i18n": i18n}) == ["utils.i18n"]

    def test_it_passes_the_one_copy_and_other_modules(self):
        modules = {
            "src": SimpleNamespace(__file__=str(SRC / "__init__.py")),
            "src.utils.i18n": SimpleNamespace(__file__=str(SRC / "utils" / "i18n.py")),
            "pytest": pytest,
            "a_namespace_package": SimpleNamespace(__file__=None),
            "a_builtin": SimpleNamespace(),
        }
        assert _short_name_copies(modules) == []


def test_no_test_file_names_a_package_by_its_short_name():
    found = {path.name: hits for path in sorted(TESTS.glob("*.py"))
             if (hits := _offenders(path.read_text(encoding="utf-8")))}
    assert found == {}


def test_pytest_puts_only_the_repo_root_on_the_path():
    lines = (ROOT / "pytest.ini").read_text(encoding="utf-8").splitlines()
    entries = [line.split("=", 1)[1].split() for line in lines
               if line.split("=", 1)[0].strip() == "pythonpath"]
    assert entries == [["."]]


def test_no_module_from_src_is_loaded_under_a_short_name():
    """Collection has imported every test module by now, so a second copy
    loaded anywhere in this run shows here, a src/ module importing another
    by its short name included."""
    assert _short_name_copies(dict(sys.modules)) == []
