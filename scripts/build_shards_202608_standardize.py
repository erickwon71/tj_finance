"""Build 5 shard corp-code files for the 2026-08 xml-recovery standardize backlog
(app.data.collect.needs_standardize_corps()), matching the established
scripts/run_gateb_audit_parallel.sh shard-file convention.

Writes scratchpad/std202608_shard_{0..4}.txt (one corp_code per line).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data import collect  # noqa: E402

N_SHARDS = 5
OUT_DIR = Path(__file__).resolve().parent.parent / "scratchpad"
OUT_DIR.mkdir(exist_ok=True)

corps = sorted(collect.needs_standardize_corps())
print(f"총 대상: {len(corps)}개사")

shards = [[] for _ in range(N_SHARDS)]
for i, corp in enumerate(corps):
    shards[i % N_SHARDS].append(corp)

for i, s in enumerate(shards):
    path = OUT_DIR / f"std202608_shard_{i}.txt"
    path.write_text("\n".join(s) + "\n")
    print(f"{path}: {len(s)}개사")
