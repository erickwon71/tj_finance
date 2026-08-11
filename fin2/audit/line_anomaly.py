"""계층2 이상치 **탐지**(값은 고치지 않는다) — 2026-07-21.

report_lines 는 원문 그대로를 유지하고, 여기서는 "이 셀은 이상하다"만 근거와 함께 기록한다.
계층3 이 그 표시를 보고 보정 여부를 판단한다(사용자 확정). 배경·원칙은
`collector.models.ReportLineAnomaly` docstring 참고.

## 현재 커버: 자본변동표(SCE) × BS 교차대조
SCE 기말자본 행의 각 자본 항목이 **같은 보고서 BS** 와 다르면 표시한다. 다른 재무제표를
근거로 삼으므로 표 내부 검산보다 훨씬 강하다 — 같은 XML 을 같은 파서로 읽은 BS 가 정상값을
내므로, 불일치는 파서가 아니라 **공시 원문**의 문제임이 구조적으로 드러난다.

실측 확인 사례(전부 원문 오기, 사용자가 DART 원문 대조):
    쏠리드 2019 연결   이익잉여금  BS 26,038,777,444 ↔ SCE  2,603,877,744  (끝자리 유실)
                       지배지분    BS 122,609,246,330 ↔ SCE 12,260,924,633  (끝자리 유실)
    에스에이티 2019 연결 총계 부호 반전
    대림제지 2023 연결  자본조정 기말 부호 누락

## 확장 지점
`detect_anomalies()` 는 statement 별 탐지기를 모아 부르는 자리다. BS/IS/CF 용 규칙(예: 표
내부 합계 불일치)을 추가할 때 여기에 붙인다.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, asdict

# ── 자본 항목 개념 사전 ────────────────────────────────────────────────────────
# **정확일치만** 인정한다. 부분일치를 쓰면 '보통주자본금'이 '자본금'으로 잡혀 BS 값이 모호해진다.
_CONCEPTS: dict[str, set[str]] = {
    "자본금":     {"자본금"},
    "자본잉여금": {"자본잉여금", "주식발행초과금"},
    "이익잉여금": {"이익잉여금", "이익잉여금결손금", "결손금", "미처분이익잉여금"},
    "비지배지분": {"비지배지분"},
    "지배지분":   {"지배기업의소유주에게귀속되는자본", "지배기업의소유주에게귀속되는지분",
                   "지배기업소유주지분", "지배기업소유주귀속자본", "지배지분",
                   "지배기업의소유주지분", "지배주주지분"},
    "자본총계":   {"자본총계", "자본합계", "총자본"},
}
_PAREN = re.compile(r"[（(][^)）]*[)）]")
_CLOSE = re.compile(r"기말")
_TOL = 0.001        # 상대오차 0.1% — 단위 반올림 흡수

# ── 열 세분화 차이 허용 ────────────────────────────────────────────────────────
# SCE 열이 BS 항목보다 **거칠게 묶여** 있는 경우가 있다. 실측(APS 054620 2022 별도):
#     BS   자본금 10,895,916,500 + 자본잉여금 124,353,775,221 = 135,249,691,721
#     SCE  '자본금' 열                                          135,249,691,721
# 라벨은 '자본금'이지만 실제로는 납입자본(자본금+자본잉여금)을 합쳐 표시한 것.
# 원문 오기도 파서 결함도 아닌 **표시 granularity 차이**다. 1:1 대응만 보면 거짓 이상치가 된다.
# → 1차 대조 실패 시 아래 대체 조합으로 한 번 더 맞춰보고, 맞으면 이상치로 보지 않는다.
#   (조합을 함부로 늘리면 진짜 오류를 덮으므로 실측으로 확인된 것만 등록한다.)
_ALT_REFERENCES: dict[str, list[tuple[str, ...]]] = {
    "자본금": [("자본금", "자본잉여금")],       # 납입자본 묶음 표시
}

# 실제로 SCE↔BS 대조를 수행할 개념. '자본잉여금' 은 위 집계의 **재료로만** 쓰고 직접
# 대조하지 않는다 — SCE 쪽 표기가 자본잉여금/주식발행초과금/기타자본잉여금 등으로 갈려
# granularity 차이가 잦고, 직접 대조하면 low 노이즈만 늘었다(실측 69건→77건).
_CHECK_CONCEPTS = ("자본금", "이익잉여금", "비지배지분", "지배지분", "자본총계")


@dataclass
class LineAnomaly:
    """ReportLineAnomaly 한 건(DB 비의존)."""
    rcept_no: str
    corp_code: str
    statement: str
    basis: str | None
    table_seq: int | None
    row_order: int | None
    col_index: int | None
    label_raw: str | None
    original_value: int | None
    suggested_value: int | None
    anomaly_kind: str
    evidence: str
    evidence_detail: str | None
    confidence: str

    def as_row(self) -> dict:
        return asdict(self)


def _norm(s: str | None) -> str:
    return (s or "").replace(" ", "").replace("　", "")


def _concept_key(label: str | None) -> str | None:
    """라벨 → 개념 키. 주석참조 괄호 제거 후 정확일치, 실패 시 접미사 '합계'를 떼고 재시도.

    ('자본합계' 처럼 접미사를 떼면 뜻이 달라지는 것은 1차 정확일치에서 이미 잡힌다.)
    """
    n = _norm(_PAREN.sub("", label or ""))
    for cand in (n, n[:-2] if n.endswith("합계") else None):
        if not cand:
            continue
        for concept, names in _CONCEPTS.items():
            if cand in names:
                return concept
    return None


def classify_anomaly(reference: int, observed: int) -> str:
    """이상치 유형 추정. reference=근거값(BS 등), observed=원문 값."""
    if reference == -observed:
        return "SIGN"
    a, b = str(abs(reference)), str(abs(observed))
    if len(a) == len(b) + 1 and a.startswith(b):
        return "DIGIT_TRUNC"        # 끝자리 유실(쏠리드 유형)
    if len(b) == len(a) + 1 and b.startswith(a):
        return "DIGIT_EXTRA"
    return "OTHER"


def _bs_concepts(lines, basis: str, col_index: int) -> dict[str, int]:
    """BS 한 기간(col_index: 0=당기 1=전기 2=전전기)의 개념별 값.

    같은 개념이 **서로 다른 값**으로 여러 번 나오면 제외한다(모호 → 근거로 못 씀).
    추측해서 하나를 고르지 않는다."""
    buckets: dict[str, set[int]] = defaultdict(set)
    for l in lines:
        if l.statement != "BS" or l.basis != basis or l.col_index != col_index:
            continue
        if l.value_won is None:
            continue
        k = _concept_key(l.label_raw)
        if k:
            buckets[k].add(l.value_won)
    return {k: next(iter(v)) for k, v in buckets.items() if len(v) == 1}


_YEAR_IN_LABEL = re.compile(r"(\d{4})[.\-]\d{1,2}[.\-]\d{1,2}")


def _close_row_year(label: str) -> int | None:
    """기말 행 라벨('2019.12.31 (기말자본)')에서 연도. 없으면 None(대조 대상에서 제외)."""
    m = _YEAR_IN_LABEL.search(label or "")
    return int(m.group(1)) if m else None


def detect_sce_anomalies(lines, *, rcept_no: str, corp_code: str,
                         report_fiscal_period: str | None = None) -> list[LineAnomaly]:
    """SCE 기말자본 행 ↔ 같은 보고서 BS 항목별 대조 → 불일치 표시.

    `lines` 는 `extract_report_lines()` 결과 전체(BS 포함)여야 한다 — 교차대조가 목적이므로.

    ★ **FY(사업보고서)만 대조한다**(실측 2026-07-22). 분기·반기 보고서는 BS 비교열이
      '전기말(직전 연말)'인데 SCE 기말 행은 '전년 동분기말'이라 **다른 날짜를 비교**하게 된다:
          Q1 보고서: BS(col1)=2014.12.31  ↔  SCE '2014.02.28 (기말자본)'
      전량적재 시험 300건에서 이 오탐이 780건 나왔다(FY 는 0건). 연도만으로 열을 짝지을 수
      없으므로 기간 종료일을 정확히 맞출 수 있게 되기 전까지는 FY 로 한정한다.
    """
    if report_fiscal_period is not None and report_fiscal_period != "FY":
        return []
    out: list[LineAnomaly] = []
    report_fy = next((l.report_fiscal_year for l in lines), None)

    for basis in ("consolidated", "separate"):
        sce = [l for l in lines if l.statement == "SCE" and l.basis == basis]
        if not sce:
            continue

        col_label: dict[int, str] = {}
        for l in sce:
            if l.col_label and l.col_index not in col_label:
                col_label[l.col_index] = l.col_label
        # SCE 열 → 개념 (다단 라벨의 마지막 단이 항목명)
        concept_col: dict[str, int] = {}
        for c, lab in col_label.items():
            k = _concept_key(lab.split(">")[-1])
            if k and k not in concept_col:
                concept_col[k] = c
        if not concept_col:
            continue

        by_row: dict[tuple, dict[int, object]] = defaultdict(dict)
        for l in sce:
            by_row[(l.table_seq, l.row_order, l.label_raw)][l.col_index] = l

        # ★ 기말 행이 여러 개다(당기·전기·전전기 블록이 세로로 쌓임). BS 도 col_index 0/1/2 로
        #   같은 기간들을 갖고 있으므로 **연도로 짝지어 전부 대조**한다. 한 보고서에서 오류가
        #   여러 건 나올 수 있고(실측 쏠리드 2019 는 한 행에서만 2건), 전부 개별 표시한다.
        for (tseq, ro, lbl), cells in sorted(by_row.items()):
            if not _CLOSE.search(_norm(lbl)):
                continue
            year = _close_row_year(lbl)
            if year is None or report_fy is None:
                continue
            bs_col = report_fy - year          # 0=당기 1=전기 2=전전기
            if not 0 <= bs_col <= 2:
                continue
            bs = _bs_concepts(lines, basis, bs_col)
            if not bs:
                continue
            for concept, c in concept_col.items():
                if concept not in _CHECK_CONCEPTS:
                    continue
                ref = bs.get(concept)
                cell = cells.get(c)
                if ref is None or cell is None or cell.value_won is None:
                    continue
                got = cell.value_won
                if got == ref or abs(got - ref) <= abs(ref or 1) * _TOL:
                    continue
                # SCE 열이 BS 보다 거칠게 묶인 표시인지 확인(_ALT_REFERENCES). 맞으면 정상.
                if any(
                    all(p in bs for p in combo)
                    and (got == (agg := sum(bs[p] for p in combo))
                         or abs(got - agg) <= abs(agg or 1) * _TOL)
                    for combo in _ALT_REFERENCES.get(concept, ())
                ):
                    continue
                kind = classify_anomaly(ref, got)
                out.append(LineAnomaly(
                    rcept_no=rcept_no, corp_code=corp_code,
                    statement="SCE", basis=basis,
                    table_seq=tseq, row_order=ro, col_index=c,
                    label_raw=lbl,
                    original_value=got,
                    # 제안값 = BS 값. **적용된 적 없다** — 계층3 이 confidence 를 보고 판단.
                    suggested_value=ref,
                    anomaly_kind=kind,
                    evidence="bs_crosscheck",
                    evidence_detail=(f"{year}년 {concept}: BS(col{bs_col}) {ref:,} "
                                     f"↔ SCE {got:,}"),
                    # SIGN/DIGIT_* 는 기계적으로 설명되는 편차라 신뢰도 높음.
                    # OTHER 는 원인 미상(원문 오기·개념 불일치 등 혼재) → 낮게 둔다.
                    confidence="high" if kind in ("SIGN", "DIGIT_TRUNC", "DIGIT_EXTRA") else "low",
                ))
    return out


# ── BS 항등식(자산=부채+자본) 대조 (2026-08-10) ─────────────────────────────
# 배경 — pre-2015 파일럿 백필 검증 중 발견: 일부 filer(실측 KG케미칼 2003~2008)는 "부채총계"
# 당기(col0) 셀만 괄호로 감싸(표준 괄호=음수 관례로 읽으면 부채가 음수가 됨) 자산=부채+자본
# 항등식이 깨진다. 반면 "부채와자본총계"(결합 총계 행)는 매번 자산과 정확히 일치해 원문에
# 진짜 오류(또는 filer 특유 표기 습관)가 있음을 강하게 시사한다. 근본원인이 원문 자체에
# 있어 파서 결값이 아니라면(R0: "판단 없이 전사") 계층2 에서 값을 고치지 않고, 여기서
# **표시만** 한다 — SCE↔BS 교차대조와 같은 원칙("계층3 이 보정 여부를 판단").
_ASSETS_LABELS = {"자산총계"}
_LIAB_LABELS = {"부채총계"}
_EQUITY_LABELS = {"자본총계", "자본합계", "총자본"}
_COMBINED_LABELS = {"부채와자본총계", "부채및자본총계", "부채자본총계"}


def _bs_total_rows(lines, basis: str, col_index: int) -> dict[str, object]:
    """BS 한 기간의 자산총계/부채총계/자본총계/(있으면)결합총계 **행 객체**.

    `_bs_concepts` 와 같은 모호성 원칙(같은 개념이 다른 값으로 여럿 나오면 제외, 추측 안 함)
    이되, 이상치 위치 표시(table_seq/row_order)를 위해 값이 아니라 행 자체를 돌려준다.
    """
    buckets: dict[str, list] = defaultdict(list)
    for l in lines:
        if l.statement != "BS" or l.basis != basis or l.col_index != col_index:
            continue
        if l.value_won is None:
            continue
        key = _norm(_PAREN.sub("", l.label_raw or ""))
        for concept, names in (("assets", _ASSETS_LABELS), ("liab", _LIAB_LABELS),
                                ("equity", _EQUITY_LABELS), ("combined", _COMBINED_LABELS)):
            if key in names:
                buckets[concept].append(l)
    out: dict[str, object] = {}
    for concept, rows in buckets.items():
        if len({r.value_won for r in rows}) == 1:
            out[concept] = rows[0]
    return out


def detect_bs_identity_anomalies(lines, *, rcept_no: str, corp_code: str) -> list[LineAnomaly]:
    """자산총계 ≠ 부채총계+자본총계 인 (basis, col_index) 를 표시한다.

    같은 표 안의 검산이라 SCE↔BS 대조보다 근거는 약하지만(다른 재무제표가 아니라 자기
    자신과의 산술), "부채와자본총계"(결합행)가 **따로** 존재하고 그게 자산과 일치하면
    분리행(부채총계/자본총계) 쪽에 확정적 근거가 생긴다 — 그 경우만 `suggested_value`
    (항등식이 함의하는 값)와 `classify_anomaly` 로 세분류해 confidence="high" 를 준다.
    결합행이 없거나 그것도 안 맞으면 "무언가 안 맞는다"만 낮은 신뢰도로 표시한다(추측 금지).

    반기/분기 포함 전체 report_fiscal_period 에 적용(SCE 대조와 달리 기간 매칭이 필요
    없는 같은 열 안 검산이라 FY 로 좁힐 이유가 없다).
    """
    out: list[LineAnomaly] = []
    cols = sorted({l.col_index for l in lines
                   if l.statement == "BS" and l.col_index is not None})
    for basis in ("consolidated", "separate"):
        for col in cols:
            rows = _bs_total_rows(lines, basis, col)
            assets, liab, equity = rows.get("assets"), rows.get("liab"), rows.get("equity")
            if assets is None or liab is None or equity is None:
                continue
            observed_sum = liab.value_won + equity.value_won
            diff = assets.value_won - observed_sum
            if abs(diff) <= max(2, abs(assets.value_won) * _TOL):
                continue
            combined = rows.get("combined")
            evidence_detail = (
                f"col{col} 자산총계 {assets.value_won:,} vs 부채총계+자본총계 {observed_sum:,}"
                f"(부채 {liab.value_won:,} + 자본 {equity.value_won:,}) diff {diff:,}")
            combined_confirms = (
                combined is not None
                and abs(combined.value_won - assets.value_won) <= max(2, abs(assets.value_won) * _TOL))
            if combined_confirms:
                evidence_detail += f" · 부채와자본총계 {combined.value_won:,}(자산과 일치)"
                reference = assets.value_won - equity.value_won   # 항등식이 함의하는 부채총계
                out.append(LineAnomaly(
                    rcept_no=rcept_no, corp_code=corp_code, statement="BS", basis=basis,
                    table_seq=liab.table_seq, row_order=liab.row_order, col_index=col,
                    label_raw=liab.label_raw, original_value=liab.value_won,
                    suggested_value=reference,
                    anomaly_kind=classify_anomaly(reference, liab.value_won),
                    evidence="bs_identity_confirmed", evidence_detail=evidence_detail,
                    confidence="high",
                ))
            else:
                out.append(LineAnomaly(
                    rcept_no=rcept_no, corp_code=corp_code, statement="BS", basis=basis,
                    table_seq=liab.table_seq, row_order=liab.row_order, col_index=col,
                    label_raw=liab.label_raw, original_value=liab.value_won,
                    suggested_value=None, anomaly_kind="OTHER",
                    evidence="bs_identity", evidence_detail=evidence_detail, confidence="low",
                ))
    return out


def detect_anomalies(lines, *, rcept_no: str, corp_code: str,
                     report_fiscal_period: str | None = None) -> list[LineAnomaly]:
    """statement 별 탐지기 집합 진입점."""
    return (
        detect_sce_anomalies(lines, rcept_no=rcept_no, corp_code=corp_code,
                             report_fiscal_period=report_fiscal_period)
        + detect_bs_identity_anomalies(lines, rcept_no=rcept_no, corp_code=corp_code)
    )


def store_anomalies(session, rcept_no: str, anomalies: list[LineAnomaly]) -> int:
    """rcept 단위 delete-then-insert — report_lines 재추출과 같은 재현성 규약."""
    from sqlalchemy import delete, insert
    from collector.models import ReportLineAnomaly

    session.execute(delete(ReportLineAnomaly).where(ReportLineAnomaly.rcept_no == rcept_no))
    if not anomalies:
        return 0
    session.execute(insert(ReportLineAnomaly).values([a.as_row() for a in anomalies]))
    return len(anomalies)
