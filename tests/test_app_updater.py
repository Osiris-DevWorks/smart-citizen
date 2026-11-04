"""Pure-function tests for utils.app_updater.

Network-hitting paths (AppUpdateCheckWorker.run, AppUpdateDownloadWorker.run)
aren't covered here — tested manually against real GitHub. These cover the
version parsing / comparison logic and the #211 installer-asset picker,
which is where silent regressions would hurt (we'd either stop nagging when
we should, start nagging on valid data, or download the wrong asset).
"""
import pytest

from src.utils.app_updater import parse_version, is_newer, pick_installer_asset


class TestParseVersion:
    def test_plain(self):
        assert parse_version("0.9.3") == (0, 9, 3)

    def test_v_prefix(self):
        assert parse_version("v0.9.3") == (0, 9, 3)

    def test_uppercase_v_prefix(self):
        assert parse_version("V0.9.3") == (0, 9, 3)

    def test_surrounding_whitespace(self):
        assert parse_version("  0.9.3  ") == (0, 9, 3)

    def test_missing_patch(self):
        assert parse_version("0.9") == (0, 9, 0)

    def test_extra_segments_ignored(self):
        assert parse_version("1.2.3.4") == (1, 2, 3)

    def test_non_numeric(self):
        assert parse_version("garbage") is None

    def test_empty(self):
        assert parse_version("") is None

    def test_none_safe(self):
        # Pass a string that hits the len<2 branch without splitting.
        assert parse_version("0") is None

    def test_partial_numeric(self):
        # Mixed alphanumeric should fail rather than partially parse.
        assert parse_version("0.9.3-rc1") is None

    def test_large_numbers(self):
        assert parse_version("v100.200.300") == (100, 200, 300)


class TestIsNewer:
    def test_strictly_newer_patch(self):
        assert is_newer("0.9.4", "0.9.3") is True

    def test_strictly_newer_minor(self):
        assert is_newer("0.10.0", "0.9.9") is True

    def test_strictly_newer_major(self):
        assert is_newer("1.0.0", "0.9.9") is True

    def test_equal(self):
        assert is_newer("0.9.3", "0.9.3") is False

    def test_older(self):
        assert is_newer("0.9.2", "0.9.3") is False

    def test_v_prefix_both(self):
        assert is_newer("v0.9.4", "v0.9.3") is True

    def test_v_prefix_one_side(self):
        assert is_newer("v0.9.4", "0.9.3") is True
        assert is_newer("0.9.4", "v0.9.3") is True

    def test_unparseable_latest_fails_safe(self):
        # When we can't read the remote tag, don't nag — behave as
        # "nothing newer available."
        assert is_newer("garbage", "0.9.3") is False

    def test_unparseable_current_fails_safe(self):
        assert is_newer("0.9.4", "garbage") is False

    def test_both_unparseable(self):
        assert is_newer("garbage", "other-garbage") is False

    def test_empty_strings(self):
        assert is_newer("", "") is False
        assert is_newer("", "0.9.3") is False
        assert is_newer("0.9.3", "") is False


def _asset(name, url="https://example.com/dl", size=1000):
    return {"name": name, "browser_download_url": url, "size": size}


class TestPickInstallerAsset:
    """Asset selection for the in-app auto-updater (#211).

    The picker must find exactly the Windows installer and nothing else —
    a wrong pick would download (and silently run) the wrong file.
    """

    def test_picks_setup_exe(self):
        assets = [_asset("SmartCitizen-2.1.2-Setup.exe", size=123456789)]
        assert pick_installer_asset(assets) == ("https://example.com/dl", 123456789)

    def test_none_assets(self):
        assert pick_installer_asset(None) is None

    def test_empty_assets(self):
        assert pick_installer_asset([]) is None

    def test_release_without_installer(self):
        assets = [_asset("SmartCitizen-Portable-v2.1.2.zip")]
        assert pick_installer_asset(assets) is None

    def test_picks_installer_among_other_assets(self):
        assets = [
            _asset("SmartCitizen-Portable-v2.1.2.zip", url="https://example.com/zip"),
            _asset("checksums.txt", url="https://example.com/txt"),
            _asset("SmartCitizen-2.1.2-Setup.exe", url="https://example.com/exe"),
        ]
        assert pick_installer_asset(assets) == ("https://example.com/exe", 1000)

    def test_case_insensitive_name(self):
        assets = [_asset("smartcitizen-2.1.2-setup.EXE")]
        assert pick_installer_asset(assets) is not None

    def test_anchored_no_suffix_junk(self):
        # A signature/sidecar file must not be mistaken for the installer.
        assets = [_asset("SmartCitizen-2.1.2-Setup.exe.sig")]
        assert pick_installer_asset(assets) is None

    def test_anchored_no_prefix_junk(self):
        assets = [_asset("not-SmartCitizen-2.1.2-Setup.exe")]
        assert pick_installer_asset(assets) is None

    def test_missing_url_skipped(self):
        assets = [{"name": "SmartCitizen-2.1.2-Setup.exe", "size": 5}]
        assert pick_installer_asset(assets) is None

    def test_malformed_entries_skipped_not_fatal(self):
        assets = [
            None,
            "just-a-string",
            {"name": "SmartCitizen-2.1.2-Setup.exe",
             "browser_download_url": "https://example.com/exe",
             "size": "not-a-number"},
            _asset("SmartCitizen-2.1.2-Setup.exe", url="https://example.com/good"),
        ]
        assert pick_installer_asset(assets) == ("https://example.com/good", 1000)

    def test_missing_size_defaults_to_zero(self):
        assets = [{"name": "SmartCitizen-2.1.2-Setup.exe",
                   "browser_download_url": "https://example.com/exe"}]
        assert pick_installer_asset(assets) == ("https://example.com/exe", 0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
