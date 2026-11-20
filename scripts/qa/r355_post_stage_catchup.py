"""R355 catch-up: run the daily post stages (⑤ Gate B, biz annual/periodic, order backlog, doc
sections) for corps with downloaded filings never marked in pipeline_post_stage_done, in chunks,
marking each chunk as it finishes. Stops starting new chunks after --until (HH:MM, local time) so
it does not overlap the 18:00 daily; whatever is left the daily picks up itself (R355).

usage: python scripts/qa/r355_post_stage_catchup.py --chunk 50 --until 17:40
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(1, str(Path(__file__).resolve().parents[1]))  # run_dq_gate imports gateb_audit

from loguru import logger  # noqa: E402

from app.data import collect  # noqa: E402
from scripts import collect_new  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", type=int, default=50)
    ap.add_argument("--until", default="17:40")
    a = ap.parse_args()
    hh, mm = (int(x) for x in a.until.split(":"))
    stop = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
    args = SimpleNamespace(no_verify=False, verify_fy_min=2015, verify_full=False)
    collect_new.POST_STAGE_CATCHUP_MAX = a.chunk
    k = 0
    while datetime.now() < stop:
        left = len(collect.post_stage_pending())
        if not left:
            break
        k += 1
        logger.info(f"[r355] chunk {k} — pending corps {left}")
        collect_new._run_post_stages({"ok_corps": []}, args, [])
    logger.info(f"[r355] done — chunks {k}, pending corps {len(collect.post_stage_pending())}")


if __name__ == "__main__":
    main()
