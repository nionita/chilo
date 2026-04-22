# Performance Notes

This file records measured speed findings and likely optimization directions. Keep it factual: update the numbers when the engine or workload changes.

## 2026-04-22 Profile Run

`perf` could not be used on this machine because `/proc/sys/kernel/perf_event_paranoid` is `4`. The fallback run used an optimized `gprof` binary:

```sh
g++ -std=c++17 -Wall -Wextra -pedantic -O3 -DNDEBUG -pg -g -fno-omit-frame-pointer \
    -o build/profile/chilo_gprof \
    chilo.cpp attack.cpp movegen.cpp make_unmake.cpp perft_lib.cpp eval.cpp search.cpp
```

The workload was four fixed-depth UCI searches with built-in weights:

- start position, depth 11
- middlegame test FEN, depth 11
- tactical test FEN, depth 11
- sparse KQK endgame FEN, depth 12

The run searched about 7.1M counted nodes. The generated report was written locally to `/tmp/chilo-gprof-report.txt`.

## Hotspots

Top flat-profile self time from the `gprof` run:

| Function | Self time |
| --- | ---: |
| `applyNnueDelta` | 19.35% |
| `undoNnueDelta` | 18.53% |
| `doMove` | 13.49% |
| `undo` | 9.54% |
| `evaluateWithAccumulator` | 5.59% |
| `quiescence` | 5.04% self, 65.1% inclusive |
| `orderMoves` | 5.04% |
| `inCheck` | 3.54% |
| `genPseudoMoves` | 3.41% |
| `probeTT` | 2.59% |

## Interpretation

The largest measured cost is NNUE accumulator maintenance. `applyNnueDelta` and `undoNnueDelta` together account for about 38% of sampled self time. The expensive path is `updateAccumulatorFeature`, which currently checks the runtime net, computes offsets, and updates all accumulator lanes for every feature add/remove.

Legal move generation is the second major cost cluster. `genLegalPseudoMoves` generates pseudo-legal moves, then tests each candidate by doing `doMove`, calling `inCheck`, and undoing the move. This explains why `doMove`, `undo`, and `inCheck` are all high in the profile.

Quiescence search dominates inclusive time. Most accumulator apply/undo calls happen below QS, so QS-specific pruning and move filtering can have a large speed effect even if their own flat self time is modest.

NPS alone can hide some changes because not every early return is counted as a searched node. Fixed-depth wall time with identical node counts is more reliable for small speed comparisons.

## Likely Optimization Directions

1. Make NNUE delta apply/undo cheaper.

   Candidate changes: avoid repeated `currentNnue()` and accumulator-validity checks in the inner feature update path, precompute per-feature lane offsets in `NnueMoveDelta`, and consider specialized code paths for common hidden sizes.

2. Reduce legal move generation overhead.

   Candidate changes: replace pseudo-legal plus full make/unmake legality filtering with pinned/check-aware legal generation, or at least add faster legality checks for common non-king moves.

3. Treat QS as a separate optimization target.

   Candidate changes: tighten noisy move generation/filtering, avoid redundant SEE/order work, and benchmark QS changes by fixed-depth wall time, not only NPS.

4. Profile again after each substantial change.

   The current profile is useful for direction, but `gprof` has limitations with optimized C++ and inlining. If `perf` becomes available, prefer `perf record -g` on an `-O3 -g -fno-omit-frame-pointer` binary.
