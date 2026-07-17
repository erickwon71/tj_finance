"""Phase 4(PRD 15) · '비용의 성격별 분류' 주석 파서 — 총 D&A 복원 + 비용성격 주석 상세.

배경: 2024+ Track A(iXBRL) 전환으로 연결 CF 감가상각이 개별 ACODE 로 태깅되지 않아 연결
EBITDA 커버리지가 42% 천장에 막혔다(data-coverage-gaps 메모리). '비용의 성격별 분류' 주석은
**매출원가+판관비를 성격별로 재분류**하므로 감가상각비/무형자산상각비 라인이 **총액**으로 들어
있다(판관비 상세표의 부분 감가상각과 다름 — 실측 삼성 감가상각비 43.6조=총액). 이 표에서 D&A
를 뽑아 note.* 합성 fact 로 공급하면 기존 rules.rule_additive_da(_DEP_CANON/_DA_TOTAL_CANON 이
note.* 를 이미 소비)가 그대로 depreciation/amortization/da_total/ebitda 를 채운다(신규 배선 불필요).

실측 4사(2026-07-12) 레이아웃:
- 라벨열이 1~2개(삼성은 '성격별 비용' 그룹열 + 세부라벨 2열), 값열='공시금액' 1열, 당기/전기 별 표.
- 감가상각/무형상각을 **분리**(삼성·현대차: 감가상각비 / 무형자산상각비) 또는 **결합**(LG화학
  '감가상각비, 무형자산상각비' / S-Oil '감가상각비 및 무형자산 상각비')하는 두 형태 모두 대응.
- 단위 '(단위: 백만원/천원)' 표 스코프에서 감지 + 매출 앵커 단위보정(notes.py 관례) 안전망.

⚠ 중복합산 방지: cf_da 와 동일 note.* canonical 을 방출하므로, 호출측(expense_nature_sync)이
depreciation IS NULL 보고서만 대상으로 불러 이중 계상을 막는다(cf_da_sync 와 동일 가드).
acontext 는 cf_da 계열과 같은 'note:{basis}:col0' 을 재사용 — 같은 rcept 에 D&A note 는 최대
1세트만 존재(타겟팅 가드가 보장)하므로 충돌 시 ON CONFLICT 갱신으로 중복행이 생기지 않는다.
"""
from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import SEC_CONSOL_NOTE, SEC_SEP_NOTE
from fin2.extract.biz_section import expand_table_grid, _tag, _text
from fin2.extract.text import declared_unit
from fin2.extract.xbrl import ExtractedFact


def _norm(s: str) -> str:
    return s.replace(" ", "").replace("　", "").replace("\n", "")


def _parse_num(cell: str) -> int | None:
    """'43,605,740' / '(254,766)' → 정수(단위 미적용). 음수 괄호 처리. 아니면 None."""
    s = cell.strip().replace(",", "").replace(" ", "").replace("　", "")
    if not s or s in ("-", "─", "―", "—", "－"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if not s or not any(ch.isdigit() for ch in s):
        return None
    try:
        v = int(float(s))
    except ValueError:
        return None
    return -v if neg else v


# 헤딩 판별: '비용의 성격별 분류'(공백 무시). 연결/별도는 basis 로 구분.
_HEAD_KW = ("비용의성격별", "성격별로분류", "성격별분류")
# 데이터 표 판별 시그널(라벨). 2개 이상 + 숫자 있으면 성격별 비용 데이터 표.
_DATA_SIG = ("감가상각", "종업원급여", "급여", "원재료", "무형자산상각", "재고자산의변동",
             "상품의매입", "복리후생", "총영업비용", "성격별비용")
# 총계/설명 행(값열 있어도 스킵할 라벨).
_SKIP_LABEL = ("성격별비용합계", "총영업비용", "합계", "성격별비용", "비용의성격별분류에대한설명")


def _find_heading(els: list, basis: str) -> int | None:
    """basis 에 맞는 '비용의 성격별 분류' 헤딩 element index. 연결=('연결' 포함), 별도=('연결' 미포함)."""
    want_consol = (basis == "consolidated")
    cand = []
    for i, e in enumerate(els):
        if _tag(e) not in ("P", "SPAN", "TITLE"):
            continue
        t = _text(e)
        if len(t) > 60:
            continue
        n = _norm(t)
        if any(k in n for k in _HEAD_KW):
            has_consol = "연결" in t
            cand.append((i, has_consol))
    # 연결 원하면 '연결' 표기 우선, 별도 원하면 '연결' 없는 것 우선.
    for i, has_consol in cand:
        if has_consol == want_consol:
            return i
    # 폴백: 표기 구분이 없으면(단일 재무제표 회사) 첫 헤딩.
    return cand[0][0] if cand else None


def _find_data_table(els: list, start: int) -> tuple[list[list[str]], object] | None:
    """헤딩 다음 첫 '성격별 비용' 데이터 표(당기). ≥2 시그널 라벨 + 숫자 + ≤30행.

    반환 (grid, table_elem). **element 도 돌려주는 이유**: 단위 `(단위 : 백만원)` 는 grid 안이
    아니라 **직전 표제표**에 있다(DART [표제표, 데이터표] 쌍 구조). 실측 4사 전부 그렇다 —
    grid 만 넘기면 선언을 못 읽어 구버전처럼 '백만원 가정'으로 되돌아간다.
    """
    for j in range(start + 1, min(start + 100, len(els))):
        if _tag(els[j]) != "TABLE":
            continue
        try:
            grid = expand_table_grid(els[j])
        except Exception:  # noqa: BLE001
            continue
        if not grid or not (2 < len(grid) <= 30):
            continue
        flat = _norm(" ".join(c for row in grid for c in row))
        nsig = sum(1 for sg in _DATA_SIG if sg in flat)
        has_num = any(_parse_num(c) is not None for row in grid for c in row)
        if nsig >= 2 and has_num:
            return grid, els[j]
    return None


# 열 헤더의 당기/전기 표기(공백 제거 후). '당기말'·'당반기' 등 변형 포함.
_CURR_COL_RE = re.compile(r"^당(기|반기|분기)(말|초)?$")
_PRIOR_COL_RE = re.compile(r"^전(기|반기|분기)(말|초)?$")


def _current_col(grid: list[list[str]]) -> int | None:
    """헤더행에서 **당기 열**의 인덱스. 당기/전기 헤더가 없으면 None(=단일 공시금액 열 서식).

    ★ 왜 필요한가(2026-07-17 실측으로 발견한 오적재):
    구버전 `_row_label_value` 는 **가장 오른쪽 숫자셀**을 값으로 삼았다. 이 모듈의 설계 표본
    (2025 iXBRL 4사)은 값열이 '공시금액' **1열**이라 우연히 맞았지만, 구형 서식은
    `[구분 | 당기 | 전기]` **2열**이다 → 오른쪽 = **전기**.
      · 진양홀딩스 20160330000576: '무형자산상각비 | 18,607,826(당기) | 22,567,007(전기)'
        → 전기값을 채택하고도 context_fiscal_year 는 당기로 적어 **전년 D&A 를 당기로 적재**.
      · 유니트론텍 20160330001925: '감가상각비 | 85,182(당기) | 73,441(전기)' → 동일 오류.
    헤더가 '당기'라고 **명시**하는데 위치로 추측할 이유가 없다(계획 X4~X7: 열 위치 추론 금지).
    """
    for row in grid:
        for i, c in enumerate(row):
            if _CURR_COL_RE.match(_norm(c)):
                # '전기' 열도 함께 있어야 2열 서식으로 확정(단독 '당기' 표기는 캡션일 수 있음)
                if any(_PRIOR_COL_RE.match(_norm(x)) for x in row):
                    return i
    return None


def _row_label_value(row: list[str], curr_col: int | None = None) -> tuple[str | None, int | None]:
    """행에서 (세부라벨, 값).

    curr_col 이 주어지면 **그 열**을 값으로 쓴다(헤더가 확정한 당기 열).
    없으면(단일 값열 서식) 가장 오른쪽 숫자셀. 라벨 = 값 왼쪽의 가장 가까운 비숫자셀.
    """
    val = None
    val_idx = None
    if curr_col is not None:
        if curr_col < len(row):
            v = _parse_num(row[curr_col])
            if v is not None:
                val, val_idx = v, curr_col
        if val is None:
            return None, None       # 당기 열이 비면 그 행은 값 없음('-') — 추측해 채우지 않는다
    else:
        for idx in range(len(row) - 1, -1, -1):
            v = _parse_num(row[idx])
            if v is not None:
                val, val_idx = v, idx
                break
        if val is None:
            return None, None
    label = None
    for idx in range(val_idx - 1, -1, -1):
        c = row[idx].strip()
        if c and _parse_num(c) is None:
            label = c
            break
    return label, val


def _classify(label_norm: str) -> str | None:
    """정규화 라벨 → note canonical. 결합(감가상각+무형)은 da_total 직접."""
    has_dep = "감가상각" in label_norm
    has_amo = "무형자산상각" in label_norm or ("무형" in label_norm and "상각" in label_norm)
    if has_dep and has_amo:
        return "note.da_total"          # 결합 라인 = da_total 직접공시
    if has_amo:
        return "note.amortization"
    if "사용권자산상각" in label_norm or "사용권상각" in label_norm:
        return "note.rou_depreciation"
    if has_dep:
        return "note.depreciation"
    if "종업원급여" in label_norm:
        return "note.employee_benefits"
    if label_norm.startswith("급여"):     # 종업원급여 없을 때만 도달(급료와임금/급여)
        return "note.employee_benefits"
    if "원재료" in label_norm:
        return "note.raw_materials_used"
    return None


def _extract_one_basis(grid: list[list[str]], table_elem) -> dict[str, int] | None:
    """데이터 표 grid → {canonical: 값(원)}. **선언 단위만** 사용. 미선언/무의미 시 None(보류).

    ★ 2026-07-17(Phase A-3) — 추측 2종 제거:

    1) **단위 추측 폐지**. 구버전은 `_detect_unit_in_text` 로 표 텍스트를 훑되 **못 찾으면
       백만원(1e6)을 가정**하고, 그 위에 다시 배율 5종(1·10³·10⁻³·10⁶·10⁻⁶)을 대입해
       **da_total/매출 비율이 4% 에 가장 가까운 배율**을 골라 **표의 전 계정에 적용**했다.
       "그럴듯한 답 고르기"이며 배율을 기록하지 않아 역산도 불가능했다.
       ⟹ `(단위 : …)` **명시 선언만** 사용하고, 없으면 **보류**(결측 > 오염).

    2) **note.da_total 합성 폐지**(D8). 구버전은 감가상각비·무형자산상각비가 **따로** 공시된
       표에서도 `by_code["note.da_total"] = dep + amo` 로 **합계를 만들어** 넣었다. 그러면
       `rules.rule_additive_da` 가 이를 `_DA_TOTAL_CANON`(= **직접 공시된 합계**)으로 보고
       우선 채택해, 회사가 실제로 공시한 합계와 코드가 더한 값이 DB 에서 **구분되지 않았다**.
       ⟹ 결합 라인('감가상각비 및 무형자산상각비')이 **원문에 실재할 때만** note.da_total 을
       방출한다. 분리 공시면 구성요소만 내보내고 합산은 rule_additive_da 가 하게 둔다 —
       그쪽은 `applied_rules=['additive_da']` 로 **파생임이 기록**되는 투명한 경로다
       (계획 §2 원칙 3: 투명한 파생은 허용하되 표시 필수).
    """
    # 단위는 그 표가 명시 선언한 것만 인정 — 표제(직전형제) 또는 표 자기 첫행(text.declared_unit).
    # 실측: 4사 전부 표제표에 '(단위 : 백만원)' 이 있다.
    unit_mult = declared_unit(table_elem)
    if unit_mult is None:
        return None

    # 값 열: 헤더가 '당기/전기' 를 명시하면 그 당기 열, 아니면 단일 값열 서식.
    curr_col = _current_col(grid)

    by_code: dict[str, int] = {}
    for row in grid:
        label, val = _row_label_value(row, curr_col)
        if label is None or val is None:
            continue
        ln = _norm(label)
        if ln in _SKIP_LABEL or any(sk in ln for sk in ("합계", "총영업비용", "대한설명")):
            continue
        code = _classify(ln)
        if code is None:
            continue
        by_code[code] = by_code.get(code, 0) + val * unit_mult

    # 원문에 **결합 라인이 있을 때만** da_total 이 존재한다(_classify 가 note.da_total 부여).
    # 없으면 만들지 않는다 — dep/amo 를 그대로 내보내고 합산은 rule_additive_da 담당.
    dep = by_code.get("note.depreciation", 0) + by_code.get("note.rou_depreciation", 0)
    amo = by_code.get("note.amortization", 0)
    if not (by_code.get("note.da_total") or dep or amo):
        return None      # D&A 가 전무한 표 = 이 추출기의 대상이 아님
    return by_code


def extract_expense_nature_facts(
    file_path: str | Path, *, rcept_no: str, corp_code: str,
    report_fiscal_year: int, report_fiscal_period: str,
    basis: str = "consolidated",
) -> list[ExtractedFact]:
    """'비용의 성격별 분류' 주석 → note.* ExtractedFact(당기, col0). 실패/보류 시 []."""
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return []
    els = list(root.iter())
    hpos = _find_heading(els, basis)
    if hpos is None:
        return []
    found = _find_data_table(els, hpos)
    if found is None:
        return []
    grid, table_elem = found
    by_code = _extract_one_basis(grid, table_elem)
    if not by_code:
        return []

    # 이 추출기는 **주석**(비용의 성격별 분류)에서 읽는다 → section_kind 를 주석으로 명시.
    # note.* 만 방출하므로 "주석 섹션이 본문 canonical 을 만들지 않는다" 불변식과 정합.
    section_kind = SEC_CONSOL_NOTE if basis == "consolidated" else SEC_SEP_NOTE
    acontext = f"note:{basis}:col0"
    return [ExtractedFact(
        corp_code=corp_code, rcept_no=rcept_no,
        report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
        acode=code, basis=basis, context_fiscal_year=report_fiscal_year,
        col_index=0, period_kind=None, period_type=None, is_cumulative=True,
        extra_dims=None, is_dimensional=False, adecimal=None, amount_won=int(amt),
        source_format="note_expense", source_ref=f"{basis}/note_expense"[:180],
        acontext_raw=acontext, context_parsed=True, canonical_account=code,
        section_kind=section_kind,
        mapping_stage="exact",        # _classify 가 고정 키워드로 직접 판정(퍼지 아님)
        mapping_confidence=1.0,
        unit_source="declared",       # _extract_one_basis 가 미선언이면 이미 보류시킴
    ) for code, amt in by_code.items() if amt]
