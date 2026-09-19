"""R144 백필 대상 스캔 — 원문 XML 안에서 **숫자 하나가 줄바꿈으로 쪼개진** 필링 찾기.

배경: 제출인이 금액 하나를 **인라인 태그 두 개로 쪼개** 담는 경우가 있다 — 실측
(삼성생명 20210517001864 연결BS):

    <TD ALIGN="RIGHT">
    <SPAN>22,270,03</SPAN>
    <SPAN>9</SPAN>
    </TD>

셀 텍스트를 뽑으면 태그 사이 공백이 그대로 남아 `'22,270,03\\n9'` 가 된다. 그런데
`parse_amount`/`_split_label_amounts_ex` 가 반각·전각·ZWSP·NBSP 공백은 지우면서 개행만
안 지워, 이 셀이 "숫자 아님"으로 판정돼 **행이 통째로 사라지거나** 뒤 열이 당기 열로
밀렸다(docs/PARSING_RULES.md R144 (4)).

이 결함은 **DB만으로는 셀 수 없다** — 유실된 행은 흔적을 안 남긴다. 그래서 원문 바이트를
직접 훑어 후보 필링을 추린다. 후보는 재적재(`reload_report_lines_corp.py` 등)로 넘긴다.

판정: **숫자 → 인라인 태그 닫힘 → 인라인 태그 열림 → 숫자** 신호만 잡는다. 태그 이름을
인라인(SPAN/FONT/B/I/U/EM/STRONG)으로 한정해 `</TD>…<TD>`(정상적인 옆 칸)를 배제한다.
바이트 정규식이라 인코딩(EUC-KR/UTF-8 혼재) 영향을 안 받는다 — 숫자·태그명·공백은 두
인코딩에서 같은 ASCII 바이트다.

읽기 경로는 **SD 카드 로컬 미러**(`/Volumes/dart_data/raw_report`)로 바꿔 읽는다 —
NAS(SMB) 전수 스캔은 느리다(메모리 규칙 `feedback-bulk-read-use-sdcard`).

후보는 **넉넉히** 잡는다(주석 표 등 재무제표 밖 적중도 포함) — 재적재는 멱등이라
불필요한 1건을 더 도는 비용이 유실 1건을 놓치는 비용보다 싸다.

사용:
    python scripts/scan_intra_number_linebreak_r144.py --limit 500      # 표본
    python scripts/scan_intra_number_linebreak_r144.py --out /tmp/r144_hits.txt
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402

# NAS 경로 → SD 카드 로컬 미러(있을 때만).
_NAS_PREFIX = "/Volumes/tj_finance_data/raw_report"
_SD_PREFIX = "/Volumes/dart_data/raw_report"

# 인라인 태그 경계로 쪼개진 금액: '…03</SPAN>\n<SPAN>9…'.
# 태그명을 인라인으로 한정 — `</TD>…<TD>`(옆 칸)·`</TR>`(다음 행)은 안 잡힌다.
_INLINE = rb"(?:SPAN|FONT|B|I|U|EM|STRONG)"
_BROKEN_NUMBER_RE = re.compile(
    rb"[0-9][ \t]*</" + _INLINE + rb">[ \t\r\n]*<" + _INLINE + rb"[^>]*>[ \t]*[0-9,]"
    # 셀 안에 개행이 리터럴로 들어간 변형도 같이 본다(같은 증상, 다른 원문 표기).
    rb"|[0-9],[0-9]{0,3}[ \t]*\r?\n[ \t]*[0-9]",
    re.IGNORECASE,
)

_SQL = text("""
    SELECT DISTINCT ON (dt.rcept_no) dt.rcept_no, dt.file_path
      FROM download_tasks dt
     WHERE dt.status = 'completed'
       AND dt.file_type = 'xml'
       AND dt.file_path IS NOT NULL
       AND EXISTS (SELECT 1 FROM report_lines rl WHERE rl.rcept_no = dt.rcept_no)
     ORDER BY dt.rcept_no
""")


def _local(path: str) -> Path:
    """가능하면 SD 카드 미러 경로로 바꾼다(없으면 원 경로)."""
    if path.startswith(_NAS_PREFIX):
        sd = Path(_SD_PREFIX + path[len(_NAS_PREFIX):])
        if sd.exists():
            return sd
    return Path(path)


def _scan_one(item: tuple[str, str]) -> tuple[str, int]:
    """(rcept_no, 상태) — 상태 1=적중 0=미적중 -1=파일없음. 워커 프로세스에서 실행."""
    rcept, path = item
    try:
        data = _local(path).read_bytes()
    except OSError:
        return rcept, -1
    return rcept, (1 if _BROKEN_NUMBER_RE.search(data) else 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="표본 개수(처리량 측정용)")
    ap.add_argument("--out", type=str, default=None, help="적중 rcept_no 목록 저장 경로")
    ap.add_argument("--workers", type=int, default=8, help="병렬 프로세스 수(기본 8)")
    ap.add_argument("--resume", action="store_true",
                    help="중단된 스캔 이어서(--out 의 .progress 파일 기준)")
    args = ap.parse_args()

    with get_session() as s:
        rows = [(r.rcept_no, r.file_path) for r in s.execute(_SQL).fetchall()]
    if args.limit:
        rows = rows[: args.limit]

    # ★중간 체크포인트(필수) — 전수 스캔은 수십 분이라 중간에 죽으면 진행이 다 날아간다.
    #   적중은 **찾는 즉시** append 하고, 진행 위치는 별도 파일에 남겨 `--resume` 으로
    #   이어서 돌린다(`ex.map` 은 입력 순서를 보존하므로 인덱스로 건너뛰면 된다).
    out_path = Path(args.out) if args.out else None
    prog_path = Path(str(out_path) + ".progress") if out_path else None
    start = 0
    if args.resume and prog_path and prog_path.exists():
        start = int(prog_path.read_text().strip() or 0)
        print(f"재개: 앞 {start}건 건너뜀")
    todo = rows[start:]
    if out_path and not args.resume:
        out_path.write_text("", encoding="utf-8")

    hits_n = missing = scanned = 0
    t0 = time.time()
    fh = out_path.open("a", encoding="utf-8") if out_path else None
    try:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for i, (rcept, state) in enumerate(
                    ex.map(_scan_one, todo, chunksize=64), 1):
                if state < 0:
                    missing += 1
                else:
                    scanned += 1
                    if state:
                        hits_n += 1
                        if fh:
                            fh.write(rcept + "\n")
                if i % 2000 == 0:
                    if fh:
                        fh.flush()
                    if prog_path:
                        prog_path.write_text(str(start + i), encoding="utf-8")
                if i % 20000 == 0:
                    el = time.time() - t0
                    print(f"  …{start + i}/{len(rows)}  적중 {hits_n}  "
                          f"{i / el:.0f} files/s  경과 {el / 60:.1f}분", flush=True)
    finally:
        if fh:
            fh.close()
        if prog_path:
            prog_path.write_text(str(len(rows)), encoding="utf-8")

    el = time.time() - t0
    print(f"\n대상 {len(rows)} · 스캔 {scanned} · 파일없음 {missing} · "
          f"적중 {hits_n} · {el:.1f}초 ({scanned / max(el, 0.001):.0f} files/s)")
    if out_path:
        print(f"적중 목록: {out_path}")


if __name__ == "__main__":
    main()
