"""R178 2차 필터 — stage1(`scan_r178_unit_header_dropped_rows_2026-09-26.py`)이 뽑은 후보
rcept 중, 실제로 지금 DB에 드롭된 채 남아있는 필링만 골라낸다(read-only, DB 쓰기 없음).

## 왜 2차 필터가 필요한가

stage1은 원문 셀 텍스트만 보고 구/신 정규식 판정 차이로 후보를 뽑는다 — "단위"라는 글자가
표 캡션·EPS 섹션제목·비재무 단위표기에도 흔해 후보가 과다생성된다(스크립트 상단 docstring
★한계 참고). 이 스크립트는 각 후보 rcept를 **현재(R178 수정 반영) 코드로 실제 재추출**해서
`extract_report_lines()`가 만드는 본문(BS/IS/CF/SCE) 행 중 "단위" 라벨을 가진 행이 있는지,
그리고 그 행이 **DB에 아직 없는지**를 직접 확인한다 — 둘 다 참이어야 R178 드롭의 실제
피해자로 확정한다.

## 판정 로직

1. `report_lines` 테이블에서 그 rcept의 corp_code/report_fiscal_year/report_fiscal_period를
   가져온다(이미 적재된 적 있는 필링이라는 뜻 — report_lines에 행이 하나도 없으면 스킵).
2. `layer2_review.py::_resolve_source()`로 원문 파일 경로를 찾는다(존재하는 파일만 채택).
3. `extract_report_lines(..., include_notes=False)`로 본문만 재추출 — 주석은 F2 경로
   (`keep_header_rows=True`)라 이 버그의 영향을 안 받는다(R178 문서 참고).
4. `_is_loadable()`로 실제 적재 대상 행만 남긴다(BS/IS/CF는 col_index=0만, SCE는 전부).
5. DB 현재값과 (statement, basis, label_raw, col_index) 키로 대조해, **새로 나타나면서
   라벨에 "단위"가 들어간 행**만 "R178 드롭 확정"으로 표시한다 — 라벨 필터를 두는 이유는
   재추출 시점 사이에 착지한 무관한 수정(R177 등)이 만드는 다른 신규 행과 섞이지 않기
   위해서다.

## --apply 없이는 DB를 건드리지 않는다

이 스크립트는 확정 후보 목록만 만든다. 실제 백필은 `vq.py batch add-targets` +
`vq.py batch reload <id>`로 한다(CLAUDE.local.md 규약 — batch_targets 추적을 남기기 위해
`store_report_lines`를 여기서 직접 부르지 않는다).

## 사용법

    python scripts/scan_r178_unit_header_stage2_live_check_2026-09-26.py \\
        docs/qa/r178_scan_stage1.jsonl \\
        > docs/qa/r178_scan_stage2_confirmed.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines, _is_loadable

_L2R = Path(__file__).resolve().parent / "layer2_review.py"
_UNIT_LABEL_RE = re.compile(r"단위")


def _resolve_source_fn():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_l2r", _L2R)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._resolve_source


def _load_candidates(path: Path) -> list[str]:
    out = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            rcept = rec.get("rcept_no")
            if rcept:
                out.append(rcept)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage1_jsonl", type=Path, help="stage1 스캔 출력(jsonl)")
    ap.add_argument("--limit", type=int, default=0, help="앞 N건만 검사")
    ap.add_argument("--shard", type=str, default=None,
                     help="i/n — n개 프로세스로 나눠 검사할 때 이 프로세스 몫(전체 재검사가"
                          " 느려 병렬화용, 읽기 전용이라 batch reload --shard와 달리 충돌 걱정 없음)")
    args = ap.parse_args()

    resolve_source = _resolve_source_fn()
    candidates = _load_candidates(args.stage1_jsonl)
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        candidates = [r for j, r in enumerate(candidates) if j % n == i]
    if args.limit:
        candidates = candidates[: args.limit]
    print(f"# stage1 후보 {len(candidates)}건 재검사 시작", file=sys.stderr)

    n_confirmed = n_no_meta = n_no_file = n_error = n_clean = 0

    with get_session() as s:
        for i, rcept in enumerate(candidates, 1):
            meta = s.execute(text("""
                SELECT corp_code, report_fiscal_year, report_fiscal_period
                FROM report_lines WHERE rcept_no = :r LIMIT 1"""),
                {"r": rcept}).mappings().first()
            if not meta:
                n_no_meta += 1
                print(json.dumps({"rcept_no": rcept, "status": "no_meta"},
                                  ensure_ascii=False))
                continue

            _kind, path = resolve_source(s, rcept)
            if not path:
                n_no_file += 1
                print(json.dumps({"rcept_no": rcept, "status": "no_file"},
                                  ensure_ascii=False))
                continue

            try:
                new_lines = extract_report_lines(
                    path, rcept_no=rcept, corp_code=meta["corp_code"],
                    report_fiscal_year=meta["report_fiscal_year"],
                    report_fiscal_period=meta["report_fiscal_period"],
                    include_notes=False)
            except Exception as exc:                              # noqa: BLE001
                n_error += 1
                print(json.dumps({"rcept_no": rcept, "status": "error",
                                   "error": f"{type(exc).__name__}: {exc}"},
                                  ensure_ascii=False))
                continue

            new_loadable = [l for l in new_lines if l.statement != "note" and _is_loadable(l)]

            cur = {(r["statement"], r["basis"], r["label_raw"], r["col_index"])
                   for r in s.execute(text("""
                       SELECT statement, basis, label_raw, col_index
                       FROM report_lines WHERE rcept_no = :r"""),
                       {"r": rcept}).mappings()}

            dropped = [l for l in new_loadable
                       if (l.statement, l.basis, l.label_raw, l.col_index) not in cur
                       and _UNIT_LABEL_RE.search(l.label_raw or "")]

            if dropped:
                n_confirmed += 1
                print(json.dumps({
                    "rcept_no": rcept, "status": "confirmed",
                    "corp_code": meta["corp_code"],
                    "n_dropped_rows": len(dropped),
                    "sample": [
                        {"statement": l.statement, "basis": l.basis,
                         "label_raw": l.label_raw, "col_index": l.col_index,
                         "value_won": l.value_won}
                        for l in dropped[:5]
                    ],
                }, ensure_ascii=False))
            else:
                n_clean += 1
                print(json.dumps({"rcept_no": rcept, "status": "clean"},
                                  ensure_ascii=False))

            if i % 200 == 0:
                print(f"# progress: {i}/{len(candidates)} — confirmed={n_confirmed} "
                      f"clean={n_clean} no_meta={n_no_meta} no_file={n_no_file} "
                      f"error={n_error}", file=sys.stderr)

    print(f"# done: {len(candidates)} checked — confirmed={n_confirmed} clean={n_clean} "
          f"no_meta={n_no_meta} no_file={n_no_file} error={n_error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
