# Futility Margin Tuning

This is the persistent record for futility-margin experiments. The current
source defaults remain `120,320,550` through depth three. Proxy tuning only
selects SPRT candidates; it does not establish playing strength.

## Accepted SPRT Basis

`f21` is the current practical playing basis: its 6+0.1 SPRT against `f01`
accepted H1, and its longer-control SPRT against the source `g4t1-64x8`
accepted H1. Future futility SPRTs compare candidates against f21. `f01`
remains frozen only as the reference control for futility proxy optimization,
baseline depth measurement, and candidate comparisons. Do not replace or
overwrite either binary.

| Binary | Margins | Status |
|---|---|---|
| `chilo-0.7.5-f01-avx2` | `120,240,360` | Accepted previous basis; frozen proxy control. |
| `chilo-0.7.5-f21-avx2` | `75,212,390,600,839` | H1 accepted versus f01 at 6+0.1 and source `g4t1-64x8` at longer control; practical SPRT basis. |

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
| G3-SR4 | seed 990319, 25k FENs | Windows anchor complete; development anchor | f01 120k, `B + 2`, 2M/root |
| G3-SR3-R2M | seed 990318, 25k FENs | Cloud anchor complete; untouched selection anchor | f01 120k, `B + 2`, 2M/root |

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

Keep every anchor as its own paired raw JSONL evidence and manifest. G3-SR4
has 22,723 ordinary trusted positions and is the optimizer development shard;
G3-SR3-R2M has 22,829 ordinary trusted positions and is the untouched
selection shard. Do not pool them until an explicit aggregation design is
reviewed. The full-corpus G3-SR3-R2M selection comparison of the two SPSA
endpoints is recorded below from its durable probe output, not inferred from
development results.

## Historical Coordinate Optimizer

`scripts/optimize_futility.py` is the original dependency-free, deterministic
coordinate-search path over explicit nondecreasing margin tuples. Its generic
search core only handles ordered integer vectors and lexicographic objective
tuples; the futility adapter alone reads probe JSONL and calculates score
regret. It remains usable as a small deterministic fallback and as the source
of the SR4 smoke outputs, but SPSA is now the primary broad-search path.

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
optimizer manifest. Existing valid JSONL candidate outputs and state entries
are reused; an anchor, probe, input, net, budget, or config hash mismatch
requires a new optimizer run directory. The example is
`scripts/futility_optimizer.example.json`.

## SPSA Margin Optimizer and Subset Sensitivity

`scripts/optimize_futility_spsa.py` is the primary dependency-free SPSA
search path. A track starts from one
fixed-depth tuple represented as first margin plus nonnegative increments.
At iteration `k`, it creates a random ±1 direction, probes `theta + c_k delta`
and `theta - c_k delta`, then updates all continuous increment coordinates
from their scalar mean-normalized-regret difference.  Projection turns those
coordinates back into nondecreasing integer margins bounded by `max_margin`.

The plus and minus probes for one track/iteration always use the same
deterministically sampled subset of the fixed anchor-derived trusted set. This
common-random-numbers pairing removes subset noise from the finite difference.
The next iteration samples a new deterministic subset. `workers` bounds all
concurrent plus/minus probes, so two tracks can occupy four workers without
changing either track's paired comparison. The seed, fraction, schedules
(`a`, `A`, alpha, `c`, gamma), objective scale, starts, worker count, anchor,
and artifact identities are all in the strict manifest.

The runner is deliberately development-only. It persists a state record and
raw candidate JSONL for every pair, supports resume by parsing valid existing
outputs, and writes `finalists.json` with projected tuples. Those tuples are
**not** automatically full-corpus ranked or sent to G3-SR3-R2M; review them
before a separate promotion run. See `scripts/futility_spsa.example.json`.

`scripts/analyze_futility_subsets.py` is the complementary read-only tool for
the four finished SR4 outputs: f01, `[40,160,280]`, `[120,160,280]`, and
`[200,320,440]`. Because each output has a fixed-node result for every input
position, filtering the raw JSONL to a deterministic trusted subset is exactly
the candidate comparison on that smaller corpus—no probe needs to rerun. The
example evaluates 5%, 10%, and 20%, with three replicates each, and reports
per-sample rankings, aggregate rank/winner stability, and paired mean-regret
deltas versus f01. `scripts/futility_subset_analysis.example.json` is a
portable template; the exact historical SR4 smoke configuration is retained
as `scripts/futility_subset_analysis.g3-sr4-smoke.json`.

The initial read-only SR4 check confirms why a tiny SPSA subset needs care. At
5% (about 1,125 trusted positions), the winner varied: f01 won two samples
and `[200,320,440]` one. At both 10% and 20%, `[40,160,280]` won all three
samples and beat f01 by mean-regret deltas of roughly `-0.00063` and
`-0.00065`, respectively. This is only a sensitivity observation from the
existing smoke outputs, not a strength claim; begin SPSA at 10% or higher
unless a deliberately noisier experiment is wanted.

The first real SPSA run used 15% deterministic subsets, two tracks, four
workers, and 100 iterations: d3 started at f01 and d5 started at f21. Its
full-G3-SR4 endpoint probes established two development improvements over
f01; neither is selected until the untouched G3-SR3-R2M comparison completes.

| Variant | Margins | Mean regret | P90 regret | Move agreement | Mean depth |
|---|---|---:|---:|---:|---:|
| f01 | `120,240,360` | 0.014838 | 0.043224 | 56.498% | 9.121 |
| SPSA d3 endpoint | `23,62,194` | 0.014321 | **0.040663** | 56.850% | 9.461 |
| SPSA d5 endpoint | `10,54,175,264,503` | **0.014221** | 0.041042 | **57.101%** | 9.690 |

The d5 endpoint improves mean regret by about 4.2% versus f01 and is the
primary candidate; the d3 endpoint improves it by about 3.5% and is the
structurally distinct alternate. These are development-proxy results, not Elo
claims. Their increase in mean depth is diagnostic only.

### G3-SR3-R2M full selection — 2026-08-28

The independently prepared Windows run evaluated both endpoints at 120k nodes
on all 22,829 trusted G3-SR3-R2M positions. It reproduced the G3-SR4 ordering
on mean regret, P90 regret, and move agreement. The durable results archive
is `g3-sr3-r2m-full-probes-win-rez.zip`; its `run/` directory contains the
probe JSONL, manifests, `results.json`, and report.

| Variant | Margins | Mean regret | P90 regret | Move agreement | Mean depth |
|---|---|---:|---:|---:|---:|
| f01 | `120,240,360` | 0.015209 | 0.045557 | 56.647% | 9.084 |
| SPSA d3 endpoint | `23,62,194` | 0.014443 | 0.042343 | 57.055% | 9.432 |
| SPSA d5 endpoint | `10,54,175,264,503` | **0.014298** | **0.041591** | **57.418%** | 9.653 |

Relative to f01, d3 improves mean regret by 5.03%, P90 regret by 7.06%, and
move agreement by 0.407 percentage points. D5 improves those metrics by
5.98%, 8.71%, and 0.771 points respectively. Thus d5 is the primary SPRT
candidate and d3 is the retained structural alternate. This is two-shard
proxy evidence only; f21 has not yet been measured under this exact per-root
selection contract.

## Post-anchor Mate Rescue

### Rationale and policy

Do not discard every reference rejection whose f01 baseline eventually reports
mate. In fixed-node PVS, a short forced mate can make later iterations cheap,
so its final completed depth may be far higher than the work needed to prove
the mate. An all-root reference must still search every alternative move and
can exhaust its per-root cap even when the tactical fact is clear. Longer
forced mates are valuable futility tests: a radically pruned candidate that
misses one must not gain an advantage merely because the position was removed
from score-regret ranking.

The **reference**, not the baseline alone, triggers rescue: it must establish
a winning mate on a root before the normal `R` failure. Let `D_found` be the
completed iterative search depth at which that root established the mate (not
the displayed mate-in-N distance), then use a rescue target of `D_found +
gap`. A heterogeneous map is acceptable only with explicit per-root depth
provenance. A higher-`R`, rejected-only rerun remains the control: it retains
the ordinary uniform contract and shows whether specialized rescue is worth
its additional complexity.

### Implemented contract

`futility_probe --per-root-mate-rescue` implements the separate
`per_root_mate_rescue_v1` contract. It is run only on a masked copy of the
already rejected input rows and writes separate rescue reference/baseline JSONL
files; it never changes the completed anchor pair.

For every supplied rejection it repeats the normal root sequence. A rescue is
eligible only when a completed root has established a **winning reference
mate** before the first normal root failure. A baseline mate alone is not an
eligibility signal. The probe records the first completed depth `D_found` at
which that root established the mate and sets the rescue target to
`D_found + gap`. Roots already searched at least that deep retain their score;
the failed and remaining roots are searched to the rescue target with the same
per-root cap. The result is rescued only when every legal root has a score.

Each rescued record carries the exact all-root score map plus
`root_score_depths`, `mate_found_depth`, `normal_target_depth`, and
`rescue_target_depth`. This makes the deliberately heterogeneous provenance
visible instead of silently treating it as a uniform reference. Non-eligible
and rescue-cap-failed rows remain durable diagnostics but are not admitted.

`scripts/rescue_futility_mates.py` masks original rejected rows, invokes this
mode, persists an artifact-locked manifest, and can score listed existing
candidate outputs both on the rescue-only population and on the combined
ordinary-trusted-plus-rescued population. The example is
`scripts/futility_mate_rescue.example.json`. Use a new rescue run directory
per anchor. The first real smoke test rescued a G3-SR4 row whose ordinary
reference failed at target depth 12: a reference root proved mate at depth 1,
so the rescue target was 3 and all 46 legal roots completed there. This is the
intended distinction from merely trusting the baseline's mate score.

### Completed G3-SR4 and G3-SR3-R2M rescue passes — 2026-08-28

Both completed anchors now have immutable rescue sidecars. G3-SR4 rescued 102
of 2,253 rejected positions in 5.06 hours; G3-SR3-R2M rescued 105 of 2,154 in
4.32 hours. They add only about 0.45% to each corpus, but include nontrivial
mates: 44 SR4 and 41 SR3-R2M rescues first proved a mate at depth 7 or deeper.

| Anchor | Combined positions | D3 combined mean regret | D5 combined mean regret |
|---|---:|---:|---:|
| G3-SR4 development | 22,825 | 0.014258 | **0.014157** |
| G3-SR3-R2M selection | 22,934 | 0.014378 | **0.014233** |

D5 had zero rescue-only mean regret on both shards. These combined values
preserve the ordinary-population ordering; they do not establish playing
strength. New optimizer configurations must declare the completed rescue
`run/` directory as `development.rescue_dir` (or `validation.rescue_dir`).
The adapter validates the rescue manifest, raw maps, baseline maps, exact
combined keys, and artifact hashes before accepting the merged population.

## Optional Historical G3-SR3 Contract Report

The old shared-budget and new per-root G3-SR3 anchors use the same input FENs,
which makes them a controlled reference-design experiment. If useful, add a
read-only report that matches records by input basename, line, and FEN and
reports:

1. deterministic agreement of the repeated 120k f01 baselines;
2. old depth separation against new per-root acceptance/rejection;
3. best-move and root-score agreement for positions complete under both
   contracts;
4. new rejection characteristics by old root count, old depth gap, and old
   root-score spread; and
5. f01/f21 and later candidate-regret/ranking agreement under both contracts.

This report extracts value from the historical anchor without treating it as a
per-root shard. The per-root work is already merged into
`futility-score-regret`; no branch preservation or merge step is required.

## Deferred Cleanup Candidates

These are intentionally retained until the optional historical G3-SR3 report
is either completed or explicitly abandoned. They must not be used for new
per-root tuning runs.

- `shared_budget_v1` support in `scripts/optimize_futility.py` and its
  historical-only tests. It exists solely to analyse the old G3-SR3 anchor;
  remove the branch and tests once that comparison no longer has value.
- `scripts/optimize_futility.py`, `scripts/discrete_optimizer.py`, and
  `scripts/futility_optimizer.example.json`, the original coordinate-search
  path. Keep the completed smoke artifacts and documentation, but remove this
  execution path if SPSA remains the only optimizer we intend to support.

## Current SPRT Status

| Candidate | Opponent | Control | Status |
|---|---|---|---|
| `f21` | `f01` | 6+0.1 | H1 accepted. |
| `f22`, `f23` | `f01` | 6+0.1 | Not started; lower proxy promise, no longer queued by default. |
| `f21` | source `g4t1-64x8` futility | longer control | H1 accepted; f21 is the practical SPRT basis. |

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
