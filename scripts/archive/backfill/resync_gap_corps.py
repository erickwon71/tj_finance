"""
갭 기업 타깃 force 재싱크
==========================
check_period_completeness.py가 생성한 기업별 로그
(logs/coverage/{corp_code}_{name}.missing_download.log)에서
갭 있는 기업 corp_code를 추출해 force 재싱크한다.

목적: NOFIL(공시 미등록) 갭이 DART list 싱크 누락인지(복구 가능)
      구조적 부재인지(복구 불가) 확정 검증.

이후:
    python3 run.py download                          # 새로 등록된 공시 다운로드
    python3 scripts/check_period_completeness.py      # 갭 재확인

사용법:
    python3 scripts/resync_gap_corps.py [--log-dir logs/coverage] [--dry-run]
"""
import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가 (collector 패키지 import용)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def collect_gap_codes(log_dir: Path) -> list[str]:
    codes = []
    for p in sorted(log_dir.glob("*.missing_download.log")):
        # 파일명: {corp_code}_{safe_name}.missing_download.log
        code = p.name.split("_", 1)[0]
        if code.isdigit() and len(code) == 8:
            codes.append(code)
    # 중복 제거 (순서 유지)
    return list(dict.fromkeys(codes))


def main():
    ap = argparse.ArgumentParser(description="갭 기업 타깃 force 재싱크")
    ap.add_argument("--log-dir", default="logs/coverage")
    ap.add_argument("--dry-run", action="store_true",
                    help="대상 corp_code만 출력, 재싱크 안 함")
    args = ap.parse_args()

    log_dir = Path(args.log_dir)
    codes = collect_gap_codes(log_dir)
    print(f"갭 기업 corp_code: {len(codes)}개")

    if not codes:
        print("대상 없음 — 갭 기업 로그가 없습니다 (먼저 check_period_completeness.py 실행).")
        return

    if args.dry_run:
        for c in codes:
            print(f"  {c}")
        print("\n[DRY-RUN] 재싱크 안 함.")
        return

    # sync_filings는 corp_codes 리스트를 한 프로세스에서 처리
    from collector.filing_collector import sync_filings
    print(f"force 재싱크 시작 — {len(codes)}개 기업 (DART list API)...")
    result = sync_filings(corp_codes=codes, force=True)
    print(f"완료: {result}")
    print("\n다음 단계:")
    print("  python3 run.py download                       # 새로 등록된 공시 다운로드")
    print("  python3 scripts/check_period_completeness.py   # 갭 재확인")


if __name__ == "__main__":
    main()
