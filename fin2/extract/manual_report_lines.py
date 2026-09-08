"""수동(사람이 원문을 눈으로 읽고 입력한) `report_lines` 적재 — 자동추출(pdf/html/xbrl)이 신뢰할
수 없는 필링을 위한 **최후 수단** 입력 경로(2026-09-07, 사용자 지시).

계기: YBM넷(00307222) FY2002 반기(rcpNo=20020814000872) 별도 대차대조표/손익계산서가 DART
원문 자체에서 항목명·값 줄바꿈이 유실돼(`<BR>` 세그먼트 수가 라벨열과 값열마다 다 다름 —
docs/plans/html_viewer_extractor_design_2026-09-07.md §8-18) 자동추출로는 안전하게 복구 불가능
하다고 확인됨. 이런 필링은 사람이 DART 원문을 직접 보고 항목을 하나씩 CSV에 타이핑해 채운다.

CSV → `ReportLineRow` 로 변환해 `report_lines`에 `unit_source='manual'`로 적재하면, 이후
(account_mapper·std_v3 등) 파이프라인은 pdf/html/xbrl과 똑같이 취급한다 — 이 소스만을 위한
특수 처리를 계층3 이후에 두지 않는다(기존 소스 다변화 패턴 재사용, `unit_source` in
{pdf,html,xbrl,declared,...}에 'manual' 하나 추가하는 것뿐).

★ `store_report_lines()`(fin2/extract/report_lines.py)는 rcept_no **전체**를 delete-then-insert
한다 — 자동추출은 한 번에 한 필링을 통째로 재생성하는 게 자연스럽기 때문. 수동입력은 반대다:
한 필링 안에서 BS/IS만 사람이 채우고 CF는 이미 자동추출이 맞게 넣어놨을 수 있다(YBM넷이 정확히
이 경우 — CF 15행이 unit_source='pdf'로 이미 있음, 원문대조 결과 이마저 신뢰 불가로 확인됐지만
다른 필링에서는 부분적으로 정상일 수 있다). 그래서 이 모듈의 delete-then-insert 스코프는
**(rcept_no, statement, basis)** 로 좁힌다.

CSV 형식(UTF-8, 헤더 필수): rcept_no,statement,basis,label_raw,value_raw[,unit][,depth]
  - rcept_no: DART 접수번호(14자). `filings` 테이블에 이미 있어야 한다(corp_code/회계연도/기간을
    거기서 자동으로 가져온다 — 사용자가 매번 타이핑할 필요 없게).
    ★엑셀 함정: 14자리 숫자열을 엑셀이 지수표기(`2.00208E+13`)로 바꿔버려서 그대로 저장하면
    접수번호가 깨진다(2026-09-07 실측). 그래서 review CSV를 생성할 때 이 컬럼을 엑셀 텍스트
    강제 트릭 `="20020814000872"` 형태로 감싸 둔다 — `unwrap_excel_text()`가 읽을 때 원래
    문자열로 되돌린다(감싸지 않은 평범한 값도 그대로 통과).
  - statement: BS/IS/CF/SCE/APPR 또는 한글(재무상태표·대차대조표/손익계산서/현금흐름표/
    자본변동표/이익잉여금처분계산서 등).
  - basis: separate/consolidated 또는 별도/연결.
  - label_raw: 원문에 인쇄된 항목명 그대로(정규화는 계층3 account_mapper가 한다 — 여기선 안 함).
  - value_raw: 원문에 인쇄된 값 그대로(콤마·괄호음수·"(-)"·"-"(공란) 다 허용 — `parse_amount()`
    재사용). 공란이면 결측으로 적재(값을 지어내지 않는다).
  - unit(선택, 기본 "원"): "원"/"천원"/"백만원" 등 — 표 상단에 적힌 단위 그대로.
  - depth(선택, 기본 0): 들여쓰기 깊이를 안다면. 모르면 비워도 된다(구조 주장 안 함).

당기(col_index=0)만 지원한다 — 자동추출 경로(`store_report_lines`)와 동일 범위.

★ CSV 파일 저장 위치: `manual_review/<시장>/<corp_code>_<회사명>/<report_type>/<연도>/
<rcept_no>_manual_review.csv`(프로젝트 로컬, `.gitignore` 대상 — `raw_report/`와 같은 하위구조를
미러링해서 원본 위치를 헷갈리지 않게 하되 실제 파일은 로컬 디스크에 둔다). **원본 XML이 있는
SD카드(`raw_report/`, 예: `/Volumes/dart_data/...`)에는 만들지 않는다** — 2026-09-07 실측:
맥 오피스 365가 외장/이동식 볼륨의 파일을 "보호된 보기"로 열어 편집을 막고, `xattr -c`로
지워도 다시 열 때마다 재발했다(파일이 아니라 볼륨 자체를 오피스가 못 미더워함).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass

from parser.common.amount_normalizer import detect_unit_multiplier, parse_amount

from fin2.extract.report_lines import ReportLineRow, _TABLE_LEVEL_COLS
from fin2.extract.text import _adecimal_from_unit

STATEMENT_ALIASES = {
    "BS": "BS", "재무상태표": "BS", "대차대조표": "BS",
    "IS": "IS", "손익계산서": "IS",
    "CF": "CF", "현금흐름표": "CF",
    "SCE": "SCE", "자본변동표": "SCE",
    "APPR": "APPR", "이익잉여금처분계산서": "APPR", "결손금처리계산서": "APPR",
    "이익잉여금처분계산서또는결손금처리계산서": "APPR",
}
BASIS_ALIASES = {
    "separate": "separate", "별도": "separate",
    "consolidated": "consolidated", "연결": "consolidated",
}
REQUIRED_COLUMNS = ("rcept_no", "statement", "basis", "label_raw", "value_raw")


class ManualCsvError(ValueError):
    """CSV 형식/값 오류 — 몇 번째 줄이 왜 잘못됐는지 사람이 바로 고칠 수 있게 메시지를 만든다."""


@dataclass(frozen=True)
class FilingMeta:
    """rcept_no 하나가 어느 회사·어느 회계연도/기간인지(`filings` 테이블 조회 결과).

    이 모듈의 순수 로직(`build_manual_report_lines`)이 DB에 의존하지 않도록 호출부가 미리 조회해
    주입한다 — `fin2/tests/test_reconcile_store.py`와 같은 관례("session.execute는 얇은 바깥쪽
    호출부로 미루고 안쪽은 순수함수로 테스트한다")."""
    corp_code: str
    fiscal_year: int
    fiscal_period: str


_EXCEL_TEXT_WRAP_RE = re.compile(r'^="(.*)"$')


def unwrap_excel_text(raw: str) -> str:
    """엑셀이 긴 숫자열(rcept_no 등)을 지수표기(`2.00208E+13`)로 바꿔버리는 걸 막으려고
    CSV 생성 시 `="20020814000872"` 형태(엑셀 수식 트릭)로 감싸 둔 값을 원래 문자열로 되돌린다.
    감싸지 않은 평범한 값은 그대로 통과— 엑셀을 안 거친 CSV/재실행에도 안전."""
    m = _EXCEL_TEXT_WRAP_RE.match(raw)
    return m.group(1) if m else raw


def _normalize_choice(raw: str, aliases: dict[str, str], field: str, line_no: int) -> str:
    key = (raw or "").strip()
    if key not in aliases:
        allowed = sorted(set(aliases.values()))
        raise ManualCsvError(f"line {line_no}: unknown {field} {raw!r} (allowed: {allowed}, or its Korean alias)")
    return aliases[key]


def read_manual_csv(csv_path: str) -> list[dict]:
    """CSV 파일 → dict 행 리스트. 헤더 검증만 하고 의미 해석(별칭 변환·금액 파싱)은
    `build_manual_report_lines()`가 한다."""
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ManualCsvError(f"CSV header missing required column(s): {missing}")
        return list(reader)


def build_manual_report_lines(
    csv_rows: list[dict], filing_lookup: dict[str, FilingMeta],
) -> list[ReportLineRow]:
    """csv_rows(`read_manual_csv()` 결과) + rcept_no→FilingMeta 매핑 → `ReportLineRow` 리스트.

    row_order는 CSV 안에서 (rcept_no, statement, basis)가 같은 행끼리 등장 순서대로 0부터
    부여한다(사용자가 원문 순서대로 타이핑했다고 가정 — 최후수단 입력이라 이 이상의 구조 추론은
    하지 않는다)."""
    group_seq: dict[tuple[str, str, str], int] = {}
    out: list[ReportLineRow] = []
    for i, row in enumerate(csv_rows, start=2):  # 헤더가 1행
        rcept_no = unwrap_excel_text((row.get("rcept_no") or "").strip())
        if not rcept_no:
            raise ManualCsvError(f"line {i}: rcept_no is required")
        meta = filing_lookup.get(rcept_no)
        if meta is None:
            raise ManualCsvError(f"line {i}: rcept_no {rcept_no!r} not found in filings table — check for a typo")

        statement = _normalize_choice(row.get("statement", ""), STATEMENT_ALIASES, "statement", i)
        basis = _normalize_choice(row.get("basis", ""), BASIS_ALIASES, "basis", i)

        label_raw = (row.get("label_raw") or "").strip()
        if not label_raw:
            raise ManualCsvError(f"line {i}: label_raw is required")

        unit_text = (row.get("unit") or "").strip() or "원"
        multiplier = detect_unit_multiplier(f"단위 : {unit_text}")
        raw_value_text = (row.get("value_raw") or "").strip() or None
        value_won = parse_amount(raw_value_text, multiplier) if raw_value_text is not None else None

        depth_text = (row.get("depth") or "").strip()
        depth = int(depth_text) if depth_text else 0

        period_kind = "instant" if statement == "BS" else "duration"
        is_cumulative = period_kind == "duration" and meta.fiscal_period != "FY"

        key = (rcept_no, statement, basis)
        row_order = group_seq.get(key, 0)
        group_seq[key] = row_order + 1

        out.append(ReportLineRow(
            corp_code=meta.corp_code,
            rcept_no=rcept_no,
            report_fiscal_year=meta.fiscal_year,
            report_fiscal_period=meta.fiscal_period,
            statement=statement,
            basis=basis,
            label_raw=label_raw,
            col_index=0,
            context_fiscal_year=meta.fiscal_year,
            period_kind=period_kind,
            is_cumulative=is_cumulative,
            value_won=value_won,
            adecimal=_adecimal_from_unit(multiplier),
            unit_source="manual",
            source_ref=f"{statement}_{basis}/manual"[:180],
            context_raw=None,
            section_path=None,
            row_order=row_order,
            depth=depth,
            node_role=None,
            table_seq=0,
            table_title=None,
            col_label=None,
            # value_won을 못 채운 칸에만 원문을 남긴다(F1 관례, report_lines.py:205 docstring).
            value_raw=None if value_won is not None else raw_value_text,
            header_hint=None,
        ))
    return out


def store_manual_report_lines(session, rows: list[ReportLineRow], overwrite: bool = False) -> dict:
    """(rcept_no, statement, basis) 스코프로 delete-then-insert.

    안전장치: 그 스코프에 `unit_source != 'manual'`인 행(자동추출 산출물)이 이미 있으면
    `overwrite=True` 없이는 거부한다 — 지우기 전에 대상부터 본다는 원칙, 그리고 자동추출이
    부분적으로 맞을 수도 있는 걸 실수로 덮어쓰지 않기 위함."""
    from sqlalchemy import delete, insert, select

    from collector.models import ReportLine

    scopes = sorted({(r.rcept_no, r.statement, r.basis) for r in rows})

    # ★먼저 스코프 전부를 검사한 뒤에만 지운다 — 검사 도중 하나라도 거부되면 앞서 확인한
    #   스코프까지 이미 지워버리는 "부분 파괴" 사고를 막는다(지우기 전에 전부 확인).
    for rcept_no, statement, basis in scopes:
        existing = session.execute(
            select(ReportLine.unit_source).where(
                ReportLine.rcept_no == rcept_no,
                ReportLine.statement == statement,
                ReportLine.basis == basis,
            )
        ).scalars().all()
        non_manual = sorted({s for s in existing if s != "manual"})
        if non_manual and not overwrite:
            raise ValueError(
                f"{rcept_no}/{statement}/{basis} already has {len(existing)} row(s) from automatic "
                f"extraction (unit_source={non_manual}) — pass overwrite=True to replace them"
            )

    for rcept_no, statement, basis in scopes:
        session.execute(delete(ReportLine).where(
            ReportLine.rcept_no == rcept_no,
            ReportLine.statement == statement,
            ReportLine.basis == basis,
        ))

    insert_rows = [{k: v for k, v in r.as_row().items() if k not in _TABLE_LEVEL_COLS} for r in rows]
    if insert_rows:
        session.execute(insert(ReportLine).values(insert_rows))
    return {"scopes": len(scopes), "rows": len(insert_rows)}
