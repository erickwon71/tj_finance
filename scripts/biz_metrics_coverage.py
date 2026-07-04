"""B4b · 사업지표(biz_metrics) 산업별 커버리지·품질 리포트(읽기전용).

corporations.induty_code(KSIC) 2자리 대분류로 묶어, 생산표 보유율(제조·자원 업종은 높아야
정상)·평균 지표행·품질 플래그를 집계한다. 파서 반복(어느 업종을 더 볼지) 우선순위 판단용.

usage:
  python scripts/biz_metrics_coverage.py                 # 전체 요약
  python scripts/biz_metrics_coverage.py --manufacturing # 제조업(10~34)만
  python scripts/biz_metrics_coverage.py --missing       # 생산표 없는 제조 기업 목록
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

# KSIC 2자리 대분류명(생산 데이터가 있어야 정상인 업종 위주). 미등록은 코드 그대로.
_KSIC2: dict[str, str] = {
    "01": "농업", "02": "임업", "03": "어업",
    "05": "석탄광업", "06": "원유·가스", "07": "금속광업", "08": "비금속광업",
    "10": "식료품", "11": "음료", "12": "담배", "13": "섬유", "14": "의복",
    "15": "가죽·신발", "16": "목재", "17": "펄프·종이", "18": "인쇄", "19": "석유정제",
    "20": "화학물질", "21": "의약품", "22": "고무·플라스틱", "23": "비금속광물제품",
    "24": "1차금속", "25": "금속가공", "26": "전자·통신", "27": "의료·정밀·광학",
    "28": "전기장비", "29": "기타기계", "30": "자동차", "31": "기타운송장비",
    "32": "가구", "33": "기타제품", "34": "기계수리·설치",
    "35": "전기·가스", "36": "수도", "37": "하수·폐기물", "38": "폐기물처리", "39": "환경정화",
    "41": "종합건설", "42": "전문공사",
    "45": "자동차판매", "46": "도매·중개", "47": "소매",
    "49": "육상운송", "50": "수상운송", "51": "항공운송", "52": "창고·운송지원",
    "55": "숙박", "56": "음식점",
    "58": "출판·SW", "59": "영상·오디오", "60": "방송·통신", "61": "통신", "62": "SW개발",
    "63": "정보서비스", "64": "금융", "65": "보험", "66": "금융지원",
    "68": "부동산", "70": "연구개발", "71": "전문서비스", "72": "엔지니어링",
    "73": "기타과학기술", "74": "사업시설관리", "75": "사업지원", "76": "임대",
    "84": "공공행정", "85": "교육", "86": "보건", "87": "사회복지",
    "90": "예술·여가", "91": "스포츠·오락",
}
_MFG = {f"{n:02d}" for n in range(10, 35)}  # 제조업 대분류


def _div(code: str | None) -> str:
    return (code or "")[:2] or "??"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manufacturing", action="store_true", help="제조업(10~34)만")
    ap.add_argument("--missing", action="store_true", help="생산표 없는 제조 기업 목록")
    args = ap.parse_args()

    with get_session() as s:
        # 활성 보통주 전체(모집단) + 생산표 보유 기업.
        pop = s.execute(text(
            "SELECT corp_code, corp_name, induty_code FROM corporations "
            "WHERE is_active AND stock_code IS NOT NULL")).fetchall()
        have = {r[0]: r[1] for r in s.execute(text(
            "SELECT corp_code, count(*) FROM biz_metrics GROUP BY 1")).fetchall()}

    if args.missing:
        rows = [(r.corp_code, r.corp_name, _div(r.induty_code)) for r in pop
                if _div(r.induty_code) in _MFG and r.corp_code not in have]
        rows.sort(key=lambda x: (x[2], x[1]))
        print(f"=== 생산표 없는 제조업(10~34) 기업 {len(rows)}사 ===")
        for cc, nm, d in rows:
            print(f"  [{d} {_KSIC2.get(d, d)}] {nm} ({cc})")
        return

    # 대분류별 집계.
    agg: dict[str, dict] = {}
    for r in pop:
        d = _div(r.induty_code)
        a = agg.setdefault(d, {"corps": 0, "covered": 0, "rows": 0})
        a["corps"] += 1
        if r.corp_code in have:
            a["covered"] += 1
            a["rows"] += have[r.corp_code]

    divs = sorted(agg)
    if args.manufacturing:
        divs = [d for d in divs if d in _MFG]
    print(f"{'div':<5} {'업종':<14} {'기업':>5} {'생산표':>6} {'커버%':>6} {'평균행':>6}")
    tot_c = tot_cov = 0
    for d in divs:
        a = agg[d]
        cov_pct = 100 * a["covered"] / a["corps"] if a["corps"] else 0
        avg = a["rows"] / a["covered"] if a["covered"] else 0
        mark = " ★" if d in _MFG and cov_pct < 50 and a["corps"] >= 5 else ""
        print(f"{d:<5} {_KSIC2.get(d, d):<14} {a['corps']:>5} {a['covered']:>6} "
              f"{cov_pct:>5.0f}% {avg:>6.1f}{mark}")
        tot_c += a["corps"]; tot_cov += a["covered"]
    print(f"{'—'*5} {'합계':<14} {tot_c:>5} {tot_cov:>6} {100*tot_cov/max(tot_c,1):>5.0f}%")
    print("★=제조업인데 커버 50% 미만(파서 반복 우선 후보). 참고: DB 백필 진행중이면 수치는 부분치.")


if __name__ == "__main__":
    main()
