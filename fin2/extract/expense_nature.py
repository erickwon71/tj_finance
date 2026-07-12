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

from math import log10
from pathlib import Path

from loguru import logger

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.note_extractor import _detect_unit_in_text
from fin2.extract.biz_section import expand_table_grid, _tag, _text
from fin2.extract.xbrl import ExtractedFact

# da_total/revenue 현실 범위(notes.py 와 동일 철학). 이 밖이면 단위오류로 간주.
_RATIO_LO, _RATIO_HI, _RATIO_TARGET = 3e-4, 2.0, 0.04
_FACTORS = (1.0, 1e3, 1e-3, 1e6, 1e-6)


def _norm(s: str) -> str:
    return s.replace(" ", "").replace("　", "").replace("\n", "")


def _unit_factor(da_total_won: int | None, revenue_ref: int | None) -> float | None:
    if not da_total_won or not revenue_ref or revenue_ref <= 0:
        return 1.0
    base = abs(da_total_won) / revenue_ref
    best = None
    for f in _FACTORS:
        ratio = base * f
        if _RATIO_LO <= ratio <= _RATIO_HI:
            dist = abs(log10(ratio) - log10(_RATIO_TARGET))
            if best is None or dist < best[0]:
                best = (dist, f)
    return best[1] if best else None


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


def _find_data_table(els: list, start: int) -> list[list[str]] | None:
    """헤딩 다음 첫 '성격별 비용' 데이터 표(당기). ≥2 시그널 라벨 + 숫자 + ≤30행."""
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
            return grid
    return None


def _row_label_value(row: list[str]) -> tuple[str | None, int | None]:
    """행에서 (세부라벨, 값). 값=가장 오른쪽 숫자셀, 라벨=값 왼쪽의 가장 구체적(가까운) 비숫자셀."""
    val = None
    val_idx = None
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


def _extract_one_basis(grid: list[list[str]], revenue_ref: int | None) -> dict[str, int] | None:
    """데이터 표 grid → {canonical: 값(원)}. 단위감지+매출앵커 보정. 실패 시 None."""
    # 표 스코프 텍스트에서 단위(백만원/천원) 감지 — grid 셀에 '(단위: ...)' 가 있을 수 있음.
    unit_text = " ".join(c for row in grid for c in row)
    unit_mult = _detect_unit_in_text(unit_text)   # 못 찾으면 1e6(백만원) 기본

    by_code: dict[str, int] = {}
    for row in grid:
        label, val = _row_label_value(row)
        if label is None or val is None:
            continue
        ln = _norm(label)
        if ln in _SKIP_LABEL or any(sk in ln for sk in ("합계", "총영업비용", "대한설명")):
            continue
        code = _classify(ln)
        if code is None:
            continue
        by_code[code] = by_code.get(code, 0) + val * unit_mult

    # da_total 계산(결합 라인 우선, 없으면 dep+amo+rou 합).
    da_direct = by_code.get("note.da_total")
    dep = by_code.get("note.depreciation", 0) + by_code.get("note.rou_depreciation", 0)
    amo = by_code.get("note.amortization", 0)
    da_total = da_direct if da_direct else (dep + amo if (dep or amo) else None)
    if not da_total:
        return None

    # 매출 앵커 단위보정 — 감지단위가 틀렸을 때 배율 재조정(notes.py 관례).
    factor = _unit_factor(da_total, revenue_ref)
    if factor is None:
        return None
    if factor != 1.0:
        by_code = {c: int(round(v * factor)) for c, v in by_code.items()}
        da_total = int(round(da_total * factor))

    # da_total 을 항상 명시(결합/분리 무관) — rules.rule_additive_da 가 우선 소비.
    by_code["note.da_total"] = da_total
    return by_code


def extract_expense_nature_facts(
    file_path: str | Path, *, rcept_no: str, corp_code: str,
    report_fiscal_year: int, report_fiscal_period: str,
    basis: str = "consolidated", revenue_ref: int | None = None,
) -> list[ExtractedFact]:
    """'비용의 성격별 분류' 주석 → note.* ExtractedFact(당기, col0). 실패 시 []."""
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return []
    els = list(root.iter())
    hpos = _find_heading(els, basis)
    if hpos is None:
        return []
    grid = _find_data_table(els, hpos)
    if grid is None:
        return []
    by_code = _extract_one_basis(grid, revenue_ref)
    if not by_code:
        return []

    acontext = f"note:{basis}:col0"
    return [ExtractedFact(
        corp_code=corp_code, rcept_no=rcept_no,
        report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
        acode=code, basis=basis, context_fiscal_year=report_fiscal_year,
        col_index=0, period_kind=None, period_type=None, is_cumulative=True,
        extra_dims=None, is_dimensional=False, adecimal=None, amount_won=int(amt),
        source_format="note_expense", source_ref=f"{basis}/note_expense"[:180],
        acontext_raw=acontext, context_parsed=True, canonical_account=code,
    ) for code, amt in by_code.items() if amt]
