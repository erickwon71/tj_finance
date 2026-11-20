"""collector/raw_paths.on_disk: an NFC path finds the NFD-named folder (NAS behaviour after macOS 27.2.1)."""
import unicodedata
from pathlib import Path

from collector import raw_paths


def _smb_like(monkeypatch):
    """APFS matches NFC and NFD itself, so emulate the NAS: only the exact on-disk spelling exists."""
    real_exists = Path.exists

    def exists(self):
        s = str(self)
        if s != unicodedata.normalize("NFD", s) and any("가" <= ch <= "힣" for ch in s):
            return False          # a composed Hangul spelling is not found
        return real_exists(self)
    monkeypatch.setattr(Path, "exists", exists)
    raw_paths.clear_cache()


def test_nfc_path_resolves_to_nfd_folder(tmp_path, monkeypatch):
    nfd = unicodedata.normalize("NFD", "00264255_바텍")
    (tmp_path / "KOSDAQ" / nfd / "quarter").mkdir(parents=True)
    (tmp_path / "KOSDAQ" / nfd / "quarter" / "1.xml").write_text("x")
    _smb_like(monkeypatch)
    nfc_path = tmp_path / "KOSDAQ" / "00264255_바텍" / "quarter" / "1.xml"
    got = raw_paths.on_disk(nfc_path)
    assert got.exists() and got.read_text() == "x"
    assert unicodedata.is_normalized("NFD", got.parent.parent.name)


def test_existing_and_unmatched_paths_are_returned_unchanged(tmp_path, monkeypatch):
    (tmp_path / "KOSDAQ" / "00111218_KD").mkdir(parents=True)
    _smb_like(monkeypatch)
    ok = tmp_path / "KOSDAQ" / "00111218_KD"
    assert raw_paths.on_disk(ok) == ok
    missing = tmp_path / "KOSDAQ" / "99999999_없음" / "x.xml"
    assert raw_paths.on_disk(missing) == missing
    assert raw_paths.on_disk_str(None) is None


def test_nfc_spelling_that_briefly_exists_still_resolves_to_nfd(tmp_path, monkeypatch):
    """R357: right after a mount the SMB client resolves an NFC lookup for a while — the stored
    path must still be the on-disk (NFD) spelling, or it stops opening minutes later."""
    nfd = unicodedata.normalize("NFD", "00108612_DS단석")
    (tmp_path / "KOSPI" / nfd / "quarter" / "2026").mkdir(parents=True)
    monkeypatch.setattr(Path, "exists", lambda self: True)     # every spelling "exists"
    raw_paths.clear_cache()
    got = raw_paths.on_disk(tmp_path / "KOSPI" / "00108612_DS단석" / "quarter" / "2026")
    assert unicodedata.is_normalized("NFD", got.parent.parent.name)
    assert got.parent.parent.name == nfd


def test_missing_tail_keeps_the_resolved_company_folder(tmp_path, monkeypatch):
    """R357: a fiscal-year folder not created yet must not undo the company folder's spelling."""
    nfd = unicodedata.normalize("NFD", "00977650_엔케이젠바이오텍코리아")
    (tmp_path / "KOSDAQ" / nfd / "annual").mkdir(parents=True)
    _smb_like(monkeypatch)
    got = raw_paths.on_disk(tmp_path / "KOSDAQ" / "00977650_엔케이젠바이오텍코리아" / "annual" / "2026")
    assert got == tmp_path / "KOSDAQ" / nfd / "annual" / "2026"
