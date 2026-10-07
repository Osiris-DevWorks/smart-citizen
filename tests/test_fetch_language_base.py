"""fetch_language_base — the URL-vs-local-path dispatch LanguageBaseDownloadWorker
relies on (#409 follow-up). Extracted to a plain function so the branch Osiris
flagged as untested (workers.py:229-244, pre-#409-fix line numbers) can be
covered without pytest-qt (see tests/CLAUDE.md: QThread workers have no
automated tests for that reason alone).
"""
from pathlib import Path

import pytest

from src.utils import updater

pytestmark = pytest.mark.unit


class TestUrlSource:
    def test_delegates_to_download_file_if_changed(self, tmp_path, monkeypatch):
        calls = []

        def fake_download(url, output_path):
            calls.append((url, output_path))
            return True

        monkeypatch.setattr(updater, "download_file_if_changed", fake_download)
        dest = tmp_path / "base.ini"

        result = updater.fetch_language_base("https://example.test/global.ini", dest)

        assert result is True
        assert calls == [("https://example.test/global.ini", dest)]

    def test_propagates_unchanged_result(self, tmp_path, monkeypatch):
        monkeypatch.setattr(updater, "download_file_if_changed", lambda url, output_path: False)
        dest = tmp_path / "base.ini"

        assert updater.fetch_language_base("http://example.test/global.ini", dest) is False

    def test_propagates_download_failure(self, tmp_path, monkeypatch):
        def fake_download(url, output_path):
            raise RuntimeError("network down")

        monkeypatch.setattr(updater, "download_file_if_changed", fake_download)

        with pytest.raises(RuntimeError, match="network down"):
            updater.fetch_language_base("https://example.test/global.ini", tmp_path / "base.ini")


class TestLocalPathSource:
    def test_copies_local_file_to_dest(self, tmp_path):
        source = tmp_path / "korean_patch" / "global.ini"
        source.parent.mkdir()
        source.write_text("key=value\n", encoding="utf-8")
        dest = tmp_path / "cache" / "lang" / "korean" / "base.ini"

        result = updater.fetch_language_base(str(source), dest)

        assert result is True
        assert dest.read_text(encoding="utf-8") == "key=value\n"

    def test_creates_missing_parent_directory(self, tmp_path):
        source = tmp_path / "global.ini"
        source.write_text("key=value\n", encoding="utf-8")
        dest = tmp_path / "does" / "not" / "exist" / "base.ini"
        assert not dest.parent.exists()

        updater.fetch_language_base(str(source), dest)

        assert dest.parent.exists()
        assert dest.exists()

    def test_missing_local_source_raises(self, tmp_path):
        missing_source = tmp_path / "nope.ini"
        dest = tmp_path / "base.ini"

        with pytest.raises(OSError):
            updater.fetch_language_base(str(missing_source), dest)

        assert not dest.exists()

    def test_accepts_path_objects_for_both_args(self, tmp_path):
        source = tmp_path / "global.ini"
        source.write_text("key=value\n", encoding="utf-8")
        dest = tmp_path / "base.ini"

        assert updater.fetch_language_base(str(source), Path(dest)) is True
        assert dest.exists()

    def test_does_not_treat_a_path_containing_http_as_a_url(self, tmp_path):
        # A local folder literally named "http" is a local path, not a URL —
        # only a scheme *prefix* should select the download branch.
        source_dir = tmp_path / "httpdocs"
        source_dir.mkdir()
        source = source_dir / "global.ini"
        source.write_text("key=value\n", encoding="utf-8")
        dest = tmp_path / "base.ini"

        assert updater.fetch_language_base(str(source), dest) is True
        assert dest.read_text(encoding="utf-8") == "key=value\n"
