"""Smart Sync: owned blueprints shared through a synced folder (#567).

The Qt-free core (src/utils/smart_sync.py): the ledger, the newest-wins merge,
the one-file-per-PC folder; and the AppSettings side: the ledger kept as the
owned set changes, Import Settings adding rather than replacing, and none of
this PC's sync state travelling in a settings backup.
"""
import json

import pytest

from src.utils import smart_sync
from src.utils.smart_sync import AT, BASELINE_AT, OWNED


def entry(owned, at):
    return {OWNED: owned, AT: at}


T1 = "2026-11-20T10:00:00.000000Z"
T2 = "2026-11-20T11:00:00.000000Z"
T3 = "2026-11-20T12:00:00.000000Z"


class TestRecord:
    def test_new_names_are_owned_now(self):
        assert smart_sync.record({}, {"Agni"}, at=T1) == {"Agni": entry(True, T1)}

    def test_a_name_dropped_from_owned_is_recorded_as_not_owned(self):
        ledger = {"Agni": entry(True, T1)}
        assert smart_sync.record(ledger, set(), at=T2) == {"Agni": entry(False, T2)}

    def test_names_that_agree_keep_their_time(self):
        ledger = {"Agni": entry(True, T1), "Norfield": entry(False, T1)}
        assert smart_sync.record(ledger, {"Agni"}, at=T3) == ledger

    def test_owning_again_after_a_removal(self):
        ledger = {"Agni": entry(False, T1)}
        assert smart_sync.record(ledger, {"Agni"}, at=T2) == {"Agni": entry(True, T2)}

    def test_inputs_are_left_alone(self):
        ledger = {"Agni": entry(True, T1)}
        smart_sync.record(ledger, set(), at=T2)
        assert ledger == {"Agni": entry(True, T1)}


class TestBaseline:
    def test_owned_names_go_in_at_the_epoch(self):
        assert smart_sync.baseline({}, {"Agni"}) == {"Agni": entry(True, BASELINE_AT)}

    def test_a_name_with_a_record_is_left_alone(self):
        ledger = {"Agni": entry(False, T1)}
        assert smart_sync.baseline(ledger, {"Agni"}) == ledger

    def test_any_real_change_wins_over_a_baseline(self):
        pc_a = smart_sync.baseline({}, {"Agni"})
        pc_b = {"Agni": entry(False, T1)}
        assert smart_sync.merge([pc_a, pc_b])["Agni"] == entry(False, T1)


class TestMerge:
    def test_union_of_different_names(self):
        merged = smart_sync.merge([{"Agni": entry(True, T1)}, {"Norfield": entry(True, T2)}])
        assert smart_sync.owned_from_ledger(merged) == {"Agni", "Norfield"}

    def test_a_newer_removal_wins(self):
        # The case a plain union gets wrong: moved back to Available on one
        # PC must not come back from the other.
        merged = smart_sync.merge([{"Agni": entry(True, T1)}, {"Agni": entry(False, T2)}])
        assert merged["Agni"] == entry(False, T2)

    def test_a_newer_gain_wins(self):
        merged = smart_sync.merge([{"Agni": entry(False, T1)}, {"Agni": entry(True, T2)}])
        assert merged["Agni"] == entry(True, T2)

    def test_order_does_not_matter(self):
        a = {"Agni": entry(True, T1), "Norfield": entry(False, T3)}
        b = {"Agni": entry(False, T2), "Norfield": entry(True, T2)}
        assert smart_sync.merge([a, b]) == smart_sync.merge([b, a])

    def test_equal_times_favour_owned(self):
        assert smart_sync.merge([{"Agni": entry(False, T1)},
                                 {"Agni": entry(True, T1)}])["Agni"] == entry(True, T1)
        assert smart_sync.merge([{"Agni": entry(True, T1)},
                                 {"Agni": entry(False, T1)}])["Agni"] == entry(True, T1)


class TestCleanLedger:
    def test_bad_entries_are_dropped(self):
        raw = {
            "Agni": entry(True, T1),
            "": entry(True, T1),
            "NoTime": {OWNED: True},
            "BadOwned": {OWNED: "yes", AT: T1},
            "NotADict": True,
        }
        assert smart_sync.clean_ledger(raw) == {"Agni": entry(True, T1)}

    def test_not_a_dict(self):
        assert smart_sync.clean_ledger([1, 2]) == {}


class TestFiles:
    def test_round_trip(self):
        ledger = {"Demeco \"Purgatory Camo\" LMG": entry(True, T1), "Ärger": entry(False, T2)}
        text = smart_sync.encode("abcd1234", ledger, {"key_b", "key_a"}, T2)
        parsed = smart_sync.decode(text)
        assert parsed.machine_id == "abcd1234"
        assert parsed.ledger == ledger
        assert parsed.seeded == {"key_a", "key_b"}
        assert parsed.updated == T2

    def test_holds_no_path_or_pc_name(self):
        text = smart_sync.encode("abcd1234", {"Agni": entry(True, T1)}, set(), T1)
        assert set(json.loads(text)) == {
            "format", "machine", "updated", "owned", "starter_seeded", "settings", "user_ini"}

    @pytest.mark.parametrize("text", ["", "not json", "[]", '{"owned": []}', '{"machine": "x"}'])
    def test_not_a_machine_file(self, text):
        assert smart_sync.decode(text) is None

    def test_times_order_as_strings(self):
        first = smart_sync.now_iso()
        assert BASELINE_AT < first <= smart_sync.now_iso()
        assert len(first) == len(BASELINE_AT)

    def test_machine_ids_are_random_hex(self):
        ids = {smart_sync.new_machine_id() for _ in range(20)}
        assert len(ids) == 20
        assert all(len(i) == 8 and int(i, 16) >= 0 for i in ids)


def write_machine(folder, machine_id, ledger, seeded=(), updated=T1, name=None):
    d = smart_sync.sync_dir(folder)
    d.mkdir(parents=True, exist_ok=True)
    path = d / (name or smart_sync.machine_file_name(machine_id))
    path.write_text(smart_sync.encode(machine_id, ledger, seeded, updated), encoding="utf-8")
    return path


class TestSync:
    def test_first_sync_makes_the_folder_and_writes_this_pcs_file(self, tmp_path):
        result = smart_sync.sync(tmp_path, "aaaa0000", {"Agni": entry(True, T1)}, set(), at=T2)
        path = smart_sync.sync_dir(tmp_path) / "machine-aaaa0000.json"
        assert result.written and result.updated == T2
        written = smart_sync.decode(path.read_text(encoding="utf-8"))
        assert written.ledger == {"Agni": entry(True, T1)}
        assert result.other_machines == 0

    def test_two_pcs(self, tmp_path):
        # PC B earned Norfield and moved Agni back to Available after PC A
        # got it; PC A learns both.
        write_machine(tmp_path, "bbbb0000",
                      {"Norfield": entry(True, T2), "Agni": entry(False, T3)})
        result = smart_sync.sync(tmp_path, "aaaa0000", {"Agni": entry(True, T1)}, set(), at=T3)
        assert smart_sync.owned_from_ledger(result.ledger) == {"Norfield"}
        assert result.other_machines == 1
        # Only this PC's own file is written; PC B's is never touched.
        b = smart_sync.sync_dir(tmp_path) / "machine-bbbb0000.json"
        assert smart_sync.decode(b.read_text(encoding="utf-8")).ledger["Agni"] == entry(False, T3)

    def test_nothing_new_writes_nothing(self, tmp_path):
        ledger = {"Agni": entry(True, T1)}
        first = smart_sync.sync(tmp_path, "aaaa0000", ledger, set(), at=T1)
        path = smart_sync.sync_dir(tmp_path) / "machine-aaaa0000.json"
        before = path.stat().st_mtime_ns
        again = smart_sync.sync(tmp_path, "aaaa0000", first.ledger, set(),
                                last_written=first.updated, at=T2)
        assert not again.written
        assert again.updated == T1
        assert path.stat().st_mtime_ns == before

    def test_starter_seed_marker_is_shared(self, tmp_path):
        write_machine(tmp_path, "bbbb0000", {}, seeded={"item_starter_a"})
        result = smart_sync.sync(tmp_path, "aaaa0000", {}, {"item_starter_b"}, at=T2)
        assert result.seeded == {"item_starter_a", "item_starter_b"}

    def test_a_conflicted_copy_is_read_too(self, tmp_path):
        write_machine(tmp_path, "bbbb0000", {"Agni": entry(True, T2)},
                      name="machine-bbbb0000 (1).json")
        result = smart_sync.sync(tmp_path, "aaaa0000", {}, set(), at=T3)
        assert smart_sync.owned_from_ledger(result.ledger) == {"Agni"}

    def test_a_bad_file_is_skipped(self, tmp_path, caplog):
        d = smart_sync.sync_dir(tmp_path)
        d.mkdir(parents=True)
        (d / "machine-broken.json").write_text("{", encoding="utf-8")
        (d / "machine-binary.json").write_bytes(b"\xff\xfe\x00")
        (d / "notes.txt").write_text("not ours", encoding="utf-8")
        write_machine(tmp_path, "bbbb0000", {"Agni": entry(True, T2)})
        result = smart_sync.sync(tmp_path, "aaaa0000", {}, set(), at=T3)
        assert smart_sync.owned_from_ledger(result.ledger) == {"Agni"}
        assert "machine-broken.json" in caplog.text
        # Leftover temps from a write that was cut off are never read.
        assert not any(p.name.startswith(".sc-") for p in d.iterdir())

    def test_another_install_with_this_pcs_id_gets_this_pc_a_new_one(self, tmp_path):
        # A copied portable folder: both installs have id aaaa0000. The other
        # one wrote after this PC last did.
        write_machine(tmp_path, "aaaa0000", {"Norfield": entry(True, T2)}, updated=T3)
        result = smart_sync.sync(tmp_path, "aaaa0000", {"Agni": entry(True, T1)}, set(),
                                 last_written=T1, at=T3)
        assert result.id_changed
        assert result.machine_id != "aaaa0000"
        # The other install's data is still merged, and its file left alone.
        assert smart_sync.owned_from_ledger(result.ledger) == {"Agni", "Norfield"}
        d = smart_sync.sync_dir(tmp_path)
        assert (d / smart_sync.machine_file_name(result.machine_id)).is_file()
        other = smart_sync.decode((d / "machine-aaaa0000.json").read_text(encoding="utf-8"))
        assert other.ledger == {"Norfield": entry(True, T2)}

    def test_this_pcs_own_last_write_is_not_another_install(self, tmp_path):
        first = smart_sync.sync(tmp_path, "aaaa0000", {"Agni": entry(True, T1)}, set(), at=T2)
        again = smart_sync.sync(tmp_path, "aaaa0000", {"Agni": entry(False, T3)}, set(),
                                last_written=first.updated, at=T3)
        assert not again.id_changed and again.machine_id == "aaaa0000"

    def test_a_folder_that_cannot_be_made_raises(self, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("x", encoding="utf-8")
        with pytest.raises(OSError):
            smart_sync.sync(blocker, "aaaa0000", {}, set())


class TestSettings:
    """The AppSettings side, on a profile under tmp_path."""

    @pytest.fixture
    def settings(self, tmp_profile):
        from src.utils.settings import AppSettings
        return AppSettings

    def test_off_by_default_and_no_ledger_kept(self, settings):
        assert settings.get_smart_sync_folder() == ""
        settings.set_owned_items({"Agni"})
        assert settings.get_smart_sync_ledger() == {}

    def test_turning_on_baselines_what_this_pc_owns(self, settings, tmp_path):
        settings.set_owned_items({"Agni"})
        settings.set_smart_sync_folder(tmp_path / "Drive")
        assert settings.get_smart_sync_ledger() == {"Agni": entry(True, BASELINE_AT)}

    def test_owned_changes_are_recorded_while_on(self, settings, tmp_path):
        settings.set_owned_items({"Agni"})
        settings.set_smart_sync_folder(tmp_path / "Drive")
        settings.set_owned_items({"Norfield"})
        ledger = settings.get_smart_sync_ledger()
        assert ledger["Agni"][OWNED] is False and ledger["Agni"][AT] != BASELINE_AT
        assert ledger["Norfield"][OWNED] is True

    def test_turning_on_again_records_changes_made_while_off(self, settings, tmp_path):
        settings.set_owned_items({"Agni"})
        settings.set_smart_sync_folder(tmp_path / "Drive")
        settings.set_smart_sync_folder(None)
        settings.set_owned_items(set())
        assert settings.get_smart_sync_ledger()["Agni"][OWNED] is True
        settings.set_smart_sync_folder(tmp_path / "Drive")
        assert settings.get_smart_sync_ledger()["Agni"][OWNED] is False

    def test_machine_id_is_made_once(self, settings):
        first = settings.get_smart_sync_machine_id()
        assert first and settings.get_smart_sync_machine_id() == first

    def test_sync_state_never_travels_in_a_backup(self, settings, tmp_path):
        settings.set_owned_items({"Agni"})
        settings.set_smart_sync_folder(tmp_path / "Drive")
        settings.get_smart_sync_machine_id()
        settings.set_smart_sync_last_written(T1)
        exported = settings.export_all_values()
        for key in (settings.SMART_SYNC_FOLDER, settings.SMART_SYNC_MACHINE_ID,
                    settings.SMART_SYNC_LEDGER, settings.SMART_SYNC_LAST_WRITTEN):
            assert key not in exported
            assert settings.is_profile_excluded_key(key)

    def test_import_replaces_the_owned_set_while_off(self, settings):
        settings.set_owned_items({"Agni", "Norfield"})
        settings.import_values({settings.OWNED_ITEMS: json.dumps(["Agni"])})
        assert settings.get_owned_items() == {"Agni"}

    def test_import_adds_to_the_owned_set_while_on(self, settings, tmp_path):
        # Replacing would read as Norfield moved back to Available on this
        # PC, and the next sync would take it off every other PC too.
        settings.set_owned_items({"Agni", "Norfield"})
        settings.set_smart_sync_folder(tmp_path / "Drive")
        settings.import_values({settings.OWNED_ITEMS: json.dumps(["Agni", "Arrowhead"])})
        assert settings.get_owned_items() == {"Agni", "Norfield", "Arrowhead"}
        ledger = settings.get_smart_sync_ledger()
        assert ledger["Norfield"][OWNED] is True
        assert ledger["Arrowhead"][OWNED] is True


class TestWorker:
    """SmartSyncWorker runs the sync and reports once, on a real thread."""

    def run_worker(self, qapp, worker):
        from PyQt6.QtCore import Qt
        got = {}
        worker.finished.connect(lambda r: got.setdefault("result", r),
                                Qt.ConnectionType.DirectConnection)
        worker.error.connect(lambda m: got.setdefault("error", m),
                             Qt.ConnectionType.DirectConnection)
        worker.start()
        assert worker.wait(10000)
        return got

    def test_reports_the_result(self, qapp, tmp_path):
        from src.gui.workers import SmartSyncWorker
        write_machine(tmp_path, "bbbb0000", {"Norfield": entry(True, T2)})
        got = self.run_worker(qapp, SmartSyncWorker(
            str(tmp_path), "aaaa0000", {"Agni": entry(True, T1)}, frozenset(), ""))
        assert "error" not in got
        assert smart_sync.owned_from_ledger(got["result"].ledger) == {"Agni", "Norfield"}

    def test_a_folder_it_cannot_use_reports_none_and_why(self, qapp, tmp_path, caplog):
        from src.gui.workers import SmartSyncWorker
        blocker = tmp_path / "file"
        blocker.write_text("x", encoding="utf-8")
        got = self.run_worker(qapp, SmartSyncWorker(str(blocker), "aaaa0000", {}, frozenset(), ""))
        assert got["result"] is None and got["error"]
        # A WARNING, never an ERROR: an ERROR record opens the global box.
        assert not [r for r in caplog.records if r.levelname == "ERROR"]


class TestTheWindowTakesTheResult:
    """MainWindow._take_smart_sync_result on a stub self with real settings."""

    @pytest.fixture
    def settings(self, tmp_profile):
        from src.utils.settings import AppSettings
        AppSettings.set_smart_sync_folder(tmp_profile / "Drive")
        return AppSettings

    def stub(self):
        from unittest.mock import MagicMock
        me = MagicMock()
        me._close_committed = False
        me.entries = []
        me._loader_worker = None
        return me

    def take(self, me, result):
        from src.gui.main_window import MainWindow
        MainWindow._take_smart_sync_result(me, result)

    def result(self, ledger, seeded=frozenset(), **kw):
        return smart_sync.SyncResult(ledger=ledger, seeded=frozenset(seeded),
                                     machine_id="aaaa0000", **kw)

    def test_another_pcs_blueprints_become_owned(self, settings):
        settings.set_owned_items({"Agni"})
        me = self.stub()
        ledger = smart_sync.merge([settings.get_smart_sync_ledger(),
                                   {"Norfield": entry(True, T2)}])
        self.take(me, self.result(ledger, other_machines=1, updated=T2, written=True))
        assert settings.get_owned_items() == {"Agni", "Norfield"}
        me._recompute_owned.assert_called_once()
        me.statusBar.return_value.showMessage.assert_called_once()
        assert settings.get_smart_sync_last_written() == T2

    def test_nothing_new_changes_nothing(self, settings):
        settings.set_owned_items({"Agni"})
        me = self.stub()
        self.take(me, self.result(settings.get_smart_sync_ledger()))
        me._recompute_owned.assert_not_called()

    def test_a_change_made_while_the_sync_ran_wins(self, settings):
        settings.set_owned_items({"Agni"})
        stale = settings.get_smart_sync_ledger()
        # The sync read Agni as owned; the player moved it back meanwhile.
        settings.set_owned_items(set())
        self.take(self.stub(), self.result(stale))
        assert settings.get_owned_items() == set()
        assert settings.get_smart_sync_ledger()["Agni"][OWNED] is False

    def test_the_seed_marker_and_a_new_id_are_kept(self, settings):
        settings.set_default_blueprints_seed({"key_a"}, True)
        self.take(self.stub(), self.result({}, seeded={"key_b"}, id_changed=True))
        assert settings.get_default_blueprints_seed() == ({"key_a", "key_b"}, True)
        assert settings.get_smart_sync_machine_id() == "aaaa0000"


# -- format 2: settings and string edits ---------------------------------------

from src.utils.smart_sync import JOIN_AT, VALUE  # noqa: E402


def val(value, at):
    return {VALUE: value, AT: at}


class TestRecordValues:
    def test_a_change_since_seen_is_stamped(self):
        out = smart_sync.record_values({}, {"theme": "light"}, {"theme": "dark"}, at=T2)
        assert out == {"theme": val("light", T2)}

    def test_an_unchanged_value_keeps_its_entry(self):
        ledger = {"theme": val("dark", T1)}
        out = smart_sync.record_values(ledger, {"theme": "dark"}, {"theme": "dark"}, at=T2)
        assert out == ledger

    def test_a_key_gone_since_seen_is_a_removal(self):
        out = smart_sync.record_values({"k": val("v", T1)}, {}, {"k": "v"}, at=T2)
        assert out == {"k": val(None, T2)}

    def test_a_setting_never_seen_joins_at_the_baseline(self):
        out = smart_sync.record_values({}, {"new": 1}, {}, at=T2)
        assert out == {"new": val(1, BASELINE_AT)}

    def test_a_new_string_edit_is_a_change(self):
        out = smart_sync.record_values({}, {"k": "v"}, {}, at=T2, new_keys_are_changes=True)
        assert out == {"k": val("v", T2)}

    def test_a_new_edit_matching_the_ledger_keeps_its_time(self):
        ledger = {"k": val("v", T1)}
        assert smart_sync.record_values(ledger, {"k": "v"}, {}, at=T2,
                                        new_keys_are_changes=True) == ledger


class TestMergeValues:
    def test_newest_wins(self):
        a = {"k": val("old", T1)}
        b = {"k": val("new", T2)}
        assert smart_sync.merge_values([a, b]) == smart_sync.merge_values([b, a]) == b

    def test_a_newer_removal_wins(self):
        assert smart_sync.merge_values([{"k": val("v", T1)}, {"k": val(None, T2)}]) == {
            "k": val(None, T2)}

    def test_a_tie_is_settled_the_same_on_every_pc(self):
        a = {"k": val("alpha", BASELINE_AT)}
        b = {"k": val("beta", BASELINE_AT)}
        assert smart_sync.merge_values([a, b]) == smart_sync.merge_values([b, a])

    def test_channels_merge_on_their_own(self):
        out = smart_sync.merge_channels([{"LIVE": {"k": val("a", T1)}},
                                         {"PTU": {"k": val("b", T1)}}])
        assert out == {"LIVE": {"k": val("a", T1)}, "PTU": {"k": val("b", T1)}}


class TestFormat2Files:
    def test_round_trip_with_settings_and_user_ini(self):
        text = smart_sync.encode("aaaa0000", {}, (), T1,
                                 {"theme": val("dark", T1)},
                                 {"LIVE": {"k": val("v", T1)}})
        parsed = smart_sync.decode(text)
        assert parsed.settings == {"theme": val("dark", T1)}
        assert parsed.user_ini == {"LIVE": {"k": val("v", T1)}}

    def test_a_format_1_file_still_reads(self):
        text = json.dumps({"format": 1, "machine": "bbbb0000", "updated": T1,
                           "owned": {"Agni": entry(True, T1)}, "starter_seeded": []})
        parsed = smart_sync.decode(text)
        assert parsed.ledger == {"Agni": entry(True, T1)}
        assert parsed.settings == {} and parsed.user_ini == {}

    def test_bad_value_entries_are_dropped(self):
        assert smart_sync.clean_value_ledger({"a": {"at": T1}, "b": val(1, T1), 3: val(1, T1)}) == {
            "b": val(1, T1)}
        assert smart_sync.clean_channel_ledgers({"LIVE": {}, "PTU": {"k": val("v", T1)}}) == {
            "PTU": {"k": val("v", T1)}}


def write_machine_v2(folder, machine_id, settings=None, user_ini=None, updated=T1):
    path = smart_sync.sync_dir(folder)
    path.mkdir(parents=True, exist_ok=True)
    (path / smart_sync.machine_file_name(machine_id)).write_text(
        smart_sync.encode(machine_id, {}, (), updated, settings, user_ini), encoding="utf-8")


class TestSyncValues:
    def test_a_pc_that_joins_takes_what_the_others_share(self, tmp_path):
        write_machine_v2(tmp_path, "bbbb0000", settings={"theme": val("light", BASELINE_AT)},
                         user_ini={"LIVE": {"k": val("theirs", BASELINE_AT)}})
        result = smart_sync.sync(tmp_path, "aaaa0000", {}, set(),
                                 baseline_settings={"theme": "dark", "mine": 1},
                                 baseline_user_ini={"LIVE": {"k": "mine", "x": "only here"}})
        assert result.settings["theme"] == val("light", BASELINE_AT)
        assert result.settings["mine"] == val(1, JOIN_AT)
        assert smart_sync.values_from_ledger(result.user_ini["LIVE"]) == {
            "k": "theirs", "x": "only here"}

    def test_the_first_pc_baselines_at_the_epoch(self, tmp_path):
        result = smart_sync.sync(tmp_path, "aaaa0000", {}, set(),
                                 baseline_settings={"theme": "dark"},
                                 baseline_user_ini={"PTU": {"k": "v"}})
        assert result.settings == {"theme": val("dark", BASELINE_AT)}
        assert result.user_ini == {"PTU": {"k": val("v", BASELINE_AT)}}
        assert result.written

    def test_a_real_change_spreads_and_nothing_new_writes_nothing(self, tmp_path):
        write_machine_v2(tmp_path, "bbbb0000", settings={"theme": val("light", T1)})
        first = smart_sync.sync(tmp_path, "aaaa0000", {}, set(),
                                settings={"theme": val("dark", T2)}, at=T2)
        assert first.settings["theme"] == val("dark", T2) and first.written
        again = smart_sync.sync(tmp_path, "aaaa0000", {}, set(), last_written=first.updated,
                                settings=first.settings)
        assert not again.written


class TestSettingsV2:
    """Smart Sync's settings side, on a profile under tmp_path."""

    @pytest.fixture
    def settings(self, tmp_profile):
        from src.utils.settings import AppSettings
        AppSettings.set_smart_sync_folder(tmp_profile / "Drive")
        return AppSettings

    def test_local_keys_are_not_shared(self, settings):
        values = settings.smart_sync_settings_values()
        assert settings.FAVORITE_PREFIX in values
        for key in (settings.SC_INSTALL_ROOT, settings.ACTIVE_CHANNEL, settings.FONT_SIZE,
                    settings.OWNED_ITEMS):
            assert key not in values
        assert not any(k.startswith("smart_sync/") for k in values)

    def test_user_ini_values_per_channel(self, settings):
        path = settings.get_channel_user_ini_path("PTU")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("k=v \n", encoding="utf-8")
        assert settings.smart_sync_user_ini_values() == {"PTU": {"k": "v "}}

    def test_state_round_trips_and_turning_off_forgets_it(self, settings):
        state = {settings.SYNC_STATE_SETTINGS: {"theme": val("dark", T1)},
                 settings.SYNC_STATE_SETTINGS_SEEN: {"theme": "dark"},
                 settings.SYNC_STATE_USER_INI: {"LIVE": {"k": val("v", T1)}},
                 settings.SYNC_STATE_USER_INI_SEEN: {"LIVE": {"k": "v"}}}
        settings.set_smart_sync_state(state)
        assert settings.get_smart_sync_state() == state
        settings.set_smart_sync_folder(None)
        assert settings.get_smart_sync_state() == {}

    def test_a_broken_state_file_reads_as_none(self, settings):
        settings.get_smart_sync_state_path().write_text("{", encoding="utf-8")
        assert settings.get_smart_sync_state() == {}

    def test_backups_keep_the_newest_five(self, settings):
        made = [settings.write_smart_sync_backup() for _ in range(7)]
        kept = sorted(settings.get_smart_sync_backups_dir().glob("*.zip"))
        assert kept == sorted(made[-5:])

    def seed_state(self, settings):
        values = settings.smart_sync_settings_values()
        settings.set_smart_sync_state({
            settings.SYNC_STATE_SETTINGS: smart_sync.baseline_values({}, values),
            settings.SYNC_STATE_SETTINGS_SEEN: values,
            settings.SYNC_STATE_USER_INI: {},
            settings.SYNC_STATE_USER_INI_SEEN: {},
        })

    def test_startup_applies_another_pcs_setting_after_a_backup(self, settings):
        self.seed_state(settings)
        state = settings.get_smart_sync_state()
        state[settings.SYNC_STATE_SETTINGS][settings.FAVORITE_PREFIX] = val("#", T2)
        settings.set_smart_sync_state(state)
        assert settings.apply_synced_settings_at_startup() == 1
        assert settings.get_favorite_prefix() == "#"
        assert len(list(settings.get_smart_sync_backups_dir().glob("*.zip"))) == 1
        # Seen now holds it, so the next start changes nothing.
        assert settings.apply_synced_settings_at_startup() == 0

    def test_startup_keeps_a_change_made_here_since_the_last_sync(self, settings):
        self.seed_state(settings)
        settings.set_favorite_prefix("!")
        assert settings.apply_synced_settings_at_startup() == 0
        assert settings.get_favorite_prefix() == "!"
        entry_ = settings.get_smart_sync_state()[settings.SYNC_STATE_SETTINGS][
            settings.FAVORITE_PREFIX]
        assert entry_[VALUE] == "!" and entry_[AT] > BASELINE_AT

    def test_startup_changes_nothing_without_a_backup(self, settings, monkeypatch):
        self.seed_state(settings)
        state = settings.get_smart_sync_state()
        state[settings.SYNC_STATE_SETTINGS][settings.FAVORITE_PREFIX] = val("#", T2)
        settings.set_smart_sync_state(state)

        def refuse():
            raise OSError("disk full")
        monkeypatch.setattr(settings, "write_smart_sync_backup", staticmethod(refuse))
        assert settings.apply_synced_settings_at_startup() == 0
        assert settings.get_favorite_prefix() == settings.DEFAULT_FAVORITE_PREFIX

    def test_startup_never_touches_a_local_key(self, settings):
        self.seed_state(settings)
        state = settings.get_smart_sync_state()
        state[settings.SYNC_STATE_SETTINGS][settings.ACTIVE_CHANNEL] = val("PTU", T2)
        settings.set_smart_sync_state(state)
        settings.apply_synced_settings_at_startup()
        assert settings.get_active_channel() == "LIVE"

    def test_off_applies_nothing(self, settings):
        self.seed_state(settings)
        settings.set_smart_sync_folder(None)
        assert settings.apply_synced_settings_at_startup() == 0

    def test_registry_strings_are_the_same_setting(self, settings):
        assert settings._same_setting(True, "true")
        assert settings._same_setting(3, "3")
        assert not settings._same_setting("a", "b")


class TestTheWindowTakesEdits:
    """MainWindow._smart_sync_inputs / _take_synced_edits on a stub self."""

    @pytest.fixture
    def settings(self, tmp_profile):
        from src.utils.settings import AppSettings
        AppSettings.set_smart_sync_folder(tmp_profile / "Drive")
        return AppSettings

    def stub(self):
        from unittest.mock import MagicMock
        me = MagicMock()
        me.entries = []
        return me

    def write_ini(self, settings, channel, text):
        path = settings.get_channel_user_ini_path(channel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def inputs(self, me):
        from src.gui.main_window import MainWindow
        return MainWindow._smart_sync_inputs(me)

    def take(self, me, result):
        from src.gui.main_window import MainWindow
        return MainWindow._take_synced_edits(me, result, smart_sync.merge([result.ledger]))

    def test_the_first_sync_passes_baselines(self, settings):
        self.write_ini(settings, "LIVE", "k=v\n")
        _args, extra, changed = self.inputs(self.stub())
        assert changed
        assert extra["baseline_user_ini"] == {"LIVE": {"k": "v"}}
        assert settings.FAVORITE_PREFIX in extra["baseline_settings"]

    def joined(self, settings, me):
        """Run one sync so the state file exists, as after a first sync."""
        _args, extra, _ = self.inputs(me)
        result = smart_sync.sync(settings.get_smart_sync_folder(), "aaaa0000", {}, set(),
                                 **extra)
        assert self.take(me, result)
        return result

    def test_an_edit_saved_here_is_recorded(self, settings):
        me = self.stub()
        self.joined(settings, me)
        self.write_ini(settings, "PTU", "k=mine\n")
        _args, extra, changed = self.inputs(me)
        assert changed
        assert extra["user_ini"]["PTU"]["k"][VALUE] == "mine"

    def test_another_pcs_edit_is_written_after_a_backup(self, settings):
        me = self.stub()
        first = self.joined(settings, me)
        self.write_ini(settings, "LIVE", "keep=me\n")
        incoming = smart_sync.SyncResult(
            ledger={}, seeded=frozenset(), machine_id="aaaa0000",
            settings=first.settings,
            user_ini={"LIVE": {"k": val("theirs", T2)}, "PTU": {"p": val("ptu", T2)}})
        # keep=me was saved here meanwhile and must survive.
        assert self.take(me, incoming)
        text = settings.get_channel_user_ini_path("LIVE").read_text(encoding="utf-8")
        assert "k=theirs" in text and "keep=me" in text
        assert "p=ptu" in settings.get_channel_user_ini_path("PTU").read_text(encoding="utf-8")
        assert list(settings.get_smart_sync_backups_dir().glob("*.zip"))
        me._take_synced_user_ini.assert_called_once()

    def test_a_removal_from_another_pc_removes_the_edit(self, settings):
        self.write_ini(settings, "LIVE", "k=v\nother=x\n")
        me = self.stub()
        first = self.joined(settings, me)
        incoming = smart_sync.SyncResult(
            ledger={}, seeded=frozenset(), machine_id="aaaa0000", settings=first.settings,
            user_ini={"LIVE": {"k": val(None, T2), "other": val("x", BASELINE_AT)}})
        assert self.take(me, incoming)
        text = settings.get_channel_user_ini_path("LIVE").read_text(encoding="utf-8")
        assert "k=" not in text and "other=x" in text

    def test_no_backup_takes_nothing(self, settings, monkeypatch):
        me = self.stub()
        first = self.joined(settings, me)

        def refuse():
            raise OSError("disk full")
        monkeypatch.setattr(settings, "write_smart_sync_backup", staticmethod(refuse))
        incoming = smart_sync.SyncResult(
            ledger={}, seeded=frozenset(), machine_id="aaaa0000", settings=first.settings,
            user_ini={"LIVE": {"k": val("theirs", T2)}})
        assert not self.take(me, incoming)
        assert not settings.get_channel_user_ini_path("LIVE").exists()
        me.statusBar.return_value.showMessage.assert_called_once()

    def test_a_setting_from_another_pc_waits_for_the_next_start(self, settings):
        me = self.stub()
        first = self.joined(settings, me)
        incoming_settings = dict(first.settings)
        incoming_settings[settings.FAVORITE_PREFIX] = val("#", T2)
        incoming = smart_sync.SyncResult(ledger={}, seeded=frozenset(), machine_id="aaaa0000",
                                         settings=incoming_settings)
        assert self.take(me, incoming)
        assert settings.get_favorite_prefix() == settings.DEFAULT_FAVORITE_PREFIX
        me.statusBar.return_value.showMessage.assert_called_once()
        assert settings.apply_synced_settings_at_startup() == 1
        assert settings.get_favorite_prefix() == "#"


class TestTheTableTakesSyncedEdits:
    def test_only_the_changed_rows_are_touched(self):
        from unittest.mock import MagicMock
        from src.gui.main_window import MainWindow
        from src.models.string_model import StringEntry
        me = MagicMock()
        a = StringEntry("a", "global", "", "A", "", "Unmodified")
        b = StringEntry("b", "global", "", "B", "mine", "Modified")
        me.entries = [a, b]
        me.default_values = {}
        MainWindow._take_synced_user_ini(me, {"b": "mine"}, {"a": "theirs", "b": "mine"})
        assert a.custom_value == "theirs" and a.status == "Modified"
        assert b.custom_value == "mine"
        me._model.notify_entry_changed.assert_called_once_with(0)
        me._mark_apply_dirty.assert_called_once()
