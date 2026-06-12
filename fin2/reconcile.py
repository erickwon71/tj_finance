"""
fin2 R-레이어: statement_source 정합.

(corp, fiscal_year, fiscal_period, basis, statement∈{BS,IS,CF}) 마다 **단일 source filing**을
fact_v2 에서 선택한다. BS/IS/CF 를 **독립** 선택하므로 부분 기재정정은 가진 statement만 이기고
미정정 statement 는 원본을 유지 → over-supersede 구조 제거([[key-bugs-fixed]] 리메드 2023).

선택 규칙(테스트가능·명명) — 우선순위 사전식:
  1) 후보 = 해당 (corp, report_fy, report_period, basis) 에서 statement 의 canonical 라인을
     1줄 이상 가진 filing(fact_v2 의 col_index=0, 비차원 기준).
  2) anchor 보유(BS=bs.total_assets / IS=is.revenue / CF=cf.operating) — 비anchor 보다 우선.
  3) **기재정정(is_amendment) 우선** — 내용정정은 원본을 대체한다. 단 BS/IS/CF 독립 선택이라
     정정본이 가진 statement 만 이긴다(부분 첨부정정은 미포함 statement 에 영향 없음).
     ⚠ 첨부정정([첨부정정])은 is_amendment=False → 이 신호 미발동(완전성으로 결정) →
     리메드 2023 over-supersede 방지 유지([[key-bugs-fixed]]). jiitech ×1000 은 기재정정
     본(올바른 단위)이 버그 원본(천원 오검출로 라인 수 부풀려짐)을 이겨 해소.
  4) 완전성(매핑 canonical 라인 수) → filed_at 최신 → rcept_no 큰 쪽.

산출: statement_source upsert + lineage 기록. S-레이어(Phase 4)가 이 선택으로 std_v2 조립.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from loguru import logger
from sqlalchemy import text

# statement → (canonical 접두어, anchor canonical)
_STATEMENTS = {
    "BS": ("bs.", "bs.total_assets"),
    "IS": ("is.", "is.revenue"),
    "CF": ("cf.", "cf.operating"),
}
def _statement_of(canonical: str) -> str | None:
    for stmt, (prefix, _) in _STATEMENTS.items():
        if canonical.startswith(prefix):
            return stmt
    return None


def select_source(candidates: list[tuple], anchor: str) -> tuple:
    """
    후보 [(rcept, lines:set, filed_at, is_amendment)] 중 source 선택(순수 함수, 테스트가능).

    우선순위(사전식): anchor 보유 > 기재정정(is_amendment) > 완전성(라인수) > filed_at 최신 > rcept_no.
    반환: best 후보 튜플(호출측이 [0]=rcept, [1]=lines 사용).
    """
    def score(c):
        rcept, lines, filed_at, is_amend = c
        return (
            anchor in lines,                  # 1. anchor 보유
            bool(is_amend),                   # 2. 기재정정 우선(정정본이 원본 대체)
            len(lines),                        # 3. 완전성
            filed_at or datetime.min.date(),  # 4. 최신
            rcept,                             # 5. tiebreak
        )
    return max(candidates, key=score)


def reconcile_corp(session, corp_code: str, fiscal_year: int | None = None) -> int:
    """
    한 기업의 fact_v2 를 정합해 statement_source 를 upsert. 반환=기록한 (statement) 행 수.

    filed_at 은 filings 에서 가져와 동점 tiebreak 에 사용.
    """
    fy_clause = "AND f.report_fiscal_year = :fy" if fiscal_year is not None else ""
    params: dict = {"corp": corp_code}
    if fiscal_year is not None:
        params["fy"] = fiscal_year

    # col_index=0(보고연도 당기) · 비차원 · 매핑된 canonical 만 후보 집계
    rows = session.execute(text(f"""
        SELECT f.report_fiscal_year AS fy, f.report_fiscal_period AS fp,
               f.basis, f.rcept_no, f.canonical_account,
               fl.filed_at, fl.is_amendment
        FROM fact_v2 f
        JOIN filings fl ON fl.rcept_no = f.rcept_no
        WHERE f.corp_code = :corp
          AND f.col_index = 0
          AND NOT f.is_dimensional
          AND f.canonical_account IS NOT NULL
          AND f.basis IN ('consolidated','separate')
          {fy_clause}
    """), params).fetchall()

    # (fy, fp, basis, statement, rcept) → {canonical 라인 set, filed_at, is_amendment}
    Cand = lambda: {"lines": set(), "filed_at": None, "is_amendment": False}
    agg: dict[tuple, dict] = defaultdict(Cand)
    for r in rows:
        stmt = _statement_of(r.canonical_account)
        if stmt is None:
            continue
        key = (r.fy, r.fp, r.basis, stmt, r.rcept_no)
        agg[key]["lines"].add(r.canonical_account)
        agg[key]["filed_at"] = r.filed_at
        agg[key]["is_amendment"] = bool(r.is_amendment)

    # (fy, fp, basis, statement) → 후보 rcept 목록
    groups: dict[tuple, list[tuple]] = defaultdict(list)
    for (fy, fp, basis, stmt, rcept), v in agg.items():
        groups[(fy, fp, basis, stmt)].append(
            (rcept, v["lines"], v["filed_at"], v["is_amendment"]))

    written = 0
    for (fy, fp, basis, stmt), cands in groups.items():
        _, anchor = _STATEMENTS[stmt]
        best = select_source(cands, anchor)
        best_rcept, best_lines = best[0], best[1]
        has_anchor = anchor in best_lines

        lineage = sorted(
            [
                {
                    "rcept": rcept,
                    "line_count": len(lines),
                    "filed_at": filed_at.isoformat() if filed_at else None,
                    "is_amendment": bool(is_amend),
                    "chosen": rcept == best_rcept,
                }
                for rcept, lines, filed_at, is_amend in cands
            ],
            key=lambda d: (-d["line_count"], d["rcept"]),
        )

        session.execute(text("""
            INSERT INTO statement_source
                (corp_code, fiscal_year, fiscal_period, basis, statement,
                 source_rcept_no, line_count, has_anchor, candidate_count, lineage, reconciled_at)
            VALUES
                (:corp, :fy, :fp, :basis, :stmt,
                 :rcept, :lc, :anchor, :cc, CAST(:lineage AS JSONB), :ts)
            ON CONFLICT (corp_code, fiscal_year, fiscal_period, basis, statement)
            DO UPDATE SET
                source_rcept_no = EXCLUDED.source_rcept_no,
                line_count      = EXCLUDED.line_count,
                has_anchor      = EXCLUDED.has_anchor,
                candidate_count = EXCLUDED.candidate_count,
                lineage         = EXCLUDED.lineage,
                reconciled_at   = EXCLUDED.reconciled_at
        """), {
            "corp": corp_code, "fy": fy, "fp": fp, "basis": basis, "stmt": stmt,
            "rcept": best_rcept, "lc": len(best_lines), "anchor": has_anchor,
            "cc": len(cands),
            "lineage": __import__("json").dumps(lineage, ensure_ascii=False),
            "ts": datetime.utcnow(),
        })
        written += 1

    logger.info(f"[reconcile2] corp={corp_code} fy={fiscal_year or 'all'} — statement_source {written}행")
    return written
