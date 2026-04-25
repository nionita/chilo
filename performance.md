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

## 2026-04-25 Branch Baseline Before Accumulator-Frame Experiment

The `codo` branch starts from the original lazy-delta NNUE search implementation: one shared accumulator, one pending-delta stack, and `applyNnueDelta` / `undoNnueDelta` around each materialized child. Before changing that design, the same `gprof` build/workload was rerun on this branch for two NNUE sizes:

- built-in hidden size `24`
- runtime hidden size `40` from `/tmp/chilo-g2t5.bin`

The workload again used the three reproducible fixed-depth search positions from the repo plus the simple KQK probe `7k/8/8/8/8/8/8/KQ6 w - - 0 1` at depth `12`.

### Hidden 24 baseline

Top flat-profile self time:

| Function | Self time |
| --- | ---: |
| `doMove` | 21.96% |
| `updateAccumulatorFeatureUnchecked` | 12.50% |
| `undo` | 11.25% |
| `evaluateWithAccumulator` | 7.32% |
| `quiescence` | 6.61% self |
| `inCheck` | 6.25% |
| `orderMoves` | 5.71% |
| `genPseudoMoves` | 4.82% |
| `makeNnueMoveDelta` | 3.21% |
| `probeTT` | 3.21% |

Reported engine times:

| Position | Time |
| --- | ---: |
| start position depth 11 | 3398 ms |
| middlegame depth 11 | 3915 ms |
| tactical depth 11 | 2095 ms |
| KQK probe depth 12 | 395 ms |

### Hidden 40 baseline

Top flat-profile self time:

| Function | Self time |
| --- | ---: |
| `doMove` | 17.09% |
| `updateAccumulatorFeatureUnchecked` | 17.09% |
| `undo` | 9.17% |
| `evaluateWithAccumulator` | 8.81% |
| `inCheck` | 8.09% |
| `orderMoves` | 7.37% |
| `quiescence` | 5.58% self |
| `genPseudoMoves` | 4.14% |
| `alphaBeta` | 4.14% |
| `probeTT` | 3.96% |

Reported engine times:

| Position | Time |
| --- | ---: |
| start position depth 11 | 1221 ms |
| middlegame depth 11 | 4407 ms |
| tactical depth 11 | 2940 ms |
| KQK probe depth 12 | 337 ms |

For both baselines, NNUE delta maintenance is still a major hotspot. The larger hidden-size-40 net makes that more obvious: `updateAccumulatorFeatureUnchecked` rises to `17.09%` of flat time and `evaluateWithAccumulator` also grows.

## 2026-04-25 Per-Ply Accumulator Frames (`copy + apply`)

The search experiment on this branch replaces the lazy delta stack with per-ply accumulator frames. Each searched child now starts from a copy of the parent accumulator frame and applies its move delta once. Returning from the child does not undo NNUE state; the next sibling simply overwrites the child frame with a fresh parent copy plus delta.

The same profiling workflow was rerun for the same two NNUE sizes.

### Hidden 24 after `copy + apply`

Top flat-profile self time:

| Function | Self time |
| --- | ---: |
| `doMove` | 18.86% |
| `undo` | 11.62% |
| `inCheck` | 8.57% |
| `evaluateWithAccumulator` | 8.19% |
| `orderMoves` | 8.00% |
| `updateAccumulatorFeatureUnchecked` | 6.86% |
| `probeTT` | 4.95% |
| `genPseudoMoves` | 4.38% |
| `alphaBeta` | 4.38% |
| `quiescence` | 4.00% self |

`prepareChildSearchNnue` shows up at only `0.57%` self time, with `applyNnueDelta` also at `0.57%`.

Reported engine times:

| Position | Before | After |
| --- | ---: | ---: |
| start position depth 11 | 3398 ms | 3213 ms |
| middlegame depth 11 | 3915 ms | 3728 ms |
| tactical depth 11 | 2095 ms | 2012 ms |
| KQK probe depth 12 | 395 ms | 466 ms |

Total sampled time moved from about `5.60s` to `5.25s`, roughly a `6.3%` reduction on this workload.

### Hidden 40 after `copy + apply`

Top flat-profile self time:

| Function | Self time |
| --- | ---: |
| `doMove` | 17.06% |
| `undo` | 9.94% |
| `evaluateWithAccumulator` | 9.94% |
| `orderMoves` | 9.07% |
| `updateAccumulatorFeatureUnchecked` | 8.64% |
| `inCheck` | 8.21% |
| `probeTT` | 6.05% |
| `genPseudoMoves` | 5.83% |
| `genSlidingMoves` | 3.24% |
| `genLegalPseudoMoves` | 3.24% |

`prepareChildSearchNnue` shows up at `0.65%` self time, with `applyNnueDelta` also at `0.65%`.

Reported engine times:

| Position | Before | After |
| --- | ---: | ---: |
| start position depth 11 | 1221 ms | 1135 ms |
| middlegame depth 11 | 4407 ms | 4174 ms |
| tactical depth 11 | 2940 ms | 2759 ms |
| KQK probe depth 12 | 337 ms | 414 ms |

Total sampled time moved from about `5.56s` to `4.63s`, roughly a `16.7%` reduction on this workload.

This experiment is a clear improvement on the three main search positions for both hidden sizes. The main effect is that the accumulator-update kernel drops substantially:

- hidden `24`: `12.50%` -> `6.86%`
- hidden `40`: `17.09%` -> `8.64%`

The downside is that the trivial KQK probe becomes slower. That suggests the extra child-frame copy cost is not free when the tree is tiny and NNUE delta work was already small. On more realistic middlegame/tactical trees, however, avoiding incremental NNUE undo is a net win.

## Likely Optimization Directions

1. Make NNUE delta apply/undo cheaper.

   The wrapper cleanup, portable four-lane reshape, optional AVX2 build path, and now the per-ply accumulator-frame experiment have all been done. On this branch, `copy + apply` is the first search-side ownership change that clearly helps on the main workloads, especially for the larger hidden-size-40 net.

2. Reduce legal move generation overhead.

   After `copy + apply`, the dominant flat-time functions are again `doMove`, `undo`, `inCheck`, and move ordering/generation. Candidate changes: replace pseudo-legal plus full make/unmake legality filtering with pinned/check-aware legal generation, or at least add faster legality checks for common non-king moves.

3. Treat QS as a separate optimization target.

   Candidate changes: tighten noisy move generation/filtering, avoid redundant SEE/order work, and benchmark QS changes by fixed-depth wall time, not only NPS.

4. Profile again after each substantial change.

   The current profile is useful for direction, but `gprof` has limitations with optimized C++ and inlining. If `perf` becomes available, prefer `perf record -g` on an `-O3 -g -fno-omit-frame-pointer` binary.
