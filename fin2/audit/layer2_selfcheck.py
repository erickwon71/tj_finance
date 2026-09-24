"""계층2 재적재 자동검산 — 사람이 원문과 대조하기 **전에** 기계가 잡을 수 있는 깨짐을 표시한다.

배경: 계층2 재적재 + 원문대조 검토 캠페인(사용자 결정 2026-09-08,
`docs/plans/layer2_reload_review_campaign_design_2026-09-08.md` §3). 검토 CSV 상단에
이 결과를 찍어, 사용자가 "의심" 항목부터 원문을 확인할 수 있게 한다.

## 설계 원칙 3가지

1. **계층2에는 canonical account 가 없다.** 그래서 판정 근거는 `label_raw` 정규식뿐이다
   (`account_mapper`/`concept_map` 을 부르지 않는다 — 그건 계층3 이고, 계층3 매핑 버그가
   계층2 검산을 오염시키면 검산의 독립성이 사라진다. `report_line_audit.py` 가 독립 리더를
   쓰는 것과 같은 이유).
2. **★R6 — 확정 못 하면 추측하지 않는다.** 근거 라벨을 못 찾으면 FAIL 이 아니라
   `NA`(판정불가)다. "자산총계 라벨이 없다"는 "대차가 안 맞는다"가 아니다.
3. **검산은 표시만 한다 — 진행을 막지 않는다.** 최종 판정은 사람의 원문 대조다(R9).
   그래서 verdict 는 차단/의심/참고 세 등급으로 나누되 어느 것도 파이프라인을 세우지 않고,
   `check_status` 롤업만 만들어 CSV 상단과 큐 테이블에 남긴다.

## 검산 목록

| code | 등급 | 내용 |
|---|---|---|
| `bs_balance`        | 차단 | 자산총계 = 부채총계 + 자본총계 (또는 부채와자본총계) |
| `cf_closing_cash`   | 차단 | 기초현금 + 영업 + 투자 + 재무 (+환율효과·매각예정재분류) = 기말현금 |
| `scope_presence`    | 차단 | 별도/연결 × BS/IS/CF 중 0행인 칸(형제 기간과 비교해 정상 결측과 구분) |
| `unit_sanity`       | 차단 | 단위를 확정 못해 금액이 공란으로 적재된 행 (단위 혼재는 정상이라 안 잡음) |
| `row_count_outlier` | 의심 | 같은 corp·basis·statement 의 다른 기간 행수 중앙값 대비 ±50% 이탈 |
| `duplicate_rows`    | 의심 | 같은 (statement,basis,table_seq) 안 라벨+값 완전중복(파서 이중 append 신호) |
| `bs_rollup`         | 참고 | 유동+비유동(+매각예정/소유주분배예정 처분자산집단) = 총계 (자산/부채) |
| `is_waterfall`      | 참고 | 매출액 − |매출원가| = 매출총이익 |

★2026-09-20 캠페인 오탐 일괄 수정 — 근거는
`docs/qa/layer2_review_campaign_issues_2026-09-20.md` 이슈 3~8·17~19·21~22.
셋 다 "원문 서식의 변형을 검산식이 못 따라간" 것이고, 파서 결함은 하나도 없었다.
공통 교훈: **표기 변형을 화이트리스트로 쫓지 말고, 성립하는 식을 여러 개 두고
먼저 맞는 것을 채택한다.** 억지로 하나의 식을 고집하면 어느 쪽 서식에서든 거짓 FAIL 이 난다.

`check_status` 롤업 = 차단 등급에 FAIL 이 하나라도 있으면 `suspect`,
전부 PASS/NA 면 `ok`, 판정 자체가 하나도 안 선 경우(행 0건 등) `na`.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass

from sqlalchemy import text

from parser.common.amount_normalizer import normalize_account_name

# 등급 — 롤업(check_status)에 반영되는지 여부를 가른다.
GRADE_BLOCKING = "차단"
GRADE_SUSPECT = "의심"
GRADE_INFO = "참고"

PASS = "PASS"
FAIL = "FAIL"
NA = "NA"

# 검산(항등식/이상치 등)이 다루는 본문 3종(사용자 범위, 2026-09-08). SCE/APPR 은
# 이 자동검산 대상 밖 — 항등식 성립 여부가 BS/CF처럼 단순하지 않다(자본변동표는
# 열=자본항목, 행=변동사유인 교차표라 이 파일의 라벨-앵커 방식이 그대로 안 맞는다).
STATEMENTS = ("BS", "IS", "CF")
BASES = ("separate", "consolidated")
BASIS_KO = {"separate": "별도", "consolidated": "연결"}
# ★STMT_KO 는 자동검산 범위(STATEMENTS)보다 넓다 — review_csv.py 가 대조용 CSV를
#   만들 때 SCE 표시 라벨로도 이 사전을 그대로 쓴다(R139 캠페인, 2026-09-18,
#   사용자 지시로 SCE도 브라우저 원문대조 대상에 포함). 자동검산은 여전히 SCE를
#   건드리지 않는다 — 최종 판정은 어차피 브라우저 대조(사람 눈과 같은 효과)다.
STMT_KO = {"BS": "재무상태표", "IS": "손익계산서", "CF": "현금흐름표", "SCE": "자본변동표"}

# 금액 일치 허용오차 — 원문이 천원/백만원 단위로 반올림돼 인쇄되면 합계가 표시단위 몇 칸
# 어긋나는 것은 원문 자체가 그런 것이다(파서 결함이 아니다). 표시단위 2칸까지 봐준다.
_ROUNDING_SLACK_UNITS = 2

_UNIT_NAME = {1: "원", 1000: "천원", 1000000: "백만원", 100000000: "억원",
              1000000000: "십억원", 1000000000000: "조원"}


@dataclass(frozen=True)
class CheckResult:
    """검산 1건. `scope` 는 사람이 읽는 범위 표기('[별도] 재무상태표' / '전체')."""
    code: str
    scope: str
    grade: str
    verdict: str      # PASS | FAIL | NA
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


# ── 라벨 사전 ─────────────────────────────────────────────────────────────────
# 원문 라벨은 회사마다 제각각이라 **정확일치가 아니라 정규식**으로 본다. 다만 넓게 잡으면
# 엉뚱한 행을 총계로 오인해 거짓 FAIL 을 만든다 — 거짓양성이 거짓음성보다 나쁘다(사람이
# 원문을 다시 열게 만드는 비용이 검산의 전부이므로). 그래서 앵커는 좁게 잡고, 못 찾으면 NA.
_RE_TOTAL_ASSETS = re.compile(r"^자산\s*총계$|^총자산$|^자산총액$")
_RE_TOTAL_LIAB = re.compile(r"^부채\s*총계$|^총부채$|^부채총액$")
_RE_TOTAL_EQUITY = re.compile(r"^자본\s*총계$|^총자본$|^자본총액$|^자기자본\s*총계$")
_RE_TOTAL_LIAB_EQUITY = re.compile(r"^부채\s*(?:및|과|와)?\s*자본\s*총계$|^자본\s*(?:및|과|와)\s*부채\s*총계$")
_RE_CURRENT_ASSETS = re.compile(r"^유동\s*자산$")
_RE_NONCURRENT_ASSETS = re.compile(r"^비유동\s*자산$")
_RE_CURRENT_LIAB = re.compile(r"^유동\s*부채$")
_RE_NONCURRENT_LIAB = re.compile(r"^비유동\s*부채$")
# ★유동/비유동 **밖의 제3의 BS 대분류.** IFRS5 매각예정·소유주분배예정(배당)으로 분류된
#   처분자산집단은 유동자산의 하위항목이 아니라 유동/비유동과 **나란한 대분류**로 인쇄돼
#   총계에 별도 가산된다(2026-09-20 실측: HD한국조선해양 20170515004618 별도
#   '소유주분배예정자산집단' 7,055,545,660천원 — 유동+비유동만 더하면 정확히 그 금액만큼
#   어긋난 거짓 FAIL 이 난다). 대분류로 인쇄된 것만 주워야 하므로 호출부가 **유동자산과
#   같은 depth·같은 section_path** 인 행으로 한정한다 — '매각예정비유동자산' 처럼 유동자산
#   **안에** 들어가는 동명 항목(depth 가 한 단계 깊다)을 이중계상하지 않기 위해서다.
_RE_BS_OTHER_TOP_GROUP = re.compile(
    r"^(?:매각예정|소유주분배예정|처분자산|중단영업).*(?:자산|부채)(?:집단|군)?$")

_RE_REVENUE = re.compile(r"^(?:매출액|매출|영업수익|수익\(매출액\))$")
_RE_COGS = re.compile(r"^매출\s*원가$")
_RE_GROSS_PROFIT = re.compile(r"^매출\s*총\s*(?:이익|손실|이익\(손실\))$")

# CF — '현금흐름' 표기는 회사마다 갈린다(영업활동현금흐름 / 영업활동으로인한현금흐름 /
# 영업활동으로 인한 현금흐름 …). 공백 제거 후 부분일치로 본다.
_RE_CF_OPERATING = re.compile(r"^(?:Ⅰ\.?)?영업활동.*현금흐름$")
_RE_CF_INVESTING = re.compile(r"^(?:Ⅱ\.?)?투자활동.*현금흐름$")
_RE_CF_FINANCING = re.compile(r"^(?:Ⅲ\.?)?재무활동.*현금흐름$")
# 기초/기말 잔액 — '반기말의 현금및현금성자산'·'분기말의…'·'현금및현금성자산의 기말잔액'
# 처럼 접두·어순이 제각각이라 **앵커 없이 부분일치**로 본다(`_find` 가 search 를 쓴다).
_RE_CF_OPENING = re.compile(r"기초.*현금|현금.*기초|期初")
_RE_CF_CLOSING = re.compile(r"기말.*현금|현금.*기말|期末")

# 환율효과 항 — ★'환율변동 효과 적용 후 현금및현금성자산의 증가(감소)' 는 환율효과가 아니라
#   **순증감 행**이다. 이걸 환율효과로 주우면 항등식이 그 금액만큼 어긋나 거짓 FAIL 이 난다
#   (2026-09-09 삼성전자 20260814003699 에서 실제로 재현). 증가/감소/순증감 토큰이 있으면 뺀다.
_RE_CF_FX_EFFECT = re.compile(r"환율변동|외화환산|외화표시|환율차이|환산효과|환율효과")
# 매각예정자산(처분자산군) 재분류 조정행 — IFRS5 로 매각예정 분류된 자회사/사업의 현금이
#   순증감 소계와 기말잔액 사이에 환율효과와 나란히 별도 인쇄된다(2026-09-12 SK스퀘어
#   20260514001477 실측: '매각예정자산에 포함된 현금및현금성자산' 50,934백만원 — 원문
#   ACODE=entity01596425_CashAndCashEquivalentsIncludedInDisposalGroupHeldForSaleOf…
#   확인. 이걸 안 더하면 정확히 그 금액만큼 어긋난 거짓 FAIL 이 난다).
_RE_CF_HFS_RECLASS = re.compile(r"매각예정.*현금|현금.*매각예정|처분자산군.*현금|현금.*처분자산군")
_RE_CF_NET_CHANGE_TOKEN = re.compile(r"증가|감소|순증감|증감")
# ★조정행의 부호가 **금액이 아니라 라벨에 있는** 서식이 있다 — DART 원문이
#   '매각예정자산 대체로 인한 현금의 감소' 를 괄호 없이 `9,137,925` 로 인쇄한다
#   (2026-09-20 원문 확인: SK이노베이션 20250318000862 연결, ACODE=…Decrease
#   InCashDueToReplacementOfAssetsHeldForSale…, ENG="Decrease in cash …").
#   그대로 더하면 정확히 그 금액의 2배만큼 어긋난 거짓 FAIL 이 난다.
#   '순증가(감소)' 처럼 증가/증감 토큰이 함께 있으면 부호는 금액 쪽에 있으므로 건드리지
#   않는다 — 실제로 '연결범위변동으로 인한 현금의 증감' 은 음수로 인쇄된다
#   (HMM 20161114002386 실측 -1,415백만).
_RE_CF_INCREASE_TOKEN = re.compile(r"증가|증감")
# 활동별 소계 — K-GAAP 구서식은 '영업활동으로 인한 현금의 증가' 처럼 쓰기도 해서,
# 순증감 소계를 고를 때 이걸 배제하지 않으면 활동 소계를 총증감으로 오인한다.
_RE_CF_ACTIVITY = re.compile(r"영업활동|투자활동|재무활동")
# '~로 인한' / '~에 따른' 은 **조정행의 문법**이다 — '외화환산으로 인한 현금의 증감',
# '연결범위 변동에 따른 현금감소분' 처럼. 진짜 순증감 소계는 이 연결어를 쓰지 않는다
# ('환율변동 효과 **적용 후** 현금및현금성자산의 증가(감소)' 는 '적용 후' 라 걸리지 않는다).
# 이걸 안 걸면 조정행을 총증감으로 오인해 그 금액만큼 어긋난 거짓 FAIL 이 난다
# (2026-09-09 실측: 20220516002148·20251114002182).
_RE_CF_CAUSAL = re.compile(r"으로인한|로인한|에따른|로인해")


def _norm(label: str) -> str:
    """라벨 정규화 — 주석번호·로마숫자 접두·전각공백을 걷어낸 뒤 공백까지 제거한다.

    계층3 의 `normalize_account_name` 을 재사용하되(주석번호 제거 규칙이 이미 R64 까지
    다듬어져 있다) 여기서는 **매핑이 아니라 앵커 탐색**이라 공백까지 지워 표기 흔들림
    ('매출 총이익' vs '매출총이익')을 흡수한다.
    """
    return re.sub(r"\s+", "", normalize_account_name(label or ""))


# ── 데이터 로딩 ───────────────────────────────────────────────────────────────
_ROWS_SQL = text(
    """
    SELECT rl.id, rl.statement, rl.basis, rl.table_seq, rl.row_order, rl.depth,
           rl.node_role, rl.section_path,
           rl.label_raw, rl.value_won, rl.value_raw, rl.adecimal, rl.unit_source,
           rl.header_hint, rl.col_index, rl.col_label,
           rt.unit_decl_raw, rt.declared_unit, rt.currency, rt.table_title
    FROM report_lines rl
    LEFT JOIN report_tables rt
           ON rt.rcept_no  = rl.rcept_no
          AND rt.statement = rl.statement
          AND rt.basis     = rl.basis
          AND rt.table_seq IS NOT DISTINCT FROM rl.table_seq
    WHERE rl.rcept_no = :r
    ORDER BY rl.statement, rl.basis, rl.table_seq NULLS FIRST, rl.row_order, rl.id
    """
    # ★rl.id 를 마지막 타이브레이커로 둔다 — row_order 가 여럿 NULL 인 행(EPS,
    # `_emit_eps_lines`)들 사이에서는 (statement,basis,table_seq,row_order) 가 전부
    # 동률이라 Postgres 가 순서를 보장하지 않는다(2026-09-09 실측: 삼성전자
    # 20260814003699 [연결] 손익계산서에서 기본/희석주당이익이 이 동률 때문에
    # 뒤바뀌어 나옴 — 사용자 원문대조로 발견). `store_report_lines()` 는 단일
    # multi-row INSERT 를 파이썬 리스트 순서 그대로 넣으므로(1340줄 부근) id 증가
    # 순서 = 추출기가 emit() 한 순서 = 원문 등장 순서. build_rows() 의 파이썬
    # sort() 는 stable 이라 이 SQL 순서를 그대로 보존한다.
)

# 같은 회사의 **다른 보고서** 행수 분포 — 이상치/범위 판정의 모집단.
#
# ★기간종류(FY/H1/Q1/Q3)뿐 아니라 **연도도 ±_SIBLING_YEARS 로 제한**한다. 안 그러면
#   2005년 K-GAAP 보고서를 2020년대 IFRS 보고서와 비교하게 돼, 그 시절엔 연결재무제표를
#   본문에 싣지도 않았다는 이유로 `scope_presence` 가 통째로 거짓 FAIL 을 낸다
#   (2026-09-09 표본 150건 실측: scope_presence FAIL 24건 중 상당수가 이 패턴).
#   행수 이상치도 마찬가지 — 서식이 시대별로 다르면 중앙값이 의미를 잃는다.
_SIBLING_YEARS = 3

_SIBLING_COUNTS_SQL = text(
    """
    SELECT rcept_no, statement, basis, count(*) AS n
    FROM report_lines
    WHERE corp_code = :c AND rcept_no <> :r
      AND statement = ANY(:stmts)
      AND report_fiscal_period = :fp
      AND report_fiscal_year BETWEEN :y0 AND :y1
    GROUP BY 1, 2, 3
    """
)


def load_rows(session, rcept_no: str) -> list[dict]:
    """그 rcept 의 report_lines 를 report_tables(단위 선언)와 조인해 전부 읽는다.

    ★CSV 생성기(`fin2/extract/review_csv.py`)와 **같은 함수를 공유**한다 — 검산이 본 것과
    사용자가 CSV 에서 본 것이 다르면 대조 자체가 무의미하기 때문.
    """
    return [dict(m) for m in session.execute(_ROWS_SQL, {"r": rcept_no}).mappings()]


# ── 개별 검산 ─────────────────────────────────────────────────────────────────
def _find(rows: list[dict], stmt: str, basis: str, pattern: re.Pattern) -> dict | None:
    """그 (statement, basis) 안에서 앵커 라벨 1개를 찾는다.

    ★후보가 여럿이면 **금액이 있는 마지막 행**을 쓴다 — BS 총계는 표 끝에 오고, 2표식
      (요약표 + 상세표)에서 앞의 것은 요약일 수 있다. 후보가 값까지 서로 다르면
      `None`(판정불가)로 돌려 R6 을 지킨다.
    """
    hits = [r for r in rows
            if r["statement"] == stmt and r["basis"] == basis
            and r["value_won"] is not None and pattern.search(_norm(r["label_raw"]))]
    if not hits:
        return None
    values = {r["value_won"] for r in hits}
    if len(values) > 1:
        return None      # 서로 다른 값의 동명 총계 — 고르지 않는다(R6)
    return hits[-1]


def row_unit(row: dict) -> int:
    """그 **행**의 표시 배수(원=1, 천원=1000 …) = 10^(-adecimal).

    ★`report_tables.declared_unit` 을 쓰지 않는다. 그 컬럼은 `store_report_tables()` 가
      표의 **첫 행 adecimal** 로 유도하는데, IS 는 EPS 행(`_emit_eps_lines`, adecimal=0)이
      먼저 방출돼 백만원 표를 `declared_unit=1` 로 잘못 적는다(2026-09-09 실측: 삼성전자
      20260814003699 IS 별도/연결 둘 다). 행의 adecimal 은 `value_won` 을 만든 바로 그
      값이라 표시금액과 절대 어긋나지 않는다.
    """
    ad = row.get("adecimal")
    return 10 ** (-ad) if ad is not None and ad <= 0 else 1


def _slack(rows: list[dict], stmt: str, basis: str) -> int:
    """표시단위 반올림 허용오차(원). 그 범위에서 가장 큰 표시 배수 × 2.

    원문이 백만원 단위로 반올림돼 인쇄되면 합계가 몇 백만원 어긋나는 것은 **원문이 그런
    것**이지 파서 결함이 아니다.
    """
    units = [row_unit(r) for r in rows
             if r["statement"] == stmt and r["basis"] == basis and r.get("value_won") is not None]
    return (max(units) if units else 1) * _ROUNDING_SLACK_UNITS


def _find_fx_effect(rows: list[dict], basis: str) -> tuple[dict | None, bool]:
    """CF 환율효과(또는 매각예정 재분류) 항 1개. 반환 (행 or None, 후보가 모호한가).

    '환율변동 효과 적용 후 … 증가(감소)' 같은 **순증감 행**을 배제한다 — 그건 환율효과가
    아니라 소계라, 더하면 항등식이 그 금액만큼 틀어져 거짓 FAIL 이 난다.
    후보가 서로 다른 값으로 여럿이면 고르지 않는다(R6) — 호출부가 NA 로 처리한다.
    """
    hits = [r for r in rows
            if r["statement"] == "CF" and r["basis"] == basis and r["value_won"] is not None
            and (_RE_CF_FX_EFFECT.search(_norm(r["label_raw"]))
                 or _RE_CF_HFS_RECLASS.search(_norm(r["label_raw"])))
            and not _RE_CF_NET_CHANGE_TOKEN.search(_norm(r["label_raw"]))]
    if not hits:
        return None, False
    if len({r["value_won"] for r in hits}) > 1:
        return None, True
    return hits[-1], False


def _fmt(n: int | None) -> str:
    return "―" if n is None else f"{n:,}"


def check_bs_balance(rows: list[dict]) -> list[CheckResult]:
    """자산총계 = 부채총계 + 자본총계. 회사가 '부채및자본총계'만 쓰면 그것과 대조."""
    out = []
    for basis in BASES:
        scope = f"[{BASIS_KO[basis]}] 재무상태표"
        assets = _find(rows, "BS", basis, _RE_TOTAL_ASSETS)
        if assets is None:
            if any(r["statement"] == "BS" and r["basis"] == basis for r in rows):
                out.append(CheckResult("bs_balance", scope, GRADE_BLOCKING, NA,
                                       "자산총계 라벨을 못 찾아 판정 불가"))
            continue
        liab = _find(rows, "BS", basis, _RE_TOTAL_LIAB)
        equity = _find(rows, "BS", basis, _RE_TOTAL_EQUITY)
        le = _find(rows, "BS", basis, _RE_TOTAL_LIAB_EQUITY)
        if liab is not None and equity is not None:
            rhs, rhs_desc = liab["value_won"] + equity["value_won"], "부채총계+자본총계"
        elif le is not None:
            rhs, rhs_desc = le["value_won"], "부채및자본총계"
        else:
            out.append(CheckResult("bs_balance", scope, GRADE_BLOCKING, NA,
                                   "부채총계/자본총계(또는 부채및자본총계) 라벨을 못 찾아 판정 불가"))
            continue
        diff = assets["value_won"] - rhs
        slack = _slack(rows, "BS", basis)
        verdict = PASS if abs(diff) <= slack else FAIL
        msg = (f"자산총계 {_fmt(assets['value_won'])} "
               f"{'=' if verdict == PASS else '≠'} {rhs_desc} {_fmt(rhs)}")
        if verdict == FAIL:
            msg += f" (차 {_fmt(diff)}원)"
        out.append(CheckResult("bs_balance", scope, GRADE_BLOCKING, verdict, msg))
    return out


def _doc_pos(row: dict) -> tuple[int, int]:
    """문서 내 위치 정렬키. table_seq/row_order 가 NULL 인 경로는 맨 앞으로."""
    return (row["table_seq"] if row["table_seq"] is not None else -1,
            row["row_order"] if row["row_order"] is not None else -1)


def _find_net_change(rows: list[dict], basis: str, closing: dict) -> dict | None:
    """CF '현금및현금성자산의 증가(감소)' 소계 행.

    ★환율효과 반영 **전/후** 두 개가 다 인쇄되는 서식이 있다. 그럴 땐 `_find` 처럼 보류하지
      않고 **기말 직전(문서상 가장 뒤)** 것을 고른다 — 정의상 그게 최종 순증감이다.
      '고르지 않는다'(R6)는 근거가 없을 때의 규칙이지, 문서 순서라는 명확한 근거가 있는
      선택까지 막는 규칙이 아니다.
    ★활동별 소계('영업활동으로 인한 현금의 증가' 같은 K-GAAP 표기)는 제외한다.
    """
    limit = _doc_pos(closing)
    cands = [r for r in rows
             if r["statement"] == "CF" and r["basis"] == basis and r["value_won"] is not None
             and "현금" in _norm(r["label_raw"])
             and _RE_CF_NET_CHANGE_TOKEN.search(_norm(r["label_raw"]))
             and not _RE_CF_ACTIVITY.search(_norm(r["label_raw"]))
             and not _RE_CF_CAUSAL.search(_norm(r["label_raw"]))
             and not _RE_CF_OPENING.search(_norm(r["label_raw"]))
             and not _RE_CF_CLOSING.search(_norm(r["label_raw"]))
             and _doc_pos(r) < limit]
    return max(cands, key=_doc_pos) if cands else None


def _fx_after(rows: list[dict], basis: str, net: dict, closing: dict) -> list[dict]:
    """순증감 소계 **뒤**, 기말 잔액 **앞**에 따로 인쇄된 조정행들(환율효과·매각예정 재분류).

    기초 행이 그 사이에 끼는 서식도 있어(20201116002012: 순증감 → 기초 → 환율효과 → 기말)
    상한은 기말 위치로 잡는다. 기초/기말 행 자체는 제외한다.
    """
    lo, hi = _doc_pos(net), _doc_pos(closing)
    return [r for r in rows
            if r["statement"] == "CF" and r["basis"] == basis and r["value_won"] is not None
            and lo < _doc_pos(r) < hi
            and (_RE_CF_FX_EFFECT.search(_norm(r["label_raw"]))
                 or _RE_CF_HFS_RECLASS.search(_norm(r["label_raw"])))
            and not _RE_CF_OPENING.search(_norm(r["label_raw"]))
            and not _RE_CF_CLOSING.search(_norm(r["label_raw"]))]


def _rows_after(rows: list[dict], basis: str, net: dict, closing: dict) -> list[dict]:
    """순증감 소계 뒤·기말 앞에 인쇄된 **모든** 행(기초/기말 행 자체는 제외).

    `_fx_after()` 가 라벨 화이트리스트(환율효과·매각예정재분류)로 좁게 줍는 데 비해, 이쪽은
    그 자리에 인쇄된 것은 전부 roll-forward 조정행이라고 본다. 화이트리스트로는 원문이
    쓰는 라벨 변형을 따라잡을 수 없다는 것이 실측으로 확인됐다 — 2026-09-20 캠페인에서만
    '기준서 변경으로 인한 효과'(한국전력 20180515002408)·'처분집단으로 분류된
    현금및현금성자산'(HMM 20171114002539)·'연결범위변동으로 인한 현금의 증감'(HMM
    20161114002386)·'중단영업 현금및현금성자산'(LS 20190401004913)·'매각예정자산으로의
    대체'(대한항공 20201116001718) 5종의 신규 라벨이 새로 나왔다.
    """
    lo, hi = _doc_pos(net), _doc_pos(closing)
    return [r for r in rows
            if r["statement"] == "CF" and r["basis"] == basis and r["value_won"] is not None
            and lo < _doc_pos(r) < hi
            and not _RE_CF_OPENING.search(_norm(r["label_raw"]))
            and not _RE_CF_CLOSING.search(_norm(r["label_raw"]))]


def _adjust_value(row: dict) -> int:
    """조정행이 roll-forward 에 기여하는 부호 있는 금액.

    라벨이 '…감소' 만 말하고 증가/증감 토큰이 없으면 **크기만큼 차감**이다 — 원문이 부호를
    금액이 아니라 라벨에 실어 쓰는 서식이 있기 때문(`_RE_CF_INCREASE_TOKEN` 주석의 SK
    이노베이션 사례). 원문이 같은 뜻을 괄호(음수)로 인쇄했다면 `-abs()` 는 그 값 그대로라
    두 서식 어느 쪽이든 같은 답이 나온다.
    """
    label = _norm(row["label_raw"])
    value = row["value_won"]
    if "감소" in label and not _RE_CF_INCREASE_TOKEN.search(label):
        return -abs(value)
    return value


def check_cf_closing_cash(rows: list[dict]) -> list[CheckResult]:
    """현금흐름표 항등식.

    두 갈래로 본다 — 강한 쪽을 먼저 쓴다:

    1. **기말 − 기초 = 순증감행** (차단 등급). 순증감 소계가 인쇄돼 있으면 이게 가장
       정확하다. 원문이 그 자리에 무엇을 넣었든(환율효과·연결범위변동·합병으로 인한 현금
       증가…) 이미 그 안에 들어 있기 때문이다.
    2. 순증감행이 없으면 **기초 + 영업 + 투자 + 재무 (+환율효과) = 기말** 로 폴백하되
       **의심 등급으로 낮춘다.** 이 식은 알려진 불완전성이 있다 — 연결범위변동·합병·
       사업양수도로 인한 현금 증감 같은 별도 조정행을 세지 않아 거짓 FAIL 이 난다
       (2026-09-09 표본 실측: 20120629000739 은 이 폴백에서 34억 어긋났지만
       'V. 현금의 증가' 소계로 보면 정확히 일치했다).

    ★순증감 소계와 기말 사이의 조정행은 환율효과만 있는 게 아니다 — IFRS5 매각예정
    분류(처분자산군)로 인한 현금 재분류행도 같은 자리에 별도로 찍힌다(2026-09-12
    SK스퀘어 20260514001477: '매각예정자산에 포함된 현금및현금성자산' 50,934백만원).
    `_fx_after()` 가 `_RE_CF_HFS_RECLASS` 로 이것도 같이 줍는다.
    """
    out = []
    for basis in BASES:
        scope = f"[{BASIS_KO[basis]}] 현금흐름표"
        if not any(r["statement"] == "CF" and r["basis"] == basis for r in rows):
            continue
        opening = _find(rows, "CF", basis, _RE_CF_OPENING)
        closing = _find(rows, "CF", basis, _RE_CF_CLOSING)
        if opening is None or closing is None:
            out.append(CheckResult("cf_closing_cash", scope, GRADE_BLOCKING, NA,
                                   "기초/기말 현금 라벨을 못 찾아 판정 불가"))
            continue
        slack = _slack(rows, "CF", basis)

        net = _find_net_change(rows, basis, closing)
        if net is not None:
            # ★순증감 소계가 **환율효과 반영 전**인 서식이 흔하다 — 그 경우 소계와 기말
            #   사이에 '외화표시 현금의 환율변동 효과'/'보유현금및현금성자산환산효과' 가
            #   따로 인쇄된다. 그 행을 안 더하면 정확히 그 금액만큼 어긋난 거짓 FAIL 이
            #   난다(2026-09-09 표본 실측: 이 한 가지로 FAIL 이 15→138 로 폭증했다).
            #   같은 자리에 IFRS5 매각예정(처분자산군) 현금 재분류행도 따로 찍히는
            #   서식이 있다(2026-09-12 SK스퀘어 20260514001477 실측).
            #   소계 **뒤에** 오는 조정행만 더한다 — 앞에 있으면 이미 소계에 포함됐다.
            # ★조정행을 "어떻게 세느냐"는 서식마다 달라서 **한 가지 식으로 못 맞춘다.**
            #   실측으로 확인된 서식이 세 갈래라(2026-09-20 캠페인) 아래 순서로 시도하고
            #   **먼저 맞는 것을 채택**한다. 셋 다 틀릴 때만 FAIL 이고, 그때는 가장 근접한
            #   식의 차이를 보고한다. 순서는 "더 강한 근거 먼저"다.
            #   ① 조정행 없음 — '기말 − 기초 = 순증감' 이 그대로 성립하면 그게 정답이다.
            #      순증감 소계가 이미 환율효과를 품고 있고, 환율효과 행은 그 안에 포함된
            #      금액을 참고로 다시 보여주는 **메모행**인 서식이 있다(2026-09-20 원문
            #      확인: 레인보우로보틱스 20230323000602 — 별도·연결 모두 3개 연도 열
            #      전부 '기초+순증감=기말' 로 재현되고 환율효과 행은 어느 열에서도
            #      가산되지 않는다). 이 행을 더하면 거꾸로 그 금액만큼 거짓 FAIL 이 난다.
            #   ② 환율효과/매각예정재분류만 가산 — 기존 동작(보수적 화이트리스트).
            #   ③ 소계~기말 사이 **모든** 행을 라벨 부호까지 반영해 가산 — 화이트리스트가
            #      못 따라잡는 신규 라벨을 통째로 흡수한다.
            tail_fx = _fx_after(rows, basis, net, closing)
            tail_all = _rows_after(rows, basis, net, closing)
            target = closing["value_won"] - opening["value_won"]
            variants = [
                ("", net["value_won"]),
                (f" + 조정행 {len(tail_fx)}행(환율효과/매각예정재분류)",
                 net["value_won"] + sum(f["value_won"] for f in tail_fx)),
                (f" + 소계~기말 사이 조정행 {len(tail_all)}행 전부",
                 net["value_won"] + sum(_adjust_value(r) for r in tail_all)),
            ]
            scored = [(abs(target - exp), desc, target - exp) for desc, exp in variants]
            hit = next((s for s in scored if s[0] <= slack), None)
            _, desc, diff = hit if hit is not None else min(scored)
            verdict = PASS if hit is not None else FAIL
            msg = (f"기말 {_fmt(closing['value_won'])} − 기초 {_fmt(opening['value_won'])} "
                   f"{'=' if verdict == PASS else '≠'} "
                   f"'{net['label_raw']}' {_fmt(net['value_won'])}{desc}")
            if verdict == FAIL:
                msg += f" (차 {_fmt(diff)}원 — 가장 근접한 식 기준)"
            out.append(CheckResult("cf_closing_cash", scope, GRADE_BLOCKING, verdict, msg))
            continue

        parts, missing = [], []
        for name, pat in (("영업", _RE_CF_OPERATING), ("투자", _RE_CF_INVESTING),
                          ("재무", _RE_CF_FINANCING)):
            hit = _find(rows, "CF", basis, pat)
            (parts if hit is not None else missing).append(hit if hit is not None else name)
        if missing:
            out.append(CheckResult("cf_closing_cash", scope, GRADE_BLOCKING, NA,
                                   f"순증감 소계도 {'/'.join(missing)}활동현금흐름도 못 찾아 판정 불가"))
            continue
        fx, fx_ambiguous = _find_fx_effect(rows, basis)
        if fx_ambiguous:
            out.append(CheckResult("cf_closing_cash", scope, GRADE_SUSPECT, NA,
                                   "환율효과 항 후보가 여럿이라 판정 불가(추측하지 않음)"))
            continue
        total = opening["value_won"] + sum(p["value_won"] for p in parts)
        if fx is not None:
            total += fx["value_won"]
        diff = closing["value_won"] - total
        verdict = PASS if abs(diff) <= slack else FAIL
        msg = (f"[순증감 소계 없음, 성분합 폴백] 기초 + 영업/투자/재무"
               f"{' + 환율효과' if fx is not None else ''} "
               f"{'=' if verdict == PASS else '≠'} 기말 {_fmt(closing['value_won'])}")
        if verdict == FAIL:
            msg += (f" (차 {_fmt(diff)}원 — 연결범위변동·합병 등 별도 조정행이 있으면 "
                    f"이 식으로는 안 맞는다)")
        out.append(CheckResult("cf_closing_cash", scope, GRADE_SUSPECT, verdict, msg))
    return out


def check_scope_presence(rows: list[dict], sibling_scopes: set[tuple[str, str]] | None) -> list[CheckResult]:
    """별도/연결 × BS/IS/CF 6칸 중 비어 있는 칸.

    ★연결재무제표가 **원래 없는 회사**(종속기업 없음)가 많다 — 그건 정상 결측이지 결함이
      아니다. 그래서 같은 회사·같은 기간종류의 **다른 보고서에는 있었는데 이번엔 없는** 칸만
      FAIL 로 올린다. 형제 표본이 없으면 판정하지 않는다(R6).
    """
    present = {(r["statement"], r["basis"]) for r in rows if r["statement"] in STATEMENTS}
    have = sorted(f"[{BASIS_KO[b]}]{s}" for s, b in present if b in BASIS_KO)
    if sibling_scopes is None:
        return [CheckResult("scope_presence", "전체", GRADE_BLOCKING, NA,
                            f"형제 보고서가 없어 정상 결측과 구분 불가 (현재: {', '.join(have) or '없음'})")]
    missing = sorted(sibling_scopes - present)
    if not missing:
        return [CheckResult("scope_presence", "전체", GRADE_BLOCKING, PASS,
                            f"형제 보고서가 가진 범위를 모두 보유 ({', '.join(have)})")]
    desc = ", ".join(f"[{BASIS_KO.get(b, b)}]{s}" for s, b in missing)
    return [CheckResult("scope_presence", "전체", GRADE_BLOCKING, FAIL,
                        f"형제 보고서엔 있는데 이번엔 0행: {desc}")]


def check_unit_sanity(rows: list[dict]) -> list[CheckResult]:
    """단위를 확정하지 못해 금액이 비어버린 행이 있는가.

    R4 대로 단위 미확정은 값이 NULL 로 남으므로 유실이지 오염은 아니다 — 그래도 사람이
    원문을 볼 때 "여기 숫자가 왜 비었나"를 미리 알아야 한다.

    ★한 재무제표 안에서 단위가 **섞이는 것은 정상**이다 — 이걸 결함으로 잡지 않는다.
      실제 서식이 "(단위: 백만원, 주당손익: 원)" 처럼 찍고, R4 자체가 "단위는 표가 아니라
      **열** 단위로 판정한다"이다. 처음엔 statement 안 단위 혼재를 FAIL 로 잡았다가
      삼성전자 20260814003699 에서 EPS 행 때문에 즉시 거짓양성이 나 걷어냈다.
    """
    body = [r for r in rows if r["statement"] in STATEMENTS]
    if not body:
        return [CheckResult("unit_sanity", "전체", GRADE_BLOCKING, NA, "본문 행 0건")]
    undet = [r for r in body if (r["unit_source"] or "") in ("undetermined", "undeclared")]
    if not undet:
        kinds = sorted({r["unit_source"] for r in body if r["unit_source"]})
        units = sorted({row_unit(r) for r in body if r.get("value_won") is not None})
        shown = "/".join(_UNIT_NAME.get(u, f"×{u:,}") for u in units)
        return [CheckResult("unit_sanity", "전체", GRADE_BLOCKING, PASS,
                            f"단위 전부 확정 ({shown}; unit_source={'/'.join(kinds)})")]
    sample = ", ".join(f"'{r['label_raw']}'" for r in undet[:3])
    return [CheckResult("unit_sanity", "전체", GRADE_BLOCKING, FAIL,
                        f"단위 미확정 {len(undet)}행 — 금액이 공란으로 적재됨: {sample}"
                        + (" 외" if len(undet) > 3 else ""))]


def check_duplicate_rows(rows: list[dict]) -> list[CheckResult]:
    """같은 (statement,basis,table_seq) 안에서 라벨+값이 완전중복 = 파서 이중 append 신호.

    근거: R4-2 함정 — 병합표 폴백을 가드 없이 걸면 같은 표가 두 번 적재된다.
    ★★키에 **`section_path`(위치)를 반드시 넣는다.** 계층2 는 "위치가 다르면 서로 다른
      행"이라 같은 라벨을 병합하지 않는다(`collector/models.py:ReportLine` docstring).
      실제로 라벨+값만으로 키를 잡았더니 표본 150건에서 21%가 걸렸고, 확인해보니 전부
      정상이었다 — '매도가능금융자산' 300,000,000 이 `자산>유동자산` 과 `자산>비유동자산`
      에 각각(20140530001276), '비지배지분' 0 이 `당기순이익의 귀속` 과 `총포괄손익의
      귀속` 에 각각(20260327000210). 진짜 이중 append 는 표가 통째로 반복되므로
      section_path 까지 같아 이 키로도 그대로 잡힌다.

    ★★값이 **0 인 행은 세지 않는다.** 0 은 서로 다른 항목끼리도 흔히 겹쳐, 라벨까지
      우연히 같으면 "완전중복" 으로 오판된다 — 2026-09-20 원문 확인: 레인보우로보틱스
      20230323000602 연결 CF 는 원문 자체가 '전환우선주의 발행' 행을 두 번 쓰는데
      (둘째는 실제로는 유상증자 28,306,586,760 의 오기재) **당기 열만** 둘 다 0 이라
      걸렸다. 진짜 이중 append 는 표가 통째로 반복되므로 0 아닌 행에서도 그대로 잡힌다.
    """
    seen: dict[tuple, int] = {}
    body = 0
    for r in rows:
        if r["statement"] not in STATEMENTS or not r["value_won"]:
            continue        # value_won 이 None 이거나 0 인 행은 중복 판정에서 뺀다
        body += 1
        key = (r["statement"], r["basis"], r["table_seq"], r["section_path"],
               _norm(r["label_raw"]), r["value_won"])
        seen[key] = seen.get(key, 0) + 1
    dups = {k: n for k, n in seen.items() if n > 1}
    if not dups:
        return [CheckResult("duplicate_rows", "전체", GRADE_SUSPECT, PASS, "완전중복 행 없음")]
    sample = sorted(dups.items(), key=lambda kv: -kv[1])[:3]
    desc = "; ".join(f"[{BASIS_KO.get(k[1], k[1])}]{k[0]} '{k[4]}' ×{n}" for k, n in sample)
    # ★중복이 **몇 행을 덮는지**를 같이 적는다 — 이중 append 는 표가 통째로 반복되므로
    #   비중이 크고, 원문 자체의 라벨 중복(2026-09-20 한진칼 20230515002432 별도 IS
    #   '기본주당우선주순이익' ×2 — 원문 확인 완료)은 한두 행에 그친다. 이 둘은 당기 열
    #   값만으로는 원리적으로 구분되지 않으므로(비교연도 열은 report_lines 에 없다)
    #   억누르지 않고 **어디를 볼지**만 알려준다.
    affected = sum(dups.values())
    share = f"{affected}/{body}행" if body else "―"
    return [CheckResult("duplicate_rows", "전체", GRADE_SUSPECT, FAIL,
                        f"라벨+값 완전중복 {len(dups)}종({share}) — {desc}")]


def check_row_count_outlier(rows: list[dict], sibling_counts: dict) -> list[CheckResult]:
    """같은 회사·같은 기간종류의 다른 보고서 행수 중앙값 대비 ±50% 이탈.

    방법은 `docs/qa/report_lines_row_count_outlier_scan_2026-09-08.md` 와 같다 —
    그쪽은 전사 IQR, 여기는 **같은 회사 안**이라 모집단이 훨씬 동질적이다.
    """
    out = []
    mine: dict[tuple[str, str], int] = {}
    for r in rows:
        if r["statement"] in STATEMENTS:
            mine[(r["statement"], r["basis"])] = mine.get((r["statement"], r["basis"]), 0) + 1
    hits = []
    for (stmt, basis), n in sorted(mine.items()):
        peers = sibling_counts.get((stmt, basis))
        if not peers or len(peers) < 3:
            continue        # 표본 3건 미만이면 중앙값이 의미 없다 — 판정하지 않는다
        med = statistics.median(peers)
        if med and (n < med * 0.5 or n > med * 1.5):
            hits.append(f"[{BASIS_KO.get(basis, basis)}]{stmt} {n}행 (동일회사 중앙값 {med:.0f})")
    if not mine:
        return [CheckResult("row_count_outlier", "전체", GRADE_SUSPECT, NA, "본문 행 0건")]
    if not hits:
        return [CheckResult("row_count_outlier", "전체", GRADE_SUSPECT, PASS,
                            "행수 분포 정상")]
    return [CheckResult("row_count_outlier", "전체", GRADE_SUSPECT, FAIL,
                        "; ".join(hits))]


def _bs_other_top_groups(rows: list[dict], basis: str,
                         cur: dict, non: dict, tot: dict) -> list[dict]:
    """유동/비유동과 **나란한** 제3의 대분류 행들(매각예정·소유주분배예정 처분자산집단 등).

    유동자산과 `depth`·`section_path` 가 같고 총계보다 앞에 인쇄된 것만 줍는다 —
    '매각예정비유동자산' 처럼 유동자산 **안에** 들어가는 동명 항목은 depth 가 한 단계
    깊어 여기 걸리지 않는다(걸리면 이중계상이 된다).
    """
    anchors = {id(cur), id(non), id(tot)}
    limit = _doc_pos(tot)
    return [r for r in rows
            if r["statement"] == "BS" and r["basis"] == basis and r["value_won"] is not None
            and id(r) not in anchors
            and r["depth"] == cur["depth"] and r["section_path"] == cur["section_path"]
            and _doc_pos(r) < limit
            and _RE_BS_OTHER_TOP_GROUP.search(_norm(r["label_raw"]))]


def check_bs_rollup(rows: list[dict]) -> list[CheckResult]:
    """유동+비유동 = 총계 (자산/부채). 참고 등급 — 금융업은 유동/비유동 구분 자체가 없다."""
    out = []
    for basis in BASES:
        scope = f"[{BASIS_KO[basis]}] 재무상태표"
        for kind, cur_re, non_re, tot_re in (
            ("자산", _RE_CURRENT_ASSETS, _RE_NONCURRENT_ASSETS, _RE_TOTAL_ASSETS),
            ("부채", _RE_CURRENT_LIAB, _RE_NONCURRENT_LIAB, _RE_TOTAL_LIAB),
        ):
            cur, non, tot = (_find(rows, "BS", basis, p) for p in (cur_re, non_re, tot_re))
            if cur is None or non is None or tot is None:
                continue        # 금융업 등 — 판정 대상 아님(NA 조차 찍지 않는다, 소음)
            slack = _slack(rows, "BS", basis)
            others = _bs_other_top_groups(rows, basis, cur, non, tot)
            # 유동/비유동 2항만으로 맞으면 그걸 채택한다(기존 동작). 안 맞을 때만 제3의
            # 대분류를 더해 다시 본다 — 둘 중 하나라도 맞으면 PASS.
            strict = tot["value_won"] - (cur["value_won"] + non["value_won"])
            extended = strict - sum(o["value_won"] for o in others)
            if abs(strict) <= slack:
                verdict, diff, extra = PASS, strict, ""
            elif others and abs(extended) <= slack:
                verdict, diff = PASS, extended
                extra = "+" + "+".join(f"'{o['label_raw']}'" for o in others)
            else:
                verdict = FAIL
                diff, extra = ((extended, "+" + "+".join(f"'{o['label_raw']}'" for o in others))
                               if others and abs(extended) < abs(strict) else (strict, ""))
            msg = (f"유동{kind}+비유동{kind}{extra} "
                   f"{'=' if verdict == PASS else '≠'} {kind}총계")
            if verdict == FAIL:
                msg += f" (차 {_fmt(diff)}원)"
            out.append(CheckResult("bs_rollup", scope, GRADE_INFO, verdict, msg))
    return out


def check_is_waterfall(rows: list[dict]) -> list[CheckResult]:
    """매출액 − 매출원가 = 매출총이익. 참고 등급 — 매출총이익을 안 쓰는 서식이 많다.

    ★매출원가의 **부호 표기는 회사마다 갈린다.** 괄호(음수)로 인쇄하는 회사가 적지 않고
      (2026-09-20 실측: POSCO홀딩스 20251114002479 −48,116,109,522,197 / LG화학
      20240315000957 별도·연결 / 한미반도체 20241114002196 별도·연결), 파서는 원문대로
      적재한다. 부호를 안 보고 늘 빼면 정확히 `2 × 매출원가` 만큼 어긋난 거짓 FAIL 이
      난다 — 위 5건의 보고 차이가 전부 이 값과 원 단위까지 일치했다. 매출원가는 비용이라
      표기 부호와 무관하게 **크기만큼 차감**이므로 `abs()` 를 쓴다.
    """
    out = []
    for basis in BASES:
        rev, cogs, gp = (_find(rows, "IS", basis, p)
                         for p in (_RE_REVENUE, _RE_COGS, _RE_GROSS_PROFIT))
        if rev is None or cogs is None or gp is None:
            continue
        diff = gp["value_won"] - (rev["value_won"] - abs(cogs["value_won"]))
        slack = _slack(rows, "IS", basis)
        verdict = PASS if abs(diff) <= slack else FAIL
        msg = (f"매출액−매출원가{'(원문 음수표기)' if cogs['value_won'] < 0 else ''} "
               f"{'=' if verdict == PASS else '≠'} 매출총이익")
        if verdict == FAIL:
            msg += f" (차 {_fmt(diff)}원)"
        out.append(CheckResult("is_waterfall", f"[{BASIS_KO[basis]}] 손익계산서",
                               GRADE_INFO, verdict, msg))
    return out


# ── 오케스트레이션 ────────────────────────────────────────────────────────────
def _sibling_stats(session, corp_code: str, rcept_no: str, fiscal_period: str,
                   fiscal_year: int | None):
    """같은 회사·같은 기간종류(FY/H1/Q1/Q3)의 다른 보고서에서 뽑은 모집단.

    반환: (범위집합 or None, {(stmt,basis): [행수, ...]})
    기간종류를 맞추는 이유 — 사업보고서와 분기보고서는 행수 스케일이 다르다.
    """
    fy = fiscal_year or 0
    peers = session.execute(_SIBLING_COUNTS_SQL, {
        "c": corp_code, "r": rcept_no, "stmts": list(STATEMENTS), "fp": fiscal_period,
        "y0": fy - _SIBLING_YEARS, "y1": fy + _SIBLING_YEARS,
    }).fetchall()
    if not peers:
        return None, {}
    counts: dict[tuple[str, str], list[int]] = {}
    per_rcept: dict[str, set[tuple[str, str]]] = {}
    for p in peers:
        counts.setdefault((p.statement, p.basis), []).append(p.n)
        per_rcept.setdefault(p.rcept_no, set()).add((p.statement, p.basis))
    # 범위 기대치 = 형제 보고서 **과반**이 가진 범위. 한 건만 가진 범위는 그쪽이 이상치일
    # 수 있으므로 기대치로 삼지 않는다.
    tally: dict[tuple[str, str], int] = {}
    for scopes in per_rcept.values():
        for s in scopes:
            tally[s] = tally.get(s, 0) + 1
    expected = {s for s, n in tally.items() if n * 2 > len(per_rcept)}
    return expected, counts


def run_checks(session, rcept_no: str, *, corp_code: str, fiscal_period: str,
               fiscal_year: int | None = None,
               rows: list[dict] | None = None) -> list[CheckResult]:
    """그 rcept 의 적재 결과에 검산 8종을 전부 돌린다.

    `rows` 를 넘기면 재조회하지 않는다 — CSV 생성기가 이미 읽어둔 것을 그대로 쓰기 위해서.
    """
    if rows is None:
        rows = load_rows(session, rcept_no)
    expected_scopes, sibling_counts = _sibling_stats(session, corp_code, rcept_no,
                                                     fiscal_period, fiscal_year)
    results: list[CheckResult] = []
    results += check_bs_balance(rows)
    results += check_cf_closing_cash(rows)
    results += check_scope_presence(rows, expected_scopes)
    results += check_unit_sanity(rows)
    results += check_row_count_outlier(rows, sibling_counts)
    results += check_duplicate_rows(rows)
    results += check_bs_rollup(rows)
    results += check_is_waterfall(rows)
    return results


def rollup(results: list[CheckResult]) -> str:
    """check_status 롤업 — 차단 등급에 FAIL 이 하나라도 있으면 suspect."""
    blocking = [r for r in results if r.grade == GRADE_BLOCKING]
    if any(r.verdict == FAIL for r in blocking):
        return "suspect"
    if not blocking or all(r.verdict == NA for r in blocking):
        return "na"
    return "ok"


def suspects(results: list[CheckResult]) -> list[CheckResult]:
    """사람이 먼저 봐야 할 것 — 등급 무관 FAIL 전부(참고 등급 FAIL 도 단서는 된다)."""
    return [r for r in results if r.verdict == FAIL]
