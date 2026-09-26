"""R178 전사 스캔 — `_header_rule_name`의 "단위표기" 부분일치 오판정으로 SCE/BS/IS/CF
본문에서 통째로 드롭됐을 가능성이 있는 필링을 찾는다(read-only, DB 쓰기 없음).

방법: raw_report(SD 미러 우선)의 TD/TE 셀 텍스트 중 "단위"를 포함하면서 구 정규식
(`re.search(r'단위\\s*[:\\(]', text)`)엔 걸리지만 신 정규식(R178, fullmatch)엔 안 걸리는
셀(=예전엔 헤더로 오분류돼 드롭됐을 데이터 행)이 있는 필링을 rcept 단위로 집계한다.
실제 드롭 여부(그 필링이 keep_header_rows=False 경로를 타는지, 실제로 그 행이 저장 전
필터에 걸렸는지)는 여기서 확정하지 않는다 — 후보만 좁힌다. 확정은 후보 rcept만
`batch add-targets` + `batch reload`로 재적재해 실제 데이터가 바뀌는지로 검증한다.

실행 (전체는 수십 분 소요 예상 — 백그라운드 권장):
    python scripts/scan_r178_unit_header_dropped_rows_2026-09-26.py > docs/qa/r178_scan_$(date +%F).jsonl

먼저 표본으로 규모를 가늠하려면 --limit 사용:
    python scripts/scan_r178_unit_header_dropped_rows_2026-09-26.py --limit 2000

★한계(2026-09-26, --limit 3000 표본 실측): "단위"라는 텍스트 자체가 원문에 극히 흔해서
(표 캡션 "(작성기간:...,단위:백만원)"·EPS 섹션제목 "주당순이익(단위:원)"·원자재현황 주석의
비재무 단위표기 "철근 각종, 단위 : ton" 등) **거의 모든 필링**이 후보로 잡힌다 — 이 스크립트
단독으로는 실사용 백필 대상 목록이 아니다. 카카오 사례처럼 **금액이 실제로 붙어 있는** 진짜
데이터 행만 걸러내려면 이 목록을 입력으로 실제 재추출(`extract_report_lines`)을 돌려
`amounts`가 있는 후보만 남기는 2단계 필터가 필요하다(후속 세션 과제, 미완료).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.xml.table_extractor import _header_rule_name  # noqa: E402

_OLD_UNIT_RE = re.compile(r'단위\s*[:\(]')
_CELL_RE = re.compile(r'<T[DE][^>]*>\s*(?:<P[^>]*>)?([^<]*단위[^<]*)(?:</P>)?\s*</T[DE]>')

_ROOTS = [Path("/Volumes/dart_data/raw_report"), Path("/Users/taejin/Project/tj_finance/raw_report")]


def _root() -> Path:
    for r in _ROOTS:
        if r.exists():
            return r
    raise SystemExit("raw_report 루트를 찾을 수 없음(SD 미러/NAS 둘 다 없음)")


def scan(limit: int | None) -> None:
    root = _root()
    n_files = 0
    n_hits = 0
    for xml_path in root.rglob("*.xml"):
        n_files += 1
        if limit and n_files > limit:
            break
        try:
            data = xml_path.read_bytes()
        except OSError:
            continue
        # 인코딩이 파일마다 다르다(utf-8 선언인데 실제 cp949인 경우도 실측됨) — 둘 다 시도.
        text = None
        for enc in ("utf-8", "cp949"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = data.decode("utf-8", errors="replace")
        if "단위" not in text:
            continue
        rescued = []
        for m in _CELL_RE.finditer(text):
            cell = m.group(1).strip()
            if not cell or not _OLD_UNIT_RE.search(cell):
                continue
            if _header_rule_name(cell) == "단위표기":
                continue  # 신 규칙으로도 여전히 헤더 — R178 영향 아님
            rescued.append(cell)
        if rescued:
            n_hits += 1
            rcept = xml_path.stem
            print(f'{{"rcept_no": "{rcept}", "path": "{xml_path}", "n_cells": {len(rescued)}, '
                  f'"sample": {rescued[:3]!r}}}')
        if n_files % 5000 == 0:
            print(f"# progress: {n_files} files scanned, {n_hits} candidates", file=sys.stderr)
    print(f"# done: {n_files} files scanned, {n_hits} candidate rcepts", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="스캔할 최대 파일 수(표본용)")
    args = ap.parse_args()
    scan(args.limit)
