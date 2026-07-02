"""I1 · DART API 교차검증 — 독립 소스로 DB 재무수치 대조.

지금까지의 검증(Gate A/B)은 전부 "공시 원문 ↔ DB" 자기일관성이다. 이 스크립트는 **독립 소스**인
DART Open API 주요계정(fnlttSinglAcnt)을 당겨 우리 `standard_financials`(std_v2)와 대조한다.
→ "보고서==DB"를 넘어 "진실(제3자 구조화값)==DB" 로 격상. ×1000 단위오류·부호오류·계정 오귀속처럼
원문과 DB가 똑같이 틀린 경우도 잡을 수 있다.

대조 항목(주요계정): 매출액·영업이익·당기순이익·자산총계·부채총계·자본총계 × 연결(CFS)/별도(OFS).
DART 주요계정은 2015 사업연도부터 제공(그 이전·일부 금융업 계정은 DART_MISSING 로 분류).

usage:
  python scripts/verify_cross_source.py                         # 무작위 표본 30사 × 2020~2024 FY
  python scripts/verify_cross_source.py --corps 00126380,00593624 --years 2021-2023
  python scripts/verify_cross_source.py --sample 100 --years 2018-2024 --out /tmp/xsrc.json
  python scripts/verify_cross_source.py --smoke                 # DART 연결성 확인(삼성전자 1콜)

종료코드: MISMATCH(원문과 DB가 어긋남)가 1건이라도 있으면 1, 아니면 0(게이트로 사용 가능).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.dart_client import DartClient, DartApiError
from collector.db import get_session

# std_financials 필드 → DART 주요계정 account_nm 후보(별칭 포함).
_FIELD_ACCOUNTS: dict[str, tuple[str, ...]] = {
    "revenue":           ("매출액", "수익(매출액)", "영업수익"),
    "operating_income":  ("영업이익", "영업이익(손실)"),
    "net_income":        ("당기순이익", "당기순이익(손실)", "당기순이익(당기순손실)"),
    "total_assets":      ("자산총계",),
    "total_liabilities": ("부채총계",),
    "total_equity":      ("자본총계",),
}
_FIELDS = tuple(_FIELD_ACCOUNTS)
_FS_DIV = {"CFS": "consolidated", "OFS": "separate"}


def _parse_amount(s: str | None):
    """DART 금액 문자열('1,234' / '-' / '' / '(1,234)') → int(원) 또는 None."""
    if s is None:
        return None
    t = s.strip().replace(",", "").replace(" ", "")
    if t in ("", "-"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    if neg:
        t = t[1:-1]
    try:
        v = int(float(t))
    except ValueError:
        return None
    return -v if neg else v


def _dart_values(rows: list[dict]) -> dict[str, dict[str, int]]:
    """fnlttSinglAcnt 응답 → {statement_type: {field: amount_won}}."""
    out: dict[str, dict[str, int]] = {"consolidated": {}, "separate": {}}
    for r in rows:
        stmt = _FS_DIV.get(r.get("fs_div", ""))
        if not stmt:
            continue
        acc = (r.get("account_nm") or "").strip()
        amt = _parse_amount(r.get("thstrm_amount"))
        if amt is None:
            continue
        for field, names in _FIELD_ACCOUNTS.items():
            if acc in names and field not in out[stmt]:
                out[stmt][field] = amt
    return out


def _db_values(session, corp_code: str, year: int) -> dict[str, dict[str, int]]:
    """standard_financials FY 행 → {statement_type: {field: amount_won}}."""
    sql = text(f"""
        SELECT statement_type, {', '.join(_FIELDS)}
        FROM standard_financials
        WHERE corp_code = :c AND fiscal_year = :y AND fiscal_period = 'FY'
    """)
    out: dict[str, dict[str, int]] = {"consolidated": {}, "separate": {}}
    for row in session.execute(sql, {"c": corp_code, "y": year}).mappings():
        stmt = row["statement_type"]
        if stmt not in out:
            continue
        out[stmt] = {f: row[f] for f in _FIELDS if row[f] is not None}
    return out


def _rel_diff(a: int, b: int) -> float:
    denom = max(abs(a), abs(b), 1)
    return abs(a - b) / denom


def _compare(corp, name, year, dart, db, tol, abs_floor):
    """(corp,year) 비교 → 결과 레코드 목록."""
    recs = []
    for stmt in ("consolidated", "separate"):
        for f in _FIELDS:
            dv, bv = dart[stmt].get(f), db[stmt].get(f)
            if dv is None and bv is None:
                continue
            if bv is None:
                cat = "DART_ONLY"          # DART엔 있는데 DB 없음(추출누락 후보)
            elif dv is None:
                cat = "DB_ONLY"            # DB엔 있는데 DART 없음(2015이전·금융업 계정 등)
            else:
                rd = _rel_diff(dv, bv)
                if abs(dv - bv) <= abs_floor or rd <= tol:
                    cat = "MATCH"
                elif dv != 0 and bv != 0 and abs(abs(dv) - abs(bv)) <= abs_floor:
                    cat = "SIGN_FLIP"      # 절대값 같고 부호만 다름
                elif dv != 0 and abs(_rel_diff(dv * 1000, bv)) <= tol:
                    cat = "X1000"          # DB가 DART의 1000배(단위오류 후보)
                else:
                    cat = "MISMATCH"
            recs.append({
                "corp_code": corp, "corp_name": name, "year": year, "stmt": stmt,
                "field": f, "dart": dv, "db": bv, "category": cat,
            })
    return recs


def _pick_corps(session, args) -> list[tuple[str, str]]:
    if args.corps:
        raw = args.corps
        if Path(raw).exists():
            raw = Path(raw).read_text()
        codes = [c.strip() for c in raw.replace("\n", ",").split(",") if c.strip()]
        rows = session.execute(text(
            "SELECT corp_code, corp_name FROM corporations WHERE corp_code = ANY(:cs)"),
            {"cs": codes}).fetchall()
        by = {r[0]: r[1] for r in rows}
        return [(c, by.get(c, "?")) for c in codes]
    pool = session.execute(text(
        "SELECT corp_code, corp_name FROM corporations "
        "WHERE is_active AND stock_code IS NOT NULL ORDER BY corp_code")).fetchall()
    rng = random.Random(args.seed)
    pool = [(r[0], r[1]) for r in pool]
    rng.shuffle(pool)
    return pool[: args.sample]


def _parse_years(spec: str) -> list[int]:
    if "-" in spec:
        a, b = (int(x) for x in spec.split("-"))
        return list(range(a, b + 1))
    return [int(x) for x in spec.split(",") if x.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps", help="corp_code 목록(쉼표) 또는 파일. 없으면 무작위 표본.")
    ap.add_argument("--sample", type=int, default=30, help="무작위 표본 기업수(--corps 없을 때)")
    ap.add_argument("--years", default="2020-2024", help="예: 2020-2024 또는 2021,2023")
    ap.add_argument("--reprt", default="11011", help="11011 FY / 11012 반기 / 11013 Q1 / 11014 Q3")
    ap.add_argument("--tol", type=float, default=0.005, help="상대오차 허용(기본 0.5%)")
    ap.add_argument("--abs-floor", type=int, default=1_000_000, help="절대오차 허용(원, 기본 100만)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", help="상세 결과 JSON 저장 경로")
    ap.add_argument("--smoke", action="store_true", help="DART 연결성만 확인(삼성전자 2023 1콜)")
    args = ap.parse_args()

    client = DartClient()

    if args.smoke:
        try:
            rows = client.get_single_account("00126380", 2023, "11011")
        except (DartApiError, Exception) as e:  # noqa: BLE001
            logger.error(f"[smoke] DART 호출 실패: {type(e).__name__}: {e}")
            sys.exit(2)
        vals = _dart_values(rows)
        logger.success(f"[smoke] DART OK — 삼성전자 2023 계정 {len(rows)}행")
        print(json.dumps(vals, ensure_ascii=False, indent=2))
        client.close()
        return

    years = _parse_years(args.years)
    with get_session() as s:
        corps = _pick_corps(s, args)
    logger.info(f"[xsrc] 대상 {len(corps)}사 × {len(years)}년({years[0]}~{years[-1]}) reprt={args.reprt}")

    all_recs: list[dict] = []
    agg = {"MATCH": 0, "MISMATCH": 0, "X1000": 0, "SIGN_FLIP": 0, "DART_ONLY": 0, "DB_ONLY": 0}
    api_err = 0
    for i, (corp, name) in enumerate(corps, 1):
        with get_session() as s:
            for y in years:
                try:
                    rows = client.get_single_account(corp, y, args.reprt)
                except DartApiError as e:
                    if e.status not in ("013", "020"):  # 013 없음/020 한도
                        api_err += 1
                        logger.warning(f"  {corp} {y}: DART [{e.status}] {e.message}")
                    continue
                except Exception as e:  # noqa: BLE001
                    api_err += 1
                    logger.warning(f"  {corp} {y}: {type(e).__name__}: {e}")
                    continue
                if not rows:
                    continue
                recs = _compare(corp, name, y, _dart_values(rows), _db_values(s, corp, y),
                                args.tol, args.abs_floor)
                for r in recs:
                    agg[r["category"]] = agg.get(r["category"], 0) + 1
                all_recs.append(recs) if False else all_recs.extend(recs)
        if i % 20 == 0 or i == len(corps):
            logger.info(f"  ..{i}/{len(corps)} 비교셀 {len(all_recs):,}")
    client.close()

    issues = [r for r in all_recs if r["category"] in ("MISMATCH", "X1000", "SIGN_FLIP")]
    print("\n===== 교차검증 요약 =====")
    for k in ("MATCH", "MISMATCH", "X1000", "SIGN_FLIP", "DART_ONLY", "DB_ONLY"):
        print(f"  {k:<10}: {agg.get(k, 0):,}")
    print(f"  API 오류   : {api_err}")
    if issues:
        print(f"\n----- 불일치 상세(상위 40) -----")
        for r in issues[:40]:
            print(f"  {r['category']:<9} {r['corp_name']}({r['corp_code']}) {r['year']} "
                  f"{r['stmt']}.{r['field']}: DART={r['dart']:,} DB={r['db']:,}")

    if args.out:
        Path(args.out).write_text(json.dumps(all_recs, ensure_ascii=False, indent=2))
        logger.info(f"[xsrc] 상세 저장 → {args.out}")

    n_issue = agg.get("MISMATCH", 0) + agg.get("X1000", 0) + agg.get("SIGN_FLIP", 0)
    print(f"\n{'✅ 불일치 없음' if n_issue == 0 else f'⚠ 불일치 {n_issue}건'}")
    sys.exit(1 if n_issue else 0)


if __name__ == "__main__":
    main()
