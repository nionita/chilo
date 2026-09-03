# Engine Decisions

This is a durable record of non-obvious engineering decisions. The current
source code and current-state notes remain authoritative. Historical entries
preserve rationale and experiment results, not old behavior as a specification.

Status labels:

- **CURRENT**: reflected by current code and documentation.
- **HISTORICAL-BUT-USEFUL**: no longer a current choice, but useful context.
- **SUPERSEDED**: deliberately replaced by a later design.
- **REJECTED**: tried and not retained.
- **OPEN**: a plausible future improvement without an accepted solution.
- **PLANNED**: an accepted change intentionally deferred to a later version
  change; current source still describes the live behavior.
- **UNCERTAIN**: the historical evidence does not establish a conclusion.

## Core And Validation

- **CURRENT**: `engine.h` is the public boundary. Keep engine behavior in
  implementation files behind it; `chess.h` is compatibility-only. This keeps
  perft tools and tests independent from search/UCI changes.
- **CURRENT**: retain the hybrid position representation and magic-bitboard
  slider lookups. A direct ray-emission rewrite was measured slower; magic
  lookups improved the then-current reference perft workload from about
  `25.6M` to `33.3M nps`.
- **CURRENT**: full semantic `doMove()`/`undo()` restoration checking belongs
  in validation builds only. Running the full comparison recursively in normal
  perft made a large cached `Position` roughly eight times slower. Cheap local
  assertions remain appropriate in normal development builds.

## Search Decisions

- **CURRENT**: assess search changes with fixed-depth wall time, node counts,
  PVs, tactical regressions, and SPRT where strength is claimed. NPS alone is
  insufficient because early returns and changed tree shape affect its meaning.
- **CURRENT**: futility-margin candidate generation is external to the engine.
  The engine exposes bounded search and per-search margins; `futility_probe`
  applies tuples to a corpus with equal node budgets and isolated TT state.
  Proxy results can screen candidates, but only SPRT establishes strength.
- **CURRENT**: SEE uses `P/N/B/R/Q = 100/330/330/500/900`. Equal knight and
  bishop values are required for exchange symmetry: unequal values classified
  bishop-for-knight exchanges as SEE-negative and incorrectly filtered them
  from non-check QS.
- **SUPERSEDED**: the broader SEE table `100/330/330/550/1000` was tried but
  the current code restored rook/queen values. Rook/queen guesses affect more
  than ordering: SEE, QS filtering, delta bounds, and promotion gains.
- **HISTORICAL-BUT-USEFUL**: the optional
  `CHILO_TT_ALWAYS_OVERWRITE` replacement policy was mixed and below one
  percent in TT-pressure benchmarks. The default deeper-entry protection stays
  in place unless a new corpus shows a meaningful win.
- **REJECTED**: skipping non-check QS underpromotions reduced nodes by only
  about `0.05%` on an opening-heavy 1,000-position benchmark and slightly
  worsened elapsed time. It is not in the current branch.
- **HISTORICAL-BUT-USEFUL**: a depth-one futility margin of `80`, combined
  with enabling futility in check, was accepted in a historical SPRT but the
  current margin is `120`. Do not treat `80` as current tuning.
- **UNCERTAIN**: no preserved result explains why the historical depth-one
  `80` setting was not carried into the current line. Current futility margins
  are starting points, not NNUE-independent constants.

### Move-Ordering Node Experiment — 2026-09-03

The fixed-depth move-ordering experiment used all 25,783 FENs in
`~/Tune/open-moves/open-moves.fen` (SHA-256
`5280ff9be9fd27af3443fafb10430a25a00fc0af66022829a5abf45d299c1122`),
the runtime net `chilo-g4t1-64x8.bin` (SHA-256
`51ee64101ee3d85f69eb0948f4caa8be6d90115abdb909d82767ffb4a53ccd90`),
and the common spsa150b futility tuple `0,40,158,488,754`. Every candidate
was a Windows AVX2 binary and every root was searched at the stated fixed
depth with a fresh process/TT. These are search-tree efficiency measurements,
not score-quality or playing-strength evidence.

`GC` denotes a non-negative-SEE capture; `BC` a negative-SEE capture. The
actual tested order and aggregate nodes were:

| Variant | Tested order after TT | Depth-7 nodes | D7 vs current | Depth-8 nodes | D8 vs current |
|---|---|---:|---:|---:|---:|
| current | GC → killers → non-capture promotions → quiets → BC | 1,480,193,669 | baseline | 3,529,987,693 | baseline |
| ordA | all queen promotions → GC → killers → minor non-capture promotions → quiets → BC | 1,480,487,823 | +0.019873% | 3,530,679,905 | +0.019609% |
| ordB | GC → all promotions → killers → quiets → remaining BC | **1,480,165,003** | **−0.001937%** | **3,529,832,083** | **−0.004408%** |
| ordC | GC → all promotions → killers → remaining BC → quiets | 1,495,792,079 | +1.053809% | 3,546,274,920 | +0.461396% |
| ordD | GC → non-capture queen promotions → killers → non-capture R/B/N promotions → quiets → BC | — | — | 3,529,889,618 | −0.002778% |

In ordB and ordC, the generic promotion branch precedes the remaining-capture
branch: a negative-SEE capture-promotion is therefore in the promotion group.
In ordD, every capture-promotion remains a capture and is separated by SEE.

The depth-8 non-PV beta-cutoff counters (`TT`, capture, killer, quiet,
promotion, other) were:

| Variant | cut_tt | cut_cap | cut_killer | cut_quiet | cut_promo | cut_other |
|---|---:|---:|---:|---:|---:|---:|
| current | 122,542,294 | 427,074,643 | 85,401,969 | 12,442,368 | 1,922 | 4,575,681 |
| ordA | 122,528,772 | 426,860,545 | 85,390,987 | 12,442,293 | 248,101 | 4,576,149 |
| ordB | 122,536,727 | 427,066,053 | 85,392,650 | 12,441,881 | 7,829 | 4,575,326 |
| ordC | 122,027,873 | 426,918,264 | 83,952,999 | 11,610,430 | 7,285 | 4,439,199 |
| ordD | 122,539,290 | 427,073,823 | 85,394,426 | 12,442,143 | 7,284 | 4,575,843 |

`cut_tt` is a beta cutoff caused by the TT-preferred move after it was
searched, not a direct TT-probe cutoff. The counters describe the cutoffs in
the visited tree; their absolute total is not an efficiency objective. In
particular, ordC searches substantially more nodes while recording fewer
cutoffs.

- **CURRENT**: ordB was adopted for version `0.7.6`. It is the lowest-node
  order at both measured depths. OrdD is close but is 57,535 nodes
  (0.001630%) behind ordB at depth 8; ordA is consistently a small loss; and
  ordC rejects moving negative-SEE captures before quiet moves. The archived
  depth-8 Windows result is
  `~/Tune/futility/chilo-move-order-d8-win-package-rez.zip` (SHA-256
  `b979b990a75872ded4aa817b170329c3ef8cd2115e119166f7876775b8c35fd8`).

## NNUE And Training

- **CURRENT**: use two white/black perspective accumulators and present them
  to dense inference as `[side-to-move, opponent]`. This replaced an
  unnecessary four-lane layout, shares the feature transformer, and is the
  foundation for the second dense hidden layer.
- **CURRENT**: per-ply accumulator frames use copy-plus-apply, so child return
  needs no NNUE undo. Low-piece subtrees rebuild instead because frame copying
  is not a net win there. `evaluate(pos)` remains the rebuild reference.
- **CURRENT**: NNUE export is an exact cross-language contract. C++ inference,
  Python parity, QAT scales, generated headers, manifests, and runtime `.bin`
  metadata must change together.
- **HISTORICAL-BUT-USEFUL**: on older Gen2/Gen3 data, seeded-noise
  initialization produced much stronger nets than plain random in at least one
  controlled comparison, despite worse export drift. The useful explanation is
  its chess prior and centipawn-scale output, not export density.
- **OPEN**: current Gen4 architecture and QAT-scale choices are recorded only
  in `nnue-qat-scale-experiments.md`. Validation loss screens candidates; it
  does not establish playing strength.

## Data Collection

- **CURRENT**: collect evaluated search leaves rather than raw played
  positions, because quiet leaves are better evaluation targets. The final game
  result is a deliberately noisy, off-trajectory bootstrap label, not tablebase
  truth.
- **CURRENT**: exclude terminal and in-check leaves, leaves below the configured
  piece count, and near-fifty-move samples from drawn games. These filters avoid
  labels the network cannot represent or that were especially noisy in early
  shallow self-play.
- **HISTORICAL-BUT-USEFUL**: shallow depth-four collection exposed implausible
  trivial-endgame labels. This was not evidence of a sign/FEN bookkeeping bug;
  it motivated deeper collection and the current filters.

## UCI On Windows

- **CURRENT**: Windows builds default to synchronous search because a
  timing-dependent per-`go` worker-thread lifecycle failure can occur when a
  GUI sends `isready` immediately after `bestmove`. Faster small NNUE nets made
  the race easier to reproduce; it is not an AVX2 or network-format failure.
- **OPEN**: replace per-search thread creation/join with a persistent search
  worker or manager. It must preserve responsive `stop` and `quit`; synchronous
  search is a practical workaround, not the final UCI design.

## Version And Experiment Caveats

- **CURRENT**: a net comparison is not net-only when engine versions differ.
  In particular, the `g3hl2q3` versus `g3t5` SPRT compares `0.7.4` against a
  `0.6.16` base, so its result cannot be attributed solely to NNUE weights.
- **HISTORICAL-BUT-USEFUL**: `0.7.x` includes the later `0.6.15/.16` SEE/QS
  technical work but not the `0.6.17` QS-underpromotion experiment.
