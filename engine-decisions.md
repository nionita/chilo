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
