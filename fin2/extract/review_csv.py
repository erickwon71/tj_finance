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
import math
import re
from datetime import datetime
from pathlib import Path

from fin2.audit.layer2_selfcheck import (BASIS_KO, STMT_KO, CheckResult, load_rows)
from fin2.audit.report_line_audit import _rl_displayed

DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept}"

REVIEW_ROOT = Path("layer2_review")

# ★본문 4종(2026-09-18부터 SCE 추가 — R139 캠페인, 사용자 지시 "bs is cf sce").
#   표시 순서 = 별도 먼저, 각 basis 안에서 BS→IS→CF→SCE. APPR(이익잉여금처분계산서)은
#   여전히 대상 밖(사용자가 명시한 범위 밖).
SCOPE_ORDER: tuple[tuple[str, str], ...] = (
    ("separate", "BS"), ("separate", "IS"), ("separate", "CF"), ("separate", "SCE"),
    ("consolidated", "BS"), ("consolidated", "IS"), ("consolidated", "CF"),
    ("consolidated", "SCE"),
)

_DISPLAY_STATEMENTS = ("BS", "IS", "CF", "SCE")

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
        # ★row_order 가 NULL 인 유일한 경로는 EPS(`_emit_eps_lines`, 표 본류 순회 밖의
        #   별도 패스라 "행 위치를 주장하지 않는다") — 원문에서는 항상 그 표의 맨 마지막에
        #   인쇄된다(주당이익은 관례상 손익계산서 하단). math.inf 로 그 표(같은 table_seq)
        #   맨 뒤로 보낸다. -1 로 두면 반대로 맨 앞(예: 매출액보다 위)에 찍혀 원문과
        #   어긋난다 — 2026-09-09 실측(삼성전자 20260814003699, 사용자가 원문대조로 발견).
        scope_rows.sort(key=lambda r: (r["table_seq"] if r["table_seq"] is not None else -1,
                                       r["row_order"] if r["row_order"] is not None else math.inf))
        label = f"[{BASIS_KO[basis]}] {STMT_KO[stmt]}"
        i = 0
        stack: list[str] = []   # 현재 "열려 있는" 조상 라벨 스택(가상 헤더 + P행 자기 라벨)
        for r in scope_rows:
            ancestors = _ancestors(r)
            # 이번 행의 조상 경로와 스택의 공통 접두를 구해, 안 맞는 부분부터 닫는다
            # (다른 그룹으로 넘어갔다는 뜻 — 예: 유동자산 그룹 끝나고 비유동자산 시작).
            common = 0
            while common < len(ancestors) and common < len(stack) and stack[common] == ancestors[common]:
                common += 1
            stack = stack[:common]
            # 아직 안 열린 조상은 **가상 헤더 행**으로 연다. 원문에는 인쇄돼 있지만
            # 금액이 없어(예: '자산'·'부채'·'자본'·'포괄손익의 귀속') report_lines 에
            # 자기 행으로 적재되지 않은 헤더 텍스트다(section_path 로만 보존됨,
            # `collector/models.py:ReportLine.section_path` 참고) — 사용자 요청
            # 2026-09-09: "section_path 가 보이고 그 아래에 각 group 에 맞게 보이면
            # 눈으로 확인하기 쉽겠다"(원문 캡처 예시: '자산' 헤더 밑에 '유동자산' 들여쓰기).
            for depth, seg in enumerate(ancestors[common:], start=common):
                i += 1
                out.append((label, "", i, depth, _indent(seg, depth), "", "",
                           "원문 헤더(금액 없음)"))
                stack.append(seg)
            depth = len(ancestors)
            i += 1
            if r["value_won"] is None:
                amount, raw = "", (r.get("value_raw") or "")
            else:
                # Thousands separator for readability — the underlying digits
                # (magnitude, sign) are unchanged, so source comparison still holds.
                amount = f"{_rl_displayed(r['value_won'], r.get('adecimal')):,}"
                raw = ""
            out.append((label, _unit_label(r), i, depth,
                        _indent(r["label_raw"], depth), amount, raw, _note(r)))
            if r.get("node_role") == "P":
                # 이 행 자체가 다음 행들의 조상이 된다(자식을 거느린 부모 — 원문에서
                # 다음 행이 한 단계 더 들여써진다는 사실, `node_role` 컬럼 정의 참고).
                stack.append(r["label_raw"])
    return out


def _ancestors(row: dict) -> list[str]:
    """`section_path`('자산>유동자산')를 조상 라벨 리스트로. 없으면 최상위(빈 리스트).

    ★저장된 `depth` 대신 **이 리스트의 길이**를 그 행의 표시 깊이로 쓴다 — 실측상
    항상 일치하고(조상 하나당 들여쓰기 한 단계), EPS 처럼 `depth` 가 NULL(표 본류
    순회 밖이라 위치를 주장하지 않는 행, `report_lines.py::_emit_eps_lines`)이어도
    `section_path='주당손익'`은 채워져 있어 깊이 1로 정확히 들여써진다."""
    path = row.get("section_path")
    return path.split(">") if path else []


def _indent(text: str, depth: int) -> str:
    """텍스트 앞에 depth × 2칸 공백 — 트리 구조를 눈으로 바로 보이게 한다(사용자 요청
    2026-09-09)."""
    return "  " * depth + text if depth > 0 else text


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
                                         for s in _DISPLAY_STATEMENTS)
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


def build_source_only_rows(missing) -> list[tuple]:
    """**원문에만 있고 적재되지 않은 행**을 CSV 데이터 블록 끝에 붙일 튜플로 만든다.

    ★왜 CSV 에 넣는가(2026-09-20) — 이 CSV 가 원문대조의 **대조 표면**이고, 캠페인
      판정 기준이 "CSV 라벨을 기준으로 화면에서 찾아 비교"라 방향이 CSV → 원문
      **단방향**이다. 그래서 CSV 에 없는 행은 아무리 성실히 대조해도 순회 대상에
      들어오지 않는다(실증: R149 EPS 결측이 '전 항목 원문대조' 규칙 시행 후에도
      신한지주 13건에서 안 걸렸다 — `docs/PARSING_RULES.md` R149).
      검산 메시지로만 알리면 예비란 한 줄이라 그냥 지나친다. **결측을 데이터 행으로
      실어야** 검토자가 "이 줄을 원문에서 확인" 하는 같은 동작으로 잡을 수 있다.
    """
    if not missing:
        return []
    rows: list[tuple] = []
    for m in missing:
        rows.append((
            f"★원문만 [{BASIS_KO.get(m.basis, m.basis)}] {m.statement}",
            "", "", "",
            m.label,
            "",                                   # 적재 금액 없음 — 그게 요점이다
            " / ".join(m.amounts),                # 원문에 인쇄된 값
            "원문에 있는데 적재 안 됨 → 원문 확인 후 결측이면 fail",
        ))
    return rows


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
    """{'separate': {'BS': 62, 'IS': 41, 'CF': 33, 'SCE': 12}, 'consolidated': {...}} —
    본문 4종만(BS/IS/CF/SCE, 2026-09-18부터 SCE 포함)."""
    out: dict[str, dict[str, int]] = {}
    for r in db_rows:
        if r["statement"] not in _DISPLAY_STATEMENTS or r["basis"] not in BASIS_KO:
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
             db_rows: list[dict] | None = None,
             source_only_rows=None) -> tuple[Path, dict[str, dict[str, int]]]:
    """DB → CSV 파일 1개. 반환 (경로, 범위별 행수).

    `source_only_rows` = `fin2.audit.row_coverage` 가 찾은 **원문에만 있는 행**
    (`build_source_only_rows` docstring 에 왜 CSV 에 실어야 하는지).
    """
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
    write_review_csv(path, preamble,
                     build_rows(rows_db) + build_source_only_rows(source_only_rows))
    return path, counts
