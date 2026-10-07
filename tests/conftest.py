"""
Pytest configuration and fixtures for SC Localization Editor tests

Provides:
- Temporary directories for file-based tests
- Mock fixtures for external dependencies
- Logging configuration
- The run's one QApplication (qapp)
"""

import pytest
import tempfile
import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# GUI tests run headless. Set here, before any test module is imported, so no
# module needs its own copy.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def no_real_install_detection_inputs():
    """First-run install detection (settings._scan_common_sc_install_locations)
    reads the RSI Launcher log under the real %APPDATA% and lists the top of
    every fixed drive. Any test that
    resolves an install root with nothing saved reaches both, and on a
    developer's machine either can find their real install. Stub them for the
    whole session, so module-scoped fixtures that build a MainWindow are
    covered too; tests of those inputs patch in their own (see
    test_sc_install_root.py), and their patches undo back to these stubs.
    Tests import settings both as src.utils.settings and as utils.settings,
    two separate module objects, so each one that is loaded gets patched."""
    try:
        import src.utils.settings  # noqa: F401  (load it so it is always patched)
    except ImportError:  # no PyQt6: nothing in this run can reach detection
        pass

    with pytest.MonkeyPatch.context() as patcher:
        for name in ("src.utils.settings", "utils.settings"):
            module = sys.modules.get(name)
            if module is None:
                continue
            patcher.setattr(module, "read_launcher_installs", lambda log_path=None: ({}, False))
            patcher.setattr(
                module, "iter_shallow_sc_install_locations", lambda drives=None: iter(())
            )
        yield


# The run's one QApplication, once _session_qapp has made it (at the first
# qapp request, or before the first test in a run with GUI tests).
_SESSION_QAPP: list = []


@pytest.fixture(scope="session")
def qapp():
    """The run's only QApplication. Request this in any test or fixture that
    builds a widget, and never create or destroy a QApplication yourself.

    It used to be one module-scoped fixture per GUI test module, each doing
    ``QApplication.instance() or QApplication([])``. Nothing else held the
    app, so it was destroyed at the end of the module that made it and the
    next GUI module built a new one: 15 apps in one full run. Qt expects one
    application object per process, and PyQt6 depends on that. Once the first
    app is gone, PyQt6 no longer notices when Qt deletes an object that Qt
    itself created (a view's own scroll bars, menu actions, a status bar), so
    its Python wrapper keeps pointing at freed memory. When Qt reuses that
    memory for a new object, PyQt6 hands back the old wrapper for it. That is
    what crashed test_tab_scrollbar_placement with an access violation:
    findChildren returned a dead QScrollBar wrapper sitting on a live
    QVBoxLayout of the new window, and isVisible() read the layout as a
    widget. The app's teardown also deleted the windows tests/gui_window.py
    keeps alive.
    """
    return _session_qapp()


def _session_qapp():
    if not _SESSION_QAPP:
        from PyQt6.QtWidgets import QApplication

        _SESSION_QAPP.append(QApplication.instance() or QApplication([]))
    return _SESSION_QAPP[0]


@pytest.fixture(scope="session", autouse=True)
def qapp_before_the_first_gui_test():
    """In a run with GUI tests, make the app before the first test, so it is
    already there whatever any module does. Collection has imported every
    test module by now, so Qt widgets being loaded means the run has GUI
    tests. A run without them (pytest tests/test_core.py) builds no app."""
    if "PyQt6.QtWidgets" in sys.modules:
        _session_qapp()
    yield
    _SESSION_QAPP.clear()


def _check_qapp(when):
    if "PyQt6.QtWidgets" not in sys.modules:
        return  # nothing in this run has touched Qt widgets
    from PyQt6 import sip
    from PyQt6.QtWidgets import QApplication

    current = QApplication.instance()
    if not _SESSION_QAPP:
        assert current is None, (
            f"a QApplication the qapp fixture did not make existed {when}. "
            "Request qapp from tests/conftest.py instead of creating one"
        )
        return
    app = _SESSION_QAPP[0]
    assert not sip.isdeleted(app) and current is app, (
        f"the run's QApplication was destroyed or replaced {when}. Every "
        "test must share the one from the qapp fixture in tests/conftest.py"
    )


@pytest.fixture(scope="module", autouse=True)
def qapp_still_in_place(request):
    """Fail as soon as a test has destroyed or replaced the run's
    QApplication, or made its own, instead of leaving it to the intermittent
    crash that losing it causes (see qapp). Checked when each module starts
    and again when it ends, so the module that did it is the one that fails,
    the run's last module included."""
    module = request.module.__name__
    _check_qapp(f"when {module} started")
    yield
    _check_qapp(f"after {module} ran")


@pytest.fixture
def temp_dir():
    """Provide a temporary directory that's cleaned up after test"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_ini_file(temp_dir):
    """Provide a sample INI file with test data"""
    ini_path = os.path.join(temp_dir, 'sample.ini')
    content = """vehicle_NameHunter=Drake Cutlass Black
vehicle_DescHunter=A versatile fighter spacecraft
item_NameSHLD_Aspirum=Aspirum Shield
item_NamePOWR_TR1=TR1 Power Plant
items_commodities_AluminumOre=Aluminum Ore
contract_001_name=First Contract
item_Name_GMNL_rifle=Gemini Rifle
"""
    with open(ini_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return ini_path


@pytest.fixture
def sample_sources():
    """Provide sample source dictionaries for merge testing"""
    return {
        'global': {
            'vehicle_NameHunter': 'Drake Cutlass Black',
            'vehicle_NameAvenger': 'Aegis Avenger',
            'item_NameSHLD_Aspirum': 'Aspirum Shield',
            'custom_key_1': 'value1',
        },
        'contracts': {
            'contract_001_name': 'Mining Contract',
            'contract_002_name': 'Delivery Contract',
            'item_NameSHLD_Aspirum': 'Aspirum Energy Shield',  # Override
        },
        'ships': {
            'vehicle_DescHunter': 'Max Speed: 210 m/s',
            'vehicle_DescAvenger': 'Max Speed: 180 m/s',
        },
        'user': {}
    }


@pytest.fixture
def mock_game_path(temp_dir):
    """Provide a mock game installation path"""
    game_path = os.path.join(temp_dir, 'StarCitizen', 'LIVE', 'data', 'Localization', 'english')
    os.makedirs(game_path, exist_ok=True)

    # Create a dummy global.ini
    ini_path = os.path.join(game_path, 'global.ini')
    with open(ini_path, 'w', encoding='utf-8') as f:
        f.write('vehicle_NameHunter=Drake Cutlass Black\n')

    return game_path


@pytest.fixture
def mock_cache_dir(temp_dir):
    """Provide a mock cache directory structure"""
    cache_dir = os.path.join(temp_dir, 'Documents', 'Smart Citizen', 'cache')
    os.makedirs(cache_dir, exist_ok=True)

    # Create subdirectories
    for subdir in ['backups', 'dataforge', 'dataforge/entity', 'dataforge/entities', 'dataforge/ships']:
        os.makedirs(os.path.join(cache_dir, subdir), exist_ok=True)

    return cache_dir


@pytest.fixture
def mock_p4k_path(temp_dir):
    """Provide a mock P4K file path"""
    p4k_path = os.path.join(temp_dir, 'Data.p4k')
    # Create a dummy p4k file (not real, just for path testing)
    with open(p4k_path, 'wb') as f:
        f.write(b'DUMMY_P4K_DATA')
    return p4k_path


def pytest_collection_modifyitems(config, items):
    """Auto-mark tests by their location"""
    for item in items:
        # Mark all tests in test_core.py as unit tests by default
        if 'test_core.py' in str(item.fspath):
            if 'Error' in item.nodeid:
                item.add_marker(pytest.mark.critical)
            elif 'Merge' in item.nodeid or 'StringEntry' in item.nodeid:
                item.add_marker(pytest.mark.critical)
            else:
                item.add_marker(pytest.mark.unit)

        # Mark all tests in test_pak_extraction.py appropriately
        if 'test_pak_extraction.py' in str(item.fspath):
            if 'Cache' in item.nodeid or 'Extract' in item.nodeid:
                item.add_marker(pytest.mark.critical)
                item.add_marker(pytest.mark.integration)
            else:
                item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def test_data_dir():
    """Provide path to test data directory"""
    tests_dir = os.path.dirname(__file__)
    data_dir = os.path.join(tests_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


class TestReporter:
    """Helper class for test reporting"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def record_pass(self, test_name):
        self.passed += 1
        print(f"✓ {test_name}")

    def record_fail(self, test_name, error):
        self.failed += 1
        print(f"✗ {test_name}: {error}")

    def summary(self):
        total = self.passed + self.failed + self.skipped
        return f"Results: {self.passed} passed, {self.failed} failed, {self.skipped} skipped out of {total}"


@pytest.fixture
def reporter():
    """Provide a test reporter fixture"""
    return TestReporter()


# Suppress warnings that clutter test output
def pytest_configure(config):
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    warnings.filterwarnings("ignore", category=PendingDeprecationWarning)
