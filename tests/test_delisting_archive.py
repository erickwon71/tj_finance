"""collector.delisting_archive 회귀 테스트 — 상장폐지 확정분 원문 이관 자동화.

데일리(collect_new.py ⓪-4)가 자동으로 **파일을 옮기고 지우는** 유일한 지점이라
여기서 고정하는 것은 전부 "사고가 나면 어떻게 되나"다:

  ① NAS 이관은 이동이지 삭제가 아니다 — 원문은 archive/delisted/{연도}/ 에 그대로 남는다
  ② SD 삭제는 NAS 아카이브 실물이 확인된 뒤에만 — 원본 없이 백업만 지우는 사고 방지(A3)
  ③ 파일 수가 모자라면(이동이 덜 끝났으면) 지우지 않는다(A3)
  ④ SD 삭제 전 `assert_storage(require_backup=True)` 를 반드시 부른다(A2 — 빈 마운트포인트)
  ⑤ 이관 대상이 상한을 넘으면 **부분 실행이 아니라 전면 중단**(A1)
  ⑥ 아카이브에 같은 이름이 이미 있으면 덮어쓰지 않는다

실제 NAS/SD/DB 를 건드리지 않도록 tmp 볼륨 + 가짜 세션으로 모듈 상수를 갈아끼운다.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector import delisting_archive as da  # noqa: E402
from tests._util import run_tests  # noqa: E402


# ── 가짜 DB ─────────────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    """corporations 한 테이블만 흉내낸다. SQL 은 키워드로 분기."""

    def __init__(self, store: list[dict]):
        self.store = store

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if sql.lstrip().upper().startswith("UPDATE"):
            for row in self.store:
                if row["corp_code"] == params["c"]:
                    row["archive_path"] = params["p"]
            return _FakeResult([])
        pending = "archive_path IS NULL" in sql
        rows = [r for r in self.store
                if r["delisting_status"] == "confirmed"
                and ((r["archive_path"] is None) if pending else (r["archive_path"] is not None))]
        return _FakeResult([(r["corp_code"], r["corp_name"], r["market"])
                            if pending else
                            (r["corp_code"], r["corp_name"], r["market"], r["archive_path"])
                            for r in rows])

    def commit(self):
        pass


@contextmanager
def fake_env(corps: list[dict], on_nas: list[str] = (), on_sd: list[str] = ()):
    """tmp NAS/SD 볼륨 + 가짜 세션으로 모듈 상수를 교체.

    corps: [{corp_code, corp_name, market, delisting_status, archive_path}]
    on_nas/on_sd: 폴더를 만들어 둘 corp_code 목록 (각 폴더에 파일 2개)
    """
    tmp = Path(tempfile.mkdtemp(prefix="tj_da_"))
    saved = {k: getattr(da, k) for k in
             ("PRIMARY_ROOT", "BACKUP_ROOT", "ARCHIVE_ROOT", "get_session", "assert_storage")}
    calls: list[bool] = []
    try:
        da.PRIMARY_ROOT = tmp / "nas" / "raw_report"
        da.BACKUP_ROOT = tmp / "sd" / "raw_report"
        da.ARCHIVE_ROOT = tmp / "nas" / "archive" / "delisted"
        for root, codes in ((da.PRIMARY_ROOT, on_nas), (da.BACKUP_ROOT, on_sd)):
            for code in codes:
                c = next(x for x in corps if x["corp_code"] == code)
                d = root / c["market"] / f"{code}_{c['corp_name']}" / "2025"
                d.mkdir(parents=True)
                (d / "a.xml").write_text("a")
                (d / "b.xml").write_text("b")

        @contextmanager
        def _session():
            yield _FakeSession(corps)

        da.get_session = _session
        da.assert_storage = lambda require_backup=False: calls.append(require_backup)
        yield tmp, calls
    finally:
        for k, v in saved.items():
            setattr(da, k, v)
        shutil.rmtree(tmp, ignore_errors=True)


def _corp(code, name="테스트", market="KOSPI", status="confirmed", archive_path=None):
    return {"corp_code": code, "corp_name": name, "market": market,
            "delisting_status": status, "archive_path": archive_path}


# ── ① NAS 이관 = 이동(삭제 아님) ────────────────────────────────────

def test_archive_moves_and_records_path():
    corps = [_corp("00000001", "노블")]
    with fake_env(corps, on_nas=["00000001"]) as (tmp, _):
        r = da.archive_confirmed(apply=True)
        assert len(r["moved"]) == 1 and not r["errors"], r
        dst = da.ARCHIVE_ROOT / str(date.today().year) / "00000001_노블"
        assert dst.is_dir(), "아카이브로 이동되지 않았다"
        assert (dst / "2025" / "a.xml").read_text() == "a", "파일 내용이 유실됐다"
        assert not (da.PRIMARY_ROOT / "KOSPI" / "00000001_노블").exists(), "원위치가 남았다"
        assert corps[0]["archive_path"] == str(dst), "archive_path 미기록"


def test_archive_dry_run_moves_nothing():
    corps = [_corp("00000001", "노블")]
    with fake_env(corps, on_nas=["00000001"]):
        r = da.archive_confirmed(apply=False)
        assert len(r["moved"]) == 1, "드라이런 대상 집계가 없다"
        assert (da.PRIMARY_ROOT / "KOSPI" / "00000001_노블").is_dir(), "드라이런인데 옮겼다"
        assert corps[0]["archive_path"] is None, "드라이런인데 DB 를 바꿨다"


def test_archive_no_source_is_not_error():
    """원문을 한 번도 받지 않은 기업 — 결함이 아니라 건너뛰기."""
    corps = [_corp("00000001", "노블")]
    with fake_env(corps):
        r = da.archive_confirmed(apply=True)
        assert len(r["no_source"]) == 1 and not r["errors"], r


def test_archive_never_overwrites_existing():
    """같은 이름이 아카이브에 이미 있으면 덮어쓰지 않는다(과거분 유실 방지)."""
    corps = [_corp("00000001", "노블")]
    with fake_env(corps, on_nas=["00000001"]):
        old = da.ARCHIVE_ROOT / str(date.today().year) / "00000001_노블"
        old.mkdir(parents=True)
        (old / "old.xml").write_text("old")
        r = da.archive_confirmed(apply=True)
        assert len(r["errors"]) == 1 and not r["moved"], r
        assert (old / "old.xml").read_text() == "old", "기존 아카이브가 덮였다"
        assert (da.PRIMARY_ROOT / "KOSPI" / "00000001_노블").is_dir(), "원문이 사라졌다"


# ── ⑤ A1 상한: 부분 실행이 아니라 전면 중단 ────────────────────────

def test_cap_exceeded_stops_everything():
    corps = [_corp(f"0000000{i}", f"기업{i}") for i in range(1, 5)]
    with fake_env(corps, on_nas=[c["corp_code"] for c in corps]):
        r = da.archive_confirmed(apply=True, limit=3)
        assert r["capped"] and not r["moved"], r
        for c in corps:
            assert (da.PRIMARY_ROOT / "KOSPI" / f"{c['corp_code']}_{c['corp_name']}").is_dir()


def test_run_daily_skips_purge_when_capped():
    """상한에 걸린 실행은 SD 도 건드리지 않는다."""
    corps = [_corp(f"0000000{i}", f"기업{i}") for i in range(1, 5)]
    saved = da.MAX_ARCHIVE_PER_RUN
    da.MAX_ARCHIVE_PER_RUN = 3
    try:
        with fake_env(corps, on_nas=[c["corp_code"] for c in corps],
                      on_sd=[c["corp_code"] for c in corps]) as (tmp, calls):
            s = da.run_daily(apply=True)
            assert s["archive_capped"] and s["backup_purged"] == 0, s
            assert True not in calls, "상한 중단인데 백업 계약 검사를 돌렸다(=SD 를 만졌다)"
    finally:
        da.MAX_ARCHIVE_PER_RUN = saved


# ── ②③④ SD 삭제 가드 ───────────────────────────────────────────────

def test_purge_removes_sd_only_after_archive_exists():
    corps = [_corp("00000001", "노블")]
    with fake_env(corps, on_nas=["00000001"], on_sd=["00000001"]) as (tmp, calls):
        da.archive_confirmed(apply=True)
        r = da.purge_backup(apply=True)
        assert len(r["purged"]) == 1 and not r["skipped"], r
        assert not (da.BACKUP_ROOT / "KOSPI" / "00000001_노블").exists(), "SD 가 안 지워졌다"
        arc = da.ARCHIVE_ROOT / str(date.today().year) / "00000001_노블"
        assert (arc / "2025" / "a.xml").is_file(), "NAS 아카이브가 온전하지 않다"
        assert True in calls, "SD 삭제 전에 require_backup 계약 검사를 안 했다"


def test_purge_skips_when_archive_missing():
    """★ 원본 없이 백업만 지우는 사고 — archive_path 는 있는데 실물이 없는 경우."""
    corps = [_corp("00000001", "노블", archive_path="/nowhere/00000001_노블")]
    with fake_env(corps, on_sd=["00000001"]):
        r = da.purge_backup(apply=True)
        assert not r["purged"] and len(r["skipped"]) == 1, r
        assert (da.BACKUP_ROOT / "KOSPI" / "00000001_노블").is_dir(), "백업이 지워졌다!"


def test_purge_skips_when_archive_has_fewer_files():
    """이동이 덜 끝난 상태 — 파일 수가 SD 보다 적으면 지우지 않는다."""
    corps = [_corp("00000001", "노블")]
    with fake_env(corps, on_nas=["00000001"], on_sd=["00000001"]):
        da.archive_confirmed(apply=True)
        arc = da.ARCHIVE_ROOT / str(date.today().year) / "00000001_노블"
        (arc / "2025" / "a.xml").unlink()          # 결함 주입: 아카이브 쪽 파일 유실
        r = da.purge_backup(apply=True)
        assert not r["purged"] and len(r["skipped"]) == 1, r
        assert (da.BACKUP_ROOT / "KOSPI" / "00000001_노블").is_dir(), "백업이 지워졌다!"


def test_purge_dry_run_deletes_nothing():
    corps = [_corp("00000001", "노블")]
    with fake_env(corps, on_nas=["00000001"], on_sd=["00000001"]):
        da.archive_confirmed(apply=True)
        r = da.purge_backup(apply=False)
        assert len(r["purged"]) == 1, "드라이런 대상 집계가 없다"
        assert (da.BACKUP_ROOT / "KOSPI" / "00000001_노블").is_dir(), "드라이런인데 지웠다"


def test_purge_ignores_non_confirmed():
    """후보(candidate)는 어떤 경우에도 파일 조치 대상이 아니다."""
    corps = [_corp("00000001", "노블", status="candidate")]
    with fake_env(corps, on_nas=["00000001"], on_sd=["00000001"]):
        assert not da.archive_confirmed(apply=True)["moved"]
        assert not da.purge_backup(apply=True)["purged"]
        assert (da.PRIMARY_ROOT / "KOSPI" / "00000001_노블").is_dir()
        assert (da.BACKUP_ROOT / "KOSPI" / "00000001_노블").is_dir()


# ── 데일리 진입점 — 이관 → SD 정리 한 번에 ──────────────────────────

def test_run_daily_archives_then_purges():
    corps = [_corp("00000001", "노블"), _corp("00000002", "바이온", market="KOSDAQ")]
    with fake_env(corps, on_nas=["00000001", "00000002"],
                  on_sd=["00000001", "00000002"]):
        s = da.run_daily(apply=True)
        assert s["archived"] == 2 and s["backup_purged"] == 2, s
        for c in corps:
            name = f"{c['corp_code']}_{c['corp_name']}"
            assert not (da.PRIMARY_ROOT / c["market"] / name).exists()
            assert not (da.BACKUP_ROOT / c["market"] / name).exists()
            assert (da.ARCHIVE_ROOT / str(date.today().year) / name / "2025" / "a.xml").is_file()


if __name__ == "__main__":
    sys.exit(1 if run_tests(globals()) else 0)
