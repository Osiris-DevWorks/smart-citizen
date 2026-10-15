"""#416: the starter blueprints every player owns from their first fabricator.

The game grants them with no "Received Blueprint" notification and no mission
offers them, so before this they showed in neither Blueprint Tracker list:
not Available (only mission rewards were listed) and not Owned (the log scan
never sees them). Now they are in the catalogue under their own label, and a
log scan adds each one to the Owned set once.

Two halves:

- ``blueprint_meta`` (Qt-free): DEFAULT_OWNED_BLUEPRINTS joins the catalogue,
  named by loc key from the loaded strings (the game's wording, the selected
  language, any Tag Builder tag stripped) with the English name as fallback,
  and ``default_owned_blueprints`` names them exactly as the catalogue does.
- ``MainWindow`` seeding, driven on stub selves (same pattern as
  test_blueprint_auto_scan.py): one-shot per item, deferred until strings have
  loaded, reported in the scan summary, never raising, and followed by the
  background already-applied check.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import src.gui.main_window as main_window  # noqa: E402
from src.gui.blueprint_tracker_tab import BlueprintTrackerTab  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.utils import blueprint_meta  # noqa: E402
from src.utils.blueprint_meta import (  # noqa: E402
    DEFAULT_OWNED_BLUEPRINTS,
    DEFAULT_OWNED_MISSION_LABEL,
    build_blueprint_metadata,
    default_owned_blueprints,
)
from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ENGLISH_NAMES = [english for _key, english in DEFAULT_OWNED_BLUEPRINTS]
ALL_KEYS = frozenset(key for key, _ in DEFAULT_OWNED_BLUEPRINTS)
NEVER = (frozenset(), False)
ALL_SEEDED = (ALL_KEYS, False)


@dataclass
class _Entry:
    key: str
    original_value: str
    category: str = "Other"


def _starter_entries(overrides=None):
    """One loaded entry per starter key, valued with its English name unless
    *overrides* ({key: value}) says otherwise."""
    overrides = overrides or {}
    return [
        _Entry(key, overrides.get(key, english), "Gear")
        for key, english in DEFAULT_OWNED_BLUEPRINTS
    ]


def _seed():
    return AppSettings.get_default_blueprints_seed()


def _mark_pending(seeded=frozenset()):
    AppSettings.set_default_blueprints_seed(seeded, pending=True)


def _mark_all_seeded():
    AppSettings.set_default_blueprints_seed(ALL_KEYS, pending=False)


@pytest.fixture
def json_backend(tmp_path):
    """Swap AppSettings._backend for a tmp JsonSettings so each test is hermetic."""
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


NINTH_KEY = "item_Name_test_starter_99"
NINTH_NAME = "Test Starter"


@pytest.fixture
def ninth_starter(monkeypatch):
    """A starter declared in a later release: appended to the list (and its
    lookup) the way a maintainer would extend it."""
    extended = DEFAULT_OWNED_BLUEPRINTS + ((NINTH_KEY, NINTH_NAME),)
    monkeypatch.setattr(blueprint_meta, "DEFAULT_OWNED_BLUEPRINTS", extended)
    monkeypatch.setattr(
        blueprint_meta, "_DEFAULT_OWNED_KEYS", {k.lower(): k for k, _ in extended},
    )
    yield


# ── The list itself ─────────────────────────────────────────────────────────


class TestTheList:
    def test_holds_exactly_the_reported_starter_items(self):
        """The eight items the issue and the follow-up named, under the
        game's own names (the magazines carry their capacity in-game)."""
        assert ENGLISH_NAMES == [
            "P4-AR Rifle",
            "P4-AR Magazine (40 cap)",
            "S-38 Pistol",
            "S-38 Magazine (20 cap)",
            "Field Recon Suit Arms",
            "Field Recon Suit Core",
            "Field Recon Suit Helmet",
            "Field Recon Suit Legs",
        ]

    def test_keys_are_unique_ignoring_case(self):
        keys = [key.lower() for key, _ in DEFAULT_OWNED_BLUEPRINTS]
        assert len(keys) == len(set(keys))

    def test_every_key_is_an_item_name_key(self):
        """Loc keys, not display names, so the name can follow the strings."""
        for key, _ in DEFAULT_OWNED_BLUEPRINTS:
            assert key.startswith("item_Name"), key


# ── In the catalogue ────────────────────────────────────────────────────────


class TestInTheCatalogue:
    def test_present_with_nothing_loaded_under_english_names(self):
        meta = build_blueprint_metadata([])
        for name in ENGLISH_NAMES:
            assert name in meta, f"{name!r} missing from blueprint metadata"
            assert meta[name].missions == frozenset({DEFAULT_OWNED_MISSION_LABEL})
            assert meta[name].tagged_name == name

    def test_types_come_from_the_loc_keys(self):
        meta = build_blueprint_metadata([])
        assert {n: meta[n].type for n in ENGLISH_NAMES} == {
            "P4-AR Rifle": "FPS Weapon",
            "P4-AR Magazine (40 cap)": "Ammo",
            "S-38 Pistol": "FPS Weapon",
            "S-38 Magazine (20 cap)": "Ammo",
            "Field Recon Suit Arms": "Armor",
            "Field Recon Suit Core": "Armor",
            "Field Recon Suit Helmet": "Armor",
            "Field Recon Suit Legs": "Armor",
        }

    def test_name_follows_the_loaded_string_not_the_fallback(self):
        """A CIG rename reaches the tracker without touching the list."""
        mag = "item_Namebehr_rifle_ballistic_01_mag"
        meta = build_blueprint_metadata(_starter_entries({mag: "P4-AR Mag (40 rounds)"}))
        assert "P4-AR Mag (40 rounds)" in meta
        assert "P4-AR Magazine (40 cap)" not in meta

    def test_name_follows_the_selected_language(self):
        helmet = "item_Name_cds_light_helmet_01"
        meta = build_blueprint_metadata(_starter_entries({helmet: "Casco Field Recon"}))
        assert meta["Casco Field Recon"].type == "Armor"
        assert "Field Recon Suit Helmet" not in meta

    def test_a_tag_builder_tag_is_stripped_via_the_stock_value(self):
        """A bracket-free tag that only the stock-value diff can remove, so
        this fails if the stock value stops reaching the normalizer."""
        rifle = "item_Namebehr_rifle_ballistic_01"
        entries = _starter_entries({rifle: "P4-AR Rifle BALL-AR"})
        meta = build_blueprint_metadata(entries, default_values={rifle: "P4-AR Rifle"})
        assert meta["P4-AR Rifle"].tagged_name == "P4-AR Rifle BALL-AR"
        assert "P4-AR Rifle BALL-AR" not in meta

    def test_key_match_ignores_capitalisation(self):
        entries = [_Entry("ITEM_NAMEBEHR_PISTOL_BALLISTIC_01", "S-38 Pistole")]
        meta = build_blueprint_metadata(entries)
        assert "S-38 Pistole" in meta
        assert "S-38 Pistol" not in meta

    def test_an_empty_loaded_value_falls_back_to_english(self):
        legs = "item_Name_cds_light_armor_01_legs"
        meta = build_blueprint_metadata(_starter_entries({legs: ""}))
        assert "Field Recon Suit Legs" in meta

    def test_a_mission_offered_starter_keeps_its_missions_and_gains_the_label(self):
        entries = _starter_entries() + [
            _Entry("Some_Title_001", "Some Mission", "Missions"),
            _Entry(
                "Some_Desc_001",
                "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- S-38 Pistol",
                "Missions",
            ),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["S-38 Pistol"].missions == frozenset(
            {"Some Mission", DEFAULT_OWNED_MISSION_LABEL}
        )

    def test_entries_may_be_a_one_shot_iterator(self):
        """Pass 1 collects the starter values, so a generator is read once
        and still names the starters from the loaded strings."""
        rifle = "item_Namebehr_rifle_ballistic_01"
        meta = build_blueprint_metadata(iter(_starter_entries({rifle: "Fusil P4-AR"})))
        assert "Fusil P4-AR" in meta
        assert "P4-AR Rifle" not in meta


class TestNamesMatchTheCatalogue:
    """The Owned set gets default_owned_blueprints' names and the tracker
    lists the catalogue's, so the two must agree or a seeded starter would
    show in both lists at once."""

    @pytest.mark.parametrize("kwargs", [
        {},
        {"enclosings": (("(", ")"),)},
        {"default_values": {"item_Namebehr_rifle_ballistic_01": "P4-AR Rifle"}},
    ])
    def test_same_names_for_the_same_inputs(self, kwargs):
        entries = _starter_entries({
            "item_Namebehr_rifle_ballistic_01": "(AR) P4-AR Rifle",
            "item_Name_cds_light_helmet_01": "Casco Field Recon",
        })
        names = {nm for _key, nm in default_owned_blueprints(entries, **kwargs)}
        meta = build_blueprint_metadata(entries, **kwargs)
        assert names <= set(meta)
        assert {n for n, item in meta.items()
                if DEFAULT_OWNED_MISSION_LABEL in item.missions} == names

    def test_seeded_starters_leave_the_available_list(self):
        entries = _starter_entries()
        meta = build_blueprint_metadata(entries)
        owned = {nm for _key, nm in default_owned_blueprints(entries)}
        available = BlueprintTrackerTab._available_blueprints(meta, owned)
        assert not set(available) & owned

    def test_two_keys_with_one_name_are_listed_once(self):
        entries = _starter_entries({
            "item_Namebehr_pistol_ballistic_01_mag": "S-38 Pistol",
        })
        names = [nm for _key, nm in default_owned_blueprints(entries)]
        assert names.count("S-38 Pistol") == 1


# ── The seed marker ─────────────────────────────────────────────────────────


class TestSeedMarkerSetting:
    def test_default_is_none_seeded_and_nothing_waiting(self, json_backend):
        assert _seed() == NEVER

    @pytest.mark.parametrize("seeded, pending", [
        (ALL_KEYS, False),
        (frozenset(), True),
        (frozenset({"item_Namebehr_pistol_ballistic_01"}), True),
        (frozenset(), False),
    ])
    def test_round_trips(self, json_backend, seeded, pending):
        AppSettings.set_default_blueprints_seed(seeded, pending=pending)
        assert _seed() == (seeded, pending)

    def test_stored_as_sorted_json(self, json_backend):
        """Ten keys, so a set that happens to iterate in sorted order (string
        hashing is randomised per run) can't make an unsorted write pass."""
        keys = [f"key_{c}" for c in "jihgfedcba"]
        AppSettings.set_default_blueprints_seed(set(keys), pending=True)
        expected = '{"seeded": [%s], "pending": true}' % ", ".join(
            f'"{k}"' for k in sorted(keys))
        assert json_backend.value(AppSettings.DEFAULT_BLUEPRINTS_SEED) == expected

    @pytest.mark.parametrize("raw", [
        "banana", "done", "pending", "[]", "42", '{"seeded": "item_X"}',
    ])
    def test_an_unreadable_value_reads_as_none_seeded(self, json_backend, raw):
        """A damaged value only means the starters are offered once more."""
        json_backend.setValue(AppSettings.DEFAULT_BLUEPRINTS_SEED, raw)
        assert _seed() == NEVER

    def test_stray_entries_inside_a_readable_value_are_dropped(self, json_backend):
        json_backend.setValue(
            AppSettings.DEFAULT_BLUEPRINTS_SEED,
            '{"seeded": [1, "item_X", null], "pending": "yes"}',
        )
        assert _seed() == (frozenset({"item_X"}), False)


class TestSeedMarkerInABackup:
    """The marker describes the owned set, so a backup carries it under the
    same rule as owned_items (only once stored) and an import takes it only
    together with owned_items."""

    SEED = AppSettings.DEFAULT_BLUEPRINTS_SEED

    def test_exported_only_once_stored_like_owned_items(self, json_backend):
        assert self.SEED not in AppSettings.export_all_values()
        assert AppSettings.OWNED_ITEMS not in AppSettings.export_all_values()
        AppSettings.set_owned_items({"Agni"} | set(ENGLISH_NAMES))
        _mark_all_seeded()
        exported = AppSettings.export_all_values()
        assert AppSettings._parse_default_blueprints_seed(exported[self.SEED]) == ALL_SEEDED
        assert AppSettings.OWNED_ITEMS in exported

    def test_a_round_trip_keeps_the_marker_with_its_owned_set(self, json_backend):
        AppSettings.set_owned_items({"Agni"})
        _mark_all_seeded()
        backup = AppSettings.export_all_values()
        AppSettings.set_default_blueprints_seed(frozenset(), pending=False)
        AppSettings.import_values(backup)
        assert _seed() == ALL_SEEDED

    def test_an_owned_set_from_before_2_5_resets_the_marker(self, json_backend, fake_boxes):
        """The review finding: a 2.4 backup replaced Owned without the
        starters and left the marker set, so no scan added them back."""
        AppSettings.set_owned_items({"Agni"} | set(ENGLISH_NAMES))
        _mark_all_seeded()

        AppSettings.import_values({AppSettings.OWNED_ITEMS: '["Agni", "Colossus"]'})

        assert _seed() == NEVER
        _Stub(entries=_starter_entries()).finish_scan()
        assert AppSettings.get_owned_items() == {"Agni", "Colossus"} | set(ENGLISH_NAMES)

    def test_a_backup_without_an_owned_set_leaves_the_marker_alone(self, json_backend, fake_boxes):
        """The other half: a stray marker must not undo the one-shot and bring
        back a starter the user moved out of Owned."""
        AppSettings.set_owned_items(set(ENGLISH_NAMES) - {"S-38 Pistol"})
        _mark_all_seeded()

        AppSettings.import_values({
            self.SEED: AppSettings._encode_default_blueprints_seed(frozenset(), False),
            AppSettings.THEME: "dark",
        })

        assert _seed() == ALL_SEEDED
        _Stub(entries=_starter_entries()).finish_scan()
        assert "S-38 Pistol" not in AppSettings.get_owned_items()

    @pytest.mark.parametrize("seeded, pending", [
        (ALL_KEYS, False),
        (frozenset({"item_Namebehr_pistol_ballistic_01"}), True),
    ])
    def test_a_backup_marker_is_taken_with_its_owned_set(self, json_backend, seeded, pending):
        AppSettings.import_values({
            AppSettings.OWNED_ITEMS: "[]",
            self.SEED: AppSettings._encode_default_blueprints_seed(seeded, pending),
        })
        assert _seed() == (seeded, pending)

    @pytest.mark.parametrize("stored", [42, "done", "banana"])
    def test_a_damaged_backup_marker_reads_as_none_seeded(self, json_backend, stored):
        _mark_all_seeded()
        AppSettings.import_values({AppSettings.OWNED_ITEMS: "[]", self.SEED: stored})
        assert _seed() == NEVER

    @pytest.mark.parametrize("stored", [
        None, 42, "done", '{"seeded": ["b", 7, "a"], "pending": true}',
    ])
    def test_an_imported_marker_is_stored_cleaned(self, json_backend, stored):
        """What the import writes is the cleaned form, so a damaged marker
        does not travel on into the next backup."""
        values = {AppSettings.OWNED_ITEMS: "[]"}
        if stored is not None:
            values[self.SEED] = stored
        AppSettings.import_values(values)
        expected = AppSettings._encode_default_blueprints_seed(*_seed())
        assert json_backend.value(self.SEED) == expected


# ── MainWindow seeding ──────────────────────────────────────────────────────


class _FakeTrackerTab:
    def __init__(self):
        self.marked_clean = False
        self.known_item_names = None

    def reset_force_rescan_checkbox(self):
        pass

    def mark_owned_clean(self):
        self.marked_clean = True

    def set_scan_logs_enabled(self, enabled):
        pass

    def set_known_item_names(self, names):
        self.known_item_names = names


class _FakeStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message):
        self.messages.append(message)


class _FakeMessageBox:
    """Stands in for QMessageBox (no QApplication needed); records the box."""

    instances = []

    def __init__(self, parent=None):
        self.text = None
        self.detailed_text = None
        _FakeMessageBox.instances.append(self)

    @staticmethod
    def information(parent, title, text):
        box = _FakeMessageBox(parent)
        box.text = text

    def setIcon(self, icon):
        pass

    def setWindowTitle(self, title):
        pass

    def setText(self, text):
        self.text = text

    def setDetailedText(self, text):
        self.detailed_text = text

    def exec(self):
        pass

    class Icon:
        Information = "information"


class _Stub:
    """Carries what the scan finish, the seed and the metadata rebuild touch."""

    _seed_default_owned_blueprints = MainWindow._seed_default_owned_blueprints
    _rebuild_blueprint_metadata = MainWindow._rebuild_blueprint_metadata
    _repair_foreign_owned_names = MainWindow._repair_foreign_owned_names
    _report_blueprints_added = MainWindow._report_blueprints_added
    _queue_deferred_starter_report = MainWindow._queue_deferred_starter_report
    _flush_deferred_starter_report = MainWindow._flush_deferred_starter_report

    def __init__(self, entries=(), log_names=(), silent=False):
        self.entries = list(entries)
        self.default_values = {}
        self._bp_scan_silent = silent
        self._bp_scan_new_names = set(log_names)
        self._status_bar = _FakeStatusBar()
        self.blueprint_tracker_tab = _FakeTrackerTab()
        self.recompute_calls = 0
        self.events = []
        self._deferred_starter_report = []
        self._close_committed = False
        self._loader_worker = None
        self._enhancements_worker = None
        self._forge_worker = None
        self._p4k_worker = None
        self._simple_run_active = False

    def statusBar(self):
        return self._status_bar

    def _recompute_owned(self):
        self.recompute_calls += 1
        self.events.append("recompute")

    def _refresh_apply_dirty_after_reload(self):
        self.events.append("applied-check")

    def _bp_header(self):
        return None

    def finish_scan(self):
        MainWindow._finish_blueprint_scan_queue(self)

    def load(self, modal_step=None):
        """What a load does here: rebuild the metadata (which finishes a
        pending seed), re-weave the Owned tags, run whatever modal step the
        load opens (*modal_step*, e.g. the enhancement categories prompt,
        whose event loop runs queued calls), and queue the report last."""
        self._rebuild_blueprint_metadata()
        self._recompute_owned()
        if modal_step is not None:
            modal_step()
        self._queue_deferred_starter_report()


@pytest.fixture
def fake_boxes(monkeypatch):
    _FakeMessageBox.instances = []
    monkeypatch.setattr("src.gui.main_window.QMessageBox", _FakeMessageBox)
    monkeypatch.setattr("src.gui.main_window._relabel_details_button", lambda *a, **k: None)
    yield _FakeMessageBox.instances


class _FakeTimer:
    """Holds QTimer.singleShot callbacks until a test runs them, standing in
    for the event loop turn after a load."""

    queued = []

    @staticmethod
    def singleShot(msec, fn):
        _FakeTimer.queued.append(fn)


@pytest.fixture(autouse=True)
def queued_calls(monkeypatch):
    _FakeTimer.queued = []
    monkeypatch.setattr("src.gui.main_window.QTimer", _FakeTimer)
    yield _FakeTimer.queued


def _run_queued(queued):
    while queued:
        queued.pop(0)()


class TestFirstScanSeeds:
    def test_first_scan_adds_every_starter_and_reports_them(self, json_backend, fake_boxes):
        AppSettings.set_owned_items(set())
        stub = _Stub(entries=_starter_entries(), log_names=["R97 Shotgun"])
        stub.finish_scan()

        assert AppSettings.get_owned_items() == set(ENGLISH_NAMES) | {"R97 Shotgun"}
        assert _seed() == ALL_SEEDED
        assert stub.recompute_calls == 1
        assert stub.blueprint_tracker_tab.marked_clean is True
        (box,) = fake_boxes
        assert set(box.detailed_text.split("\n")) == set(ENGLISH_NAMES) | {"R97 Shotgun"}

    def test_a_scan_that_finds_nothing_still_adds_the_starters(self, json_backend, fake_boxes):
        """Without this the summary would say "no new blueprints" while
        eight had just been added."""
        stub = _Stub(entries=_starter_entries())
        stub.finish_scan()

        assert AppSettings.get_owned_items() == set(ENGLISH_NAMES)
        (box,) = fake_boxes
        assert box.detailed_text is not None
        assert str(len(ENGLISH_NAMES)) in box.text

    def test_silent_auto_scan_reports_them_in_the_status_bar(self, json_backend, fake_boxes):
        AppSettings.set_auto_scan_show_popup_enabled(False)
        stub = _Stub(entries=_starter_entries(), silent=True)
        stub.finish_scan()

        assert AppSettings.get_owned_items() == set(ENGLISH_NAMES)
        assert fake_boxes == []
        assert len(stub._status_bar.messages) == 1
        assert str(len(ENGLISH_NAMES)) in stub._status_bar.messages[0]

    def test_starters_already_owned_are_not_reported_again(self, json_backend, fake_boxes):
        AppSettings.set_owned_items({"S-38 Pistol", "P4-AR Rifle"})
        stub = _Stub(entries=_starter_entries())
        stub.finish_scan()

        assert AppSettings.get_owned_items() == set(ENGLISH_NAMES)
        assert _seed() == ALL_SEEDED
        (box,) = fake_boxes
        listed = set(box.detailed_text.split("\n"))
        assert listed == set(ENGLISH_NAMES) - {"S-38 Pistol", "P4-AR Rifle"}

    def test_existing_owned_items_are_kept(self, json_backend, fake_boxes):
        AppSettings.set_owned_items({"Agni", "Colossus"})
        _Stub(entries=_starter_entries()).finish_scan()
        assert {"Agni", "Colossus"} <= AppSettings.get_owned_items()

    def test_a_profile_that_scanned_before_this_release_is_seeded_on_its_next_scan(
            self, json_backend, fake_boxes):
        """A 2.4 user already has a watermark and owned items but no seed
        marker, so their next scan is their first since updating."""
        from datetime import datetime, timezone
        AppSettings.set_blueprint_log_watermark(
            datetime(2026, 9, 1, tzinfo=timezone.utc), channel="LIVE"
        )
        AppSettings.set_owned_items({"Agni"})
        _Stub(entries=_starter_entries()).finish_scan()
        assert AppSettings.get_owned_items() == {"Agni"} | set(ENGLISH_NAMES)

    def test_seeded_names_follow_the_loaded_strings(self, json_backend, fake_boxes):
        helmet = "item_Name_cds_light_helmet_01"
        stub = _Stub(entries=_starter_entries({helmet: "Casco Field Recon"}))
        stub.finish_scan()
        owned = AppSettings.get_owned_items()
        assert "Casco Field Recon" in owned
        assert "Field Recon Suit Helmet" not in owned


class TestOneShotPerItem:
    def test_a_starter_moved_back_to_available_stays_there(self, json_backend, fake_boxes):
        _Stub(entries=_starter_entries()).finish_scan()
        owned = AppSettings.get_owned_items()
        owned.discard("S-38 Pistol")
        AppSettings.set_owned_items(owned)

        fake_boxes.clear()
        _Stub(entries=_starter_entries()).finish_scan()

        assert "S-38 Pistol" not in AppSettings.get_owned_items()
        (box,) = fake_boxes  # the plain "nothing new" message
        assert box.detailed_text is None

    def test_a_load_after_the_seed_adds_nothing(self, json_backend, fake_boxes):
        _Stub(entries=_starter_entries()).finish_scan()
        AppSettings.set_owned_items(set())
        _Stub(entries=_starter_entries()).load()
        assert AppSettings.get_owned_items() == set()

    def test_a_load_with_no_scan_yet_adds_nothing(self, json_backend):
        """Before the first scan the starters sit in Available only."""
        AppSettings.set_owned_items(set())
        _Stub(entries=_starter_entries()).load()
        assert AppSettings.get_owned_items() == set()
        assert _seed() == NEVER

    def test_a_starter_declared_later_reaches_owned_on_the_next_scan(
            self, json_backend, fake_boxes, ninth_starter):
        """The review finding: one "done" marker for the whole list meant a
        starter added in a later release never reached Owned for anyone who
        had already scanned."""
        AppSettings.set_owned_items(set(ENGLISH_NAMES))
        _mark_all_seeded()
        entries = _starter_entries() + [_Entry(NINTH_KEY, NINTH_NAME, "Gear")]

        _Stub(entries=entries).finish_scan()

        assert AppSettings.get_owned_items() == set(ENGLISH_NAMES) | {NINTH_NAME}
        assert _seed() == (ALL_KEYS | {NINTH_KEY}, False)
        (box,) = fake_boxes
        assert box.detailed_text == NINTH_NAME

    def test_a_moved_back_starter_stays_while_a_new_one_arrives(
            self, json_backend, fake_boxes, ninth_starter):
        AppSettings.set_owned_items(set(ENGLISH_NAMES) - {"S-38 Pistol"})
        _mark_all_seeded()
        entries = _starter_entries() + [_Entry(NINTH_KEY, NINTH_NAME, "Gear")]

        _Stub(entries=entries).finish_scan()

        owned = AppSettings.get_owned_items()
        assert NINTH_NAME in owned
        assert "S-38 Pistol" not in owned

    def test_a_later_starter_found_before_the_strings_load_waits_for_them(
            self, json_backend, fake_boxes, queued_calls, ninth_starter):
        AppSettings.set_owned_items(set(ENGLISH_NAMES))
        AppSettings.set_auto_scan_show_popup_enabled(True)
        _mark_all_seeded()

        _Stub(entries=[]).finish_scan()
        assert _seed() == (ALL_KEYS, True)

        fake_boxes.clear()
        _Stub(entries=_starter_entries() + [_Entry(NINTH_KEY, NINTH_NAME)]).load()
        assert NINTH_NAME in AppSettings.get_owned_items()
        assert _seed() == (ALL_KEYS | {NINTH_KEY}, False)
        _run_queued(queued_calls)
        (box,) = fake_boxes
        assert box.detailed_text == NINTH_NAME, "only the new starter is reported"

    def test_two_keys_with_one_name_are_both_recorded(self, json_backend, fake_boxes, caplog):
        """Every new key is recorded, even one whose name came out the same as
        another starter's, so later scans don't redo the work every time."""
        entries = _starter_entries({"item_Namebehr_pistol_ballistic_01_mag": "S-38 Pistol"})
        stub = _Stub(entries=entries)
        stub.finish_scan()
        assert _seed() == ALL_SEEDED

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="src.gui.main_window"):
            assert stub._seed_default_owned_blueprints() == set()
        assert "Starter blueprints" not in caplog.text


class TestScanBeforeStringsLoad:
    """The startup auto-scan can finish before the strings load. The names
    come from the loaded strings, so the seed waits for them."""

    def test_scan_with_no_strings_marks_the_seed_pending(self, json_backend, fake_boxes):
        AppSettings.set_owned_items(set())
        stub = _Stub(entries=[])
        stub.finish_scan()

        assert AppSettings.get_owned_items() == set()
        assert _seed() == (frozenset(), True)
        (box,) = fake_boxes  # the plain "nothing new" message
        assert box.detailed_text is None

    def test_the_next_load_finishes_a_pending_seed(self, json_backend, fake_boxes):
        _Stub(entries=[]).finish_scan()
        stub = _Stub(entries=_starter_entries({
            "item_Name_cds_light_helmet_01": "Casco Field Recon",
        }))
        stub.load()

        owned = AppSettings.get_owned_items()
        assert "Casco Field Recon" in owned, "named from the loaded strings"
        assert "Field Recon Suit Helmet" not in owned, "not the English fallback"
        assert len(owned) == len(ENGLISH_NAMES)
        assert _seed() == ALL_SEEDED

    def test_the_load_seeds_before_the_owned_tags_are_woven(self, json_backend):
        """The rebuild seeds, then the caller's _recompute_owned weaves the
        tags and refreshes the tracker with the starters already owned."""
        _mark_pending()
        seen = []
        stub = _Stub(entries=_starter_entries())
        stub._recompute_owned = lambda: seen.append(set(AppSettings.get_owned_items()))
        stub.load()
        assert seen == [set(ENGLISH_NAMES)]

    def test_a_second_scan_before_the_load_keeps_it_pending(self, json_backend, fake_boxes):
        _Stub(entries=[]).finish_scan()
        _Stub(entries=[]).finish_scan()
        assert _seed() == (frozenset(), True)
        assert AppSettings.get_owned_items() == set()


class TestDeferredSeedIsReported:
    """The review finding: a load that finished a pending seed added the
    starters with no message at all, though the scan that deferred them had
    already reported. Reported now the way a silent auto-scan reports."""

    def test_status_bar_message_after_the_load(self, json_backend, fake_boxes, queued_calls):
        AppSettings.set_auto_scan_show_popup_enabled(False)
        _mark_pending()
        stub = _Stub(entries=_starter_entries())
        stub.load()

        assert stub._status_bar.messages == [], "not inside the load itself"
        assert len(queued_calls) == 1
        _run_queued(queued_calls)
        assert len(stub._status_bar.messages) == 1
        assert str(len(ENGLISH_NAMES)) in stub._status_bar.messages[0]
        assert fake_boxes == []

    def test_the_popup_when_that_option_is_on(self, json_backend, fake_boxes, queued_calls):
        AppSettings.set_auto_scan_show_popup_enabled(True)
        _mark_pending()
        stub = _Stub(entries=_starter_entries())
        stub.load()
        _run_queued(queued_calls)

        (box,) = fake_boxes
        assert set(box.detailed_text.split("\n")) == set(ENGLISH_NAMES)
        assert stub._status_bar.messages == []

    def test_reports_only_what_it_added(self, json_backend, fake_boxes, queued_calls):
        AppSettings.set_auto_scan_show_popup_enabled(True)
        AppSettings.set_owned_items({"S-38 Pistol"})
        _mark_pending()
        _Stub(entries=_starter_entries()).load()
        _run_queued(queued_calls)

        (box,) = fake_boxes
        assert set(box.detailed_text.split("\n")) == set(ENGLISH_NAMES) - {"S-38 Pistol"}

    def test_nothing_reported_when_nothing_was_added(self, json_backend, fake_boxes, queued_calls):
        AppSettings.set_owned_items(set(ENGLISH_NAMES))
        _mark_pending()
        stub = _Stub(entries=_starter_entries())
        stub.load()

        assert queued_calls == []
        assert _seed() == ALL_SEEDED

    def test_an_ordinary_load_reports_nothing(self, json_backend, fake_boxes, queued_calls):
        _Stub(entries=_starter_entries()).load()
        _mark_all_seeded()
        _Stub(entries=_starter_entries()).load()
        assert queued_calls == []


class TestDeferredReportWaitsForTheLoad:
    """The re-review finding: the report for a seed a load finished was queued
    from inside the metadata rebuild, so a modal step later in the same load
    (the enhancement categories prompt) ran it inside its own event loop. The
    load now queues it as its very last step, and it waits out long jobs."""

    def test_a_modal_step_in_the_load_does_not_run_the_report(
            self, json_backend, fake_boxes, queued_calls):
        AppSettings.set_auto_scan_show_popup_enabled(True)
        _mark_pending()
        stub = _Stub(entries=_starter_entries())

        stub.load(modal_step=lambda: _run_queued(queued_calls))

        assert fake_boxes == [], "nothing reported inside the load"
        _run_queued(queued_calls)
        (box,) = fake_boxes
        assert set(box.detailed_text.split("\n")) == set(ENGLISH_NAMES)

    @pytest.mark.parametrize("busy", [
        "_loader_worker", "_enhancements_worker", "_forge_worker", "_p4k_worker",
        "_simple_run_active",
    ])
    def test_it_waits_out_a_long_job_and_goes_out_after_the_next_load(
            self, json_backend, fake_boxes, queued_calls, busy):
        AppSettings.set_auto_scan_show_popup_enabled(True)
        _mark_pending()
        stub = _Stub(entries=_starter_entries())
        stub.load()
        setattr(stub, busy, True if busy == "_simple_run_active" else object())

        _run_queued(queued_calls)
        assert fake_boxes == []
        assert stub._deferred_starter_report == sorted(ENGLISH_NAMES), "kept for later"

        setattr(stub, busy, False if busy == "_simple_run_active" else None)
        stub.load()  # the reload that ends the job
        _run_queued(queued_calls)
        (box,) = fake_boxes
        assert set(box.detailed_text.split("\n")) == set(ENGLISH_NAMES)
        assert stub._deferred_starter_report == []

    def test_never_while_closing(self, json_backend, fake_boxes, queued_calls):
        AppSettings.set_auto_scan_show_popup_enabled(True)
        _mark_pending()
        stub = _Stub(entries=_starter_entries())
        stub.load()
        stub._close_committed = True
        _run_queued(queued_calls)
        assert fake_boxes == []
        assert stub._status_bar.messages == []


class TestLoadPathsQueueTheReportLast:
    """Both real load paths, on a MagicMock self: the report is queued as the
    very last step, after anything that can open a modal dialog."""

    def test_the_async_load(self, json_backend):
        me = MagicMock()
        me._loader_worker = None
        me._reload_follows_clean_apply = False
        me._check_enhancements_after_loading = True
        MainWindow._on_loading_finished(me, [], {}, [])

        names = [call[0] for call in me.mock_calls]
        assert names.count("_queue_deferred_starter_report") == 1, "queued once, last"
        assert names[-1] == "_queue_deferred_starter_report"
        assert names.index("_check_enhancements_freshness") < len(names) - 1
        assert names.index("_refresh_apply_dirty_after_reload") < len(names) - 1

    def test_the_synchronous_reload(self, json_backend, monkeypatch):
        monkeypatch.setattr(
            main_window, "load_sources_from_settings",
            lambda: ({AppSettings.SOURCE_GLOBAL: {}}, [AppSettings.SOURCE_GLOBAL], {}),
        )
        monkeypatch.setattr(main_window, "load_source_files", lambda *a, **k: [])
        me = MagicMock()
        me._snapshot_pending_user_edits.return_value = {}
        me._restore_pending_user_edits.return_value = 0
        MainWindow.perform_merge_and_reload(me)

        names = [call[0] for call in me.mock_calls]
        assert names.count("_queue_deferred_starter_report") == 1, "queued once, last"
        assert names[-1] == "_queue_deferred_starter_report"
        assert names.index("_update_status_bar") < len(names) - 1


class TestApplyIsRechecked:
    """The review finding: a scan that added blueprints left Apply red and the
    close prompt armed, though starters are in no mission list and so change
    nothing in the game file. The scan now hands the verdict to the same
    background check a reload runs, after the re-weave."""

    def test_a_scan_that_adds_only_starters_rechecks_after_the_reweave(
            self, json_backend, fake_boxes):
        stub = _Stub(entries=_starter_entries())
        stub.finish_scan()
        assert stub.events == ["recompute", "applied-check"]

    def test_a_scan_with_a_real_find_rechecks_too(self, json_backend, fake_boxes):
        _mark_all_seeded()
        stub = _Stub(entries=_starter_entries(), log_names=["R97 Shotgun"])
        stub.finish_scan()
        assert stub.events == ["recompute", "applied-check"]

    def test_a_quiet_scan_changes_nothing_and_checks_nothing(self, json_backend, fake_boxes):
        _mark_all_seeded()
        stub = _Stub(entries=_starter_entries())
        stub.finish_scan()
        assert stub.events == []

    def test_no_check_once_closing_is_committed(self, json_backend, fake_boxes):
        """Re-review: the check is a thread closeEvent would not wait for."""
        _mark_all_seeded()
        stub = _Stub(entries=_starter_entries(), log_names=["R97 Shotgun"])
        stub._close_committed = True
        stub.finish_scan()
        assert stub.events == ["recompute"]

    def test_no_check_while_a_load_is_running(self, json_backend, fake_boxes):
        """Re-review: that load runs its own check after its re-weave."""
        _mark_all_seeded()
        stub = _Stub(entries=_starter_entries(), log_names=["R97 Shotgun"])
        stub._loader_worker = object()
        stub.finish_scan()
        assert stub.events == ["recompute"]

    def test_no_check_before_anything_is_loaded(self, json_backend, fake_boxes):
        stub = _Stub(entries=[], log_names=["R97 Shotgun"])
        stub.finish_scan()
        assert stub.events == ["recompute"]


class TestCloseSettlesAfterThePrompt:
    """Re-review: the unapplied-changes prompt runs its own event loop, where
    a scan can finish and start a check. Exiting from it settles again, so no
    check thread outlives the window. Cancel and Apply Now stay open."""

    @staticmethod
    def _closing(monkeypatch, choice):
        order = []
        box = MagicMock()
        apply_btn, exit_btn, cancel_btn = object(), object(), object()
        box.addButton.side_effect = [apply_btn, exit_btn, cancel_btn]
        box.exec.side_effect = lambda: order.append("prompt")
        box.clickedButton.return_value = {"apply": apply_btn, "exit": exit_btn,
                                          "cancel": cancel_btn}[choice]
        monkeypatch.setattr(main_window, "QMessageBox", MagicMock(return_value=box))
        for setter in ("set_window_state", "set_window_geometry", "set_string_column_widths"):
            monkeypatch.setattr(AppSettings, setter, staticmethod(lambda *a, **k: None))
        me = MagicMock()
        me._session_has_unapplied_edit = True
        me._suppress_user_ini_autosave = False
        me._loader_worker = None
        me._user_resized_columns = False
        me.entries = []
        me.apply_to_game.return_value = True
        me._settle_applied_state_check.side_effect = lambda: order.append("settle")
        me._request_extraction_stops.side_effect = lambda: order.append("commit")
        return me, order

    def test_exit_settles_again_before_committing(self, monkeypatch):
        me, order = self._closing(monkeypatch, "exit")
        MainWindow.closeEvent(me, MagicMock())
        assert order == ["settle", "prompt", "settle", "commit"]

    @pytest.mark.parametrize("choice", ["cancel", "apply"])
    def test_staying_open_does_not_settle_again(self, monkeypatch, choice):
        me, order = self._closing(monkeypatch, choice)
        MainWindow.closeEvent(me, MagicMock())
        assert order == ["settle", "prompt"]


class TestSeedNamesMatchTheTracker:
    """The seed must name the starters with the same inputs the metadata
    rebuild uses (the stock values and the Tag Builder enclosings), or a
    seeded starter shows in Owned under one name and in Available under
    another."""

    RIFLE = "item_Namebehr_rifle_ballistic_01"

    def test_the_seed_strips_a_tag_via_the_stock_value(self, json_backend, fake_boxes):
        stub = _Stub(entries=_starter_entries({self.RIFLE: "P4-AR Rifle BALL-AR"}))
        stub.default_values = {self.RIFLE: "P4-AR Rifle"}
        stub.finish_scan()

        owned = AppSettings.get_owned_items()
        assert "P4-AR Rifle" in owned
        assert "P4-AR Rifle BALL-AR" not in owned

    def test_the_seed_uses_the_configured_enclosings(self, json_backend, fake_boxes):
        from dataclasses import replace
        from src.utils.tag_builder import DEFAULT_TAG_CONFIGS
        AppSettings.set_tag_config(
            "components", replace(DEFAULT_TAG_CONFIGS["components"], enclosing="round"),
        )
        _Stub(entries=_starter_entries({self.RIFLE: "(X) P4-AR Rifle"})).finish_scan()

        owned = AppSettings.get_owned_items()
        assert "P4-AR Rifle" in owned
        assert "(X) P4-AR Rifle" not in owned

    def test_after_a_load_every_seeded_name_is_in_the_catalogue_not_available(
            self, json_backend, fake_boxes):
        from dataclasses import replace
        from src.utils.tag_builder import DEFAULT_TAG_CONFIGS
        AppSettings.set_tag_config(
            "components", replace(DEFAULT_TAG_CONFIGS["components"], enclosing="round"),
        )
        entries = _starter_entries({
            self.RIFLE: "P4-AR Rifle BALL-AR",
            "item_Namebehr_pistol_ballistic_01": "(X) S-38 Pistol",
        })
        stub = _Stub(entries=entries)
        stub.default_values = {self.RIFLE: "P4-AR Rifle"}
        stub.finish_scan()
        stub.load()

        owned = AppSettings.get_owned_items()
        assert owned <= set(stub._blueprint_meta)
        available = BlueprintTrackerTab._available_blueprints(stub._blueprint_meta, owned)
        assert not set(available) & owned
        assert {"P4-AR Rifle", "S-38 Pistol"} <= owned


class TestNeverRaises:
    def test_a_failure_is_logged_and_left_for_the_next_scan(
            self, json_backend, monkeypatch, caplog):
        def boom():
            raise OSError("registry unavailable")

        monkeypatch.setattr(AppSettings, "get_owned_items", staticmethod(boom))
        stub = _Stub(entries=_starter_entries())
        with caplog.at_level(logging.ERROR, logger="src.gui.main_window"):
            assert stub._seed_default_owned_blueprints() == set()
        assert "#416" in caplog.text
        assert _seed() == NEVER
