"""
Track A XBRL 추출기 (fin2 E-레이어).

DART XML 의 TE[@ACODE] 셀을 **추론이 아닌 저장**으로 fact_v2 행으로 변환한다.
- 단위: ADECIMAL 권위 (amount_won = 표기값 × 10^(-adecimal)). AUNIT 무시.
- 연결/별도·기간·차원: acontext.parse_acontext 구조 파싱 결과 그대로 보존.
- 매핑(canonical_account)은 여기서 하지 않음(별도 concept_map 책임). E-레이어는 acode 원문만 저장.

Track 판정: TE[@ACODE] 가 ifrs-full_*/dart_* + ACONTEXT 를 가질 때만 추출(=Track A).
그 외 파일(구형/Track B)은 행 0개 → P2 텍스트/PDF 폴백 담당.

실행 경로: run.py extract2 → extract_file().
XML 로더는 기존 parser._parse_xml_file(malformed/인코딩 자동복구) 재사용.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from parser.common.amount_normalizer import parse_amount
from parser.xml.dart_xml_parser import _parse_xml_file
from fin2.extract.acontext import parse_acontext
from fin2.taxonomy.concept_map import map_acode

# Track A 로 인정하는 ACODE 네임스페이스 접두어
_XBRL_PREFIXES = ("ifrs-full_", "dart_")


@dataclass
class ExtractedFact:
    """fact_v2 한 행의 추출 산출물(DB 비의존, 테스트 가능)."""
    corp_code: str
    rcept_no: str
    report_fiscal_year: int
    report_fiscal_period: str
    acode: str
    basis: str | None
    context_fiscal_year: int | None
    col_index: int | None
    period_kind: str | None
    period_type: str | None
    is_cumulative: bool
    extra_dims: list[list[str]] | None
    is_dimensional: bool
    adecimal: int | None
    amount_won: int | None
    source_format: str
    source_ref: str | None
    acontext_raw: str | None
    context_parsed: bool
    canonical_account: str | None = None  # Track A=concept_map.map_acode, Track B=account_mapper. 미매핑 NULL

    # ── provenance (2026-07-17 재구축) — fact_v2 동명 컬럼에 그대로 실린다 ──────
    # 이 값들이 "원본을 읽은 행"과 "코드가 추측한 행"을 DB 에서 구분한다. 추출기가 채우지
    # 않으면 NULL 로 남고(Track A 등 미개편 경로), 재구축 대상 경로는 반드시 채운다.
    section_kind: str | None = None       # DART 섹션 출처(연결재무제표/재무제표/…주석)
    mapping_stage: str | None = None      # exact/normalized/guard/fuzzy/unknown
    mapping_confidence: float | None = None
    unit_source: str | None = None        # 'declared' 만 적재(미표기·추측은 보류)

    def as_row(self) -> dict:
        """SQLAlchemy bulk upsert 용 dict (FactV2 컬럼명 기준)."""
        return {
            "corp_code": self.corp_code,
            "rcept_no": self.rcept_no,
            "report_fiscal_year": self.report_fiscal_year,
            "report_fiscal_period": self.report_fiscal_period,
            "acode": self.acode,
            "canonical_account": self.canonical_account,
            "basis": self.basis,
            "context_fiscal_year": self.context_fiscal_year,
            "col_index": self.col_index,
            "period_kind": self.period_kind,
            "period_type": self.period_type,
            "is_cumulative": self.is_cumulative,
            "extra_dims": self.extra_dims,
            "is_dimensional": self.is_dimensional,
            "adecimal": self.adecimal,
            "amount_won": self.amount_won,
            "source_format": self.source_format,
            "source_ref": self.source_ref,
            "acontext_raw": self.acontext_raw,
            "context_parsed": self.context_parsed,
            "section_kind": self.section_kind,
            "mapping_stage": self.mapping_stage,
            "mapping_confidence": self.mapping_confidence,
            "unit_source": self.unit_source,
        }


def _cell_text(te) -> str:
    """TE 셀의 표기 텍스트. te.text → <P> 자식 → 전체 itertext 순으로 탐색."""
    raw = (te.text or "").strip()
    if not raw:
        p = te.find("P")
        if p is not None:
            raw = (p.text or "").strip()
    if not raw:
        raw = "".join(te.itertext()).strip()
    return raw


def _unit_multiplier(adecimal: int | None) -> int:
    """ADECIMAL → 원 환산 배수. amount_won = 표기값 × 10^(-adecimal).
    ADECIMAL=0 이면 표기값이 이미 원 단위(배수 1). 양수(반올림 자리)는 배수 1."""
    if adecimal is not None and adecimal < 0:
        return 10 ** (-adecimal)
    return 1


def extract_facts(
    file_path: str | Path,
    *,
    rcept_no: str,
    corp_code: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
    source_format: str = "xbrl_acode",
) -> list[ExtractedFact]:
    """
    단일 DART XML 파일에서 Track A fact_v2 행들을 추출한다.

    Track A 가 아니면(=XBRL ACODE+ACONTEXT 셀 없음) 빈 리스트를 반환한다.
    같은 (acode, acontext) 셀이 문서 내 중복 등장하면 1개로 합치되 금액 있는 것을 우선한다.
    """
    root = _parse_xml_file(Path(file_path))
    if root is None:
        logger.warning(f"[extract2] XML 루트 없음: {file_path}")
        return []

    # 한 보고서 내 (acode, acontext_raw) 셀은 유일해야 함(uq_fact_v2_cell).
    # 중복 등장(요약표+상세표 등) 시 금액 보유 행 우선.
    dedup: dict[tuple[str, str], ExtractedFact] = {}

    for te in root.findall(".//TE[@ACODE]"):
        acode = te.get("ACODE", "")
        if not acode.startswith(_XBRL_PREFIXES):
            continue
        if len(acode) > 255:
            continue  # 초장문 기업확장 공시테이블 항목(>255) — 핵심 재무 아님, 스킵
        acontext = te.get("ACONTEXT", "")
        if not acontext:
            continue  # ACONTEXT 없는 XBRL 셀은 Track A 대상 아님

        text = _cell_text(te)
        if not text:
            continue

        # 단위(ADECIMAL 권위)
        adecimal_str = te.get("ADECIMAL", "")
        try:
            adecimal = int(adecimal_str)
        except (ValueError, TypeError):
            adecimal = None
        amount_won = parse_amount(text, _unit_multiplier(adecimal))
        if amount_won is None:
            continue  # 공란/비수치 셀은 보존하지 않음

        ctx = parse_acontext(acontext)
        acontext_raw = acontext[:255]
        extra_dims = [[a, m] for a, m in ctx.extra_dims] if ctx.extra_dims else None

        fact = ExtractedFact(
            corp_code=corp_code,
            rcept_no=rcept_no,
            report_fiscal_year=report_fiscal_year,
            report_fiscal_period=report_fiscal_period,
            acode=acode,
            basis=ctx.basis,
            context_fiscal_year=ctx.fiscal_year,
            col_index=ctx.col_index,
            period_kind=ctx.period_kind,
            period_type=ctx.period_type,
            is_cumulative=ctx.is_cumulative,
            extra_dims=extra_dims,
            is_dimensional=ctx.is_dimensional,
            adecimal=adecimal,
            amount_won=amount_won,
            source_format=source_format,
            source_ref=f"{ctx.basis or '?'}/{acode}"[:180],
            acontext_raw=acontext_raw,
            context_parsed=ctx.parsed,
            canonical_account=map_acode(acode),
        )

        key = (acode, acontext_raw)
        prev = dedup.get(key)
        if prev is None or prev.amount_won is None:
            dedup[key] = fact

    return list(dedup.values())


def store_facts(session, facts: list[ExtractedFact]) -> int:
    """추출 행들을 fact_v2 에 upsert(ON CONFLICT uq_fact_v2_cell). 반환=처리 행 수."""
    if not facts:
        return 0
    from datetime import datetime
    from sqlalchemy.dialects.postgresql import insert
    from collector.models import FactV2

    rows = [f.as_row() for f in facts]
    for r in rows:
        r["parsed_at"] = datetime.utcnow()

    stmt = insert(FactV2).values(rows)
    # 충돌 시 재추출 값으로 갱신(파서 개선 반영). id/생성시각 제외 전 컬럼 갱신.
    update_cols = {
        c.name: stmt.excluded[c.name]
        for c in FactV2.__table__.columns
        if c.name not in ("id",)
    }
    stmt = stmt.on_conflict_do_update(
        constraint="uq_fact_v2_cell",
        set_=update_cols,
    )
    session.execute(stmt)
    return len(rows)


def store_extended_facts_v3(session, facts: list[ExtractedFact]) -> int:
    """`ExtractedFact` 목록을 `extended_facts_v3`(라벨 기반 확장 캐노니컬)에 upsert.

    ★2026-09-01(fact_v2 GC 트랙 Track 1, `docs/plans/
    factv2_sync_scripts_migration_design_2026-09-01.md`) — `store_facts()`(fact_v2)의
    자매 함수. `collector/expense_nature_sync.py`가 뽑는 `note.employee_benefits`/
    `note.raw_materials_used`(EXTENDED_CATALOG 등재, `combine.py`의 일반 라벨매핑이
    만들지 못하는 canonical)를 `fact_v2` 대신 여기로 직접 적재한다 — `extended_financials`
    뷰가 이제 `extended_facts_v3`만 읽으므로(§4-2, commit `243e9ee`) 이게 유일한
    유효 목적지다. 그레인이 `std_financials_v3`와 동일(당기 FY, col_index=0)이라
    `report_fiscal_year`/`report_fiscal_period`/`basis`를 그대로 옮겨 쓸 수 있다.
    """
    if not facts:
        return 0
    from datetime import datetime
    from sqlalchemy.dialects.postgresql import insert
    from collector.models import ExtendedFactV3

    rows = [
        {
            "corp_code": f.corp_code,
            "fiscal_year": f.report_fiscal_year,
            "fiscal_period": f.report_fiscal_period,
            "statement_type": f.basis,
            "canonical_account": f.canonical_account,
            "amount_won": f.amount_won,
            "built_at": datetime.utcnow(),
        }
        for f in facts
        if f.canonical_account and f.basis and f.amount_won is not None
    ]
    if not rows:
        return 0

    stmt = insert(ExtendedFactV3).values(rows)
    update_cols = {
        c.name: stmt.excluded[c.name]
        for c in ExtendedFactV3.__table__.columns
        if c.name not in ("corp_code", "fiscal_year", "fiscal_period",
                          "statement_type", "canonical_account")
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["corp_code", "fiscal_year", "fiscal_period",
                        "statement_type", "canonical_account"],
        set_=update_cols,
    )
    session.execute(stmt)
    return len(rows)


def extract_file(
    session,
    file_path: str | Path,
    *,
    rcept_no: str,
    corp_code: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
) -> int:
    """추출 + 저장 일괄. 반환=저장된 fact 수(0이면 Track A 아님 또는 데이터 없음)."""
    facts = extract_facts(
        file_path,
        rcept_no=rcept_no,
        corp_code=corp_code,
        report_fiscal_year=report_fiscal_year,
        report_fiscal_period=report_fiscal_period,
    )
    return store_facts(session, facts)
