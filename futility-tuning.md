# Futility Margin Tuning

This is the persistent record for futility-margin experiments. The current
source defaults remain `120,320,550` through depth three. Proxy tuning only
selects SPRT candidates; it does not establish playing strength.

## Accepted SPRT Basis

`f21` is the current short-control playing basis: its 6+0.1 SPRT against
`f01` accepted H1. `f01` remains frozen as the reference control for futility
proxy optimization, baseline depth measurement, and candidate comparisons.
Do not replace or overwrite either binary.

| Binary | Margins | Status |
|---|---|---|
| `chilo-0.7.5-f01-avx2` | `120,240,360` | Accepted previous basis; frozen proxy control. |
| `chilo-0.7.5-f21-avx2` | `75,212,390,600,839` | H1 accepted versus f01 at 6+0.1; current practical playing candidate. |

The variant manifest for `f01` through `f06` is maintained externally at
`~/Tune/futility/futility-sprt-g4t1-64x8-d3-d5-first.json`.

## G3-SR1 Candidate Filter — 2026-08-21

The G3-SR1 filter used:

- corpus: `~/Tune/futility/g3-25k-seed990317.csv` (25,000 positions; 24,980 evaluated)
- net: `chilo-g4t1-64x8.bin`
- candidate budget: 40,000 nodes per position
- all-root reference budget: 320,000 cumulative nodes per position
- reference/baseline anchor: `~/Tune/futility/g3-sr1/`

The reference root-score memory is `probes/reference.jsonl`; it and the
candidate-budget baseline are reusable for later candidate-family changes.
The proxy baseline for this sweep was `120,320,550`, not `f01`.

## G3-SR2 Deep Reference Anchor — 2026-08-22

The follow-up anchor at `~/Tune/futility/g3-sr2/` uses the same corpus, net,
probe, and 40,000-node candidate baseline as G3-SR1, but raises the all-root
reference budget to 2,560,000 nodes per position. It completed at mean depth
10.107 (median 9, P90 13), versus 7.476 for the baseline.

Future G3-SR2 candidate ranking uses the fixed anchor-derived trusted set:
reference completed depth must be at least baseline completed depth plus one.
This keeps 23,007 of 24,980 evaluable positions (92.1%). The trusted set is
fixed before candidate probes, recorded by count and deterministic key hash in
`candidates_manifest.json`, and used identically for every family. Full-corpus
metrics remain diagnostics; do not filter raw probe evidence or choose a
candidate-specific position set.

## G3-SR2 Candidate Filter — 2026-08-22

Thirty linear and power tuples were searched at 40,000 nodes against the deep
G3-SR2 reference. All ranking metrics selected the same power-family winner:
mean trusted regret, trusted P90 regret, trusted move agreement, and trusted
mean completed depth. The top three are retained as separate SPRT candidates;
their external build manifest and receipt are
`~/Tune/futility/g3-sr2-sprt.json` and
`~/Tune/futility/g3-sr2-sprt.build-receipt.json`.

| Code | Trusted rank | Margins | Family | Mean regret | P90 regret | Move agreement | Mean depth | All-position mean regret |
|---|---:|---|---|---:|---:|---:|---:|---:|
| `f21` | 1 | `75,212,390,600,839` | power d5, scale 75, exponent 1.5 | 0.018260 | 0.054151 | 57.456% | 7.491 | 0.017023 |
| `f22` | 2 | `70,200,330` | linear d3, slope 130, intercept -60 | 0.018334 | 0.054698 | 57.330% | 7.451 | 0.017110 |
| `f23` | 3 | `75,244,485,792,1157` | power d5, scale 75, exponent 1.6 | 0.018371 | 0.054619 | 57.352% | 7.461 | 0.017129 |

Against the `120,320,550` proxy baseline, `f21` reduces trusted mean regret by
3.85%, raises trusted move agreement by 0.535 percentage points, and gains
0.162 completed plies. Its full-corpus diagnostics move in the same direction.
The older G3-SR1 mean/P90/agreement candidates rank 15th, 7th, and 12th under
this deeper trusted proxy, respectively.

## G3-SR2 f01 Control and 120k Follow-up — 2026-08-23

The 6+0.1 SPRT compared `f21` with accepted control `f01`, not with the
G3-SR2 source-style proxy baseline `120,320,550`. To make that direct proxy
comparison, `f01` was probed at 40,000 nodes using the existing G3-SR2
reference. Its returned JSONL used a remote source path, so it was validated
against the local reference by the complete `(input line, FEN)` identity; all
25,000 records matched.

On the original 40k trusted set, f01 ranks about 13th among the 30 G3-SR2
candidates. Both f01 and f21 are improvements over the source-style baseline,
and f21 remains an improvement over f01 in the proxy:

| Variant | Mean regret | P90 regret | Move agreement | Mean depth |
|---|---:|---:|---:|---:|
| source base `120,320,550` | 0.018990 | 0.056625 | 56.922% | 7.328 |
| `f01` `120,240,360` | 0.018671 | 0.055569 | 57.165% | 7.368 |
| `f21` `75,212,390,600,839` | 0.018260 | 0.054151 | 57.456% | 7.491 |

The paired mean-regret differences are negative in the better direction:
f01 minus source base is -0.000319 (95% interval -0.000513 to -0.000126),
and f21 minus f01 is -0.000411 (-0.000674 to -0.000149). These are proxy
intervals, not Elo intervals; they do not establish a conversion from regret
to playing strength.

The live 6+0.1 PGN shows that 40,000 nodes is not representative of most game
moves. For f21, recorded node counts were P10 67k, median 118k, mean 121k, and
P90 180k; only 1.9% of moves used fewer than 40k nodes. A serial cloud run
therefore probed f01/f21/f22/f23 at 120,000 nodes on the same corpus and net.

At 120k, the existing 2.56M all-root reference is marginal. Relative to f01,
its nominal completed-depth advantage over all evaluable positions averaged
+0.843 ply, with P10 -1, median +1, and P90 +3; it was deeper in 13,744 positions,
equal in 6,923, and shallower in 4,313. The f01-derived trusted set therefore
contains only 13,744 positions (55.0%). On that set f21 has the best point
metrics, with mean regret 0.011534 versus f01's 0.012640.

That f01-only gate is not conservative enough for selecting among the 120k
candidates, because f21/f22/f23 themselves search deeper than f01. The fixed
common gate requiring the reference to complete at least one more ply than
every one of f01/f21/f22/f23 retains 11,967 positions (47.9%):

| Variant | Mean regret | P90 regret | Move agreement | Mean depth |
|---|---:|---:|---:|---:|
| `f01` | 0.012227 | 0.033300 | 56.330% | 9.384 |
| `f21` | 0.011967 | 0.031877 | 56.965% | 9.524 |
| `f22` | 0.012012 | 0.032506 | 56.664% | 9.470 |
| `f23` | 0.011968 | 0.031820 | 56.940% | 9.502 |

On this strict set f21 and f23 are effectively tied. In particular, f21's
paired mean-regret interval against f01 crosses zero (-0.000568 to +0.000047).
The 120k outputs are useful evidence that higher budgets can change the proxy,
but not a sufficiently reliable basis for a new 120k ranking.

Conclusion: the 2.56M full-root reference is suitable for the 40k G3-SR2
screen but marginal for 120k PVS searches. A future high-budget screen should
use f01 as its direct control and a smaller corpus with a reference made
substantially deeper than every compared candidate. Do not extrapolate either
the 40k or 120k regret differences directly into Elo. The subsequent f21/f01
SPRT accepted H1, which validates the directional prediction without turning
small proxy deltas into an Elo conversion.

## Historical G3-SR3 Shared-Budget Anchor

G3-SR3 seed `990318` is a 25,000-position corpus, FEN-disjoint from G3-SR2.
Its completed historical anchor at `~/Tune/futility/g3-sr3/` used f01 at 120k
for the baseline and a 10.24M **position-wide** full-root budget. Retain its
`probes/reference.jsonl` and `probes/baseline.jsonl` as durable raw evidence;
they remain valid only under the shared-budget contract.

The old reference hit its total cap on 99.4% of non-terminal positions, yet it
completed at least one nominal ply beyond f01 in 23,045 of 24,983 non-terminal
positions (92.2%), and at least two plies beyond in 19,237 (77.0%). f01's
score-regret baseline on the +1 trusted set is mean `0.015773`, P90
`0.046616`, and 58.61% move agreement. The retained maps contain a mean 26.66
legal root moves per position (median 28; P90 42).

This anchor may still screen a known candidate such as f21 at 120k as an
independent old-contract holdout. Do not pool it with per-root ranking results
or overwrite it with the new contract.

## Per-root Reference Anchors and Contract Comparison

The per-root contract is the future proxy basis. For each position, f01 first
searches at the candidate budget and completes at depth `B`. Every legal root
is then searched independently with a full window, its own cap `R`, and target
depth `B + gap`. A position is complete only if every legal root reaches that
target. The first failed root rejects the position and records the FEN,
baseline/target depths, root counts, failed move, failed depth/nodes, and
reason. No partial root-score map is retained.

`R` is a safety bound, not a work target: a root stops as soon as it completes
the common target. Score regret is calculated only on complete references;
depth is a reference-quality gate, never a candidate ranking objective.

| Anchor | Corpus | Status | Contract |
|---|---|---|---|
| G3-SR4 | seed 990319, 25k FENs | Windows anchor running | f01 120k, `B + 2`, 2M/root |
| G3-SR3-R2M | seed 990318, 25k FENs | serial cloud anchor running | f01 120k, `B + 2`, 2M/root |

The earlier 480k/root SR4 calibration completed 411 and rejected 393 of 804
non-terminal positions; 392 failures exhausted the cap and 320 were only one
iteration short. The 2M/root restart is therefore intentional. Both current
anchors report every 100 positions with completed/rejected/terminal counts,
nodes, elapsed time, rate, and an `HH:MM` ETA. The cloud launcher runs under
`nohup` with a PID and durable log, so an SSH disconnect is safe.

G3-SR4 was sampled from `chilo-2.csv` with seed 990319, excluding the merged
G3-SR2/SR3 FEN set. Its provenance JSON records 25,000 unique FENs and zero
overlap. The sampler itself remains single-input; do not introduce generic
multi-shard sampling merely to support these two anchors.

Keep every anchor as its own paired raw JSONL evidence and manifest. After the
two per-root runs complete, treat one shard as optimizer development evidence
and the other as an untouched selection shard until an explicit aggregation
design is reviewed.

## Discrete Margin Optimizer

`scripts/optimize_futility.py` runs a dependency-free, deterministic
coordinate search over explicit nondecreasing margin tuples. Its generic
search core only handles ordered integer vectors and lexicographic objective
tuples; the futility adapter alone reads probe JSONL and calculates score
regret. No SciPy or other optimizer package is required, and the existing
`~/Sources/chilo/.venv` can run the script from this worktree.

The optimizer configuration names a development and validation reference
directory independently. Its first intended experiment uses G3-SR4 as the
development anchor because it is expected first, and keeps G3-SR3-R2M
untouched for validation. `--phase optimize` is the safe default; it searches
only development and persists every candidate output and state under its run
directory. `--phase validate` promotes the top five distinct non-baseline
development tuples, reruns them against the selection anchor, and ranks only
that fixed set there. `--phase all` is explicit because validation is costly.

Each configuration must give a seed for every enabled maximum futility depth.
The first search covers depths 3 through 7, represents a profile as its first
margin plus nonnegative increments, and refines with 80, 40, 20, then 10 cp
steps. The default cap of 80 newly probed development tuples, maximum allowed
margin, promoted-count, seeds, and steps are all configuration parameters.
The ordering remains mean normalized regret, then P90, median, and the margin
tuple; depth and all other probe metrics remain diagnostics.

The reference directory and its declared contract are part of the strict
optimizer manifest. `per_root_v1` is the future contract; `shared_budget_v1`
can be named for a separately labelled historical G3-SR3 experiment, but must
never be pooled with per-root results. Existing valid JSONL candidate outputs
and state entries are reused; an anchor, probe, input, net, budget, or config
hash mismatch requires a new optimizer run directory. The example is
`scripts/futility_optimizer.example.json`.

### Future: Post-anchor Mate Rescue

Do not discard every reference rejection whose f01 baseline eventually reports
mate. In fixed-node PVS, a short forced mate can make later iterations cheap,
so its final completed depth may be far higher than the work needed to prove
the mate. An all-root reference must still search every alternative move and
can exhaust its per-root cap even when the tactical fact is clear. Longer
forced mates are valuable futility tests: a radically pruned candidate that
misses one must not gain an advantage merely because the position was removed
from score-regret ranking.

After G3-SR4 completes, inspect only the rejected records and run a separate
mate-rescue pass; do not change or repeat the full anchor. The **reference**,
not the baseline alone, triggers rescue: it must establish a winning mate on a
root before the normal `R` failure. Let `D_found` be the completed iterative
search depth at which that mate was established (not the displayed mate-in-N
distance), then use a fixed rescue target of `D_found + gap`.

Roots already searched beyond that target retain their stronger score and
record their individual score depth; later roots are searched to the rescue
target. A heterogeneous map is acceptable for this mate-specific contract,
but its depth provenance must be retained. Its regret is defined from the
exact best reference value `+1`: a candidate selecting a certified winning
mate has regret zero; for each distinct non-mating root selected by any
evaluated candidate, refine that root to the fixed rescue target when its
available score is shallower, then calculate `1 - transformed(selected-root
score)`. Deduplicate these selected-root refinements across candidates and
retain the rescue contract, root scores, depths, cap, and mate metadata in
separate durable artifacts.

First measure the number and type of G3-SR4 rejections, including how many
are mate-interesting, before implementing this new contract. A simple
higher-`R`, rejected-only rerun remains the control comparison: it retains the
ordinary uniform contract and reveals whether the specialized rescue is worth
its additional complexity.

### G3-SR3 Old-versus-New Reference Report

The old shared-budget and new per-root G3-SR3 anchors use the same input FENs,
which makes them a controlled reference-design experiment. On
`futility-score-regret`, add a read-only report that matches records by input
basename, line, and FEN and reports:

1. deterministic agreement of the repeated 120k f01 baselines;
2. old depth separation against new per-root acceptance/rejection;
3. best-move and root-score agreement for positions complete under both
   contracts;
4. new rejection characteristics by old root count, old depth gap, and old
   root-score spread; and
5. f01/f21 and later candidate-regret/ranking agreement under both contracts.

This report extracts value from the historical anchor without treating it as a
per-root shard. Keep `futility-score-regret` available until it and any desired
old-contract candidate probes are complete. Before merging the per-root branch,
tag the old-contract tip so the analysis remains reproducible.

## Current SPRT Status

| Candidate | Opponent | Control | Status |
|---|---|---|---|
| `f21` | `f01` | 6+0.1 | H1 accepted. |
| `f22`, `f23` | `f01` | 6+0.1 | Not started; lower proxy promise, no longer queued by default. |
| `f21` | source futility `0.7.4` | longer control | Planned confirmation of the practical best version. |

## Future: Root-Budget-Adaptive Futility Profiles

Static futility margins may have different strength optima at different time
controls: aggressive pruning can buy useful depth at short controls, while a
more conservative tuple may avoid tactical losses when searches are longer.
Do not assume one tuple dominates across the whole time-control range.

The first implementation should choose one discrete futility profile at the
start of every root search, after the UCI time manager has calculated that
move's search budget. It must keep that profile fixed across the entire
iterative-deepening search. Select from a small short/normal/long profile set
using the allocated root time (or an equivalent fixed-node bucket); fixed-depth
and fixed-node tooling retain an explicit stable profile. Do **not** switch
profiles between iterative-deepening iterations initially: that would make
results sensitive to timing noise and would no longer match the static-profile
SPRT evidence.

Validation plan:

1. Confirm f21 against source futility `0.7.4` at a longer control. Do not
   automatically consume time on f22/f23 unless later per-root evidence makes
   one a useful structural control.
2. Test promising static tuples at at least one much shorter and one much
   longer control, for example 1+0.01, 6+0.1, and 30+0.3. Keep the net,
   openings, adjudication, and other tournament settings fixed across those
   comparisons.
3. Only if different tuples show repeatable wins in different budget ranges,
   implement a two-threshold short/normal/long selector at root-search setup.
4. Test the adaptive engine against the strongest fixed tuple at each target
   control, then against that fixed basis over a representative mixed control
   set. SPRT remains the strength gate.
