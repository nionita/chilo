# Futility Margin Tuning

This is the persistent record for futility-margin experiments. The current
source defaults remain `120,320,550` through depth three. Proxy tuning only
selects SPRT candidates; it does not establish playing strength.

## Accepted SPRT Basis

`f21` is the current practical playing basis: its 6+0.1 SPRT against `f01`
accepted H1, and its longer-control SPRT against the source `g4t1-64x8`
accepted H1. Future futility SPRTs compare candidates against f21. `f01`
remains frozen as the anchor baseline, baseline-depth measurement, and a
stable comparison variant. The deep per-root reference, not f01, defines the
current tail-risk safety gates. Do not replace or overwrite either binary.

| Binary | Margins | Status |
|---|---|---|
| `chilo-0.7.5-f01-avx2` | `120,240,360` | Accepted previous basis; frozen anchor baseline. |
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

## SPSA-150 Holdout Failure and Tail-Risk Diagnostics — 2026-08-30

A second SPSA run used 150 iterations, 20% deterministic subsets, and two
five-depth tracks. Its SR4 development endpoints were `0,40,98,202,424`
(center) and `0,40,158,488,754` (nearby, later called `spsa150b`). Both drove
the first margin to zero. Full SR4 combined-population probes made the nearby
endpoint the nominal mean-regret winner:

| Variant | SR4 combined mean regret | SR4 P90 regret | SR4 move agreement |
|---|---:|---:|---:|
| f01 | 0.014772 | 0.043051 | 56.683% |
| previous D5 `10,54,175,264,503` | 0.014157 | 0.040669 | 57.284% |
| center | 0.014082 | 0.041145 | **57.336%** |
| nearby / `spsa150b` | **0.014074** | **0.040416** | 57.306% |

The untouched G3-SR3-R2M combined selection population rejected both new
endpoints. The earlier D5 tuple is the winner and remains the proxy candidate;
do not promote either SPSA-150 endpoint to SPRT. Manual GUI inspection also
made `spsa150b` look implausibly aggressive, but that observation is
diagnostic only, not a controlled strength result.

| Variant | SR3-R2M combined mean regret | SR3-R2M P90 regret | SR3-R2M move agreement |
|---|---:|---:|---:|
| f01 | 0.015140 | 0.045296 | 56.841% |
| previous D5 `10,54,175,264,503` | **0.014233** | **0.041414** | 57.609% |
| nearby / `spsa150b` | 0.014452 | 0.043125 | 57.661% |
| center | 0.014582 | 0.042412 | **57.683%** |

This is adaptive development overfitting and/or corpus-distribution shift, not
an argument that seven physical margins alone are too many parameters for
25,000 positions. SPSA adaptively sampled and compared many perturbations on
SR4 before its endpoints were selected. The independent selection shard is
therefore essential. It remains unclear whether the main cause is optimizer
noise, SR4-specific structure, or a mismatch between fixed-node root regret
and real-game loss; do not change the optimizer on this evidence alone.

### Read-only risk analysis

`scripts/analyze_futility_risk.py` calculates additional candidate diagnostics
from completed JSONL only; it does not run the engine. It uses the shared
anchor/rescue adapter, so all ordinary trusted and certified mate-rescue
positions are included. The portable configuration is
`scripts/futility_risk_analysis.example.json`.

For each candidate it reports normalized-regret tails directly against the
deep reference-root scores. The reference is the appropriate safety standard:
a candidate and f01 can share the same tactical failure, so a candidate-only
excess over f01 would incorrectly report no additional risk.

```text
CVaR top q% = mean regret of the worst ceil(q% * position_count) positions
mean squared regret = mean(candidate regret ^ 2)
```

P99 is only the cutoff below which 99% of the regrets lie; CVaR top 1% is the
average severity of the worst 1%. With SR4's 22,825 combined positions, that
tail contains 229 positions. The tool also reports mean squared regret,
regret-threshold rates, and semantic reference-to-candidate transitions. The
initial semantic thresholds are
tentative: a clear non-mate advantage is at least +150 cp and a clear loss is
at most -150 cp. Winning-mate loss is counted separately, so categories do not
double-count those positions.

The completed SR4/SR3-R2M comparison used f01, the earlier D3/D5 endpoints,
and both SPSA-150 endpoints. It provides useful diagnostics but no new ranking
rule yet:

| Variant | SR4 CVaR top 1% | SR4 squared downside | SR3 CVaR top 1% | SR3 squared downside |
|---|---:|---:|---:|---:|
| previous D3 | 0.340163 | **0.000477** | **0.314329** | **0.000428** |
| previous D5 | 0.330943 | 0.000498 | 0.323791 | 0.000526 |
| nearby / `spsa150b` | **0.329445** | 0.000542 | 0.321794 | 0.000520 |
| center | 0.331604 | 0.000606 | 0.336676 | 0.000640 |

This historical table used f01-relative downside and is retained only as
evidence from the earlier inspection; it is not a valid future gate. Absolute
CVaR alone would not have rejected `spsa150b`: on SR4 it is the best tail and
on SR3 it is still better than f01. The D3 tuple has the consistently smallest
historical relative downside but not the best mean regret. These diagnostics
expose a real mean-versus-risk trade-off; they do not yet justify a numerical
safety threshold or a replacement objective.

The eventual policy may be to reject candidates outside a calibrated risk
envelope (for example, reference-relative mean squared regret and CVaR) and
rank the survivors by mean regret. First calibrate any such gate
retrospectively on more known candidates and out-of-sample results. In
particular, do not use a literal maximum-regret rule: a single unusually
difficult or imperfectly referenced position would dominate it.

### Future: real-game score-swing telemetry

Static root regret cannot identify every practical failure. A collection build
should record a **suspect** after an engine move whose final completed root
score later falls sharply when the engine searches again after the opponent
reply. Store both searches from the engine's fixed-color point of view:
pre-move FEN, selected and opponent moves, scores/mate classes, completed
depths/nodes, PVs, interruption status, time allocation, engine/net identity,
and pruning counters.

An initial trigger is a score drop of roughly 150--200 cp, both searches having
completed a reasonable depth (initially 8--9), and the later depth no more
than one ply below the first. Winning-mate to non-winning-mate and
non-losing-to-losing-mate transitions always trigger. This is not an in-game
proof of a blunder and must not spend extra game time. Offline re-search of the
saved pre-move position, its selected child, and a less aggressive control can
classify each event as a pruning/horizon miss, an evaluation correction, or an
ordinary depth limitation. A sufficiently large target-time-control failure
corpus can later calibrate risk metrics against actual score collapses.

## Gated Random Hill Climb — 2026-08-30, revised 2026-08-31

`scripts/optimize_futility_gated.py` is a separate development-only optimizer
for the case where mean normalized regret is useful but insufficient. It does
not replace the historical SPSA runner or reinterpret old runs. Each attempt
uses one fresh deterministic common-random-number subset and runs exactly two
ordinary candidate probes in parallel: the current incumbent and one signed
random perturbation in margin-increment coordinates. A proposal replaces the
incumbent only if it improves the sampled mean normalized regret by the
track's configured `min_mean_improvement` **and** passes its configured risk
gate. This makes a current best point and lack-of-progress meaningful despite
the discrete projected tuples.

Each track must explicitly provide these gate hyperparameters; there are no
hidden safety defaults:

```json
"gate": {
  "mode": "downside | cvar1 | both",
  "max_squared_regret": 0.002500,
  "max_cvar1_regret": 0.350000,
  "min_mean_improvement": 0.000020,
  "max_stalled_attempts": 20
}
```

The two gate statistics use the same direct reference calculation as
`scripts/analyze_futility_risk.py` on the attempt subset:

- **downside** is mean squared candidate regret;
- **cvar1** is the mean regret of the worst `ceil(1% * sample_count)`
  candidate positions; and
- **both** enforces both caps. Inactive limits are still recorded, allowing
  like-for-like comparison of the three modes.

This is deliberately a breaking optimizer-contract change. The schemas are
versioned, so an old f01-relative run cannot resume under the absolute gates;
start a new run directory and calibrate the two absolute limits from known
candidates on the development and untouched selection populations.

The initial tuple must pass its selected gate on its first sampled evaluation.
Afterward every accepted tuple has passed that gate when selected. A rejected
proposal (gate failure or insufficient mean improvement) increments the
stalled count; an accepted proposal resets it. A track stops as `stalled` at
`max_stalled_attempts`, or as `max_attempts` at the run-wide cap. The durable
state records the two metric sets, gate decision, subset hash, and probe hashes
for every attempt; a matching manifest is mandatory for resume.

Use `scripts/futility_gated_hillclimb.example.json` as the portable template.
The illustrative f21-derived limits are only a calibration hypothesis from
the current small set of SPRT-labelled candidates. They are not proven safety
thresholds. Full-development ranking, untouched G3-SR3-R2M evaluation, and
then SPRT remain mandatory before promotion.

### Corrected-gate calibration and active evaluations — 2026-08-31

The first Windows gated hill climb used the now-obsolete f01-relative gates.
That comparison can hide a shared tactical failure: if f01 and a candidate
both choose the same bad move, candidate-minus-f01 excess is zero although
both have substantial reference regret. The v2 gated optimizer and risk
analysis now use only direct deep-reference quantities:

- **squared regret** = mean of squared normalized reference regret;
- **CVaR-1%** = mean reference regret among the worst 1% of positions; and
- semantic diagnostics are direct reference-to-candidate transitions.

This is an intentionally incompatible run contract. The old field names
`max_squared_positive_excess` and `max_cvar1_excess`, and the v1 optimizer
state schema, cannot resume under v2. The old f01-relative risk table above
is historical evidence only.

The interrupted Windows v1 run was retained in full and re-scored rather than
discarded. It contains 47 committed fresh-20%-subset attempts for each of
three D3 tracks (141 paired comparisons total), plus an uncommitted 48th
attempt that is not used for decisions. Its durable old-gate incumbents are:

| Old track | Accepted / attempts | Incumbent margins | Last accepted sample: mean / squared / CVaR-1% |
|---|---:|---|---:|
| downside | 14 / 47 | `55,69,169` | 0.013317 / 0.001625 / 0.272227 |
| cvar1 | 19 / 47 | `14,68,259` | 0.014200 / 0.001998 / 0.305868 |
| both | 16 / 47 | `31,104,198` | 0.013636 / 0.002384 / 0.328996 |

The best single-subset proposals are not endpoint candidates: they have a
winner's-curse selection bias. Tuple `45,160,240`, the best observation from
the old `both` track, already has a full SR4/SR3-R2M evaluation and is not
rerun. The three durable incumbents above are the only old-run tuples being
promoted to full evaluation.

The old-run re-score establishes practical v2 trial limits. The D3 start
`23,62,194` had observed 20% samples through 0.002689 squared regret and
0.365551 CVaR-1%; across all old-run proposals the corresponding 90th
percentiles were 0.002778 and 0.370688. The prepared short v2 Windows trial
therefore has one `both` stream with limits 0.002800 and 0.380000, 20% fresh
samples, `c=20`, `gamma=0.101`, `min_mean_improvement=0.000050`, two workers,
30 attempts, and early stop after 10 stalled attempts. Two workers are enough
because its incumbent and proposal probes run concurrently.

The package `g3-sr4-gated-v2-d3-win.zip` is a development-only test of this
corrected optimizer. Separately, the serial Linux package
`g3-sr4-gated-d3-endpoints-linux.tgz` completed the three old-run incumbents
at 120k on both G3-SR4 and untouched G3-SR3-R2M, with the v2 read-only risk
analysis; its result is recorded below. The SR3-R2M result, not the adaptive
SR4 trajectory, determines whether an endpoint merits SPRT consideration.

### Corrected-gate D3 result and full-evaluation package — 2026-08-31

The completed Windows result archive is `g3-sr4-gated-v2-d3-win-rez.zip`
(SHA-256 `1a84a6365fe3c6d9f3a7e549bba7750ef68dfe1b8d474b65169b820f286deab2`).
Its sole `both`-gate track ran all 30 fresh 20% SR4 subsets and committed 11
improvements, finishing at `69,83,207`. The final accepted subset was not a
full-evaluation result: it had mean regret 0.014511, squared regret 0.002148,
and CVaR-1% 0.332051 on 4,565 positions, passing the buffered 0.002800 and
0.380000 direct-reference gates. Treat it as an optimizer endpoint only.

The v2 trajectory is still useful diagnostic evidence. Across its 30 paired
fresh-subset attempts, 11 proposals were accepted, 16 failed the minimum mean
improvement, and 3 were gate-rejected. The accepted transitions were:

| Attempt | Incumbent -> accepted margins | Paired mean-regret improvement |
|---:|---|---:|
| 1 | `23,62,194` -> `42,62,213` | 0.000283 |
| 5 | `42,62,213` -> `25,28,196` | 0.000109 |
| 13 | `25,28,196` -> `40,40,223` | 0.000441 |
| 14 | `40,40,223` -> `55,55,253` | 0.000327 |
| 15 | `55,55,253` -> `70,85,268` | 0.000642 |
| 17 | `70,85,268` -> `55,85,253` | 0.000411 |
| 18 | `55,85,253` -> `70,85,238` | 0.000339 |
| 23 | `70,85,238` -> `55,55,193` | 0.000308 |
| 25 | `55,55,193` -> `41,41,165` | 0.000058 |
| 28 | `41,41,165` -> `55,55,165` | 0.000250 |
| 29 | `55,55,165` -> `69,83,207` | 0.000214 |

Each delta is a valid same-subset paired comparison, but the subsets differ
between attempts, so their 0.003382 sum is not a whole-corpus improvement.
All three gate-rejected proposals also had negative paired mean improvement;
the corrected risk caps therefore did not change an otherwise acceptable
incumbent decision in this short trajectory. They were feasibility limits, not
a monotonic tail-risk objective: accepted attempt 17 worsened both squared
regret and CVaR while remaining below the caps. The complete full-population
comparison eventually shows the endpoint slightly worse than the D3 start on
SR4 (0.014275 versus 0.014258) and materially worse on SR3-R2M (0.014867
versus 0.014378), which is exactly why fresh optimizer improvements need both
full development and untouched-selection evaluation.

`g3-sr4-gated-v2-d3-full-eval-win.zip` is the self-contained Windows package
for its fixed 120k full evaluation. It uses the same committed probe
(`5483f2a6...acd2ea50`), g4t1 weights, immutable anchors, and mate-rescue
sidecars as the prior comparable runs. `run-full-evaluation.cmd` starts the
SR4 development and SR3-R2M untouched-selection probes concurrently and then
writes a direct-reference risk report for each. The configuration has a
four-worker ceiling, but exactly two independent jobs, so it deliberately
uses two workers rather than rerunning already comparable controls to fill
the machine. The launcher never overwrites a `run/` directory; return the
whole extracted directory when complete.

### Corrected-gate D3 full evaluation — 2026-08-31

The completed return archive is
`g3-sr4-gated-v2-d3-full-eval-win-rez.zip` (SHA-256
`dd7524d3943ea0caa708de5b00ebd51af57159b237e990ca38b10d40264eb032`).
Its two complete normal-PVS 120k outputs have the same g4t1 weights,
`per_root_v1` anchors, rescue sidecars, 22,825 SR4 positions, and 22,934
SR3-R2M positions as the comparison set.

| Candidate | Margins | SR4 mean / squared / CVaR-1% | SR3-R2M mean / squared / CVaR-1% |
|---|---|---|---|
| corrected-gate D3 | `69,83,207` | 0.014275 / 0.002263 / 0.333735 | 0.014867 / 0.002226 / 0.322232 |
| f01 | `120,240,360` | 0.014772 / 0.002415 / 0.346279 | 0.015140 / 0.002343 / 0.330023 |
| previous D5 | `10,54,175,264,503` | 0.014157 / 0.002223 / 0.330943 | **0.014233 / 0.002191 / 0.323791** |

The direct start-versus-end gate comparison makes the intended trade explicit:

| Population | Tuple | Mean regret | Squared regret gate | CVaR-1% gate | P95 / P99 |
|---|---|---:|---:|---:|---:|
| SR4 | start `23,62,194` | **0.014258** | 0.002322 | 0.340163 | **0.079745 / 0.200100** |
| SR4 | end `69,83,207` | 0.014275 | **0.002263** | **0.333735** | 0.081001 / 0.202626 |
| SR3-R2M | start `23,62,194` | **0.014378** | **0.002104** | **0.314329** | **0.084530 / 0.203463** |
| SR3-R2M | end `69,83,207` | 0.014867 | 0.002226 | 0.322232 | 0.086597 / 0.206783 |

Thus SR4 shows the desired limited trade: mean regret worsens by 0.000017
(0.12%) while squared regret improves by 2.57% and CVaR-1% by 1.89%; its P95
and P99 nevertheless worsen. On untouched SR3-R2M there is no safety gain:
mean regret worsens by 3.40%, squared regret by 5.81%, CVaR-1% by 2.51%, and
both P95/P99 worsen. Semantic diagnostics agree: relative to the start, the
endpoint has SR4 +7 winning-mate misses, +11 clear-advantage losses, and +2
non-losing-to-losing transitions; SR3-R2M has +11, +14, and +0 respectively.
Passing an absolute cap therefore means only that the candidate is allowed,
not that it is safer than the start or that its safety trade generalizes.

The corrected-gate tuple improves on f01, but is sixth of nine candidates on
SR4 and eighth of nine on untouched SR3-R2M by mean regret. Its SR3-R2M mean
is 0.000634 worse than previous D5, despite slightly better CVaR-1%. It is
therefore rejected as an endpoint and must not advance to SPRT. This one
short corrected-gate trajectory is evidence about this calibration and start,
not a reason to abandon the direct-reference gate design.

### Conclusion: fixed per-sample absolute gates did not establish a safety trade

The tested v2 rule—strict sampled mean-regret improvement subject to fixed
absolute squared-regret and CVaR-1% caps—did not produce an out-of-sample
safety trade. Its three gate rejections were already mean regressions, so the
caps did not reject any otherwise acceptable step; the selected endpoint then
lost both mean and safety metrics on SR3-R2M. Do not use this exact
per-sample constrained-mean rule or its `0.002800` / `0.380000` calibration
to promote a candidate.

This does not show that direct-reference safety metrics are unhelpful. It
shows that absolute feasibility caps do not *reward* safer proposals, while
the required positive mean improvement forbids an intentional mean-for-safety
trade. A mere blind tightening is not the preferred next run: the D3 start
itself reached 0.002689 squared regret and 0.365551 CVaR-1% on valid 20%
samples, so substantially lower fixed caps would make start feasibility depend
on subset luck and only modestly lower caps would probably remain inactive.

Before another engine run, do a read-only calibration over the retained v1/v2
paired attempt JSONL and completed full evaluations. Then review a new,
versioned optimizer contract with incumbent-relative same-subset safety
criteria: separate squared-risk, CVaR-risk, and both-risk tracks should
require a predeclared safety improvement (or non-worsening within a calibrated
tolerance) and allow only a predeclared bounded mean-regret concession. Use
the paired sample differences to choose those tolerances and the mean budget;
do not copy numeric limits from this failed absolute-cap test. Only then run a
short development-only trial, full-SR4-evaluate its durable endpoints, and
send at most the preselected development winner to untouched SR3-R2M.

### Relative-risk v3 implementation — 2026-08-31

`scripts/optimize_futility_gated.py` now writes a separate v3 manifest and
state schema (`chilo.futility_relative_risk_hillclimb.v3`). It cannot resume a
v1/v2 state: a fresh run directory is required because the acceptance
semantics changed. The name remains for continuity with the earlier operator
workflow, but v3 is not an absolute-gate optimizer.

Each track has an `acceptance` object with one of three modes:

| Mode | Required same-sample safety progress | Other safety metric | Mean regret |
|---|---|---|---|
| `squared` | squared-regret delta at most `-min_squared_regret_improvement` | CVaR-1% may worsen only within its configured tolerance | may worsen only through `max_mean_regret_concession` |
| `cvar1` | CVaR-1% delta at most `-min_cvar1_regret_improvement` | squared regret may worsen only within its configured tolerance | same bounded concession |
| `both` | both squared and CVaR-1% meet their required negative deltas | neither condition is waived | same bounded concession |

Here a delta is `proposal - incumbent`; negative is safer and positive mean
delta is a mean-regret concession. The optimizer persists the paired deltas,
thresholds, backstop result, and specific rejection reason for every attempt.
This makes the intended mean-for-safety trade observable instead of rejecting
it by construction. `max_squared_regret` and `max_cvar1_regret` are optional
nullable hard backstops. They can exclude a catastrophic candidate, but never
count as safety progress and should normally remain `null` until separately
justified.

`scripts/analyze_futility_gated_calibration.py` is the required read-only
preflight. Its config explicitly maps every retained v1/v2 run to a matching
anchor and every promoted tuple to its completed full-development and
selection outputs. It validates the state-recorded attempt JSONL identities,
recomputes their direct-reference paired deltas, and writes JSON plus a short
Markdown report. It reports empirical distributions only; it deliberately
does not generate a runnable v3 configuration or recommend thresholds.
See `scripts/futility_gated_calibration.example.json` and
`scripts/futility_gated_hillclimb.example.json` for schemas, not approved
numeric settings.

Implementation does not authorize a calibration run, package, optimizer run,
full evaluation, or SPRT. Review the resulting report and set the three
tracks' thresholds explicitly before any new development-only experiment.

### Old gated-D3 endpoint comparison — 2026-08-31

The completed cloud archive is retained as
`g3-sr4-gated-d3-endpoints-linux-rez.tgz` (SHA-256
`e5b02c3fd5de8ae41563e0dd2d0201c0bddf459f5a7bc12fca83b2efb3dec6a5`).
It contains six complete normal-PVS 120k JSONL outputs: the three old-gate D3
incumbents on every one of the 25,000 SR4 and SR3-R2M inputs. Its recorded
anchor/reference and mate-rescue identities exactly match the retained local
per-root combined populations: 22,825 SR4 and 22,934 SR3-R2M positions.

A fresh v2 direct-reference risk pass compared those outputs with f01, the
earlier D3/D5 endpoints, and both SPSA-150 endpoints on those exact complete
populations. Mean normalized regret is the ranking objective:

| Variant | Margins | SR4 mean regret | SR3-R2M mean regret |
|---|---|---:|---:|
| previous D5 | `10,54,175,264,503` | 0.014157 | **0.014233** |
| previous D3 | `23,62,194` | 0.014258 | 0.014378 |
| old-gate both | `31,104,198` | 0.014176 | 0.014398 |
| old-gate downside | `55,69,169` | 0.014371 | 0.014428 |
| SPSA-150 nearby | `0,40,158,488,754` | **0.014074** | 0.014452 |
| old-gate cvar1 | `14,68,259` | 0.014396 | 0.014564 |
| SPSA-150 center | `0,40,98,202,424` | 0.014082 | 0.014582 |
| f01 | `120,240,360` | 0.014772 | 0.015140 |

`31,104,198` is the best of the three promoted old-gate incumbents, but it is
0.000165 worse than the previous D5 tuple on the untouched selection shard.
It also trails the previous D3 tuple there by 0.000020. The downside tuple has
the lowest old-gate SR3-R2M CVaR-1% (0.317197), while the previous D3 has the
lowest SR3-R2M squared regret (0.002104); neither tail observation overrides
the mean-regret ranking. None of the three old-gate incumbents becomes an
SPRT candidate. The received archive records the net filename and matching
anchor hashes, but lacks a standalone build/weights manifest; retain that
provenance limitation with the result.

## Future: General Search-Pruning Optimization

The score-regret proxy is not inherently a futility-pruning measure. Given a
fixed high-quality reference-root map, the same candidate node budget, and a
candidate-selected root move, it measures the quality of any changed search
policy through the normalized reference score of that move. It can therefore
screen LMR, null-move pruning, razoring, and similar pruning/reduction
techniques, provided the net, corpus, node budget, reference contract, and all
non-tuned search settings remain fixed.

Do **not** generalize the implementation before selecting the next technique.
When that happens, retain the durable reference/proxy/evaluation machinery and
add a small technique adapter. The adapter owns the candidate CLI mapping,
parameter validation, legal constraints, and decoding; the optimizer only sees
an objective over a numeric latent vector. This keeps the reference format and
mean normalized score-regret objective shared rather than copying the futility
workflow for every pruning family.

Raw SPSA coordinates must not be assumed comparable across mixed parameters.
Futility margins happen to have similar native units, but LMR coefficients,
depth thresholds, null-move reductions, and guards do not. For a future
adapter, optimize normalized latent coordinates and decode each coordinate into
the engine parameter:

```text
normalized coordinate -> technique-specific scale/transform -> legal native value
```

Each coordinate should declare a start, a meaningful perturbation scale, a
safe feasible range, and any integer rounding or coupled constraints. Bounds
are a deliberate definition of the policy family being searched, not a claim
that the optimum lies at a boundary. Start with projection/clamping after
decoding; a sigmoid makes SPSA ineffective near a bound. Strongly coupled
parameters should use a constrained representation (for example a base value
plus nonnegative increments). Categorical choices and booleans should be
separate tracks or outer experiments, not forced into a continuous SPSA
direction. If needed later, coordinate-specific SPSA gains and perturbations
can reflect differing sensitivities.

Initially tune one pruning technique at a time. Its optimum is conditional on
the fixed settings of all the other pruning mechanisms; only after trustworthy
single-technique results exist should a deliberately scoped joint optimization
be considered. Keep missed reference-winning mates, candidate mate claims,
completed depth, speed, and futility-style counts as safety diagnostics. Mean
score regret remains the ranking objective, while diagnostics and final SPRT
guard against a proxy blind spot.

## Separate Search-Core Experiments

The `history-saturating` branch is a separate future experiment, not a
futility-margin candidate. It changes the quiet-history update itself, so its
candidate probes cannot be pooled with the existing f01/f21/D3/D5/SPSA or
gated evidence. Its initial 1,000-position, 256k fixed-node depth screen with
f21 margins showed only a modest mean completed-depth increase (+0.075 ply).

If that branch is pursued, use a clean paired experiment under the modified
search: regenerate the matching anchor/reference and baseline/candidate probe
outputs with the same source revision, net, corpus, and node budget. Do not
reuse the present per-root reference maps as direct strength evidence across
that search-core change.

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

1. `f21` already passed the longer-control SPRT against source futility
   `0.7.4`; do not automatically consume time on f22/f23 unless later
   per-root evidence makes one a useful structural control.
2. Test promising static tuples at at least one much shorter and one much
   longer control, for example 1+0.01, 6+0.1, and 30+0.3. Keep the net,
   openings, adjudication, and other tournament settings fixed across those
   comparisons.
3. Only if different tuples show repeatable wins in different budget ranges,
   implement a two-threshold short/normal/long selector at root-search setup.
4. Test the adaptive engine against the strongest fixed tuple at each target
   control, then against that fixed basis over a representative mixed control
   set. SPRT remains the strength gate.
