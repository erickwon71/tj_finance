"""R96 census — DART document.xml 저장 시 첨부(감사보고서 등)가 본문으로 잘못 채택된
필링 전수조사 (2026-09-12).

배경: `collector/downloader.py::_pick_best_file_by_size()` 가 ZIP 안에 xml이 여러 개일
때 "가장 큰 파일"을 본문으로 오채택하는 버그(R96, `docs/PARSING_RULES.md` R96)를 양지사
(20150930000130)/티로보틱스(20180402000209) 2건에서 발견·수정했다. 이 2건 말고 같은
증상(로컬에 저장된 xml의 `<DOCUMENT-NAME>`이 본문이 아니라 첨부)이 더 있는지 확인되지
않았다 — 이 스크립트가 그 전수조사다.

## 방법
`download_tasks`(file_type='xml', status='completed') × `filings`(report_type IN
annual/half/quarter) 전체(187,417건, 2026-09-12 기준) 각 파일의 **첫 2KB만** 읽어
`<DOCUMENT-NAME ...>...</DOCUMENT-NAME>` 태그를 뽑고, 본문 키워드(사업보고서/반기보고서/
분기보고서)가 아니면 후보로 기록한다(전체 콘텐츠 읽기 아님 — 187K 파일 대량 read라
[[feedback-bulk-read-use-sdcard]] 원칙대로 SD카드 미러에서 읽는다. SD에 없으면 NAS로
폴백 — 파일 자체가 없는 것과 SD 미동기화를 구분하기 위해 두 결과를 따로 집계한다).

★SD카드가 4일 전(2026-09-08) 기준이라 이미 고친 2건(양지사/티로보틱스)은 SD에 옛날
(오답) 버전이 남아있어 여기서도 "후보"로 다시 잡힌다 — 이미 알려진 해결건이니 결과에서
알려진 rcept_no는 별도 표시만 하고 넘어간다. **이 스크립트는 순수 read-only 조사**이고
DB/파일을 전혀 쓰지 않는다.

사용:
    python scripts/census_r96_body_attachment_swap_2026-09-12.py
    python scripts/census_r96_body_attachment_swap_2026-09-12.py --limit 5000   # 시험
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from collector.storage_guard import BACKUP_ROOT, SYMLINK as _RAW_REPORT_SYMLINK

# 본문으로 인정하는 키워드 — DART DOCUMENT-NAME 텍스트(ACODE 태그 값 말고 태그 내용).
# 정정("[기재정정]" 등)은 파일 내부 DOCUMENT-NAME에는 안 붙는다(실측: 순수 "사업보고서"
# 등만 들어있음) — R6 원칙대로 모르는 표현은 후보로 남긴다(과잉탐지 쪽으로 안전하게).
_BODY_KEYWORDS = ("사업보고서", "반기보고서", "분기보고서")

_DOC_NAME_RE_BYTES = re.compile(rb"<DOCUMENT-NAME[^>]*>([^<]*)</DOCUMENT-NAME>")

_KNOWN_FIXED = {"20150930000130", "20180402000209"}  # R96에서 이미 발견·수정한 2건


def _load_targets(limit: int | None, fy_min: int) -> list[dict]:
    sql = text("""
        SELECT dt.rcept_no, dt.file_path, f.report_type, f.fiscal_year, f.corp_code
        FROM download_tasks dt
        JOIN filings f USING (rcept_no)
        WHERE dt.status = 'completed' AND dt.file_type = 'xml'
          AND dt.file_path IS NOT NULL
          AND f.report_type IN ('annual', 'half', 'quarter')
          AND f.fiscal_year >= :fy_min
        ORDER BY f.fiscal_year, dt.rcept_no
        """ + (f" LIMIT {int(limit)}" if limit else ""))
    with get_session() as s:
        return [dict(r) for r in s.execute(sql, {"fy_min": fy_min}).mappings()]


def _read_head_bytes(path: Path, n: int = 4096) -> bytes | None:
    try:
        with open(path, "rb") as f:
            return f.read(n)
    except OSError:
        return None


def _decode_doc_name(raw: bytes) -> tuple[str | None, bool]:
    """(doc_name, found_tag). ★바이트 그대로 정규식 매칭 후 **매칭된 구간만** 디코드한다
    — 고정 n바이트로 자르면 멀티바이트(EUC-KR 2바이트/UTF-8 3바이트) 문자 중간이 잘려
    디코드가 깨진다(실측: 2011년 필링에서 재현 — 태그 자체는 멀쩡한데 청크 끝단이
    깨져 전체 디코드가 replacement文자로 오염됨). 태그 안쪽만 잘라 디코드하면 이 문제가
    없다 — 태그 여닫음(`<...>`)이 경계라 멀티바이트 문자가 걸쳐 잘릴 일이 없다.
    """
    m = _DOC_NAME_RE_BYTES.search(raw)
    if not m:
        return None, False
    seg = m.group(1)
    for enc in ("utf-8", "euckr"):   # pre-2010대 다수는 EUC-KR([[feedback-grep-euckr-locale-trap]])
        try:
            return seg.decode(enc).strip(), True
        except UnicodeDecodeError:
            continue
    return seg.decode("utf-8", errors="replace").strip(), True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="대상 상한(시험용)")
    ap.add_argument("--fy-min", type=int, default=2011,
                     help="이 연도 이상만 스캔(기본 2011 — 그 이전은 별도의 레거시 인코딩"
                          " 손상 이슈가 있어 R96 판정과 섞이면 안 됨, 별도 조사 필요)")
    args = ap.parse_args()

    rows = _load_targets(args.limit, args.fy_min)
    logger.info(f"대상 {len(rows):,}건 — SD카드 미러에서 헤더만 읽어 스캔")

    n_ok = n_suspect = n_missing_both = n_no_tag = 0
    suspects: list[dict] = []
    t0 = time.time()
    for i, r in enumerate(rows, start=1):
        primary_path = Path(r["file_path"])
        try:
            sd_path = BACKUP_ROOT / primary_path.relative_to(_RAW_REPORT_SYMLINK)
        except ValueError:
            sd_path = None   # raw_report/ 바깥(예: 상장폐지 archive/) — SD 미러 대상 아님
        head = _read_head_bytes(sd_path) if sd_path is not None else None
        source = "sd"
        if head is None:
            head = _read_head_bytes(primary_path)   # SD에 없거나 대상 아니면 NAS 폴백
            source = "nas_fallback"
        if head is None:
            n_missing_both += 1
            suspects.append({**r, "reason": "파일없음(SD/NAS 둘다)", "source": "none",
                              "doc_name": None})
            continue

        doc_name, found_tag = _decode_doc_name(head)
        if not found_tag:
            n_no_tag += 1
            suspects.append({**r, "reason": "DOCUMENT-NAME 태그 미검출(첫 4KB 안)",
                              "source": source, "doc_name": None})
            continue

        if any(kw in doc_name for kw in _BODY_KEYWORDS):
            n_ok += 1
        else:
            n_suspect += 1
            suspects.append({**r, "reason": "본문 키워드 아님", "source": source,
                              "doc_name": doc_name})

        if i % 20000 == 0:
            elapsed = time.time() - t0
            logger.info(f"{i:,}/{len(rows):,} — {elapsed/60:.1f}분 경과 "
                        f"(정상 {n_ok:,} · 의심 {n_suspect:,} · "
                        f"태그없음 {n_no_tag:,} · 파일없음 {n_missing_both:,})")

    elapsed = time.time() - t0
    logger.success(f"완료 — 전체 {len(rows):,} · 정상 {n_ok:,} · 의심 {n_suspect:,} · "
                   f"태그없음 {n_no_tag:,} · 파일없음(SD+NAS) {n_missing_both:,} "
                   f"— {elapsed/60:.1f}분")

    if suspects:
        out = Path("manual_review/_r96_census_2026-09-12/suspects.csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        import csv
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["rcept_no", "corp_code", "report_type", "fiscal_year",
                        "doc_name", "reason", "source", "already_known_fixed",
                        "dart_link", "file_path"])
            for s_ in suspects:
                w.writerow([
                    s_["rcept_no"], s_["corp_code"], s_["report_type"], s_["fiscal_year"],
                    s_["doc_name"], s_["reason"], s_["source"],
                    s_["rcept_no"] in _KNOWN_FIXED,
                    f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={s_['rcept_no']}",
                    s_["file_path"]])
        logger.info(f"의심 목록 {len(suspects):,}건 → {out}")


if __name__ == "__main__":
    main()
