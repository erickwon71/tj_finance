"""퍼지 매핑 전수 조사 — account_maps alias 승격 작업목록 생성 (재구축 Phase C 선행).

## 왜 필요한가
Phase A-3(M1/M2)에서 **퍼지 매핑에 canonical 을 주지 않도록** 했다(유사도만으로 표준계정을
부여하지 않는다). 그런데 퍼지는 그동안 **두 가지 일을 동시에** 하고 있었다:

  (A) alias 사전에 없는 **정당한 표기변형**을 구제 — '법인세비용(수익)'(등록된 건
      '법인세비용(이익)') · '판매비와일반관리비'(vs '판매비와관리비').
  (B) **다른 개념에 과잉매핑** — '금융부채'→bs.short_term_debt · '기타무형자산'→bs.intangibles
      (상위개념의 부분집합!) · '매출채권 및 기타유동채권'→bs.trade_receivables.

(B)는 이번 재구축의 표적이라 없어지는 게 정답이지만, (A)까지 같이 죽어서 실측 **287건 중
214건(74.6%)** 보고서가 std_v2 지표를 잃는다. (A)를 **alias 로 승격**해야 커버리지가 돌아온다.
값을 손으로 채우는 게 아니라 **사전을 고쳐 패턴 전체를 해결**한다(계획 §2 원칙 4).

## 왜 DB 가 아니라 원문에서 세는가
`fact_v2.mapping_stage` 는 재추출 전까지 **전 행 NULL** 이다(A-2 컬럼은 메타데이터만 추가).
따라서 지금은 raw_report 파일을 직접 파싱해 세야 한다. 재구축 이후에는 아래로 대체 가능:
    SELECT acode, count(*) FROM fact_v2 WHERE mapping_stage='fuzzy' GROUP BY 1 ORDER BY 2 DESC;

## 무엇을 세는가
본문 섹션(연결재무제표/재무제표) 데이터표의 라벨만 대상으로,
`AccountMapper.map()` 이 stage='fuzzy' 를 반환하는 (정규화 라벨 → 후보 canonical) 쌍을
**영향도 순**으로 집계한다. std_v2 가 실제로 읽는 canonical(rules.CONSUMED_CANON)에
가중치를 둔다 — 아무도 안 읽는 계정은 승격해도 지표가 살아나지 않는다.

사용:
    python scripts/fuzzy_alias_survey.py --limit 400
    python scripts/fuzzy_alias_survey.py --limit 400 --out docs/qa/fuzzy_alias_worklist.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from fin2.extract.text import _detect_body_statement_tables
from fin2.standardize.rules import CONSUMED_CANON
from parser.common.account_mapper import get_mapper
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.table_extractor import extract_rows

_RAW = Path("raw_report")


def _sample_files(limit: int, per_corp: int = 1) -> list[tuple[Path, int, str]]:
    """2015+ 보고서를 기업당 per_corp 건씩 고루 뽑는다(대형사 편중 방지)."""
    out: list[tuple[Path, int, str]] = []
    for mkt in ("KOSPI", "KOSDAQ"):
        base = _RAW / mkt
        if not base.exists():
            continue
        for corp in sorted(base.glob("*")):
            got = 0
            for kind, fp in (("annual", "FY"), ("half", "H1"), ("quarter", "Q1")):
                for f in sorted((corp / kind).glob("*/*.xml"), reverse=True):
                    try:
                        fy = int(f.parent.name)
                    except ValueError:
                        continue
                    if fy >= 2015:
                        out.append((f, fy, fp))
                        got += 1
                        break
                if got >= per_corp:
                    break
            if len(out) >= limit:
                return out
    return out


def survey(limit: int) -> dict:
    mapper = get_mapper()
    files = _sample_files(limit)
    logger.info(f"[fuzzy-survey] 표본 {len(files)}건 파싱 시작")

    # 같은 라벨이 수없이 반복되므로 매핑 결과를 메모이즈(퍼지가 전 alias 순회라 매우 비쌈)
    memo: dict[tuple[str, str], object] = {}

    def _map(label: str, sec: str):
        key = (label, sec)
        if key not in memo:
            memo[key] = mapper.map(label, fs_section=sec)
        return memo[key]

    # (정규화라벨, 후보canonical) → 등장 fact 수 / 보고서 수
    pair_facts: Counter = Counter()
    pair_reports: defaultdict[tuple, set] = defaultdict(set)
    pair_alias: dict[tuple, tuple] = {}      # → (matched_alias, confidence)
    # canonical 이 그 보고서에서 **퍼지에만** 의존했는지(= 승격 안 하면 진짜 손실)
    canon_only_fuzzy: Counter = Counter()
    reports_losing: set = set()
    n_ok = 0

    for f, fy, fp in files:
        try:
            root = _parse_xml_file(f)
            if root is None:
                continue
            groups = _detect_body_statement_tables(root, "A")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"  skip {f}: {e}")
            continue
        if not groups:
            continue
        n_ok += 1
        rid = f.stem
        strict_here: set = set()
        fuzzy_here: defaultdict[str, set] = defaultdict(set)

        for code, tbls in groups.items():
            sec = code.split("_")[0].lower()
            for tbl, unit, _kind in tbls:
                if unit is None:
                    continue
                for row in extract_rows(tbl, multiplier=unit, num_cols=3, direct_only=True):
                    if not row.account_name:
                        continue
                    # ★ 금액이 없는 행은 **fact 가 되지 않는다**(_emit_section 이 amount None 을
                    # 건너뛴다) → 세면 안 된다. 실측: BS 의 '자산'/'부채'/'자본' 은 금액 없는
                    # **섹션 헤더**인데(25건 검사 46/46 전부 금액없음), 이를 세면 '자산→
                    # bs.total_assets 347보고서' 같은 유령 항목이 작업목록 최상단에 올라온다.
                    if not any(a is not None for a in row.amounts):
                        continue
                    m = _map(row.account_name, sec)
                    if m.account_code.startswith("unknown."):
                        continue
                    if m.stage == "fuzzy":
                        key = (m.matched_alias or "", m.account_code)
                        # 라벨은 normalize 된 형태로 집계(사전 등록 단위와 맞춤)
                        nk = (_norm_label(row.account_name), m.account_code)
                        pair_facts[nk] += 1
                        pair_reports[nk].add(rid)
                        pair_alias[nk] = (m.matched_alias, round(m.confidence, 3))
                        fuzzy_here[m.account_code].add(nk[0])
                    else:
                        strict_here.add(m.account_code)

        lost = False
        for canon in fuzzy_here:
            if canon in CONSUMED_CANON and canon not in strict_here:
                canon_only_fuzzy[canon] += 1
                lost = True
        if lost:
            reports_losing.add(rid)

    return {
        "n_reports": n_ok,
        "n_reports_losing": len(reports_losing),
        "pair_facts": pair_facts,
        "pair_reports": {k: len(v) for k, v in pair_reports.items()},
        "pair_alias": pair_alias,
        "canon_only_fuzzy": canon_only_fuzzy,
    }


def _norm_label(s: str) -> str:
    from parser.common.amount_normalizer import normalize_account_name
    return normalize_account_name(s) or s.strip()


def render(r: dict, top: int) -> str:
    L: list[str] = []
    n, losing = r["n_reports"], r["n_reports_losing"]
    L.append("# 퍼지 alias 승격 작업목록 (자동 생성)")
    L.append("")
    L.append(f"- 표본 보고서(본문 검출): **{n}**")
    L.append(f"- 퍼지를 끄면 std_v2 소비 canonical 을 잃는 보고서: "
             f"**{losing} ({losing/max(n,1)*100:.1f}%)**")
    L.append("")
    L.append("## 1. 퍼지가 유일 출처인 canonical (승격 우선순위)")
    L.append("")
    L.append("| canonical | 영향 보고서 |")
    L.append("|---|---|")
    for c, k in r["canon_only_fuzzy"].most_common(30):
        L.append(f"| `{c}` | {k} |")
    L.append("")
    L.append("## 2. 라벨 → 후보 canonical (판정 대상)")
    L.append("")
    L.append("`판정` 열을 채울 것: **A**=alias 승격(정당한 표기변형) / "
             "**B**=무매핑 확정(과잉매핑) / **?**=원문 확인 필요")
    L.append("")
    L.append("| 판정 | 원문 라벨(정규화) | → 후보 canonical | 붙은 alias | 유사도 | 보고서 | fact |")
    L.append("|---|---|---|---|---|---|---|")
    for (label, canon), nf in r["pair_facts"].most_common(top):
        alias, conf = r["pair_alias"][(label, canon)]
        nrep = r["pair_reports"][(label, canon)]
        star = "★" if canon in CONSUMED_CANON else ""
        L.append(f"|  | `{label}` | {star}`{canon}` | `{alias}` | {conf} | {nrep} | {nf} |")
    L.append("")
    L.append("★ = std_v2 가 실제로 읽는 canonical (승격 효과가 지표로 나타남)")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400, help="표본 보고서 수")
    ap.add_argument("--top", type=int, default=80, help="라벨 표 상위 N")
    ap.add_argument("--out", type=Path, help="마크다운 저장 경로")
    ap.add_argument("--json", type=Path, help="원자료 JSON 저장 경로")
    a = ap.parse_args()

    r = survey(a.limit)
    md = render(r, a.top)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(md, encoding="utf-8")
        logger.success(f"[fuzzy-survey] 작성 → {a.out}")
    else:
        print(md)
    if a.json:
        payload = {
            "n_reports": r["n_reports"],
            "n_reports_losing": r["n_reports_losing"],
            "canon_only_fuzzy": dict(r["canon_only_fuzzy"]),
            "pairs": [
                {"label": k[0], "canonical": k[1], "alias": r["pair_alias"][k][0],
                 "confidence": r["pair_alias"][k][1],
                 "reports": r["pair_reports"][k], "facts": v,
                 "consumed": k[1] in CONSUMED_CANON}
                for k, v in r["pair_facts"].most_common()
            ],
        }
        a.json.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        logger.success(f"[fuzzy-survey] JSON → {a.json}")


if __name__ == "__main__":
    main()
