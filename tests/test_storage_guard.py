"""collector.storage_guard 회귀 테스트 — 저장소 계약 불변식 I1/I2/I3.

실제 NAS/SD 를 건드리지 않도록 tmp 디렉터리로 가짜 볼륨을 만들고 모듈 상수를 갈아끼운다.
각 케이스는 "이 결함을 주입하면 반드시 StorageContractError 가 난다"를 고정한다.
경고 후 진행(2026-07-17 실패 패턴)이 되살아나면 여기서 잡힌다.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector import storage_guard as sg  # noqa: E402
from tests._util import run_tests  # noqa: E402


@contextmanager
def fake_volumes(primary_sentinel: str | None = "nas-primary",
                 backup_sentinel: str | None = "sd-backup",
                 symlink_to_backup: bool = False,
                 primary_empty: bool = False):
    """가짜 PRIMARY/BACKUP 볼륨 + raw_report 심링크를 만들고 모듈 상수를 교체."""
    tmp = Path(tempfile.mkdtemp(prefix="tj_sg_"))
    saved = {k: getattr(sg, k) for k in
             ("PRIMARY_VOLUME", "BACKUP_VOLUME", "PRIMARY_ROOT", "BACKUP_ROOT", "SYMLINK")}
    try:
        pv, bv = tmp / "nas", tmp / "sd"
        pr, br = pv / "raw_report", bv / "raw_report"
        for d in (pr, br):
            d.mkdir(parents=True)
        if not primary_empty:
            (pr / "KOSPI").mkdir()
        (br / "KOSPI").mkdir()
        if primary_sentinel is not None:
            (pv / sg.SENTINEL_NAME).write_text(primary_sentinel + "\n")
        if backup_sentinel is not None:
            (bv / sg.SENTINEL_NAME).write_text(backup_sentinel + "\n")

        link = tmp / "raw_report"
        link.symlink_to(br if symlink_to_backup else pr)

        sg.PRIMARY_VOLUME, sg.BACKUP_VOLUME = pv, bv
        sg.PRIMARY_ROOT, sg.BACKUP_ROOT = pr, br
        sg.SYMLINK = link
        yield tmp
    finally:
        for k, v in saved.items():
            setattr(sg, k, v)
        shutil.rmtree(tmp, ignore_errors=True)


def _raises(fn) -> bool:
    try:
        fn()
    except sg.StorageContractError:
        return True
    return False


# ── 정상 경로 ───────────────────────────────────────────────────────

def test_healthy_contract_passes():
    with fake_volumes():
        sg.assert_storage()
        sg.assert_storage(require_backup=True)


# ── I1: 심링크 드리프트 ─────────────────────────────────────────────

def test_symlink_drift_to_backup_raises():
    """4회 재발한 드리프트. 심링크가 BACKUP 을 가리키면 반드시 실패."""
    with fake_volumes(symlink_to_backup=True):
        assert _raises(sg.assert_storage), "심링크 드리프트가 통과됐다"


def test_symlink_not_a_symlink_raises():
    with fake_volumes() as tmp:
        sg.SYMLINK.unlink()
        sg.SYMLINK.mkdir()
        assert _raises(sg.assert_storage)


def test_symlink_broken_raises():
    """대상 볼륨 미마운트 = 끊어진 심링크."""
    with fake_volumes():
        shutil.rmtree(sg.PRIMARY_ROOT)
        assert _raises(sg.assert_storage)


# ── I2: sentinel ────────────────────────────────────────────────────

def test_primary_sentinel_missing_raises():
    """NAS 언마운트 후 빈 마운트포인트가 남은 상태."""
    with fake_volumes(primary_sentinel=None):
        assert _raises(sg.assert_storage)


def test_primary_sentinel_wrong_id_raises():
    """엉뚱한 볼륨이 마운트포인트에 붙은 상태."""
    with fake_volumes(primary_sentinel="sd-backup"):
        assert _raises(sg.assert_storage)


def test_backup_sentinel_only_checked_when_required():
    """백업 sentinel 결손은 require_backup=False 면 통과, True 면 실패."""
    with fake_volumes(backup_sentinel=None):
        sg.assert_storage()                                   # 미러 아닌 단계는 통과
        assert _raises(lambda: sg.assert_storage(require_backup=True))


# ── I3: 읽기/쓰기 ───────────────────────────────────────────────────

def test_primary_empty_raises():
    """원문 루트가 비었다 = 볼륨이 제대로 안 붙었다."""
    with fake_volumes(primary_empty=True):
        assert _raises(sg.assert_storage)


def test_primary_not_writable_raises():
    """2026-07-17 EPERM 재현 — 다운로드 시작 전에 잡아야 한다."""
    with fake_volumes():
        sg.PRIMARY_ROOT.chmod(0o500)
        try:
            assert _raises(sg.assert_storage)
        finally:
            sg.PRIMARY_ROOT.chmod(0o755)


# ── 계약 위반은 예외여야 한다(경고 후 진행 금지) ──────────────────

def test_failure_is_exception_not_return_value():
    """assert_storage 는 bool 을 돌려주지 않는다 — 호출자가 무시할 수 없어야 한다."""
    with fake_volumes():
        assert sg.assert_storage() is None


if __name__ == "__main__":
    sys.exit(1 if run_tests(globals()) else 0)
