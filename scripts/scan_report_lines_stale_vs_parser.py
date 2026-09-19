"""전수 대조 — DB `report_lines` 가 **현재 파서 출력과 다른** 필링을 찾는다.

왜 필요한가: 파서 수정(R144/R145 등) 뒤의 소급 백필은 "영향 필링 선별"로 돌렸는데,
선별식이 DB 흔적으로만 만들어져 **흔적을 안 남기는 결함**(행 유실·열 밀림)을 놓친다.
실측으로 드러난 예 — KBI메탈 `20220323000134` 희석주당이익: DB 는 당기=56 인데 원문은
당기 공란/전기=56 이다(R144 열 위치 수정이 이 필링에 반영 안 됨). 값이 "있어" 보여서
어떤 DB 시그니처로도 안 걸린다. 그래서 **재추출해서 직접 비교**하는 수밖에 없다.

★유령행 시그니처의 한계(2026-09-19 실측). R144 백필이 쓰던 판정식은
    본류값 = EPS값 × 10^(-adecimal)      # 같은 숫자, 다른 단위
인데 **두 경로가 서로 다른 열을 고른 경우는 이 등식이 성립하지 않아 안 걸린다.**
SK스퀘어 `20230814001786` 연결IS(반기): EPS 경로가 3개월 -4,969 를, 본류가 누적
-8,713 을 골라 `-8,713,000,000` 유령행이 남았는데 -4,969×10⁶ ≠ -8,713,000,000 이라
시그니처를 통과했다. 이 스캔(멀티셋 전량 대조)은 그런 것도 잡는다.

★쓰는 자리: 계층2 캠페인(`layer2_review.py next`)은 매 건 `_reload_one()` 으로 현재
파서 재적재를 하므로 **`pending` 건의 stale 은 캠페인이 저절로 해소한다**. 이 스캔을
전수로 돌릴 이유는 없고, **캠페인이 영영 안 지나가는 건**(`status IN ('pass','blocked')`)
에만 돌리면 된다 — 2026-09-19 기준 454건, 3분. 전수(104,153건)는 2시간이 걸리는데
그중 107,131건은 "곧 저절로 고쳐질 것"을 미리 세는 낭비다(사용자 지적).

비교 규약:
  · DB 에 적재되는 것은 `col_index=0`(당기) 행뿐(`_is_loadable`) → 비교도 거기로 맞춘다.
  · 키 = (statement, basis, label, EPS경로 여부, value_won) 의 **멀티셋**.
    같은 라벨이 한 표에 여러 번 나오는 서식(보통주/우선주 등)이 흔해 집합/딕셔너리로
    비교하면 충돌한다 — 개수까지 세는 멀티셋이라야 한다.
  · `section_path` 는 비교에서 **제외**한다. R145 가 EPS 행의 값을 안 바꾸고 경로만
    바꾸므로, 넣으면 2015+ EPS 보유 필링이 전부 "차이 있음"으로 나와 신호가 죽는다.

★**원문은 SD카드 미러에서 읽는다**(`--read-root`, 기본 `/Volumes/dart_data/raw_report`).
DB `file_path` 는 NAS(SMB) 심링크를 가리키는데, 수만 건 소파일 랜덤 접근을 SMB 로 하면
몇 분간 진척 0 이다가 조용히 죽는다(실측 재현: 이 스캔 1차 시도에서 10분/0건, 그리고
2026-08-15 `find`·`grep` 전수 스캔 사고). 심링크 자체는 건드리지 않는다 — 프로덕션
경로는 NAS 가 main 이고, SD 로 되돌린 것이 과거 drift 사고 원인이었다.
SD 는 폴백 미러라 최신성 100% 보장이 아니므로, **없으면 원래 경로로 폴백**하고 그
건수를 보고한다(`n_fallback`).

사용:
    python scripts/scan_report_lines_stale_vs_parser.py --shard 0 --shards 8 \
        --out logs/stale_shard0.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from fin2.extract.report_lines import extract_report_lines  # noqa: E402


def _key(statement, basis, label, is_eps, value):
    return (statement, basis, (label or "").strip(), is_eps, int(value))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--year-min", type=int, default=2015)
    ap.add_argument("--never-revisited", action="store_true",
                    help="캠페인이 안 지나가는 건만(status IN ('pass','blocked')). "
                         "평소엔 이걸 쓴다 — 위 docstring '쓰는 자리' 참고.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--read-root", default="/Volumes/dart_data/raw_report",
                    help="원문을 읽을 미러 루트(위 docstring 참고). 빈 문자열이면 DB 경로 그대로.")
    ap.add_argument("--nas-root", default="/Users/taejin/Project/tj_finance/raw_report",
                    help="DB file_path 안에서 --read-root 로 치환할 접두사")
    args = ap.parse_args()

    def _resolve(p: str) -> tuple[str, bool]:
        """(읽을 경로, 폴백여부). SD 미러에 없으면 원래(NAS) 경로로 되돌린다."""
        if not args.read_root or not p.startswith(args.nas_root):
            return p, False
        alt = args.read_root + p[len(args.nas_root):]
        return (alt, False) if Path(alt).exists() else (p, True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 재시작 가능: 이미 기록한 rcept 는 건너뛴다.
    done: set[str] = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    done.add(json.loads(line)["rcept_no"])
                except Exception:  # noqa: BLE001
                    pass
    print(f"[shard {args.shard}] 이미 처리 {len(done)}", flush=True)

    with get_session() as s:
        rows = s.execute(text("""
            SELECT dt.rcept_no, dt.file_path, f.fiscal_year, f.fiscal_period, f.corp_code
            FROM download_tasks dt JOIN filings f USING(rcept_no)
            WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
              AND f.fiscal_year >= :ymin
              AND EXISTS (SELECT 1 FROM report_lines rl WHERE rl.rcept_no=dt.rcept_no)
              AND ('x' || substr(md5(dt.rcept_no), 1, 8))::bit(32)::bigint % :n = :k
              AND (NOT :only_nr OR EXISTS (
                    SELECT 1 FROM layer2_review_queue q
                    WHERE q.rcept_no = dt.rcept_no AND q.status IN ('pass','blocked')))
            ORDER BY dt.rcept_no
        """), {"ymin": args.year_min, "n": args.shards, "k": args.shard,
                 "only_nr": args.never_revisited}).fetchall()
        rows = [r for r in rows if r.rcept_no not in done]
        if args.limit:
            rows = rows[:args.limit]
        print(f"[shard {args.shard}] 대상 {len(rows)}", flush=True)

        fh = out.open("a", encoding="utf-8")
        n_diff = n_fallback = 0
        for i, r in enumerate(rows, 1):
            rec = {"rcept_no": r.rcept_no, "corp_code": r.corp_code,
                   "fy": r.fiscal_year, "fp": r.fiscal_period}
            read_path, fell_back = _resolve(r.file_path)
            if fell_back:
                n_fallback += 1
                rec["nas_fallback"] = True
            try:
                db = Counter(
                    _key(x.statement, x.basis, x.label_raw,
                         (x.source_ref or "").startswith("eps/"), x.value_won)
                    for x in s.execute(text("""
                        SELECT statement, basis, label_raw, source_ref, value_won
                        FROM report_lines
                        WHERE rcept_no = :r AND col_index = 0 AND value_won IS NOT NULL
                    """), {"r": r.rcept_no}))
                cur = Counter(
                    _key(l.statement, l.basis, l.label_raw,
                         l.source_ref.startswith("eps/"), l.value_won)
                    for l in extract_report_lines(
                        read_path, rcept_no=r.rcept_no, corp_code=r.corp_code,
                        report_fiscal_year=r.fiscal_year,
                        report_fiscal_period=r.fiscal_period, include_notes=False)
                    if l.col_index == 0 and l.value_won is not None)
                gone, added = db - cur, cur - db
                rec["n_db"], rec["n_cur"] = sum(db.values()), sum(cur.values())
                rec["gone"], rec["added"] = sum(gone.values()), sum(added.values())
                if gone or added:
                    n_diff += 1
                    rec["sample_gone"] = [list(k) for k in list(gone)[:6]]
                    rec["sample_added"] = [list(k) for k in list(added)[:6]]
            except Exception as e:  # noqa: BLE001
                rec["err"] = f"{type(e).__name__}: {e}"
                rec["tb"] = traceback.format_exc()[-400:]
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if i % 50 == 0:
                fh.flush()
                print(f"[shard {args.shard}] {i}/{len(rows)} 차이 {n_diff} "
                      f"NAS폴백 {n_fallback}", flush=True)
        fh.close()
        print(f"[shard {args.shard}] 완료 — {len(rows)}건 중 차이 {n_diff}, "
              f"NAS폴백 {n_fallback}", flush=True)


if __name__ == "__main__":
    main()
