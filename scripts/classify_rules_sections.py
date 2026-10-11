"""Draft classification of docs/PARSING_RULES.md sections into target rule files (plan step B).

Output is a proposal for human review: heading/body path signals only, no semantic judgement.
"""
import re
import sys

SRC = "docs/PARSING_RULES.md"
OUT = "docs/plans/parsing_rules_classification_heuristic.tsv"  # superseded draft; final table is parsing_rules_classification.tsv

SIGNALS = {
    "10_layer2_parse": r"fin2/extract|parser/|table_extractor|report_lines|parse_amount|collector/|계층2|xbrl_|statement_titles|text\.py|pdf\.py|note_lines|header_hint",
    "20_layer3_map": r"fin2/layer3|combine\.py|account_maps?|account_mapper|concept_map|layer3_cell_corrections|_resolve|계층3|std_v3|unit_overrides|_CURRENT_STRICT",
    "30_audit_verify": r"face_audit|gateb|Gate B|fin2/audit|fin2/verification|verify_|vq\.py|machine_compare|line_audit|Gate B|gateb_audit",
    "40_ops_pipeline": r"collect_new|launchd|백업|backup|유니버스|런북|runbook|배선|데일리",
}
FIX_HEAD = {"10_layer2_parse": "계층2", "20_layer3_map": "계층3", "30_audit_verify": "검증", "40_ops_pipeline": "운영"}


# Human-confirmed status (2026-10-11, bodies read): rule -> status. Everything else heuristically listed is NOT superseded.
CONFIRMED_STATUS = {
    "R0-1": "일부 대체됨(→R0-2: 2015+ 부호복원 증명·정합화 대기 표·'이 절이 이긴다'. 표기 해석 1항은 유효)",
    "R124": "대체됨(→R125, SB성보 회귀로 폐기)",
    "R139": "대체됨(→R167, 2026-09-24 사용자 결정, 이력으로 보존)",
    "R155": "대체됨(→R168)",
    "R197": "유효(내부 R197-a 만 측정 후 폐기)",
    "R2": "유효(내부 '표 단위 델타' 설계 문단만 폐기)",
    "R85": "일부 대체 후보(→R88 열 판정 3갈래 추측) — D단계 확인",
    "R86": "일부 대체 후보(→R88 열 판정 3갈래 추측) — D단계 확인",
    "R87": "일부 대체 후보(→R88 열 판정 3갈래 추측) — D단계 확인",
}
SIGN_FAMILY_TARGET = "20_layer3_map"  # user decision 2026-10-11: sign-restoration family belongs to layer 3 (R0-2)


def main() -> None:
    lines = open(SRC, encoding="utf-8").read().split("\n")
    heads = [i for i, l in enumerate(lines) if l.startswith("## ")]
    rows = []
    for k, i in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        head = lines[i][3:]
        body = "\n".join(lines[i:end])
        m = re.match(r"(R[\w-]+)", head)
        rid = m.group(1) if m else head[:12]
        scores = {}
        for f, pat in SIGNALS.items():
            h = len(re.findall(pat, head))
            b = len(re.findall(pat, body))
            scores[f] = h * 8 + min(b, 40)
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        top, second = ranked[0], ranked[1]
        target = top[0] if top[1] > 0 else "UNKNOWN"
        status = "유효"
        if re.search(r"로 대체|대체됨|폐지", head):
            status = "대체됨/폐지(제목 근거)"
        elif re.search(r"대체|supersed|폐지", "\n".join(lines[i + 1:i + 8])):
            status = "대체 가능성(본문 앞부분 언급 — 사람 확인)"
        elif re.search(r"미해결|이행 ?중|보류", head):
            status = "이행중/미해결(제목 근거)"
        ambiguous = []
        if top[1] == 0:
            ambiguous.append("신호없음")
        elif second[1] >= 0.6 * top[1] and second[1] >= 8:
            ambiguous.append(f"걸침:{second[0]}")
        if rid.startswith("R0") or rid in ("R2", "R2-0", "R6", "R9"):
            target, ambiguous = "00_principles/cross", ambiguous + ["지배원칙·걸침"]
        if head.startswith(("0.", "부록")):
            target = "index/appendix"
        if target == "UNKNOWN" and rows:
            target = rows[-1][4]  # '같은 파일/같은 함수' style sections continue the previous rule
            ambiguous.append("직전규칙 승계")
        if re.search(r"부호", head) and re.search(r"복원|반전|뒤집|거울|R0-2", body):
            ambiguous.append("부호복원계열(R0-2 이행: 계층2→3 소속 결정 필요)")
        if "부호복원계열" in ";".join(ambiguous):
            target = SIGN_FAMILY_TARGET
            ambiguous = [a for a in ambiguous if not a.startswith("부호복원")] + ["부호복원계열→계층3(사용자 결정)"]
        if rid in CONFIRMED_STATUS:
            status = CONFIRMED_STATUS[rid]
        elif status.startswith(("대체 가능성", "대체됨/폐지(제목")):
            status = "유효"  # keyword hit was a false positive (checked 2026-10-11)
        rows.append((rid, i + 1, end, end - i, target, status, ";".join(ambiguous),
                     " / ".join(f"{FIX_HEAD[f]}{s}" for f, s in ranked if s), head[:80]))
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("rule\tstart\tend\tlines\ttarget\tstatus\tambiguous\tscores\ttitle\n")
        for r in rows:
            fh.write("\t".join(map(str, r)) + "\n")
    from collections import Counter
    print(len(rows), Counter(r[4] for r in rows))
    print("ambiguous:", sum(1 for r in rows if r[6]))
    print(Counter(r[5] for r in rows))


if __name__ == "__main__":
    main()
