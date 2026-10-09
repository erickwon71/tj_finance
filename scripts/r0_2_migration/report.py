"""R0-2 migration report: reload outcome per status, corrections per rule/statement/kind, drift list.

Usage (cwd = repo root, DATABASE_URL set):
  python scripts/r0_2_migration/report.py <out.md> <reload_s0.jsonl> [<reload_s1.jsonl> ...]
"""
import json
import os
import sys
from collections import Counter

import psycopg2


def main():
    out_path, logs = sys.argv[1], sys.argv[2:]
    rows = {}
    for p in logs:
        for line in open(p):
            d = json.loads(line)
            rows[d["rcept"]] = d                  # last record wins (resumed runs)
    status = Counter(d["status"].split(":")[0] for d in rows.values())
    drift = sorted((d for d in rows.values() if d["status"] == "drift"), key=lambda d: d["rcept"])
    errs = sorted((d for d in rows.values() if d["status"].startswith("err")), key=lambda d: d["rcept"])

    cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
    cur.execute("""SELECT rule, statement, kind, count(*), count(DISTINCT rcept_no)
                   FROM layer3_cell_corrections GROUP BY 1, 2, 3 ORDER BY 4 DESC""")
    by_rule = cur.fetchall()
    cur.execute("SELECT count(*), count(DISTINCT rcept_no) FROM layer3_cell_corrections")
    n_cells, n_filings = cur.fetchone()

    md = ["# R0-2 이행 결과 — 2015+ 재적재 (2026-10-10)", "",
          "설계: `docs/plans/layer2_as_printed_migration_2026-10-10.md` · 규칙: `docs/PARSING_RULES.md` R0-2", "",
          "## 재적재 결과 (필링)", "", "| 상태 | 필링 | 뜻 |", "|---|---|---|"]
    meaning = {
        "done": "계층2 를 인쇄값으로 다시 쓰고 보정을 계층3 테이블에 저장",
        "full_done": "R159 대상 — 노트 포함 전체 재적재",
        "already": "이미 인쇄값(파일럿 등) — 보정만 갱신",
        "nochange": "규칙이 바꾸는 셀 없음 — 쓰지 않음",
        "drift": "DB 가 현재 코드(규칙 켬) 결과와 달라 건너뜀 — 별도 결정",
        "empty": "추출 0행 — 건드리지 않음",
        "nosource": "XML/XBRL 원문 없음(PDF 등) — 해당 없음",
    }
    for st, n in status.most_common():
        md.append(f"| {st} | {n:,} | {meaning.get(st, '오류' if st.startswith('err') else '')} |")
    md += ["", f"## 계층3 보정 (`layer3_cell_corrections`): {n_cells:,}셀 · {n_filings:,}필링", "",
           "| 규칙 | 재무제표 | 종류 | 셀 | 필링 |", "|---|---|---|---|---|"]
    md += [f"| {r} | {s} | {k} | {c:,} | {f:,} |" for r, s, k, c, f in by_rule]
    md += ["", f"## drift 필링 ({len(drift):,}) — 재적재하지 않음", "",
           "DB 값이 현재 코드의 규칙 켬 결과와 다르다(옛 적재·다른 추출 경로·근거 변화). 계층2 는 아직 옛 값 그대로다.", "",
           "| rcept | 차이 셀 | 예 (키, DB, 규칙 켬) |", "|---|---|---|"]
    for d in drift[:300]:
        ex = d.get("diff", [[None]])[0]
        md.append(f"| {d['rcept']} | {d.get('n')} | `{json.dumps(ex, ensure_ascii=False)[:160]}` |")
    if len(drift) > 300:
        md.append(f"| … | | 나머지 {len(drift) - 300:,}건은 reload 로그 참조 |")
    if errs:
        md += ["", f"## 오류 ({len(errs)})", ""] + [f"- {d['rcept']}: {d['status'][:200]}" for d in errs[:100]]
    open(out_path, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(out_path, dict(status), n_cells, n_filings)


if __name__ == "__main__":
    main()
