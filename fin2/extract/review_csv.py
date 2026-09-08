"""계층2 재적재 검토 CSV — DB 에 적재된 `report_lines` 를 **보고서 원문과 눈으로 대조할 수
있는 모양**으로 뽑는다 (사용자 결정 2026-09-08,
`docs/plans/layer2_reload_review_campaign_design_2026-09-08.md` §4).

## 왜 DB 에서 다시 읽는가
파싱 직후의 메모리 객체가 아니라 **적재된 DB 행을 다시 읽어** 만든다. 그래야
`store_report_lines()` 의 `_is_loadable` 필터(col_index=0만)·컬럼 매핑까지 검증 범위에
들어온다. 파싱 결과를 그대로 찍으면 "적재 단계에서 사라진 행"을 영영 못 본다.

## 형식 규칙 (사용자 지정)
- 상단에 **보고서 링크와 단위**를 둔다. 이어서 자동검산 요약(`fin2/audit/layer2_selfcheck`).
- 본문 순서는 **별도 BS → IS → CF → 연결 BS → IS → CF**. 연결이 없으면 별도만.
- 행 순서는 원문 그대로 = `ORDER BY table_seq, row_order` (`collector/models.py:ReportLine`).
- **금액은 보고서에 인쇄된 그대로** — `value_won × 10^adecimal`
  (`fin2/audit/report_line_audit.py::_rl_displayed` 재사용). 원문이 천원 단위로 찍혔으면
  천원 단위 숫자가 나온다. 사람이 원문과 자릿수까지 그대로 비교할 수 있어야 하기 때문.
  가독성을 위해 1,000 단위 콤마만 넣는다(`f"{n:,}"`) — 자릿수·부호는 그대로라 대조에 영향 없다.

## 전사 규약 (계층2 원칙을 CSV 에서도 지킨다)
- `value_won IS NULL` → 금액 칸은 비우고 `원문값`에 `value_raw` 를 넣는다. R4 의 NULL 규약
  ("단위 미확정은 유실이지 오염이 아니다")을 사람이 볼 수 있게 그대로 노출한다.
- `unit_source='fx_declared'` → **환산하지 않는다.** 단위 칸에 통화코드를 찍고 비고에
  '표시통화' 라고 적는다 (`collector/models.py:ReportLine.value_won` 의 유일한 예외).
- `header_hint IS NOT NULL` 행도 **숨기지 않는다.** 계층3 는 이 행을 거르지만(R5), 원문에는
  인쇄돼 있으므로 대조 대상이다. 비고에 걸린 규칙 이름을 적는다.

## 저장 위치
`layer2_review/<시장>/<corp_code>_<회사명>/<report_type>/<연도>/<rcept_no>_review.csv`
— `raw_report/` 트리를 미러링한다(`fin2/extract/manual_report_lines.py:39` 와 같은 관례,
프로젝트 로컬 + `.gitignore`). ★`manual_review/` 와는 **다른 디렉터리**다: 그쪽은 사람이
값을 타이핑해 넣는 **입력용** CSV 라 컬럼 스키마가 다르고,
`scripts/load_manual_report_lines.py` 가 이 파일을 집어삼키면 안 된다.

★엑셀 함정 — 14자리 접수번호는 `="20250320001312"` 로 감싼다(안 그러면 엑셀이
`2.02503E+13` 로 바꿔버린다, 2026-09-07 실측). `manual_report_lines.unwrap_excel_text()`
가 읽을 때 되돌린다.
★인코딩 — UTF-8 **with BOM**. 맥 엑셀이 BOM 없는 UTF-8 CSV 의 한글을 깨뜨린다.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from fin2.audit.layer2_selfcheck import (BASIS_KO, STMT_KO, CheckResult, load_rows)
from fin2.audit.report_line_audit import _rl_displayed

DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept}"

REVIEW_ROOT = Path("layer2_review")

# 본문 3종만(사용자 범위). 표시 순서 = 별도 먼저, 각 basis 안에서 BS→IS→CF.
SCOPE_ORDER: tuple[tuple[str, str], ...] = (
    ("separate", "BS"), ("separate", "IS"), ("separate", "CF"),
    ("consolidated", "BS"), ("consolidated", "IS"), ("consolidated", "CF"),
)

HEADER = ("구분", "단위", "순번", "깊이", "항목명", "금액", "원문값", "비고")

_UNIT_LABEL = {1: "원", 1000: "천원", 1000000: "백만원", 100000000: "억원",
               1000000000: "십억원", 1000000000000: "조원"}


def excel_text(value: str) -> str:
    """엑셀이 숫자로 해석하지 못하게 감싼다(`unwrap_excel_text` 의 역함수)."""
    return f'="{value}"'


def safe_name(name: str) -> str:
    """파일시스템 안전 기업명 — `collector/models.py:Corporation.safe_name` 과 같은 규칙."""
    return re.sub(r'[\\/:*?"<>|]', "_", name or "unknown")


def csv_path_for(*, market: str | None, corp_code: str, corp_name: str,
                 report_type: str | None, fiscal_year: int | None, rcept_no: str,
                 root: Path | None = None) -> Path:
    """`raw_report/` 미러 경로. 디렉터리는 만들지 않는다(호출부가 write 직전에 만든다)."""
    return ((root or REVIEW_ROOT)
            / (market or "UNKNOWN")
            / f"{corp_code}_{safe_name(corp_name)}"
            / (report_type or "unknown")
            / str(fiscal_year or "unknown")
            / f"{rcept_no}_review.csv")


def _unit_label(row: dict) -> str:
    """그 **행**의 단위 표기. 금액 칸과 반드시 같은 근거(`adecimal`)에서 나온다.

    ★`report_tables.declared_unit`(표 단위 컬럼)을 쓰지 않는다 — `store_report_tables()` 가
      표의 **첫 행 adecimal** 로 유도하는데, IS 는 EPS 행(adecimal=0)이 먼저 방출돼 백만원
      표가 `declared_unit=1`(원)로 잘못 적힌다(2026-09-09 실측: 삼성전자 20260814003699
      IS 별도/연결 둘 다). 그걸 CSV 에 찍으면 **금액은 백만원인데 단위는 원**이라고 적혀
      사용자가 원문과 대조할 때 정확히 틀린 안내를 하게 된다.
      행의 `adecimal` 은 `value_won` → 표시금액 환산에 쓰인 바로 그 값이라 어긋날 수 없다.
    ★단위를 확정 못 한 행(adecimal NULL)은 **빈칸**으로 둔다 — 지어내지 않는다(R4/R6).
    """
    if (row.get("unit_source") or "") == "fx_declared":
        return row.get("currency") or "외화"
    ad = row.get("adecimal")
    if ad is None:
        return ""
    mult = 10 ** (-ad) if ad <= 0 else 1
    return _UNIT_LABEL.get(mult, f"×{mult:,}")


def _note(row: dict) -> str:
    """비고 — 사람이 "이 행은 왜 이런가"를 CSV 안에서 바로 알 수 있게."""
    bits = []
    if (row.get("unit_source") or "") == "fx_declared":
        bits.append(f"표시통화({row.get('currency') or '?'}) 미환산")
    if row.get("header_hint"):
        bits.append(f"header_hint:{row['header_hint']}")
    if row.get("value_won") is None and not (row.get("value_raw") or "").strip():
        bits.append("금액 없음(원문 공란 또는 단위 미확정)")
    src = row.get("unit_source") or ""
    if src in ("undetermined", "undeclared", "doc_default", "inherited"):
        bits.append(f"unit_source={src}")
    return " / ".join(bits)


def build_rows(db_rows: list[dict]) -> list[tuple]:
    """DB 행 → CSV 데이터 행. 순수 함수(테스트 대상).

    입력은 `layer2_selfcheck.load_rows()` 결과와 같은 모양이며 정렬은 여기서 다시 한다
    (SQL 정렬은 statement 알파벳순이라 BS→IS→CF 가 아니다).
    """
    out: list[tuple] = []
    for basis, stmt in SCOPE_ORDER:
        scope_rows = [r for r in db_rows if r["statement"] == stmt and r["basis"] == basis]
        if not scope_rows:
            continue
        # 원문 순서. table_seq 가 NULL 인 경로(수동입력 등)는 맨 앞으로.
        scope_rows.sort(key=lambda r: (r["table_seq"] if r["table_seq"] is not None else -1,
                                       r["row_order"] if r["row_order"] is not None else -1))
        label = f"[{BASIS_KO[basis]}] {STMT_KO[stmt]}"
        for i, r in enumerate(scope_rows, start=1):
            if r["value_won"] is None:
                amount, raw = "", (r.get("value_raw") or "")
            else:
                # Thousands separator for readability — the underlying digits
                # (magnitude, sign) are unchanged, so source comparison still holds.
                amount = f"{_rl_displayed(r['value_won'], r.get('adecimal')):,}"
                raw = ""
            out.append((label, _unit_label(r), i,
                        r["depth"] if r["depth"] is not None else "",
                        r["label_raw"], amount, raw, _note(r)))
    return out


def build_preamble(*, corp_name: str, corp_code: str, market: str | None,
                   corp_rank: int | None, report_nm: str | None,
                   fiscal_year: int | None, fiscal_period: str | None,
                   rcept_no: str, filed_at, source_kind: str,
                   reloaded_at: datetime, checks: list[CheckResult],
                   counts: dict[str, dict[str, int]]) -> list[list[str]]:
    """CSV 상단 메타 + 자동검산 블록. 모든 줄이 `#` 로 시작해 데이터와 섞이지 않는다."""
    rank = f"  시총순위 {corp_rank}" if corp_rank else ""
    lines: list[list[str]] = [
        ["# 회사", f"{corp_name} ({corp_code}) {market or ''}{rank}".strip()],
        ["# 보고서", f"{fiscal_year or '?'}{fiscal_period or ''}  {report_nm or ''}".strip()],
        ["# 접수번호", excel_text(rcept_no)],
        ["# DART 원문", DART_VIEWER.format(rcept=rcept_no)],
        ["# 접수일", str(filed_at or "")],
        ["# 파싱 소스", source_kind],
        ["# 재적재", reloaded_at.strftime("%Y-%m-%d %H:%M:%S")],
    ]
    if source_kind in ("pdf", "html"):
        lines.append(["# ⚠ 주의", "PDF/HTML 복구 경로 — 값조작 결함 이력 있음"
                                  "(docs/qa/report_lines_row_count_outlier_scan_2026-09-08.md "
                                  "Pattern A). 숫자를 특히 꼼꼼히 대조할 것."])
    summary = "  ·  ".join(
        f"[{BASIS_KO[b]}] " + " / ".join(f"{s} {counts.get(b, {}).get(s, 0)}"
                                         for s in ("BS", "IS", "CF"))
        for b in ("separate", "consolidated") if counts.get(b))
    lines.append(["# 적재 행수", summary or "0행"])
    lines.append(["#"])
    lines.append(["# ── 자동검산 ──"])
    if not checks:
        lines.append(["#", "검산 없음"])
    for c in checks:
        mark = {"PASS": "PASS", "FAIL": "FAIL", "NA": "판정불가"}[c.verdict]
        lines.append([f"# {c.grade} {c.code}", c.scope, mark, c.message])
    lines.append(["#"])
    return lines


def write_review_csv(path: Path, preamble: list[list[str]], rows: list[tuple]) -> Path:
    """UTF-8 with BOM 으로 저장. 디렉터리는 여기서 만든다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerows(preamble)
        w.writerow(HEADER)
        w.writerows(rows)
    return path


def scope_counts(db_rows: list[dict]) -> dict[str, dict[str, int]]:
    """{'separate': {'BS': 62, 'IS': 41, 'CF': 33}, 'consolidated': {...}} — 본문 3종만."""
    out: dict[str, dict[str, int]] = {}
    for r in db_rows:
        if r["statement"] not in ("BS", "IS", "CF") or r["basis"] not in BASIS_KO:
            continue
        out.setdefault(r["basis"], {}).setdefault(r["statement"], 0)
        out[r["basis"]][r["statement"]] += 1
    return out


def generate(session, *, rcept_no: str, corp_code: str, corp_name: str,
             market: str | None, corp_rank: int | None, report_type: str | None,
             report_nm: str | None, fiscal_year: int | None, fiscal_period: str | None,
             filed_at, source_kind: str, checks: list[CheckResult],
             reloaded_at: datetime | None = None,
             root: Path | None = None,
             db_rows: list[dict] | None = None) -> tuple[Path, dict[str, dict[str, int]]]:
    """DB → CSV 파일 1개. 반환 (경로, 범위별 행수)."""
    rows_db = load_rows(session, rcept_no) if db_rows is None else db_rows
    counts = scope_counts(rows_db)
    path = csv_path_for(market=market, corp_code=corp_code, corp_name=corp_name,
                        report_type=report_type, fiscal_year=fiscal_year,
                        rcept_no=rcept_no, root=root)
    preamble = build_preamble(
        corp_name=corp_name, corp_code=corp_code, market=market, corp_rank=corp_rank,
        report_nm=report_nm, fiscal_year=fiscal_year, fiscal_period=fiscal_period,
        rcept_no=rcept_no, filed_at=filed_at, source_kind=source_kind,
        reloaded_at=reloaded_at or datetime.now(), checks=checks, counts=counts)
    write_review_csv(path, preamble, build_rows(rows_db))
    return path, counts
