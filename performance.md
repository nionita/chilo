# Performance Notes

This file records measured speed findings and likely optimization directions. Keep it factual: update the numbers when the engine or workload changes.

## 2026-04-22 Baseline Profile Run

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

## 2026-04-22 Delta Apply/Undo Optimization

The first optimization changed NNUE delta apply/undo so that runtime-net lookup and accumulator validity checks happen once per `NnueMoveDelta`, not once per feature change. It also split add/subtract paths to avoid `sign * weight` in the hidden loop.

The same `gprof` workload searched the same node counts and produced the same PVs. The generated report was written locally to `/tmp/chilo-gprof-after-delta-opt.txt`.

Top flat-profile self time after the change:

| Function | Self time |
| --- | ---: |
| `updateAccumulatorFeatureUnchecked` | 32.66% |
| `doMove` | 14.02% |
| `undo` | 6.79% |
| `quiescence` | 6.07% self |
| `evaluateWithAccumulator` | 5.78% |
| `orderMoves` | 4.77% |
| `inCheck` | 4.34% |
| `genPseudoMoves` | 3.76% |
| `genLegalPseudoMoves` | 3.03% |
| `probeTT` | 2.60% |

The wrapper functions themselves dropped to `0.58%` for `applyNnueDelta` and `0.72%` for `undoNnueDelta`. The remaining NNUE accumulator cost is now the unavoidable lane update loop plus offset calculation in `updateAccumulatorFeatureUnchecked`.

The total sampled time for this instrumented workload moved from about `7.34s` to `6.92s`, roughly a `5.7%` reduction. Reported engine times also improved with identical node counts:

| Position | Before | After |
| --- | ---: | ---: |
| start position depth 11 | 4127 ms | 3956 ms |
| middlegame depth 11 | 4753 ms | 4627 ms |
| tactical depth 11 | 2471 ms | 2391 ms |
| sparse KQK depth 12 | 51 ms | 48 ms |

## 2026-04-22 Portable Kernel Reshape

The second optimization kept the code portable but reshaped `updateAccumulatorFeatureUnchecked`: instead of nested color/perspective loops, it now computes the four fixed accumulator lanes directly and calls small lane add/subtract helpers.

The same `gprof` workload searched the same node counts and produced the same PVs. The generated report was written locally to `/tmp/chilo-gprof-after-kernel-reshape.txt`.

Top flat-profile self time after the reshape:

| Function | Self time |
| --- | ---: |
| `doMove` | 16.57% |
| `updateAccumulatorFeatureUnchecked` | 13.77% |
| `undo` | 10.98% |
| `inCheck` | 7.78% |
| `evaluateWithAccumulator` | 6.19% |
| `orderMoves` | 5.79% |
| `quiescence` | 5.19% self |
| `probeTT` | 4.59% |
| `genPseudoMoves` | 4.59% |
| `genLegalPseudoMoves` | 3.59% |

`updateAccumulatorFeatureUnchecked` dropped from `32.66%` to `13.77%` of sampled self time. Total sampled time for the instrumented workload moved from about `6.92s` to `5.01s`, roughly a `27.6%` reduction from the previous profile and about `31.7%` lower than the original baseline profile.

Reported engine times with identical node counts:

| Position | Previous | After |
| --- | ---: | ---: |
| start position depth 11 | 3956 ms | 3396 ms |
| middlegame depth 11 | 4627 ms | 3922 ms |
| tactical depth 11 | 2391 ms | 2109 ms |
| sparse KQK depth 12 | 48 ms | 49 ms |

## 2026-04-22 AVX2 Build Variant

An optional compile-time AVX2 path was added for accumulator lane add/subtract. The portable build remains the default; AVX2 binaries are built with `-DCHILO_AVX2 -mavx2` and require AVX2-capable CPUs.

The same `gprof` workload searched the same node counts and produced the same PVs. The generated report was written locally to `/tmp/chilo-gprof-after-avx2.txt`.

Top flat-profile self time for the AVX2 build:

| Function | Self time |
| --- | ---: |
| `doMove` | 17.17% |
| `undo` | 10.98% |
| `updateAccumulatorFeatureUnchecked` | 10.78% |
| `orderMoves` | 9.18% |
| `inCheck` | 6.39% |
| `alphaBeta` | 5.79% |
| `quiescence` | 5.59% self |
| `genPseudoMoves` | 5.19% |
| `genLegalPseudoMoves` | 4.59% |
| `evaluateWithAccumulator` | 4.39% |

`updateAccumulatorFeatureUnchecked` dropped from `13.77%` to `10.78%` of sampled self time. Total sampled time stayed at about `5.01s`, which is likely within `gprof` sampling noise at this workload size, but reported engine times improved with identical node counts:

| Position | Portable | AVX2 |
| --- | ---: | ---: |
| start position depth 11 | 3396 ms | 3209 ms |
| middlegame depth 11 | 3922 ms | 3681 ms |
| tactical depth 11 | 2109 ms | 1983 ms |
| sparse KQK depth 12 | 49 ms | 47 ms |

## Likely Optimization Directions

1. Make NNUE delta apply/undo cheaper.

   The wrapper cleanup, portable four-lane reshape, and optional AVX2 build path have been done. Remaining candidate changes: precompute per-feature lane offsets in `NnueMoveDelta` or add hidden-size specializations.

2. Reduce legal move generation overhead.

   Candidate changes: replace pseudo-legal plus full make/unmake legality filtering with pinned/check-aware legal generation, or at least add faster legality checks for common non-king moves.

3. Treat QS as a separate optimization target.

   Candidate changes: tighten noisy move generation/filtering, avoid redundant SEE/order work, and benchmark QS changes by fixed-depth wall time, not only NPS.

4. Profile again after each substantial change.

   The current profile is useful for direction, but `gprof` has limitations with optimized C++ and inlining. If `perf` becomes available, prefer `perf record -g` on an `-O3 -g -fno-omit-frame-pointer` binary.
