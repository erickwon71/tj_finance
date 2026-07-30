"""원문 금액셀의 **형식 파괴** 규모 측정 — 셀 병합 + float 정밀도 (READ-ONLY).

배경 (2026-07-30 충실성 전수조사에서 드러남)
--------------------------------------------
DART 원문 XML 이 깨져 lxml 이 태그를 중첩시키면 `_get_cells` 의 `itertext()` 가 **여러 셀의
텍스트를 한 셀로 합친다**. 그러면 `parse_amount` 가 이어붙은 숫자를 하나의 금액으로 읽어
**없는 값을 만들어낸다**:

    원문 TD 2개 '723,570,750' + '723,570,750'
      → 병합 '723,570,750 723,570,750'
      → parse_amount 콤마·공백 제거 '723570750723570750'
      → int(float(...)) = 723,570,750,723,570,688   (7.2억원 → 7.2해원)

★ `layer2_fidelity_full.py` 의 역방향 검사는 **이 결함을 구조적으로 못 잡는다** — 검사기도
같은 `itertext()` 경로로 원문을 읽어 병합된 문자열을 '원문에 있는 숫자'로 보기 때문이다.
위 사례가 역방향에서 걸린 건 float 손실로 값이 병합문자열과 **달라졌을 때**뿐이다.
따라서 병합 규모는 **원문 셀 형식**을 직접 봐야 알 수 있다 — 이 스크립트가 그 일을 한다.

판정 기준 (추측 아님 — 콤마 그룹 문법)
--------------------------------------
정상 금액은 콤마가 3자리 그룹 경계에만 온다(`^\\(?\\d{1,3}(,\\d{3})+\\)?$`). 병합되면
그룹 문법이 깨진다('16,325,7765,746,586,918' → '7765' 4자리). 문법이 깨졌는데
`parse_amount` 가 값을 돌려주면 **날조**다.

Usage
-----
    python scripts/qa_malformed_amount_cells.py --limit 300
    python scripts/qa_malformed_amount_cells.py --shard 0/6      # 전수
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.common.amount_normalizer import parse_amount
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import table_direct_rows
from parser.xml.table_extractor import (_get_cells, _is_fs_title_row,
                                        _is_header_cell, _split_label_amounts)

# 정상 3자리 그룹 금액. table_extractor._AMOUNT_GROUPED_PATTERN 과 같은 문법이지만
# 부호·전각기호까지 벗긴 뒤 적용한다.
# ★소수부 허용 필수: '1,106.52'(환율)·'1,530.70'(주가) 는 정상 표기다. 초판이 이걸
#   빠뜨려 4,930건을 전부 '날조'로 오판했다(검사기 버그 — 교훈 §7 그대로 반복됐다).
_WELL_FORMED = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")
_PLAIN_INT = re.compile(r"^\d+$")
_DECIMAL = re.compile(r"^\d+\.\d+$")
_FLOAT53 = 2 ** 53

TARGETS_SQL = """
    SELECT f.rcept_no, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE d.status='completed' AND d.file_type='xml' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015
    ORDER BY f.rcept_no
"""


def _is_complete_number(tok: str) -> bool:
    """토큰 하나가 **온전한 금액 표기**인가(부호·괄호 벗긴 뒤 3자리 그룹 또는 무콤마 정수/소수)."""
    tk = tok.strip()
    if tk.startswith("(") and tk.endswith(")"):
        tk = tk[1:-1]
    tk = tk.lstrip("-△▲+").rstrip(",")
    if not tk:
        return False
    return bool(_WELL_FORMED.fullmatch(tk) or _PLAIN_INT.fullmatch(tk)
                or _DECIMAL.fullmatch(tk))


def classify(raw: str) -> tuple[str, int | None]:
    """셀 텍스트 하나를 분류한다. 반환 (분류, parse_amount 결과)."""
    got = parse_amount(raw)

    # ★먼저 공백 분리를 본다 — parse_amount 는 공백을 지우고 이어붙이므로, 한 셀에 온전한
    #   숫자가 2개 이상 나열된 원문('723,570,750 723,570,750')이 한 숫자로 날조된다.
    #   원문 실측: 제출인이 두 논리행을 한 행에 접어 넣은 표에서 나온다(라벨도 '3.배당금
    #   현금배당' 처럼 2개가 붙어 있고, 다른 셀은 '- -' 로 2토큰이다).
    toks = raw.split()
    if len(toks) >= 2 and all(_is_complete_number(tk) for tk in toks):
        uniq = {tk.strip() for tk in toks}
        return ("★병합(공백·동일값)" if len(uniq) == 1
                else "★병합(공백·상이값)"), got

    s = (raw.strip().replace(" ", "").replace("　", "")
         .replace("\xa0", "").replace("​", ""))
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    s = s.lstrip("-△▲+")
    if not s:
        return "빈셀", got
    if "," in s:
        if _WELL_FORMED.fullmatch(s):
            # 소수부가 있으면 parse_amount 의 int(float()) 가 잘라낸다(1,106.52 → 1,106).
            # 환율·주가 셀이라 금액 왜곡은 아니지만 원문 충실성 손실이므로 따로 센다.
            cls = "정상(그룹소수·절단)" if "." in s else "정상(그룹)"
        elif got is not None:
            cls = "★날조(그룹문법파괴)"
        else:
            cls = "비금액(거부됨)"
    elif _PLAIN_INT.fullmatch(s):
        cls = "정상(무콤마)"
    elif _DECIMAL.fullmatch(s):
        cls = "정상(소수)"
    else:
        cls = "비금액(거부됨)" if got is None else "숫자아님인데수락"
    return cls, got


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=300, help="0 = 전수")
    ap.add_argument("--shard", help="a/n")
    ap.add_argument("--seed", type=int, default=20260730)
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    with get_session() as session:
        rows = list(session.execute(text(TARGETS_SQL)).fetchall())
    if args.shard:
        a, n = (int(x) for x in args.shard.split("/"))
        rows = [r for i, r in enumerate(rows) if i % n == a]
    elif args.limit:
        random.Random(args.seed).shuffle(rows)
        rows = rows[: args.limit]
    print(f"대상 {len(rows)} filing", flush=True)

    t: Counter[str] = Counter()
    bad_filings: Counter[str] = Counter()
    samples: list[str] = []
    t0 = time.time()

    for i, f in enumerate(rows, 1):
        if i % 200 == 0:
            print(f"  … {i}/{len(rows)} ({(time.time()-t0)/i:.2f}s/filing)", flush=True)
        p = Path(f.file_path)
        if not p.exists():
            t["파일없음"] += 1
            continue
        try:
            root = _parse_xml_file(p)
        except Exception:  # noqa: BLE001
            t["파싱실패"] += 1
            continue
        if root is None:
            t["파싱실패"] += 1
            continue
        t["filing"] += 1

        # ★추출기와 같은 경로로 셀을 골라야 한다. 초판은 모든 TD 를 그냥 훑어서, 실제로는
        #   `_split_label_amounts` 의 주석참조 가드가 이미 걸러내는 셀('4,5,6,8,10,21,40')
        #   까지 '날조'로 셌다 — 671건이 과대계상이었다(교훈 §7 재발).
        for tb in root.iter("TABLE"):
            for tr in table_direct_rows(tb):
                cells = _get_cells(tr)
                if not cells:
                    continue
                if _is_header_cell(cells[0].strip()) or _is_fs_title_row(cells):
                    continue
                _, amt_cells = _split_label_amounts(cells)
                for raw in amt_cells:
                    if not raw.strip():
                        continue
                    cls, got = classify(raw)
                    t[cls] += 1
                    if cls.startswith("★") or cls == "숫자아님인데수락":
                        bad_filings[f.rcept_no] += 1
                        if len(samples) < args.show:
                            shown_val = f"{got:,}" if got is not None else "None(거부됨)"
                            samples.append(f"{f.rcept_no}  {cls[1:14]:<14} "
                                           f"원문={raw!r:32} → {shown_val}")
                    if got is not None and abs(got) > _FLOAT53:
                        t["★float53초과(정밀도손실)"] += 1

    el = time.time() - t0
    n = max(t["filing"], 1)
    print(f"\n=== 금액셀 형식 진단 (filing {n}, {el:.0f}s, {el/n:.2f}s/filing) ===")
    total = sum(v for k, v in t.items()
                if k.startswith(("정상", "★날조", "★병합", "비금액", "숫자아님")))
    print(f"  (분류 대상 셀 {total:,})")
    for k in ("정상(그룹)", "정상(그룹소수·절단)", "정상(무콤마)", "정상(소수)",
              "비금액(거부됨)", "★병합(공백·동일값)", "★병합(공백·상이값)",
              "★날조(그룹문법파괴)", "숫자아님인데수락",
              "★float53초과(정밀도손실)"):
        if t[k] or k.startswith("★"):
            pct = t[k] / max(total, 1) * 100
            print(f"  {k:<26} {t[k]:>10,} ({pct:7.4f}%)")
    print(f"\n  영향 filing {len(bad_filings):,} / {n:,} ({len(bad_filings)/n*100:.2f}%)")
    if bad_filings:
        print("  상위 filing: " + ", ".join(
            f"{r}({c})" for r, c in bad_filings.most_common(5)))
    for k in ("파일없음", "파싱실패"):
        if t[k]:
            print(f"  {k}: {t[k]}")
    if samples:
        print("\n--- 사례 ---")
        for s in samples:
            print(f"  {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
