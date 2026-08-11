"""Phase 4 (파일럿 백필) todo 4-2/4-3 — 항등식(자산=부채+자본) + 실패율/미설명 잔여율 측정.

pre-2015 pilot(26개 corp, 1999~2014, `load_report_lines.py --fy-min 1999 --fy-max 2014`)의
결과를 검증한다. 읽기 전용(DB 미기록).

4-2: report_lines 에 담긴 '자산총계'/'부채총계'/'자본총계' 라벨행으로 BS 항등식
     (자산=부채+자본)을 (rcept_no, basis, col_index) 단위로 검사한다.
4-3: 0행으로 끝난 filing 을 원문 대조로 버킷 분류(오류=우리 문제 vs 결측=원문 자체에 없음)한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import SEC_SEP_FS, SEC_CONSOL_FS, SEC_LEGACY_FS, normalize_dart_section_title

PILOT_CORPS = [
    "00132992", "00122825", "00172079", "00126089", "00143651", "00125521", "00148531",
    "00113508", "00120526", "00198697", "00101220", "00199252", "00116408", "00122472",
    "00149804", "00120021", "00116949", "00107066", "00260930", "00121154", "00137012",
    "00126308", "00222435", "00244561", "00346407", "00171867",
]


def check_identity(session) -> None:
    sql = text("""
        WITH bs AS (
            SELECT rl.rcept_no, rl.basis, rl.col_index,
                   MAX(CASE WHEN rl.label_raw ~ '^자산\\s*총\\s*계$' THEN rl.value_won END) AS assets,
                   MAX(CASE WHEN rl.label_raw ~ '^부채\\s*총\\s*계$' THEN rl.value_won END) AS liabs,
                   MAX(CASE WHEN rl.label_raw ~ '^자본\\s*총\\s*계$' THEN rl.value_won END) AS equity
            FROM report_lines rl
            JOIN report_line_load_progress p ON p.rcept_no = rl.rcept_no
            WHERE p.corp_code = ANY(:corps) AND p.fiscal_year BETWEEN 1999 AND 2014
              AND rl.statement = 'BS'
            GROUP BY rl.rcept_no, rl.basis, rl.col_index
        )
        SELECT rcept_no, basis, col_index, assets, liabs, equity,
               (assets - (liabs + equity)) AS diff
        FROM bs
        WHERE assets IS NOT NULL AND liabs IS NOT NULL AND equity IS NOT NULL
        ORDER BY rcept_no, basis, col_index
    """)
    rows = session.execute(sql, {"corps": PILOT_CORPS}).fetchall()
    print(f"\n=== 4-2. BS 항등식(자산=부채+자본) ===")
    print(f"검사 대상(자산/부채/자본 총계 3종 다 있는 rcept×basis×col) = {len(rows)}")
    ok = [r for r in rows if abs(r.diff) < 2]
    bad = [r for r in rows if abs(r.diff) >= 2]
    print(f"항등식 성립(오차<2원) = {len(ok)} ({100*len(ok)/max(len(rows),1):.1f}%)")
    print(f"항등식 위반 = {len(bad)}")
    for r in bad[:30]:
        print(f"  {r.rcept_no} {r.basis} col{r.col_index}: 자산={r.assets:,} "
              f"부채+자본={r.liabs+r.equity:,} diff={r.diff:,}")
    if len(bad) > 30:
        print(f"  ... 외 {len(bad)-30}건")


def classify_zero(session) -> None:
    sql = text("""
        SELECT p.rcept_no, p.fiscal_year, f.report_type, f.corp_name, dt.file_path
        FROM report_line_load_progress p
        JOIN filings f ON f.rcept_no = p.rcept_no
        JOIN download_tasks dt ON dt.rcept_no = p.rcept_no
        WHERE p.corp_code = ANY(:corps) AND p.fiscal_year BETWEEN 1999 AND 2014
          AND COALESCE(p.n_lines, 0) = 0
    """)
    zero = session.execute(sql, {"corps": PILOT_CORPS}).mappings().all()

    total_progress = session.execute(text("""
        SELECT count(*) FROM report_line_load_progress
        WHERE corp_code = ANY(:corps) AND fiscal_year BETWEEN 1999 AND 2014
    """), {"corps": PILOT_CORPS}).scalar()

    buckets = {"corrupted": [], "no_fs_section": [], "has_fs_section_but_empty": [], "file_missing": []}
    for r in zero:
        p = Path(r["file_path"])
        if not p.exists():
            buckets["file_missing"].append(r)
            continue
        raw = p.read_bytes()
        if raw.count(b"\xef\xbf\xbd") > 50:
            buckets["corrupted"].append(r)
            continue
        root = _parse_xml_file(p)
        if root is None:
            buckets["file_missing"].append(r)
            continue
        titles = set()
        for sec in root.iter():
            tag = sec.tag if isinstance(sec.tag, str) else ""
            if tag.upper().startswith("SECTION"):
                t = sec.find("TITLE")
                if t is not None:
                    titles.add(normalize_dart_section_title("".join(t.itertext())))
        if SEC_SEP_FS in titles or SEC_CONSOL_FS in titles:
            buckets["has_fs_section_but_empty"].append(r)
        else:
            buckets["no_fs_section"].append(r)

    print(f"\n=== 4-3. 실패율/미설명 잔여율 ===")
    print(f"pilot 전체 filing(1999~2014) = {total_progress}")
    print(f"0행(zero) = {len(zero)} ({100*len(zero)/max(total_progress,1):.1f}%)")
    print(f"  ├ corrupted(원문 자체 손상, replacement-char 대량) = {len(buckets['corrupted'])}"
          f" ({100*len(buckets['corrupted'])/max(total_progress,1):.1f}%) — 우리 문제 아님, 원본 재확보 필요")
    print(f"  ├ no_fs_section(재무제표/연결재무제표 SECTION-2 자체가 문서에 없음"
          f" = 절단·요약전용·4번째변종) = {len(buckets['no_fs_section'])}"
          f" ({100*len(buckets['no_fs_section'])/max(total_progress,1):.1f}%)")
    print(f"  └ has_fs_section_but_empty(섹션은 있는데 탐지 0행 = 진짜 잔여 파서 갭)"
          f" = {len(buckets['has_fs_section_but_empty'])}"
          f" ({100*len(buckets['has_fs_section_but_empty'])/max(total_progress,1):.1f}%)")

    print("\n  has_fs_section_but_empty 표본(전체):")
    for r in buckets["has_fs_section_but_empty"]:
        print(f"    {r['rcept_no']} {r['corp_name']} fy{r['fiscal_year']} {r['report_type']}")


def main() -> None:
    with get_session() as s:
        check_identity(s)
        classify_zero(s)


if __name__ == "__main__":
    main()
