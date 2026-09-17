"""PDF 복구 경로 주석번호-오염 검증 (2026-09-17).

배경: `fin2/extract/pdf.py`가 header 감지에 실패한 표에서 콤마 없는 단독
주석번호(예: "17", "14")를 실제 금액으로 오인식해 `report_lines`에 조그만
값(1~99원)이 잘못 저장된 사례가 다수 발견됨(솔트웨어 20220802000208에서
최초 발견, `docs/plans/parser_source_fallback_cascade_design_2026-09-12.md`
§6 참고). 이 스크립트는 그 후보들을 실제 PDF 원문(DART에서 재수신, 로컬
캐시 없음 — `collector.legacy_downloader.LegacyDartScraper` 재사용)과
대조해 진짜 값을 찾아 검증한다.

읽기 전용 — DB/코드를 수정하지 않는다. 결과는 CSV로 저장.

사용:
    python scripts/verify_pdf_note_contamination_2026-09-17.py --limit 20
    python scripts/verify_pdf_note_contamination_2026-09-17.py --out manual_review/pdf_note_contamination_verified_2026-09-17.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from collector.legacy_downloader import LegacyDartScraper
from fin2.extract.pdf import (
    _find_anchors, _region_has_anchor_labels, _looks_like_real_amount,
    _NOTE_REF_STRIP_RE, parse_number,
)

_NUM_TOKEN_RE = re.compile(r"\(?-?[△▲]?\s?[0-9][0-9,]*\)?")


def _find_real_value_in_region(region: str, label_raw: str) -> list[dict]:
    """region 안에서 `label_raw`(DB에 이미 저장된, "(주석"까지 포함한 잘린
    라벨) 그대로를 찾아 그 줄에서 진짜 금액을 뽑는다.

    ★잘린 라벨 자체를 검색키로 쓴다(정제된 라벨 아님) — "법인세비용"처럼 짧은
    라벨은 "법인세비용차감전순이익" 같은 **다른 계정의 부분 문자열**과 겹쳐
    오매치가 난다(실측: 유한양행/삼성중공업). "법인세비용(주석"은 그 계정
    자신의 실제 원문에만 등장하는 고유 문자열이라 훨씬 정밀하다.

    금액 추출은 기존 `_looks_like_real_amount()`/`_NOTE_REF_STRIP_RE`를
    그대로 재사용한다(새 로직 발명 금지 — 이미 검증된 필터 재사용) — 라벨
    직후의 "(주석2,9)" 같은 다중참조 괄호를 먼저 지운 뒤, 남은 숫자 토큰 중
    `_looks_like_real_amount`를 통과하는 첫 값을 진짜 금액으로 채택한다.
    """
    matches = []
    for m in re.finditer(re.escape(label_raw), region):
        line_start = region.rfind("\n", 0, m.start()) + 1
        line_end = region.find("\n", m.end())
        if line_end == -1:
            line_end = len(region)
        line = region[line_start:line_end]
        after = line[m.end() - line_start:]
        after_stripped = _NOTE_REF_STRIP_RE.sub("", after, count=1)
        # 괄호로 안 닫힌 잔여 주석번호(예: "3과9) ...")까지 대비해 선두의
        # ")"·콤마 섞인 짧은 잔재도 한 번 더 제거.
        after_stripped = re.sub(r"^[^\d]*\d[\d,와과및\s]{0,10}\)\s*", "", after_stripped)
        real_value = None
        for tok in _NUM_TOKEN_RE.findall(after_stripped):
            if _looks_like_real_amount(tok):
                real_value = parse_number(tok)
                break
        matches.append({"line": line.strip()[:200], "real_value": real_value})
    return matches


def _process_rcept(scraper, rcept_no: str, candidates: list[dict]) -> list[dict]:
    """candidates: [{statement, basis, label_raw, db_value}, ...] (같은 rcept_no)."""
    out = []
    try:
        pdf_bytes = scraper.fetch_pdf_bytes(rcept_no)
    except Exception as e:
        for c in candidates:
            out.append({**c, "rcept_no": rcept_no, "status": "fetch_error",
                       "detail": str(e)[:200]})
        return out
    if not pdf_bytes:
        for c in candidates:
            out.append({**c, "rcept_no": rcept_no, "status": "no_pdf", "detail": ""})
        return out

    from fin2.extract.pdf import _read_pdf_text
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as f:
        f.write(pdf_bytes)
        f.flush()
        text = _read_pdf_text(f.name)
    if not text:
        for c in candidates:
            out.append({**c, "rcept_no": rcept_no, "status": "pdf_text_empty", "detail": ""})
        return out

    anchors = _find_anchors(text)
    for c in candidates:
        stmt, basis, label_raw, db_value = (
            c["statement"], c["basis"], c["label_raw"], c["db_value"])
        region = None
        for i, anc in enumerate(anchors):
            if anc.statement != stmt or anc.basis != basis:
                continue
            end = anchors[i + 1].start if i + 1 < len(anchors) else len(text)
            cand_region = text[anc.start:end]
            if _region_has_anchor_labels(cand_region, anc.statement):
                region = cand_region
                break

        matches = _find_real_value_in_region(region, label_raw) if region else []
        confidence = "region"
        if not matches:
            # 폴백 — 표 구역 판정이 이 계정을 못 잡았을 수 있다(예: 별도
            # 주석 섹션에 있는 상세내역표). 문서 전체에서 첫 매치를 대신
            # 쓰되, 신뢰도를 낮춰 표시한다(비교연도 중복 위험 — 사람 확인 권장).
            matches = _find_real_value_in_region(text, label_raw)
            confidence = "wholedoc_fallback"
        if not matches:
            out.append({**c, "rcept_no": rcept_no, "status": "label_not_found_anywhere",
                       "detail": ""})
            continue
        first = matches[0]
        out.append({
            **c, "rcept_no": rcept_no,
            "status": "found",
            "match_confidence": confidence,
            "n_matches_in_source": len(matches),
            "real_line": first["line"],
            "candidate_real_value": first["real_value"],
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="처리할 rcept_no 개수 제한")
    ap.add_argument("--out", default="manual_review/pdf_note_contamination_verified_2026-09-17.csv")
    ap.add_argument("--only-truncated-label", action="store_true", default=True,
                    help="라벨이 '(주석'으로 잘린 고확신 후보만(기본값)")
    args = ap.parse_args()

    from collector.db import get_session
    from sqlalchemy import text as sa_text

    with get_session() as session:
        rows = session.execute(sa_text("""
            SELECT rl.rcept_no, rl.corp_code, co.corp_name, rl.report_fiscal_year,
                   rl.report_fiscal_period, rl.statement, rl.basis, rl.label_raw, rl.value_won
            FROM report_lines rl
            LEFT JOIN corporations co ON co.corp_code = rl.corp_code
            WHERE rl.unit_source='pdf' AND rl.value_won BETWEEN 1 AND 99
              AND (rl.label_raw LIKE '%(주석%')
            ORDER BY rl.rcept_no, rl.statement
        """)).fetchall()

    by_rcept: dict[str, list[dict]] = {}
    meta: dict[str, dict] = {}
    for r in rows:
        by_rcept.setdefault(r.rcept_no, []).append({
            "statement": r.statement, "basis": r.basis,
            "label_raw": r.label_raw, "db_value": r.value_won,
        })
        meta[r.rcept_no] = {"corp_code": r.corp_code, "corp_name": r.corp_name,
                            "fiscal_year": r.report_fiscal_year,
                            "fiscal_period": r.report_fiscal_period}

    rcepts = list(by_rcept.keys())
    if args.limit:
        rcepts = rcepts[:args.limit]

    logger.info(f"대상 rcept_no: {len(rcepts)}건 (총 후보 행 {sum(len(by_rcept[r]) for r in rcepts)}개)")

    scraper = LegacyDartScraper()
    all_out = []
    for i, rcept in enumerate(rcepts, 1):
        logger.info(f"[{i}/{len(rcepts)}] {rcept} ({meta[rcept]['corp_name']}) "
                    f"{len(by_rcept[rcept])}건 처리 중")
        results = _process_rcept(scraper, rcept, by_rcept[rcept])
        for r in results:
            r.update(meta[rcept])
        all_out.extend(results)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["rcept_no", "corp_code", "corp_name", "fiscal_year", "fiscal_period",
                 "statement", "basis", "label_raw", "db_value", "status",
                 "match_confidence", "n_matches_in_source", "candidate_real_value",
                 "real_line", "detail"]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_out)

    status_counts: dict[str, int] = {}
    for r in all_out:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
    logger.info(f"완료: 총 {len(all_out)}건. 상태별: {status_counts}")
    logger.info(f"결과 → {out_path}")


if __name__ == "__main__":
    main()
