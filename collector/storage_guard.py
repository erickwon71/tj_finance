"""저장소 계약 검증 — 원문(raw_report)의 쓰기 대상과 미러 소스에 대한 불변식.

배경(2026-07-31 감사):
  - `raw_report` 는 심링크이고, `download_tasks.file_path` 18만 건이 전부 이 심링크 경로로
    저장돼 있다. 따라서 심링크 대상이 곧 **원문을 읽고 쓰는 볼륨**이다.
  - 그 대상이 조용히 SD카드로 바뀌는 드리프트가 4회 재발했다(2026-07-07/11/26, 07-31).
  - 2026-07-17 실행은 심링크 대상 볼륨에 접근이 안 돼 다운로드 13/13 이 EPERM 으로 실패했는데,
    파이프라인은 이를 "비치명적"으로 넘기고 성공 로그를 남겼다.

지키는 불변식:
  I1  raw_report 심링크가 가리키는 볼륨 == 미러 소스 볼륨 == PRIMARY(NAS)
  I2  PRIMARY/BACKUP 이 각각 "진짜 그 볼륨"이다 (빈 마운트포인트가 아니다)
  I3  PRIMARY 를 지금 읽고 쓸 수 있다 (스테일 마운트가 아니다)

I2 가 중요한 이유: NAS 가 언마운트돼도 `/Volumes/tj_finance_data` 는 **빈 디렉터리로 존재**할 수
있다. 마운트 여부만 보면 이를 정상으로 오인하고, 그 상태로 미러의 삭제 동기화를 돌리면 백업이
통째로 지워진다. 그래서 볼륨 루트의 sentinel 파일 **내용까지** 확인한다.

sentinel 은 `raw_report` **바깥**(볼륨 루트)에 둔다 — 미러가 `raw_report/` 만 복사하므로
sentinel 이 백업으로 전파돼 서로 덮어쓰는 일이 없다.

실패는 예외다. 경고 후 진행하지 않는다(07-17 의 교훈).
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from loguru import logger

# ── 저장소 계약 상수 ────────────────────────────────────────────────
PRIMARY_VOLUME = Path("/Volumes/tj_finance_data")   # NAS(RAID1)
BACKUP_VOLUME  = Path("/Volumes/dart_data")         # SD카드

# 자동 재마운트 대상 — PRIMARY_VOLUME 과 별개 상수로 둔다. 테스트는 PRIMARY_VOLUME 을
# tmp 디렉터리로 갈아끼우므로, 이 고정값과 비교하면 테스트에서 자연히 스킵된다.
_PRODUCTION_MOUNT_POINT = Path("/Volumes/tj_finance_data")
_SMB_URL = "smb://tjkwon@192.168.0.96/tj_finance_data"
_MOUNT_WAIT_S = 20

PRIMARY_ROOT = PRIMARY_VOLUME / "raw_report"        # 쓰기 대상 · 미러 소스
BACKUP_ROOT  = BACKUP_VOLUME / "raw_report"         # 미러 목적지
ARCHIVE_ROOT = PRIMARY_VOLUME / "archive" / "delisted"

SENTINEL_NAME = ".tj_volume_id"
PRIMARY_ID    = "nas-primary"
BACKUP_ID     = "sd-backup"

# 리포지토리의 raw_report 심링크. 실제 원문 접근은 전부 이 경로를 통한다.
SYMLINK = Path(__file__).resolve().parents[1] / "raw_report"


class StorageContractError(RuntimeError):
    """저장소 계약 위반. 파이프라인은 즉시 중단해야 한다."""


# ── 개별 게이트 ─────────────────────────────────────────────────────

def check_sentinel(volume: Path, expected_id: str) -> None:
    """G1/G5 (I2) — 볼륨이 "진짜 그 볼륨"인지 sentinel 내용으로 확인."""
    sentinel = volume / SENTINEL_NAME
    if not sentinel.is_file():
        raise StorageContractError(
            f"[I2] sentinel 없음: {sentinel}\n"
            f"     볼륨이 마운트되지 않았거나 빈 마운트포인트일 수 있다."
        )
    try:
        actual = sentinel.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise StorageContractError(f"[I2] sentinel 읽기 실패: {sentinel} — {exc}") from exc
    if actual != expected_id:
        raise StorageContractError(
            f"[I2] sentinel 불일치: {sentinel}\n"
            f"     기대 '{expected_id}' · 실제 '{actual}'\n"
            f"     엉뚱한 볼륨이 이 마운트포인트에 붙어 있다."
        )


def check_symlink() -> None:
    """G2 (I1) — raw_report 심링크가 PRIMARY 를 가리키는지.

    이것이 깨지면 다운로드가 SD 로 가고 NAS(RAID1)에 원본이 쌓이지 않는다.
    미러가 덧붙이기 전용이라 파일이 삭제되지는 않지만, 이중화 없는 매체에만
    존재하는 원본이 생긴다.
    """
    if not SYMLINK.is_symlink():
        raise StorageContractError(
            f"[I1] raw_report 가 심링크가 아니다: {SYMLINK}"
        )
    try:
        target = SYMLINK.resolve(strict=True)
    except OSError as exc:
        raise StorageContractError(
            f"[I1] raw_report 심링크 대상 해석 실패(대상 볼륨 미마운트?): {SYMLINK} — {exc}"
        ) from exc
    expected = PRIMARY_ROOT.resolve()
    if target != expected:
        raise StorageContractError(
            f"[I1] 심링크 드리프트!\n"
            f"     {SYMLINK}\n"
            f"       가리킴: {target}\n"
            f"       기대값: {expected}\n"
            f"     원복: ln -sfn {PRIMARY_ROOT} {SYMLINK}"
        )


def check_writable(root: Path) -> None:
    """G3 (I3) — 지금 쓸 수 있는지. 07-17 의 EPERM 을 작업 시작 전에 잡는다."""
    probe = root / f".tj_write_probe.{os.getpid()}"
    try:
        probe.write_bytes(b"probe")
        probe.unlink()
    except OSError as exc:
        raise StorageContractError(
            f"[I3] 쓰기 불가: {root} — {type(exc).__name__}: {exc}\n"
            f"     스테일 마운트이거나 권한 문제. 2026-07-17 다운로드 전건 실패와 같은 상태."
        ) from exc


def check_readable(root: Path) -> None:
    """G4 (I3) — 지금 읽을 수 있는지. 전수 순회 없이 최상위 목록+stat 만 본다."""
    try:
        entries = os.listdir(root)
    except OSError as exc:
        raise StorageContractError(
            f"[I3] 읽기 불가: {root} — {type(exc).__name__}: {exc}"
        ) from exc
    if not entries:
        raise StorageContractError(
            f"[I3] 비어 있음: {root}\n"
            f"     원문 루트가 비었다는 것은 볼륨이 제대로 붙지 않았다는 뜻이다."
        )
    # 항목 하나를 실제로 stat — 목록만 캐시되고 실접근이 죽는 스테일 마운트 탐지
    try:
        (root / entries[0]).stat()
    except OSError as exc:
        raise StorageContractError(
            f"[I3] stat 실패(스테일 마운트 의심): {root / entries[0]} — {exc}"
        ) from exc


def ensure_mounted() -> None:
    """NAS(SMB) 가 언마운트 상태면 재마운트를 시도한다 — 사용자가 지금 수동으로 하는
    Finder Cmd+K 와 같은 경로(`open smb://...`)라 저장된 Keychain 자격증명을 그대로
    재사용한다(비밀번호를 코드/설정에 저장하지 않는다).

    **최선형 편의 기능**이다 — 실패해도 예외를 던지지 않는다. 이 함수 다음에 오는
    `assert_storage` 의 기존 검사(I1/I2/I3)가 여전히 명확한 에러로 막으므로, 재마운트에
    실패해도 07-17 의 "경고 후 진행" 패턴으로 되돌아가지 않는다.

    PRIMARY_VOLUME 이 실제 프로덕션 마운트포인트일 때만 시도한다 — 테스트는 PRIMARY_VOLUME
    을 tmp 디렉터리로 갈아끼우므로 자연히 스킵된다.
    """
    if PRIMARY_VOLUME != _PRODUCTION_MOUNT_POINT:
        return
    if os.path.ismount(PRIMARY_VOLUME):
        return
    logger.warning(f"[storage] {PRIMARY_VOLUME} 마운트 안 됨 — SMB 재마운트 시도")
    try:
        subprocess.run(["open", _SMB_URL], check=False, timeout=5)
    except Exception as exc:                        # noqa: BLE001 — 편의 기능, 실패해도 계속
        logger.warning(f"[storage] SMB 재마운트 명령 실행 실패(계약 검증이 계속 막을 것): {exc}")
        return
    for _ in range(_MOUNT_WAIT_S):
        time.sleep(1)
        if os.path.ismount(PRIMARY_VOLUME):
            logger.success(f"[storage] SMB 재마운트 성공 — {PRIMARY_VOLUME}")
            return
    logger.warning(
        f"[storage] SMB 재마운트 {_MOUNT_WAIT_S}초 대기 후에도 안 됨 "
        f"(Keychain 자격증명 미저장이거나 서버 응답 없음) — 계약 검증에서 명확한 에러로 막힘")


# ── 통합 진입점 ─────────────────────────────────────────────────────

def assert_storage(require_backup: bool = False) -> None:
    """저장소 계약 전체 검증. 하나라도 실패하면 StorageContractError.

    Args:
        require_backup: 미러 단계처럼 BACKUP 볼륨까지 필요할 때 True.
    """
    ensure_mounted()                             # NAS 언마운트 상태면 재마운트 시도(최선형)
    check_sentinel(PRIMARY_VOLUME, PRIMARY_ID)   # G1 (I2)
    check_symlink()                              # G2 (I1)
    check_writable(PRIMARY_ROOT)                 # G3 (I3)
    check_readable(PRIMARY_ROOT)                 # G4 (I3)

    if require_backup:
        check_sentinel(BACKUP_VOLUME, BACKUP_ID)  # G5 (I2)
        check_writable(BACKUP_ROOT)

    logger.debug(
        f"[storage] 계약 확인 — primary={PRIMARY_ROOT} "
        f"backup={'ok' if require_backup else 'skip'}"
    )


def describe() -> str:
    """현재 저장소 상태 요약(로그·리포트용). 예외를 던지지 않는다."""
    lines = [f"PRIMARY  {PRIMARY_ROOT}", f"BACKUP   {BACKUP_ROOT}"]
    try:
        lines.append(f"SYMLINK  {SYMLINK} -> {SYMLINK.resolve()}")
    except OSError as exc:
        lines.append(f"SYMLINK  {SYMLINK} -> (해석 실패: {exc})")
    for label, vol, want in (("primary", PRIMARY_VOLUME, PRIMARY_ID),
                             ("backup", BACKUP_VOLUME, BACKUP_ID)):
        try:
            got = (vol / SENTINEL_NAME).read_text(encoding="utf-8").strip()
        except OSError:
            got = "(없음)"
        lines.append(f"sentinel({label}) 기대 '{want}' · 실제 '{got}'")
    return "\n".join(lines)
