"""Exact-duplicate line drop for .plain corpora — Stage 3 step 0 (July 2026).

Duplicate games in the v2 corpus come from restart-amnesia stem replays
(10M mini-audit: ~1.2% of games, max replay 3). Because the engine is
deterministic at fixed nodes, a replayed game emits byte-identical lines,
so exact line dedup removes them completely; unrelated games never emit
identical lines (eval + FEN counters differ). Runs BEFORE SF18 relabeling
so the relabeler (and its parallel chunks) see an already-unique corpus.

Key: 8-byte blake2b of the raw line (deterministic across runs/processes;
~2.5 GB peak set memory at 50M lines).

Usage:
    python -m scripts.dedup_plain --input "C:/torch_data/selfplay_v2.shard*.plain" \
        --output C:/torch_data/selfplay_v2_dedup.plain
"""

import argparse
import glob
import hashlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser(description="Drop exact-duplicate lines from .plain shards")
    ap.add_argument("--input", required=True, help="path or glob of input .plain files")
    ap.add_argument("--output", required=True, help="single deduped output .plain")
    args = ap.parse_args()

    files = sorted(glob.glob(args.input))
    if not files:
        sys.exit(f"no files match {args.input}")
    print(f"deduping {len(files)} file(s) -> {args.output}")

    seen: set[int] = set()
    kept = dropped = 0
    t0 = time.time()
    with open(args.output, "w", encoding="utf-8") as out:
        for path in files:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    h = int.from_bytes(
                        hashlib.blake2b(line.encode("utf-8"), digest_size=8).digest(), "big")
                    if h in seen:
                        dropped += 1
                        continue
                    seen.add(h)
                    out.write(line)
                    kept += 1
            print(f"  {path}: cumulative kept {kept:,} dropped {dropped:,}", flush=True)

    el = time.time() - t0
    print(f"\ndone in {el/60:.1f} min: kept {kept:,}  dropped {dropped:,} "
          f"({100*dropped/max(kept+dropped,1):.3f}%)")


if __name__ == "__main__":
    main()
