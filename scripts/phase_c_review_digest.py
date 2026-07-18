"""
Phase C 패턴루프 다이제스트 — 보류큐를 원인 패턴별로 묶어 사용자 검토용 마크다운 생성
==============================================================================
실행계획 = docs/plans/loop-vivid-bubble.md §D4. 파싱 루프(24/7 무인)와 분리된 **결정 루프**의
입력물. 사용자가 가용시간(평일 20-22 / 토·일 08-22)에 이 문서를 열어 **패턴 단위**로 판정하고,
파서를 고친 뒤 해당 rcept status 를 'pending' 으로 리셋하면 파싱 루프가 재처리한다.

두 갈래 보류를 집계한다:
  A) held 대상(rebuild_target_track1.status IN held_no_facts/missing_file) — 재파싱했으나 fact 0.
     원인을 원문 파일 경량 검사로 분류: 본문없음(별첨FS 추정)/단위미선언/파일소실.
  B) 값 충돌 보류(std_financials_v2.value_lineage, version=2) — 후보 다중으로 canonical 미확정.

출력: docs/qa/phase_c_review_<date>.md (DART 원문 링크 포함).

usage:
  python scripts/phase_c_review_digest.py                 # 전체
  python scripts/phase_c_review_digest.py --examples 20   # 패턴당 예시 수
  python scripts/phase_c_review_digest.py --out docs/qa/phase_c_review_2026-07-18.md
"""
from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
_BODY_RE = re.compile(r"연결재무제표|재무제표\s*등|재무상태표|손익계산서")
_UNIT_RE = re.compile(r"\(단위")


def _classify_held(file_path: str | None) -> str:
    """held 대상의 원인 분류(경량 파일 검사). 본문없음/단위미선언/파일소실/기타."""
    if not file_path or not Path(file_path).exists():
        return "파일소실"
    try:
        raw = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return "파일소실"
    if not _BODY_RE.search(raw):
        return "본문없음(별첨FS 추정)"
    if not _UNIT_RE.search(raw):
        return "단위미선언"
    return "기타(값충돌 등)"


def _held_section(session, n_examples: int) -> list[str]:
    rows = session.execute(text("""
        SELECT t.rcept_no, t.corp_code, c.corp_name, t.fiscal_year, t.fiscal_period,
               t.file_path, t.status
        FROM rebuild_target_track1 t
        LEFT JOIN corporations c ON c.corp_code = t.corp_code
        WHERE t.status IN ('held', 'missing_file')
        ORDER BY t.corp_code, t.fiscal_year DESC, t.fiscal_period
    """)).fetchall()

    by_reason: dict[str, list] = defaultdict(list)
    for r in rows:
        reason = "파일소실" if r.status == "missing_file" else _classify_held(r.file_path)
        by_reason[reason].append(r)

    out = ["## A. held 대상 — 재파싱했으나 fact 0 (본문/단위 보류)", ""]
    if not rows:
        out += ["_(held 대상 없음)_", ""]
        return out
    out += [f"총 **{len(rows)}건**. 원인 패턴별:", ""]
    for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        out.append(f"### {reason} — {len(items)}건")
        for r in items[:n_examples]:
            out.append(f"- {r.corp_name or '?'}({r.corp_code}) {r.fiscal_year}{r.fiscal_period} "
                       f"— [{r.rcept_no}]({DART.format(r.rcept_no)})")
        if len(items) > n_examples:
            out.append(f"- … 외 {len(items) - n_examples}건")
        out.append("")
    return out


def _lineage_section(session, n_examples: int) -> list[str]:
    rows = session.execute(text("""
        SELECT s.corp_code, c.corp_name, s.fiscal_year, s.fiscal_period, s.statement_type,
               s.value_lineage, s.bs_rcept, s.is_rcept, s.cf_rcept
        FROM std_financials_v2 s
        LEFT JOIN corporations c ON c.corp_code = s.corp_code
        WHERE s.version = 2 AND s.value_lineage IS NOT NULL
          AND NOT COALESCE(s.is_discrete, false)
    """)).fetchall()

    canon_counter: Counter = Counter()
    examples: dict[str, list] = defaultdict(list)
    for r in rows:
        vl = r.value_lineage or {}
        if not isinstance(vl, dict):
            continue
        for canon, cands in vl.items():
            canon_counter[canon] += 1
            if len(examples[canon]) < n_examples:
                rcept = r.bs_rcept or r.is_rcept or r.cf_rcept
                examples[canon].append((r, cands, rcept))

    out = ["## B. 값 충돌 보류 — 후보 다중으로 canonical 미확정 (max-abs 폐지의 짝)", ""]
    if not canon_counter:
        out += ["_(값 충돌 보류 없음)_", ""]
        return out
    out += [f"충돌 canonical **{len(canon_counter)}종** / 영향 std_v2 행 **{len(rows)}개**. 빈도순:", ""]
    for canon, cnt in canon_counter.most_common():
        out.append(f"### `{canon}` — {cnt}행")
        for r, cands, rcept in examples[canon]:
            vals = cands if isinstance(cands, list) else [cands]
            preview = ", ".join(str(v.get("value") if isinstance(v, dict) else v) for v in vals[:4])
            link = f"[{rcept}]({DART.format(rcept)})" if rcept else "(rcept 미상)"
            out.append(f"- {r.corp_name or '?'}({r.corp_code}) {r.fiscal_year}{r.fiscal_period}"
                       f"/{r.statement_type} — 후보[{preview}] {link}")
        out.append("")
    return out


def _note_coverage_section(session, n_examples: int) -> list[str]:
    """note 추출층(D&A/R&D) 결측 — 파서 개선(cf_da·expense_nature·rd_note) 작업목록.
    v2 FY 연결 행 중 da_total/rd_expense 결측을 대표사례+DART링크로. (영업이익 있는 실체 행만)"""
    out = ["## C. note 추출층 결측 — D&A/R&D 파서 개선 대상", ""]
    for label, col in (("D&A(da_total)", "da_total"), ("R&D(rd_expense)", "rd_expense")):
        rows = session.execute(text(f"""
            SELECT s.corp_code, c.corp_name, s.fiscal_year, s.is_rcept
            FROM std_financials_v2 s LEFT JOIN corporations c ON c.corp_code=s.corp_code
            WHERE s.version=2 AND s.fiscal_period='FY' AND s.statement_type='consolidated'
              AND NOT COALESCE(s.is_discrete,false) AND NOT COALESCE(s.is_stub,false)
              AND s.{col} IS NULL AND s.operating_income IS NOT NULL
            ORDER BY s.corp_code, s.fiscal_year DESC
        """)).fetchall()
        out.append(f"### {label} 결측 — {len(rows)}건 (FY·연결·영업이익 존재 행 기준)")
        for r in rows[:n_examples]:
            link = f"[{r.is_rcept}]({DART.format(r.is_rcept)})" if r.is_rcept else "(rcept 미상)"
            out.append(f"- {r.corp_name or '?'}({r.corp_code}) {r.fiscal_year}FY — {link}")
        if len(rows) > n_examples:
            out.append(f"- … 외 {len(rows) - n_examples}건")
        out.append("")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", type=int, default=15, help="패턴당 대표 예시 수")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out_path = Path(args.out) if args.out else \
        Path(f"docs/qa/phase_c_review_{date.today().isoformat()}.md")

    with get_session() as s:
        n_done = s.execute(text(
            "SELECT count(*) FROM rebuild_target_track1 WHERE status='done'")).scalar()
        n_total = s.execute(text("SELECT count(*) FROM rebuild_target_track1")).scalar()
        n_v2 = s.execute(text(
            "SELECT count(*) FROM std_financials_v2 WHERE version=2")).scalar()
        header = [
            f"# Phase C 패턴루프 다이제스트 — {date.today().isoformat()}",
            "",
            "> 계획=docs/plans/loop-vivid-bubble.md §D4. **패턴 단위로 판정**(값 하나씩 아님).",
            f"> 진행: 대상 {n_total:,} 중 done **{n_done:,}** · std_v2 version=2 **{n_v2:,}행**.",
            "",
        ]
        body = (_held_section(s, args.examples) + _lineage_section(s, args.examples)
                + _note_coverage_section(s, args.examples))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(header + body), encoding="utf-8")
    print(f"[digest] 작성: {out_path}  (done {n_done:,}/{n_total:,}, v2 {n_v2:,}행)")


if __name__ == "__main__":
    main()
