"""이미 아카이브된 상장폐지 기업의 download_tasks.file_path 소급 재배선.

배경 — `collector/delisting_archive.py` 의 `archive_confirmed()` 가 원문 폴더를 NAS
아카이브로 이관하면서 `corporations.archive_path` 만 갱신하고 `download_tasks.file_path`
는 옛 raw_report 경로 그대로 두던 결함이 있었다(2026-08). 그 함수 자체는 고쳤지만
(`_repoint_download_tasks`), 결함이 살아있던 동안 이미 이관된 기업들의 file_path 는
여전히 존재하지 않는 옛 경로를 가리킨다 — 그 filing 들은 로더마다 "file missing" 으로
조용히 영구 스킵된다.

이 스크립트는 `corporations.archive_path IS NOT NULL` 인 기업 전부를 대상으로,
file_path 가 아직 archive_path 로 시작하지 않는(=재배선 안 된) 것만 골라 한 번 교정한다.
이미 정상인 기업(이 수정 이후 새로 이관된 기업)은 자동으로 대상에서 빠진다 — 몇 번을
다시 돌려도 안전하다.

옛 경로가 이미 사라진 뒤라 정확한 접두(prefix)를 알 수 없다. 대신 archive_path 의 폴더명
(`{corp_code}_{안전화된 회사명}`)이 file_path 안에 그대로 들어 있다는 사실(둘 다
`_build_file_path()`/`_corp_dir()` 가 같은 폴더명을 쓴다)을 이용해 그 지점부터
잘라 붙인다. 붙인 뒤에는 실제로 그 경로에 파일이 있는지 확인하고서만 UPDATE 한다
(A3 와 같은 원칙 — 확인 없이 DB 만 바꾸지 않는다).

★ macOS 정규화 함정: `archive_path` 의 폴더명은 `Path.iterdir()` 로 **실제 디스크에서**
읽은 이름이라 한글이 NFD(분해형, 자모가 따로)로 온다. `file_path` 는 다운로드 시점에
Python 문자열로 만든 것이라 NFC(조합형)다. 둘 다 화면엔 똑같이 보이지만 바이트가 달라
그냥 `str.find()` 로는 못 찾는다 — 그래서 비교 전에 `unicodedata.normalize("NFC", ...)`
로 맞춘다(원문 XML 트랩과 무관한 별개 함정이니 `docs/PARSING_RULES.md` 대상은 아니다).

DB 텍스트 갱신만 한다 — 파일 이동·삭제는 하지 않는다. 기본은 조회만, `--apply` 로 실행.

사용:
    PYTHONPATH=. .venv/bin/python scripts/repoint_archived_file_paths.py
    PYTHONPATH=. .venv/bin/python scripts/repoint_archived_file_paths.py --apply
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="실제 UPDATE 실행(기본은 조회만)")
    args = ap.parse_args()

    with get_session() as s:
        corps = s.execute(text("""
            SELECT corp_code, corp_name, archive_path FROM corporations
            WHERE archive_path IS NOT NULL ORDER BY corp_name
        """)).fetchall()

    if not corps:
        logger.info("아카이브된 기업 없음 — 대상 없음")
        return 0

    total_stale = total_updated = total_unmatched = 0
    for corp_code, corp_name, archive_path in corps:
        with get_session() as s:
            rows = s.execute(text("""
                SELECT dt.rcept_no, dt.file_path
                FROM download_tasks dt JOIN filings f ON f.rcept_no = dt.rcept_no
                WHERE f.corp_code = :c AND dt.file_path IS NOT NULL
            """), {"c": corp_code}).fetchall()
            stale = [(r, fp) for r, fp in rows if not fp.startswith(archive_path)]
            if not stale:
                continue
            total_stale += len(stale)
            logger.info(f"{corp_name}({corp_code}) — {len(stale)}건 재배선 대상")

            folder = Path(archive_path).name  # "{corp_code}_{안전화된 회사명}" (디스크발=NFD)
            folder_nfc = unicodedata.normalize("NFC", folder)
            n = 0
            for rcept_no, fp in stale:
                fp_nfc = unicodedata.normalize("NFC", fp)
                idx = fp_nfc.find(folder_nfc)
                if idx == -1:
                    logger.warning(f"    {rcept_no}: 경로에 폴더명({folder}) 미포함, "
                                   f"건너뜀 ({fp})")
                    total_unmatched += 1
                    continue
                new_fp = archive_path + fp_nfc[idx + len(folder_nfc):]
                if not Path(new_fp).is_file():
                    logger.warning(f"    {rcept_no}: 새 경로에 파일 없음, 건너뜀 ({new_fp})")
                    total_unmatched += 1
                    continue
                if not args.apply:
                    logger.info(f"    {rcept_no}: {fp} → {new_fp}")
                    n += 1
                    continue
                s.execute(text(
                    "UPDATE download_tasks SET file_path = :fp WHERE rcept_no = :r"),
                    {"fp": new_fp, "r": rcept_no})
                n += 1
            if args.apply:
                s.commit()
                logger.success(f"    {n}건 갱신")
            total_updated += n

    if not args.apply:
        logger.info(f"조회만 함 — 대상 {total_stale}건(경로 불일치 {total_unmatched}건 제외 "
                    f"{total_updated}건 재배선 가능). --apply 로 실행")
    else:
        logger.success(f"완료 — {total_updated}건 재배선, {total_unmatched}건 건너뜀")
    return 0


if __name__ == "__main__":
    sys.exit(main())
