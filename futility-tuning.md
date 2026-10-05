# Futility Margin Tuning

This is the persistent record for futility-margin experiments. The current
source defaults remain `120,320,550` through depth three. Proxy tuning only
selects SPRT candidates; it does not establish playing strength.

## Accepted SPRT Basis

`f21` is the established practical control: its 6+0.1 SPRT against `f01`
accepted H1, and its longer-control SPRT against the source `g4t1-64x8`
accepted H1. `spsa150b` subsequently accepted H1 against `f21` at 30+0.5 and
is therefore the strongest directly tested futility tuple. `f01` remains
frozen as the anchor baseline, baseline-depth measurement, and a stable
comparison variant. The deep per-root reference, not f01, defines the current
tail-risk safety gates. Do not replace or overwrite either binary.

| Binary | Margins | Status |
|---|---|---|
| `chilo-0.7.5-f01-avx2` | `120,240,360` | Accepted previous basis; frozen anchor baseline. |
| `chilo-0.7.5-f21-avx2` | `75,212,390,600,839` | H1 accepted versus f01 at 6+0.1 and source `g4t1-64x8` at longer control; practical SPRT basis. |
| `chilo-0.7.5-spsa150b-avx2` | `0,40,158,488,754` | H1 accepted versus f21 at 30+0.5; strongest directly tested tuple. |

The variant manifest for `f01` through `f06` is maintained externally at
`~/Tune/futility/futility-sprt-g4t1-64x8-d3-d5-first.json`.

## Full SR4/SR3-R2M f21 and SPSA-150B Matrix — 2026-09-02

The returned Windows archive
`~/Tune/futility/g3-sr4-sr3-r2m-f21-spsa150b-matrix-win-rez.zip` (SHA-256
`79336a596c0aacc4c9d0f63f9f26a4b4bb0aa8c58c5431f25f37129b477693fc`)
contains four fresh, complete normal-PVS 120k probes: `f21` and `spsa150b` on
full G3-SR4 development and untouched G3-SR3-R2M selection inputs. Its package
artifacts, inputs, `per_root_v1` anchors, rescue sidecars, controls, probe,
and weights all match the package manifest. Analysis uses 22,825 trusted SR4
and 22,934 trusted SR3-R2M positions.

The SR3-R2M table is the historical single-shard validation view, not the
extended 141,099-position selection population documented below. Lower is better for every
metric except that the semantic columns are direct regression counts, which
are also lower-is-better. `Clear` is clear advantage lost and `Adv-><=0` is a
clear advantage becoming non-positive.

| Rank | Candidate | Margins | Mean regret | Squared | P95 | P99 | CVaR 1% | Mates / Clear / Adv-><=0 / Nonlose->loss | SPRT evidence |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `d3-0009` | `0,25,139` | **0.014369** | **0.002076** | **0.084819** | **0.199647** | **0.312449** | 218 / 216 / **17** / **14** | Not tested. |
| 2 | `spsa150b` | `0,40,158,488,754` | 0.014452 | 0.002167 | 0.084990 | 0.201051 | 0.321794 | **205** / 221 / 19 / 16 | H1 accepted versus f21 at 30+0.5. |
| 3 | `pareto-0041` | `0,44,205` | 0.014521 | 0.002167 | 0.085379 | 0.205161 | **0.319430** | 219 / 225 / 19 / 15 | Not tested. |
| 4 | `d3-0062` / `pareto-0040` | `0,58,205` | 0.014732 | 0.002231 | 0.086320 | 0.206254 | 0.325278 | 228 / 217 / 22 / 16 | Not tested. |
| 5 | `f21` | `75,212,390,600,839` | 0.014778 | 0.002278 | 0.085782 | 0.203774 | 0.329138 | 220 / 223 / 21 / 18 | H1 accepted versus f01; established control. |
| 6 | `f01` | `120,240,360` | 0.015140 | 0.002343 | 0.088668 | 0.208117 | 0.330023 | 230 / 228 / 21 / 18 | Lost to f21. |

`spsa150b` beats `f21` on every listed continuous metric on both full
populations; on SR3-R2M its mean regret is 2.25% lower, squared regret 5.12%
lower, and CVaR-1% 2.28% lower. The observed proxy and known game-strength
ordering therefore agree for the two direct edges `f01 < f21 < spsa150b`.
This is encouraging calibration evidence, not an Elo conversion or a license
to promote a proxy winner without SPRT.

At the time of this matrix, `d3-0009` was the best single-shard selection proxy
tuple, including every continuous risk metric. Its subsequent SPRT against
`spsa150b` did not pass; the table's "Not tested" entry records the historical
snapshot, not its later status. This is an example of proxy ranking not proving
superior playing strength. `d3-0062` trailed both on SR3-R2M.

### Pareto-v4 cloud search and 0041 evaluation — 2026-09-04

The one-worker cloud Pareto search from `d3-0009` ended after 63 proposals
(64 evaluated tuples including the initial point), rather than its requested
86. At the fixed three-depth perturbation radius it could not generate a new
unevaluated tuple after 1,000 deterministic retries; retries did not enlarge
that radius. This is an optimizer-neighborhood exhaustion, not a probe or
reference failure. The completed search archive is retained as
`~/Tune/futility/g3-sr4-pareto-v4-d3-86-linux-rez.tgz` (SHA-256
`be94ac76c4370054fbdd9933bceab7e102dc7907c8e6df919a629015d27753af`).

Its two useful final tuples were `pareto-0040` = `0,58,205` and
`pareto-0041` = `0,44,205`. `pareto-0040` is exactly the already evaluated
`d3-0062`, so only 0041 required fresh complete probes. The repair-only
analysis completed without rerunning those probes; its returned archive is
`~/Tune/futility/g3-sr4-sr3-r2m-pareto-0040-0041-results.tgz` (SHA-256
`a14d58cd7754909393a5fdff33af9f32d4a256e57de5fc61b088dfae0062e3ca`).
It contains normal-PVS 120k output for all 25,001 input records on each
population and direct-reference analyses over 22,825 trusted SR4 and 22,934
trusted SR3-R2M positions.

On development SR4, 0041 was the lowest-mean tuple (mean `0.014055`, squared
`0.002169`, CVaR-1% `0.324880`), narrowly ahead of `spsa150b` (`0.014074`,
`0.002188`, `0.329445`). The tail-oriented 0040 was better on SR4 squared
regret and CVaR-1% (`0.002143`, `0.322649`). On untouched SR3-R2M, 0041
regressed relative to `spsa150b` on mean regret (`0.014521` vs `0.014452`) and
P95/P99, although it had a slightly lower CVaR-1% (`0.319430` vs `0.321794`).
It also had more clear-advantage losses (225 vs 221). Thus 0041 is a useful
recorded Pareto trade-off, but not a compelling new SPRT priority over the
already SPRT-validated `spsa150b`. The selection table above is the matched
single-shard view at that time; use the later pooled-selection evidence for
extended validation.

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

Keep every anchor as its own paired raw JSONL evidence and manifest. The
current development/selection roles and canonical local registry are recorded
in `~/Tune/futility/validation/README.md`; that file is the operational source
of truth for current Pareto-search inputs, validation coverage, and archive
cleanup. The historical full-corpus G3-SR3-R2M comparison of the two SPSA
endpoints remains recorded below from durable probe output, not inferred from
development results.

### Current corpus roles and extended selection store — 2026-09-17

G3-SR4 is the only development population: its mate-rescue combined reference
has 22,825 trusted positions. It is where optimizer proposals are generated;
do not count it as candidate validation.

The current validation population contains 141,099 trusted positions under the
same `per_root_v1`, f01-120k, `B + 2`, 2M/root contract:

| Selection component | Nominal inputs | Trusted positions | Role |
|---|---:|---:|---|
| G3-SR3-R2M | ~25,000 | 22,934 | Original untouched selection shard |
| SR3V production (`sr3v-01`…`05`) | 125,000 | 114,507 | Extended selection population |
| SR3V smoke (`sr3v-test1`, `test2`) | 4,000 | 3,658 | Retained test shards; disjoint from SR3V production |
| **Selection total** | **~154,000** | **141,099** | Current validation set |

The difference between nominal and trusted counts is expected reference-quality
filtering: a position is retained only when every legal root reaches its
required `B + 2` depth; mate rescue restores certified rejected mate cases.
The three components are FEN-disjoint by sampling exclusions. Keep their raw
JSONL evidence separate and pool metrics by position, never by concatenating
or replacing reference files.

The first extended batch, retained as
`g3-sr3v-initial-candidates-v1-results.tgz` (SHA-256
`ffe4bf8f7adf09315c7ac42466f638b5c728bb27acede4b64ffd5cb846c41929`),
gave f21, spsa150b, and d3-0009 complete normal-PVS 120k coverage on the
118,165 new SR3V positions. Together with their matching full G3-SR3-R2M
probes, these are their first exact additive whole-selection results:

| Candidate | Margins | Mean regret | Move agreement | Squared regret |
|---|---|---:|---:|---:|
| spsa150b | `0,40,158,488,754` | **0.014176** | **57.451%** | **0.002108** |
| d3-0009 | `0,25,139` | 0.014446 | 57.176% | 0.002141 |
| f21 | `75,212,390,600,839` | 0.014707 | 56.938% | 0.002229 |

These figures are exact position-weighted aggregates over all 141,099 trusted
selection positions. P90/CVaR are non-additive order statistics, so do not
label them as full-selection values until they are recalculated from the now
canonical raw root-score maps in one pooled pass. The table is proxy evidence
only; `spsa150b`'s existing SPRT win over f21 remains the game-strength
evidence.

On the cloud server, keep raw evidence and candidate outputs separate:

```text
~/futility-validation/
  populations/per-root-v1/development/g3-sr4/
  populations/per-root-v1/selection/g3-sr3-r2m/
  populations/per-root-v1/selection/sr3v-production/run/
  populations/per-root-v1/selection/sr3v-smoke/run/
  artifacts/<probe-sha>-<weights-sha>/  # exact frozen executable and net
  candidate-probe-cache/                # immutable normal-PVS outputs, keyed by raw search contract
  evals/<batch-name>/                   # disposable normal-PVS outputs/reports
```

`scripts/setup_futility_validation_store.sh STORE_ROOT PROD_PACKAGE
[SMOKE_PACKAGE]` is the guarded one-time migration. It requires completed
receipts, refuses existing destinations, moves only each package's `run/`,
leaves an old-path symlink for provenance, and copies the exact probe/net into
the hash-named artifact directory. It never runs a probe.

`scripts/run_futility_validation_batch.py --config CONFIG` is the serial
candidate evaluator. A config names the immutable input, anchor, and rescue
directories for every shard plus the frozen probe/net and candidate tuples. It
hash-binds all of them in `batch_manifest.json`, reuses only complete candidate
JSONL files, and writes normal PVS outputs only below the new evaluation run.
It pools records by position only after each shard's anchor/rescue contract has
validated. Use `--dry-run` before a cloud launch; rerunning the same command
continues after an interruption, but a partially written ordinary candidate
probe is intentionally restarted from scratch.

`candidate-probe-cache/` is deliberately below the same validation-store root
but outside an evaluation campaign. Its content-addressed key binds only the
normal-PVS search contract: probe and weights hashes, ordered input hashes,
node budget, and margins. It excludes the reference/rescue evidence, score
scale, reporting cadence, paths, and campaign name. A cache hit is copied into
the campaign or validation job's normal output path, so the campaign still
contains self-contained raw evidence and calculates its own reference-relative
metrics. Cache entries are immutable; a malformed or mismatched entry is an
error, never an overwrite.

`scripts/backfill_futility_probe_cache.py --store-root STORE_ROOT --dry-run`
inspects only canonical `STORE_ROOT/evals/` manifests and complete normal-PVS
JSONL outputs. The non-dry-run form validates every source artifact identity
before importing each output into the cache; `--report PATH` preserves its
import/existing/skipped receipt. It is the one-time cloud migration for prior
campaign and batch outputs, not a way to import ad-hoc files from elsewhere.

### Forward Pareto workflow

Future Pareto work should begin by choosing one or more documented starting
tuples, then run both the development search and candidate validation on the
cloud. The cloud retains immutable raw references and produces only the
relevant candidate JSONL/manifests under its evaluation store. Copy those
returned candidate results here into the local validation registry for raw
analysis and comparison over the current selection set. Decide there which
tuples merit SPRT; run the SPRT locally, not on the cloud. This keeps expensive
search and validation remote while preserving the final evidence and
promotion decision beside the local engine/test environment.

### Unified campaign runner

`scripts/run_futility_campaign.py` remains the entry point for individual Pareto
searches and explicit validation batches. For continuous automatic promotion,
use the loop below. A campaign config names the immutable development and selection
populations, one fixed candidate probe/net pair, the common 120k/f01 scoring
contract, Pareto parameters, and explicitly selected validation tuples. Its
only writable location is `store_root/evals/<run_id>/`; the campaign manifest
records both the frozen campaign artifacts and the historical anchor
provenance. A historical Windows/Linux reference probe therefore does not have
to equal the new candidate probe, but neither identity is hidden.

Use `--phase search`, `--phase validate`, or explicit `--phase all`.
`--max-work-units 1` performs one initial/proposal probe or one
candidate-by-shard probe, allowing safe cron execution; `0` is an unlimited
interactive invocation. The `all` phase never derives validation candidates
from the Pareto frontier: validation candidates remain explicit in the config.
The companion `scripts/run_futility_campaign_cron.sh CONFIG all 1` wraps that
command in a non-blocking `flock` and appends to the campaign's `cron.log`.
Interrupted ordinary candidate JSONL is intentionally rerun, while completed
probe output and atomic optimizer state are reused.

For a fresh search, `pareto_search.initial_margins` is measured normally. A
later campaign can instead seed itself from a completed proposal in an earlier
campaign, without naming or manually copying a JSONL file:

```json
"initial_evaluation": {
  "campaign_run_id": "previous-campaign",
  "evaluation_id": "candidate-0007"
}
```

When this field is used, omit `pareto_search.initial_margins`; the stored
proposal margins are authoritative. The runner obtains the raw normal-PVS
output only from `evals/<campaign_run_id>/search/state.json`, validates its
recorded probe/net, SR4 reference/baseline/rescue contract, and output hash,
then atomically stages it as the new run's `search/probes/initial.jsonl`.
It rejects a candidate from a different fixed campaign probe rather than
silently mixing search implementations. The approved source output is first
imported into the raw-probe cache if necessary, then the current campaign
stages its independent copy. The cache receipt is stored as
`search/logs/initial.cache.json`; a staged complete initial JSONL does not
consume a work unit, so a one-unit cron invocation can begin proposal 1
immediately.

### Continuous development/selection loop — 2026-09-18

`scripts/run_futility_loop.py` coordinates the existing Pareto optimizer and
full-validation batch evaluator on Linux, using only the Python standard
library. Start from `scripts/futility_loop.example.json`. It runs indefinitely;
preparing the config does not start any engine work. No SPRT is launched by
this tool, and no extra holdout is introduced: pooled selection metrics screen
candidates, while actual SPRT is the independent playing-strength decision.

The phase sequence is:

1. If initialization has pending validation tuples, validate them and the
   manually designated SPRT best first. Otherwise begin with development.
2. Start each dev cycle from that SPRT best on **SR4 only**, with a fresh
   deterministic seed (`search.seed + cycle - 1`). Within the cycle, parents
   come from its evolving Pareto frontier. Default: 15 proposals, one worker,
   `perturbation_c=40`, `perturbation_gamma=0.101`, `max_margin=1200`.
3. Apply the dev selector and schedule only tuples not already fully validated
   under this loop's fixed contract. Validate survivors over **all configured
   selection shards**, including rescues. Existing raw-probe cache hits avoid
   engine work; missing candidate/shard pairs run serially. The proven base
   also receives complete matching coverage before challenges are published.
4. Rebuild the cumulative selection frontier from every fully validated tuple.
   Compute pooled metrics from position-level data, never averages of shard
   CVaRs. Publish surviving untested tuples to the manual SPRT queue and return
   to development. A cycle with no new validation tuples goes straight to the
   next dev cycle.

`dev_selector` and `validation_selector` are independent. Each selects any
nonempty subset of `mean_regret`, `squared_regret`, `cvar1` as minimization
objectives (all three by default), then applies ordered semantic filters.
Defaults discard the worst 25% by missed winning mates, followed by the worst
25% by nonlosing-to-losing transitions. These are reference-relative metrics.
Cutoff ties are retained, so these fractions are not hard queue-size caps;
`semantic_filters: []` disables semantic decimation. No scalar ranking is
implied between nondominated survivors.

The example initializes the proven base to spsa150b `[0,40,158,488,754]` and
the validation pool to candidate-0014 `[0,70,218,578,814]`. Review these before
starting. `initialization.imports` optionally lists prior campaign or batch
run directories. Imports verify artifact/input and recorded output hashes,
parse complete raw probes, and populate the shared cache; they never trust
old aggregate statistics as the new selection result. A partial-shard batch
adds its tuples to pending validation and fills only missing probes. Prior
campaign searches supply dev cache evidence, not selection evidence. The
source directories are not modified. Inputs must retain accessible recorded
artifact paths (as in the canonical cloud store); ad-hoc JSONL and older matrix
layouts must first be migrated explicitly. Initialization is immutable once
the loop exists.

One operational directory is `store_root/evals/<loop_id>/`:

| File/directory | Purpose |
|---|---|
| `loop_state.json` | Authoritative atomic checkpoint: fixed contract, active phase, candidates, pending validation, complete validation archive, policy revisions and queue history |
| `control.json` | Short-lock-protected stop request, manually updated proven base, and SPRT status commands |
| `cycles/000001/` | Automatically named dev subrun, frozen config, resumable optimizer state and raw probes |
| `validation/000001/` | Automatically named whole-selection batch, raw probes and pooled results (number is the phase number) |
| `selection_frontier.json`, `sprt_queue.json` | Regenerable projections of the checkpoint; queue entries include stable tuple IDs, aliases and margins |

Stable tuple IDs bind margins to the full evaluation contract. Changing the
probe/net, inputs, reference/baseline/rescue data, population membership,
candidate budget, score scale, or metric version requires a **new loop ID**.
The full-validation archive prevents repeat validation across cycles; this is
separate from the shared raw cache, which can reuse matching candidate/shard
probes even when a new loop is necessary.

Operator commands (replace `loop.json` with the actual config path):

```bash
python3 scripts/run_futility_loop.py run --config loop.json
python3 scripts/run_futility_loop.py status --config loop.json
python3 scripts/run_futility_loop.py stop --config loop.json
python3 scripts/run_futility_loop.py resume --config loop.json
python3 scripts/run_futility_loop.py set-base --config loop.json --margins 0,40,158,488,754 --alias spsa150b
python3 scripts/run_futility_loop.py sprt --config loop.json --candidate t-REPLACE --status running --note 'local SPRT started'
```

`stop` requests a graceful stop **after the entire active dev or validation
phase**, not between candidate probes. Wait until `status` reports
`stopped: true`. Cron invocations then remain stopped until explicit `resume`.
A `set-base` update is read at the next dev cycle, never halfway through the
current phase. Record SPRT `running`, `accepted`, or `rejected` manually; these
statuses survive later frontier changes and do not change the proven base.
Untested `pending` entries become `superseded` if no longer qualified and can
requalify later. Status commands are applied at a phase boundary (or upon
resume if the loop is stopped); retain SPRT evidence outside this proxy loop.

To change selectors or search parameters: request `stop`, wait for the phase
boundary, edit the config, run `reconfigure --config loop.json`, then `resume`.
Reconfiguration records a new policy revision, reselects archived dev results
and rebuilds the selection queue without discarding completed validation.
Already pending validation remains pending. Editing config while a phase is
active is rejected at its boundary; restore the prior config to stop cleanly.

For cron, use `crontab -e` to add an entry like the following, with absolute
paths and a pre-existing log directory:

```cron
*/10 * * * * bash /absolute/scripts/run_futility_loop_cron.sh /absolute/loop.json >> /absolute/loop.log 2>&1
```

The runner owns a nonblocking process lock; an existing `loop.lock` file is
not evidence of a running process. The launcher stays alive across phases;
later cron invocations exit while it is running. After an unexpected failure,
the next invocation resumes the active subrun; complete probes are retained,
but a partially written ordinary candidate probe is rerun. Use `stop`, not
killing just the Python parent and leaving orphan engine processes. For a
bounded local smoke test, `run --max-phases 2` returns after two whole phases
without setting the persistent stop flag (cron would continue it).

### BO motivation and original proposal — historical 2026-10-03

The proposal below motivated the subsequent pilots. BO is now implemented as
an opt-in continuous-loop backend; see "BO in the continuous loop — 2026-10-05"
for current operation. Implementation does not imply that a remote loop has
been switched or that BO candidates have passed validation/SPRT. BO assumes
that mean normalized regret is the main useful
proxy for strength; the metric-to-Elo relationship still needs empirical
calibration from SPRT results.

The 2026-10-03 loop review makes this option timely. After 22 completed dev
cycles, 330 proposals covered 263 distinct new tuples, and the validation
archive contained 30 fully evaluated tuples. No new SPRT queue entry had been
produced since cycle 6. Removing dev semantic filters allowed further tuples
through validation, but none from cycles 14–21 entered the global validation
Pareto frontier. Cycle 22's two nominees were still awaiting validation.
The snapshot is preserved in `~/Tune/futility/futility-loop-review-20261003.tgz`.
This indicates diminishing screening yield, not proof that the neighbourhood
contains no stronger tuple. Rejected SPRT candidates remain in the metric
archive and can still dominate subsequent candidates under the current policy.

BO would fit a predictive model to evaluated margin tuples and choose further
evaluations by balancing predicted improvement against uncertainty about
unexplored tuples. It would learn from unsuccessful evaluations as well as
frontier members. With only 3–7 integer margins and expensive probes, this
could reduce the number of engine evaluations required. The benefit is not
guaranteed: small integer margin changes can produce irregular search results.

The preferred first experiment is:

1. Use a separate search for each fixed maximum futility depth, preserving
   nonnegative, nondecreasing integer margins and explicit feasible bounds.
   Keep the manually designated SPRT best as the comparison baseline; a new
   depth needs an explicitly chosen starting tuple of that depth.
2. Optimize mean regret on the full, fixed SR4 development population. Warm
   start from compatible, previously evaluated tuples of the same depth,
   including unsuccessful proposals, and retain observations between phases.
   A short new phase should not restart learning from scratch.
3. Give each phase a configurable budget of new probe evaluations. Reuse the
   existing cache under matching probe, weights, inputs, and node budget;
   model observations must also match the reference/population and metric
   contract. Deduplicate tuples after integer projection.
4. Nominate at most one new, actually evaluated development candidate for
   full pooled validation. A single nominee is an operating policy, not proof
   of a unique optimum. If the best tuple is already validated, use its saved
   result and consider the next eligible tuple or continue development; do
   not repeat validation merely to fill a phase.
5. Retain tail and semantic metrics for comparison and collect SPRT outcomes.
   Initially avoid adding uncalibrated hard tail gates to the scalar search;
   validation and SPRT still decide whether a nominee deserves promotion.
   Compare BO against a mean-regret random search with the same fresh-evaluation
   budget and starting evidence, so changing the objective from Pareto to
   mean regret is not mistaken for an improvement from BO itself.

On a fixed corpus with a deterministic probe, a tuple's measured regret is
repeatable. Finite-population uncertainty concerns generalization to other
positions and real games; repeating the same probe does not reduce it.
BO's uncertainty about unevaluated tuples is a separate quantity. The smaller
development population can also reward changes that fail on validation.

The available observations support different targets. The 263 new dev tuples
can seed a model of SR4 metrics; only the 30 fully validated tuples can seed
a model of full pooled validation metrics. Include the compatible initial
control as well, deduplicate observations, and verify contracts before reuse.
A model trained on dev mean regret predicts dev mean regret: better acquisition
does not itself correct development-to-validation ranking reversals or the
proxy-to-strength mismatch. Judge this first experiment by whether it finds
better validation nominees for a fixed fresh-evaluation budget, not merely
lower SR4 values.

A later alternative is to optimize pooled validation mean regret directly:
each call is more expensive, but the model learns the quantity used for
selection. Validation then participates in optimization, while SPRT remains
the final independent strength test. A more complex multi-fidelity model
could use both dev and validation observations to allocate effort; it must
learn their relationship rather than treat their scores as interchangeable,
given the ranking reversals already observed between populations.

Validation's current three-metric Pareto target does not have to be collapsed
into an assumed Elo exchange rate. Possible BO formulations are scalar mean
regret, mean regret with explicit tail restrictions, or multi-objective BO over
mean regret, squared regret, and CVaR-1%. The scalar development experiment
above is the simplest first comparison. Tail limits still need calibration;
multi-objective BO preserves trade-offs but adds complexity. If scalar dev BO
mainly finds SR4-specific winners, reconsider direct validation optimization
or a model trained on paired dev/validation observations.

Targeting game strength directly remains a future experiment after the current
2–3 day SR4 BO loop review (see the plan below). We currently have too few
comparable margin-only SPRT results to fit a useful five-dimensional strength
model, and differences of a few Elo remain uncertain. Collect numerical Elo,
its reported uncertainty, baseline, time control, and engine/net provenance;
binary acceptance/rejection alone loses useful information. In particular,
the cycle-6 comparison used a different move-ordering implementation from its
baseline, so it is not an isolated margin observation. These outcomes can
eventually inform a strength model, but do not yet justify replacing the
production objective with SPRT outcomes.

The initial standalone implementation below reused the probe/cache and
population interfaces without replacing the continuous Pareto loop. BO has
since been integrated as its development backend; see "BO in the continuous
loop" for current operation. Neither path requires a new reference run.

### Future: Direct game-outcome BO with sequential matches

Revisit this after the current 2–3 day BO loop run, alongside its new full
validation results and the `bo4-p0001` SPRT. This is a design proposal, not an
implemented backend or authority to launch another expensive experiment.

The objective would be playing strength measured in engine matches, rather
than score regret or a synthetic combination of mean/tail metrics. Describe
it as **BO over game outcomes with SPRT stopping**, not optimization of binary
SPRT pass/fail. Keep accepted, rejected and budget-limited/inconclusive runs as
numerical observations with uncertainty. Proxy observations may suggest initial
coordinates or eventually support a qualified multi-fidelity model, but must
not be relabelled as Elo observations.

Potential advantages are avoiding proxy-to-strength mismatch, early termination
of clearly inferior proposals, and obtaining game-strength evidence during the
optimization itself. Clearly superior candidates can also finish quickly;
near-equal candidates or candidates near the SPRT decision boundary can be
exceptionally expensive. BO may increasingly propose such small improvements.
Early rejection does not guarantee lower total cost than proxy screening.

#### Measurements and BO support

- Freeze the reference opponent, engine/search source, net, opening policy,
  resource budget and adjudication rules within the first experiment. Start
  locally around spsa150b and use only comparable margin-only historical match
  measurements. Changing the opponent changes the target; do not automatically
  switch it after finding a winner. Mixing opponents would require an explicit
  strength/comparison model, not simply adding Elo differences as common labels.
- Retain paired-game pentanomial counts, numerical strength estimates and
  uncertainty, game counts, stopping reason, resource consumption, and exact
  tuple/source/net/opponent/opening provenance. Preserve negative and
  inconclusive observations as well as successes. Fast rejection is a useful
  decision, not a guarantee of a precise effect-size estimate.
- Begin with per-observation variance estimates supplied to the GP, rather
  than a second model learning the noise function over parameter space. Match
  lengths and outcome distributions differ, so one shared observation-noise
  level is inadequate. Tinibo currently supports shared learned noise; it
  needs an explicit variance API, correct scaling into standardized target
  units, replay/checkpoint support, and replacement/aggregation of a tuple's
  measurement when further game batches arrive. Its current duplicate-ignore
  behavior cannot silently discard those additional measurements.
- Choose the estimation procedure before implementation. Sequential stopping
  and adaptive selection complicate interpreting terminal Elo/error bars;
  do not blindly regard every displayed pair as an unbiased Gaussian sample.
  Use pentanomial-aware uncertainty and qualify the approximation under the
  actual stopping rule. A likelihood-based outcome model is a later alternative
  if Gaussian strength summaries prove unreliable.
- Evaluate in resumable game-pair batches, with a hard maximum budget and
  retained inconclusive results. Permit allocating further games to a promising
  but uncertain existing tuple, not only proposing new tuples. Acquisition
  should use uncertainty about latent strength rather than chase the luckiest
  raw estimate; evaluate whether variable measurement cost warrants explicit
  cost-aware allocation.
- A short-control H1 acceptance still has false-positive risk, amplified by
  repeatedly selecting promising measurements. Fresh confirmation for finalists
  is valuable; longer-control confirmation remains necessary for pruning and
  reductions. No fitted proxy-to-Elo exchange rate is assumed.

Tinibo work should follow our usual requirements/fixture handover and handback
procedure. Qualification should include unequal-variance weighting, continued
measurements, exact checkpoint replay, synthetic known-strength matches under
the chosen sequential stopping rule, and matched-budget comparisons with the
existing proposal method. Judge progress by confirmed strength per total
compute budget, not merely the number of H1 decisions or a lower fitted loss.

#### Fixed-node games on the cloud

The proposed first variant allocates the same fixed node budget per move to
both players. Identical search code and weights differ only in runtime futility
tuples; later the parameter interface could cover other pruning/reduction
methods. Cloud load then changes completion time rather than the competitive
search allowance. It does **not** eliminate game noise or the compute cost of
near-equal comparisons.

The source already exposes `SearchLimits.nodeLimit` and runtime
`SearchParameters` for futility. `chilo.cpp` accepts UCI `go nodes`.
`selfplay_collect.cpp` currently offers depth/time-driven training-data games,
stochastic early move selection and leaf collection, so it is reusable game
logic, not an already complete fixed-node match runner.

The lowest-infrastructure prototype is fixed-node fastchess, retaining its
existing SPRT, paired games, adjudication, logs and recovery. Its engine
configuration supports `nodes=N`. Initially use matched-source tuple binaries;
a later runtime UCI tuple option could let both players use the same binary.
This option is not presently exposed by our UCI interface, and our wrapper
still needs node-budget configuration support. Verify installed fastchess
behavior and watchdog/recovery handling before an unattended run.

If an integrated runner is worthwhile later, reuse the collector's move/game
logic but disable training leaf collection and stochastic move sampling during
competitive play. Required additions are per-player parameters/node budgets,
paired openings with colours reversed, completed-pair journaling, robust game
termination/adjudication, resumable statistics and sequential stopping. Search
currently has global state including its transposition table: two alternating
tuples must not share the other's cached search results. Use separate player
contexts/processes, or deliberately isolated searches for both with the loss
of between-move TT reuse explicitly documented. Parallel matches must not run
unsafe shared-global searches in threads.

Fixed-node strength is not identical to equal-time strength. Pruning can change
cost per node, and constant nodes per move removes normal time allocation.
Treat node budgets as distinct experimental conditions; verify speed effects
and confirm finalists under normal short and longer time controls. This first
experiment should retain a fixed budget rather than pool results from several
budgets or time controls as interchangeable labels.

Useful primary references:

- [Fishtest statistical methods](https://official-stockfish.github.io/docs/fishtest-wiki/Fishtest-Mathematics.html)
  for pentanomial outcomes and sequential Elo estimation.
- [Fishtest FAQ](https://official-stockfish.github.io/docs/fishtest-wiki/Fishtest-FAQ.html)
  for uncertainty, selection bias and staged testing.
- [BoTorch model documentation](https://botorch.org/docs/models)
  for supplied observation variance versus learned heteroscedastic noise.
- [Fastchess manual](https://github.com/Disservin/fastchess/blob/master/man.md)
  for fixed-node engine configuration and match/SPRT facilities.

### Standalone BO pilot — 2026-10-03

`scripts/run_futility_bo.py` integrates the separately maintained `tinibo`
library; `scripts/futility_bo.example.json` describes the first cloud pilot.
The package builder `scripts/package_futility_bo_pilot.py` freezes both Git
revisions, the complete Chilo Python import closure, the numerical library,
configuration, and external artifact/population hashes. No probe, population,
cache, or development environment is duplicated in the package.

The pilot starts from the operator-designated SPRT best `spsa150b`,
`[0,40,158,488,754]`, at depth 5 and 120k candidate nodes. It imports **all
completed compatible development cycles** from `futility-loop-v1`, checking
each raw probe's hash, position coverage, metric contract and target. Repeated
tuples are deduplicated; conflicting targets fail rather than being averaged.
Full validation records are imported separately only to exclude already
validated nominees, never as development training labels.

Five sequential new-to-model tuples are selected by expected improvement of
SR4 mean normalized regret. Each pool contains 10,000 unseen, nonnegative,
nondecreasing integer tuples bounded by 1200: 80% local perturbations (±80 cp
around the base and ten best observed tuples), 20% broad samples. The qualified
model is Matérn-5/2, scaled GP fitting, learned noise, raw `xi=0`, eight coverage
restarts and 100 fit iterations. These are configurable, frozen run settings.
Tail and semantic metrics remain diagnostics, not acquisition gates.

Before preparing this pilot, tinibo's real-data qualification used 264 distinct
development observations: predictive RMSE was 23.8% below the mean predictor,
and a matched finite-pool experiment improved normalized optimization regret
by 54.4% over random search. These establish numerical/model suitability, not
playing strength or guaranteed improvement on new engine evaluations.

Gracefully stop the source loop first and wait for its phase boundary. The
pilot holds that loop's existing process lock without changing its control
files; the stopped old loop can remain registered in cron. A separate pilot
lock makes overlapping invocations no-ops. Pending tuples, acquisition
diagnostics, pool RNG and tinibo state are checkpointed **before** probing.
Completed raw outputs/cache entries are reused after interruption; the same
proposal sequence is preserved on resume. Python, NumPy, helper code, config
and effective contracts must remain unchanged within a pilot.

The cloud package contains `setup.sh`, `run.sh`, `collect.sh` and a real-data
numerical/checkpoint-replay qualification. Setup creates a small NumPy-only
venv, verifies package hashes and external contracts, and does not search.
Python 3.10–3.13 uses pinned NumPy 2.2.6; Python 3.14 uses 2.5.3. The target
runtime must pass qualification before launch; these environments need not
produce identical proposals to each other.

```bash
cd ~/futility-bo-d5-pilot1-linux
bash setup.sh
nohup ./run.sh > runner.log 2>&1 < /dev/null & echo $! > run.pid
```

Use the same `run.sh` to resume, or add it to cron after successful setup.
`--max-evaluations 1` bounds an invocation, not the total five-step budget.
Each previously unseen tuple counts once even if its probe is a cache hit.
`SIGTERM`/foreground Ctrl-C terminates the child probe and retains the pending
tuple. The pilot does **not** automatically validate, enqueue SPRT, or change
the best tuple.

Outputs live at `store_root/evals/bo-d5-pilot1`: `manifest.json`, frozen
`observations.json`, authoritative `state.json`, five raw probe JSONLs,
`results.json`, `report.md`, and `nominee.json`. At completion, at most one
actually evaluated, previously unvalidated tuple improving the base dev mean
regret is nominated. No improvement produces no nominee. Review locally,
then decide whether to run full pooled validation. `bash collect.sh` archives
this small output with the package and numerical receipts for transfer back;
it excludes the shared cache, populations and venv.

Adapter tests (using tinibo's qualified environment, without engine searches):

```bash
PYTHONPATH=../tinibo:scripts ../tinibo/.venv/bin/python -m unittest scripts.test_run_futility_bo
```

Recovery tests cover interruptions before probing, after raw-output completion,
and during checkpoint commit, along with cache reuse, exact proposal replay,
contract/history mismatches, locking, and development/validation separation.

#### Pilot 1 outcome and local-only continuation — 2026-10-04

The first pilot imported 264 distinct development observations and 32 full
validation records. All five probes were cache misses; summed probe time was
3h 48m. The returned archive is `~/Tune/futility/bo-d5-pilot1-results.tgz`
(SHA-256 `a6035e391eb151fbd23da52c91b5ba5953dcd479294775f05837bcfcb0972f13`).
Raw outputs and diagnostic replay are preserved under
`validation/evaluations/bo-d5-pilot1/`. Hashes, raw normal-PVS records and
recomputed full SR4 metrics matched; all selected tuples and candidate-pool
hashes were reproduced offline.

| Candidate | Margins | Predicted mean regret | Actual mean regret | Squared regret | CVaR-1% |
|---|---|---:|---:|---:|---:|
| spsa150b | 0,40,158,488,754 | — | 0.014074236 | 0.002188075 | 0.329444948 |
| bo-0000 | 1018,1019,1126,1194,1198 | 0.014228287 | 0.016771965 | 0.002874692 | 0.372479662 |
| bo-0001 | 53,88,116,1124,1168 | 0.014125525 | 0.014426743 | 0.002324253 | 0.339487444 |
| bo-0002 | 63,173,1105,1129,1143 | 0.014666246 | 0.014718863 | 0.002278023 | 0.335573453 |
| bo-0003 | 2,20,69,119,237 | 0.014323384 | 0.014401331 | 0.002257035 | 0.332991009 |
| bo-0004 | 25,958,980,1136,1147 | 0.014975192 | 0.015379624 | 0.002506884 | 0.347690624 |

No tuple improved the base on any of the three main metrics, so no nominee
was produced. All five selections came from the 20% broad pool component;
an 80% local pool is not an evaluation quota. EI favoured high uncertainty
outside the observed region. Imported depth-1 margins spanned only 0–77,
whereas the first proposal used 1018; its measured result was about 12 latent
model standard deviations above prediction. No zero-EI fallback occurred.
This exposes extrapolation/calibration weakness; it is not evidence of a
probe failure, nor sufficient evidence to abandon BO within the measured
neighbourhood.

Completed BO runs can now be imported explicitly with `import_bo_runs`:

```json
"import_bo_runs": ["bo-d5-pilot1"]
```

The runner imports their **completed evaluations**, including poor ones, after
checking the frozen metric/population contract, producer lock, complete state,
raw output hashes and coverage, frozen observation hash and recorded history.
It deduplicates tuples against the loop and other imported runs; conflicting
targets fail. Numerical runtime/model settings may differ between experiments:
these are measurements, not restored GP checkpoints. Imports are frozen in the
new run's `observations.json`, so resume does not require rereading old BO runs.
For later continuations, explicitly list every earlier BO run whose completed
evaluations should be carried forward; imports are not discovered recursively.

The second pilot configuration is `scripts/futility_bo_local.example.json`:
`bo-d5-pilot2`, five new sequential evaluations, the same seed, model, probe,
weights and node budget, but `local_fraction=1.0`. It adds the five pilot-1
measurements to the 264 loop observations (269 total with the loop unchanged).
The aim is to isolate candidate-domain effects, not promise improvement.
Keep the source loop stopped, leave the old package/results untouched, and
launch the new package through its own setup/run scripts. The collection
script now derives the result archive name from the configured run ID.

#### Pilot 2 outcome — 2026-10-04

The local-only continuation correctly imported all 269 distinct observations,
including the five measured pilot-1 points, and retained 32 full validation
records separately. Five new normal-PVS probes were completed (all cache
misses), using 3h 50m summed probe time. Archive:
`~/Tune/futility/bo-d5-pilot2-results.tgz`, SHA-256
`dacad4f0c91b71eacc628148f1843a99673f809bd9462258fa023cb5fc40eec6`.
Canonical evidence: `validation/evaluations/bo-d5-pilot2/`.

| Candidate | Margins | Predicted mean regret | Actual mean regret | Squared regret | CVaR-1% |
|---|---|---:|---:|---:|---:|
| spsa150b | 0,40,158,488,754 | — | 0.014074236 | 0.002188075 | 0.329444948 |
| bo-0000 | 103,105,222,374,578 | 0.014153970 | 0.014423719 | 0.002316794 | 0.338962906 |
| bo-0001 | 2,115,189,786,856 | 0.014154079 | 0.014323163 | 0.002261677 | 0.331050825 |
| bo-0002 | 0,0,324,786,830 | 0.014319889 | 0.014632794 | 0.002329913 | 0.337368484 |
| bo-0003 | 46,50,178,786,984 | 0.014262149 | 0.014121074 | 0.002283102 | 0.338180558 |
| bo-0004 | 87,92,327,442,815 | 0.014214647 | 0.014296046 | 0.002314955 | 0.338255247 |

All five were worse than the base on all three main development metrics; no
nominee was produced. The best mean regret was bo-0003, 0.33% worse than the
base. There is no full-selection or SPRT evidence for these BO candidates.
The source experiment's numbering is package-local: distinguish
`bo-d5-pilot2/bo-0003` from the earlier pilot's `bo-0003`.

Verification matched the producer/backend hashes, contract, five prior
measurement imports, raw probe hashes, checkpoint/results history, and
recomputed complete SR4 metrics/risk/semantic counts. Offline replay reproduced
the five candidate-pool hashes, selected tuples and final pool RNG; numerical
predictions were compared with tolerance because the local Python/NumPy runtime
differs from the cloud runtime. No zero-EI fallback occurred.

Removing broad exploration did not produce an improvement in this small
sample. Four proposals lay 80 cp from their nearest measured tuple in maximum
coordinate distance; the fifth lay 74 cp away. The model's predictions at the
known controls expose smoothing: initially it predicts 0.014195 for the base
(measured 0.014074) and 0.014141 for `[30,66,188,454,656]` (measured 0.013911,
the best imported development target). EI compares with that best **measured**
target, not the fitted mean at the incumbent. Consequently, a promising
low-uncertainty pool point can have very little EI, while a more uncertain edge
point wins. This is an acquisition/surrogate diagnostic, not proof of a bug.
The learned noise represents a modeling approximation; fixed-probe scores
remain deterministic and these standard deviations are not Elo uncertainty.

On these five acquisition-selected points, saved prediction RMSE was 0.000213
versus 0.000203 for a sequential running-mean predictor. This is a tiny,
selection-biased diagnostic, not an independent model qualification failure.
The accumulated 274 development measurements should inform offline comparison
of GP smoothing/noise, coordinate sensitivity and noisy-incumbent acquisition
behaviour before another unchanged expensive pilot. Keep all ten new BO
measurements; there is no reason to discard valid poor results.

#### Tinibo follow-up and acquisition integration — 2026-10-04

Tinibo's completed offline comparison is recorded in
`~/Sources/tinibo/benchmarks/results/futility-followup-2026-10-04/README.md`
and `HANDBACK.md` (final evidence commit `4d57553`). Its report audit passed:
source/payload hashes, splits and label-reveal order, recomputed statistics,
both historical pilot replays and practical limits. The report records 117
passing tinibo tests. No replacement passed all predeclared qualification
gates. Learned Matérn-5/2 remains the strongest retained surrogate; posterior
incumbent EI is available for explicit comparison, not a new default.

LCB with kappa 0.5 improved the augmented 274-tuple finite-pool results but
worsened the original 264-tuple results. Treat it as an **unqualified exploratory
pilot**, not a promoted acquisition. The Chilo adapter now permits
`bo.model.kappa` (finite nonnegative number) and `bo.model.ei_incumbent`
(`observed` or `posterior_mean`). Omitting them retains observed-incumbent EI
and the library's kappa 2.0; the application default is still EI. For LCB use
`"acquisition": "ucb", "kappa": 0.5`; the historical API name means minimizing
`mean - kappa * latent_std`. A null `ei_reference` is expected for LCB and is
retained in proposal diagnostics. Posterior-mean incumbent EI uses the minimum
fitted mean over observed training coordinates, not over the unseen pool;
it is not integrated noisy EI.

New runs use `tinibo.optimizer.v2`, recorded in the run/package manifests and
numerical qualification receipt. V1 checkpoints are explicitly rejected for
resume; never relabel them or edit historical run manifests. Keep the original
package/runtime to resume old work, or use a **new run ID** with
`import_bo_runs` to reuse completed v1 measurements. Import checks raw evidence
and ordered observation history without restoring the old model or RNG.
New v2 checkpoints still require unchanged config/code/Python/NumPy to resume.
Package qualification now replays the **configured acquisition**, not just EI,
and checks LCB units and null EI reference before any engine work.

`scripts/futility_bo_lcb.example.json` describes the proposed five-measurement
pilot: unchanged probe/net/SR4 contract, 120k nodes, local-only 10k pool, radius
80, seed 20261003, ten best centers plus spsa150b. It explicitly imports both
completed pilots as well as the stopped loop, yielding 274 unique development
observations without remeasurement. Validation/Elo labels stay separate. The
tinibo diagnostic first proposal is `[73,88,220,497,764]`; its true target is
unknown and cross-runtime numeric replay is tolerance-based. No package or
engine run is started by this integration. Decide on full selection evaluation
and SPRT only after fresh measured results.

Integration verification passed 147 futility Python tests plus four discrete
optimizer tests. The 31 BO tests also passed separately under tinibo's pinned
Python 3.14.3 / NumPy 2.5.3 environment (the Chilo venv currently uses NumPy
2.4.4). Tests cover invalid option rejection, defaults, 274 ordered measurement
imports from v1 producers without probes/model restoration, v2 round-trip and
pending-work replay, null LCB EI-reference logging and frozen model/runtime
receipts. With the checked-out tinibo benchmark evidence available, the
real-data test also reproduces the handback pool hash and first LCB proposal
within the predeclared 1e-9 numeric tolerance. Core-only tinibo installations
skip that optional fixture check; synthetic import/resume coverage remains.

```bash
PYTHONPATH=../tinibo OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python -B -m unittest discover -s scripts -p 'test_*futility*.py'
```

#### Pilot 3 launch — 2026-10-04

The operator reports that `bo-d5-pilot3-lcb05` is running on the cloud server.
The results have now been returned and verified (see below). The frozen package is
`~/Tune/futility/futility-bo-d5-pilot3-lcb05-linux.tgz`, SHA-256
`c89b30389e454d51f06061c7286783ef74e8246c9bf4bc77efcaef48af9cd498`.
It uses Chilo `8d318cf` and tinibo `4d57553`, with the same external contract
as the previous pilots. Archive bytes, staged imports and configured LCB
checkpoint replay were verified before upload to `PUBLIC/transf`; downloading
the uploaded copy reproduced the archive hash. Five new completed measurements
would extend the 274-point development history to 279 points.

Keep this package and its environment unchanged while it runs. The old
development/selection loop remains stopped; it has not been converted to BO.
On completion, run `bash collect.sh` in the cloud package directory and return
`bo-d5-pilot3-lcb05-results.tgz` for the review procedure below. Subsequent
documentation commits do not change the running package's pinned revisions.

#### Pilot 3 results — local LCB, kappa 0.5

`bo-d5-pilot3-lcb05` completed five new normal-PVS measurements, all cache
misses, after importing 274 distinct development measurements and 32 separate
validation records. Summed probe time was 3h 55m; this is not wall-clock time
including initialization/model fitting. All evaluations use the complete
22,825-position combined SR4 development population, 120k nodes, and the
unchanged per-root reference/rescue contract. Probe SHA-256 starts `90e43a61`,
net SHA-256 starts `51ee6410`; the full hashes are retained in the manifest.

| Candidate | Margins | Predicted mean regret | Actual mean regret | Squared regret | CVaR-1% |
|---|---|---:|---:|---:|---:|
| spsa150b | 0,40,158,488,754 | — | 0.014074236 | 0.002188075 | 0.329444948 |
| bo-0000 | 73,88,220,497,764 | 0.014119497 | 0.014207805 | 0.002262828 | 0.335069873 |
| bo-0001 | 67,80,223,483,744 | 0.014125935 | 0.014236916 | 0.002250188 | 0.333172296 |
| bo-0002 | 58,80,170,707,917 | 0.014148916 | 0.014366341 | 0.002293863 | 0.337151618 |
| bo-0003 | 63,82,195,502,750 | 0.014130517 | 0.014233344 | 0.002251197 | 0.332306406 |
| bo-0004 | 53,89,197,478,733 | 0.014134557 | 0.014290833 | 0.002292573 | 0.338082481 |

None beat spsa150b on any of the three principal development metrics; no
nominee was produced. The best mean regret, bo-0000, was 0.95% worse than the
base. Pilot 2's best remained closer (0.33% worse); these small, sequentially
different experiments are not a matched acquisition comparison. There is no
full-selection or SPRT evidence for these new tuples.

All five predicted means were optimistic: measured minus predicted regret was
3.10, 4.21, 3.69, 4.74 and 8.23 saved latent standard deviations, respectively.
This is a selected-proposal diagnostic, not a coverage test or Elo uncertainty.
Reducing exploration did not solve discovery in this pilot. These observations
suggest investigating surrogate smoothing/coordinate sensitivity and its
uncertainty estimates before another unchanged expensive pilot, rather than
assuming that the acquisition switch alone is enough. They do not establish
that BO itself cannot work.

Verification matched the original package/config receipts, Chilo/tinibo code
hashes, external contract, both previous pilots' imported measurements, raw
probe hashes, and complete checkpoint/result history. Recomputed SR4 metrics,
risk and semantic counts matched exactly. Offline replay reproduced all five
10k pool hashes, selected tuples and final pool RNG; prediction comparisons
used tolerance across different numerical runtimes. LCB values matched
`mean - 0.5 * latent_std`, with null EI reference. The first tuple matched
tinibo's handback prediction. No engine searches were run locally.

Accepted archive: `~/Tune/futility/bo-d5-pilot3-lcb05-results.tgz`, SHA-256
`6bcc4b637839f2e96e9d24aa26854f48b1cbdefe1c173bf0a5b918984e278198`.
Canonical evidence and analysis: `validation/evaluations/bo-d5-pilot3-lcb05/`.
Retain all five valid measurements: the compatible development history now
contains 279 distinct tuples. A future continuation must explicitly import
pilots 1, 2 and 3; imports are not recursive. The continuous loop remains a
separate backend and is not automatically resumed or changed by this review.

#### ARD surrogate handback and pilot 4 preparation — 2026-10-05

The tinibo surrogate follow-up is committed at `c103340`; its report and
`HANDBACK.md` live under `benchmarks/results/futility-surrogates-2026-10-05/`.
The independent audit verified 293 reports, 280 selection traces and 5,600
reveals, source/payload hashes, splits, recomputed metrics/gates and all three
historical pilot replays. The report records 155 passing tinibo tests and one
optional forest skip. ARD improved finite measured-pool retrieval; no setting
passed every universal screening gate. Some strict-win gates were unattainable
because too few starts were nonoptimal or controls had already reached the
pool optimum. Thresholds were not weakened after seeing the results.

The conditional next experiment is **ARD Matérn-5/2 with LCB kappa 0.5**.
Important limitations remain: pilot-3 shadow RMSE was 3.2295 times the
training-mean baseline, and 1,470 of 1,600 ARD fits touched parameter bounds.
Do not claim calibrated uncertainty or novelty/strength gains from retrieval.
Locality remains benchmark-only and is not integrated; Matérn-3/2 is supported
for explicit comparison but not selected for this pilot. No default promotion.

Chilo now accepts strictly boolean `bo.model.gp_ard` (default false) and
`kernel: matern32`, retaining the previous shared-scale Matérn/EI defaults.
New runs use **tinibo.optimizer.v3**; v1/v2 states must resume with their
original packages or import compatible completed measurements into a new run.
Model identity, scalar/vector length scales, training count, kernel/ARD flag,
scale ratio, bounds and restart diagnostics remain in manifests/checkpoints
and proposal records. Package qualification checks the configured surrogate
and exact same-runtime proposal replay without invoking an engine.

`scripts/futility_bo_ard.example.json` defines `bo-d5-pilot4-ard-lcb05`:
five sequential full-SR4/120k measurements, seed 20261003, local-only 10k pool,
radius 80, ten best centers plus spsa150b, unchanged bounds `[0,1200]^5` and
learned-noise fit settings. It explicitly imports pilots 1, 2 and 3 for
**279** unique warm measurements; validation labels remain separate. Compared
with pilot 3, the surrogate is the experimental change; the new measured
history also changes, so this is not a perfectly matched fresh-engine trial.

Integration verification passed 150 futility Python tests, including v3
checkpoint/pending-work replay, v1/v2 measurement imports without restoration
or probes, validation-label exclusion, strict option validation, preservation
of ARD diagnostics, and real 279-point/10k-pool proposal replay. No C++ search
changes or expensive local engine probes are part of this integration.

The package builder creates `~/Tune/futility/futility-bo-d5-pilot4-ard-lcb05-linux.tgz`
from committed Chilo and tinibo sources, bound to the established cloud store.
Package preparation does not start or upload the run. Disable the **old loop's
cron entry** during the pilot: even stopped-loop invocations can briefly hold
its lock while verifying data. Keep historical packages untouched. From the
unpacked new package, run `bash setup.sh`, then:

```bash
nohup ./run.sh > runner.log 2>&1 < /dev/null & echo $! > run.pid
```

Return `bo-d5-pilot4-ard-lcb05-results.tgz` using `bash collect.sh`. Evaluate
any nominee on full selection separately before deciding on SPRT.

#### Pilot 4 results — ARD/LCB

`bo-d5-pilot4-ard-lcb05` completed all five new normal-PVS measurements after
importing 279 distinct development tuples and 32 separate validation records.
All five probes were cache misses; summed probe time was **3h 50m**, excluding
initialization/model-fitting overhead. The full 22,825-position combined SR4,
120k-node, per-root reference/rescue contract and probe/net hashes remained
unchanged. The package used Chilo `80b5d80`, tinibo `c103340`, Python 3.12.3 /
NumPy 2.2.6, one BLAS thread, ARD Matérn-5/2 and LCB kappa 0.5, schema v3.

| Candidate | Margins | Predicted mean regret | Actual mean regret | Squared regret | CVaR-1% |
|---|---|---:|---:|---:|---:|
| spsa150b | 0,40,158,488,754 | — | 0.014074236 | 0.002188075 | 0.329444948 |
| bo-0000 | 51,128,238,476,603 | 0.013831968 | 0.014011699 | 0.002268603 | 0.334579045 |
| bo-0001 | 20,23,315,512,810 | 0.013932298 | 0.013888654 | 0.002182332 | 0.328601459 |
| bo-0002 | 27,28,377,484,843 | 0.013894300 | 0.013897449 | 0.002258511 | 0.330314236 |
| bo-0003 | 43,58,109,458,601 | 0.013913825 | 0.014234255 | 0.002371830 | 0.347375170 |
| bo-0004 | 43,123,237,472,581 | 0.013863221 | 0.014148362 | 0.002350190 | 0.342601976 |

The first three improve the base's development mean regret. **bo-0001** is
the automatic nominee: 1.32% lower mean than spsa150b, and modestly lower
squared regret and CVaR-1% too. Its mean also beats the previous best measured
SR4 tuple `[30,66,188,454,656]` (0.013910572); bo-0002 does as well, although
its tails are worse than spsa150b. At pilot completion neither had new selection
or SPRT evidence. Bo-0001's subsequent pooled selection result is recorded below;
bo-0002 remains an optional development candidate, not a validated promotion.

This is the first successful new-tuple discovery among these four small BO
pilots. It supports further testing of ARD, not universal/default promotion,
calibrated uncertainty, or a claim of improved playing strength. All five fits
put the fourth coordinate's length scale at its upper bound; scale ratios
were about 63k–65k. Retain these diagnostics: they do not establish that this
margin has no effect. Pilot comparisons differ in warm history and are not
perfectly matched engine experiments.

Accepted archive: `~/Tune/futility/bo-d5-pilot4-ard-lcb05-results.tgz`, SHA-256
`6825e7c880e73547c8cd886b0dddac870df80be731dcc04a1c9ae35fe87efcf7`.
Canonical evidence: `validation/evaluations/bo-d5-pilot4-ard-lcb05/`.
The compatible development history now contains **284 distinct measured tuples**;
future runs must explicitly import all four pilot runs to reuse them.

Verification matched the frozen package/config, code/backend and external
contract hashes, imported measurements from all three prior pilots, raw-probe
hashes and complete 284-point checkpoint/result history. Recomputed full-SR4
metrics, risk and semantic counts matched exactly; all five 10k pool hashes,
selected tuples and final pool RNG replayed, with tolerance-based numerical
prediction comparisons across runtimes. Nominee selection matched the eligible
unvalidated records. No local engine searches were run during this review.

#### Pilot 4 bo-0001: full-selection validation package

Prepared `~/Tune/futility/futility-bo-d5-pilot4-bo0001-validation-linux.tgz`
for `pilot4-bo0001 = [20,23,315,512,810]` and the spsa150b control. Archive
SHA-256: `1e1dde74e0c9e9ee3e0ec70251c3a9308c6e58c64603c5c0bcbed9bc4088c4a2`.
The package uses the committed `80b5d80` campaign/batch runner import closure
and hashes its custom validation-only contract-check/launch/collection scripts.
It freezes the pilot's exact external probe/net/population identities and
nominee provenance. No tinibo/NumPy, venv, pip or sudo setup is needed.

Run ID: `bo-d5-pilot4-bo0001-validation`. One serial worker evaluates all eight
selection shards, pooled over **141,099 trusted positions**, at 120k nodes.
The control uses matching shared-cache entries; missing entries are evaluated,
not assumed present. No SR4 candidate evaluation, reference search, automatic
loop promotion or SPRT runs. Allow approximately 5–7 hours plus any uncached
control work; keep the development loop stopped to leave the other CPU free.

Package verification passed the standard-library import closure, actual local
population/artifact dry validation against the frozen pilot contract, no-write/
no-probe dry-run checks, changed budget/net/tuple rejection, overlapping-launch
locking and refusal to collect incomplete results. Shell syntax, archive bytes
and file hashes were checked. On the cloud, `bash setup.sh` repeats external
validation; then start `nohup ./run.sh > runner.log 2>&1 < /dev/null & echo $! > run.pid`.
The package-local lock protects both manual and cron starts without polluting
the campaign's first-init directory. Completed candidate/shard outputs survive
restart; an interrupted individual shard probe is rerun from its beginning.

Output: `~/futility-validation/evals/bo-d5-pilot4-bo0001-validation/validation/`.
Inspect `progress.json`, then the pooled `report.md`/`results.json` and completion
receipt. Return `bo-d5-pilot4-bo0001-validation-results.tgz` via `bash collect.sh`;
retain raw probes, manifests and receipts for local analysis. Preparation and
upload do not authorize starting the job.

#### Pilot 4 bo-0001: full-selection results — 2026-10-05

The serial cloud validation completed all 16 candidate/shard probes for
`pilot4-bo0001 = [20,23,315,512,810]` and spsa150b. The compatible eight-shard
selection population contains **141,099 trusted positions**, including mate
rescues, with normal-PVS candidate searches at 120k nodes, score scale 600,
and the existing `per_root_v1` references. Probe SHA-256 is
`90e43a617cbe6b7c41b8a4faa35d6997078912eefc7f3579804eb538f2503f41`;
net SHA-256 is
`51ee64101ee3d85f69eb0948f4caa8be6d90115abdb909d82767ffb4a53ccd90`.

| Candidate | Margins | Mean regret | P90 | Squared regret | CVaR-1% | Move agreement | Mean depth |
|---|---|---:|---:|---:|---:|---:|---:|
| spsa150b | 0,40,158,488,754 | 0.014176040 | 0.041639442 | 0.002107537 | 0.320262583 | 57.4512% | 9.7405 |
| pilot4-bo0001 | 20,23,315,512,810 | 0.014262621 | 0.041893579 | 0.002107664 | 0.319042554 | 57.1655% | 9.6092 |

Bo-0001's 1.32% SR4 mean-regret improvement did **not** generalize to the pooled
selection set: its mean is 0.61% worse, P90 is 0.61% worse, and squared regret
is essentially unchanged (0.006% worse). CVaR-1% improves by 0.38%, so this is
a mean-versus-tail trade-off, not dominance by either tuple on the three
continuous objectives. Reference-winning mates missed increase from 1,223 to
1,297; nonlosing-to-losing counts increase from 98 to 100. Mean regret improves
on three of eight individual shards (SR3-R2M, SR3V-02 and SR3V-05), but the
decision uses the pooled population, not a vote over shards. No paired
significance test or Elo conversion was established by this comparison.

Conclusion: ARD BO has demonstrated development discovery, but this nominee
does not establish a validation improvement or deserve automatic promotion
over spsa150b. It remains a measured trade-off; no SPRT was started and the
operator-confirmed base is unchanged. Keep selection results out of BO
training labels; retain the valid SR4 observation for future compatible fits.

Canonical evidence:
`~/Tune/futility/validation/evaluations/bo-d5-pilot4-bo0001-validation/`.
Accepted archive: `~/Tune/futility/bo-d5-pilot4-bo0001-validation-results.tgz`,
SHA-256 `67cee003571a6d6a60857963f1916e92b8cb624fc7554da51efe4cfae034a328`.
Verified gzip/tar integrity, cloud-original hash, completion receipts, all
eight local population identities/trusted-key hashes and all 16 raw-output
hashes. Independently recomputed every per-shard and raw-pooled score/risk
metric against local references; results match. The local verification receipt
and returned package metadata are retained with the evidence. No engine probes
were run locally.

Transfer incident: two earlier staged copies failed gzip validation; the cloud
original and the Windows local copy were valid. Recopying to a new WebDAV
filename and checking SHA-256 at cloud, Windows staging and local download
resolved it. Never accept equal byte counts as an integrity substitute; damaged
copies were not imported into the canonical store.

### BO in the continuous loop — 2026-10-05

`run_futility_loop.py` now accepts `search.backend: "bo"`; omitted means the
original `"pareto"` backend. Only development proposal generation changes.
Development selection, full pooled validation, tuple identities, validation
novelty checks, the SPRT queue, and manual SPRT-best updates are unchanged.
The pilot-4 nominee's separate validation is now complete (see the results
above); neither its discovery nor validation is playing-strength evidence or
an automatic base promotion.

For completed external full-selection evidence, the stopped-boundary command
`import-validation --validation-dir BATCH_DIR` validates completion receipts,
probe/net/node/scoring identities, the complete ordered shard contract and raw
output hashes, then recomputes pooled metrics without engine searches. It adds
the tuples to the existing validation archive, preserves manual SPRT statuses
and removes already validated tuples from pending work. Repeating the import
is idempotent; conflicting metrics or incomplete/mismatched batches fail before
loop-state changes. It never changes the proven base.

The first cloud setup exposed a campaign/batch context-shape mismatch:
`import-validation` passed campaign shards directly to `execution_manifest`,
which requires batch-specific `anchor_manifest` and `rescue_completion`
identities. Numerical qualification and reconfiguration had succeeded, but
the import failed before archive changes or searches. The import now uses the
ordinary batch loader to bind those receipts and recompute metrics with the
matching contexts. A regression test uses campaign-shaped shards, real batch
loading/scoring, idempotent import and changed-receipt rejection; no probes
are launched. Repair the stopped package in place, then repeat only the
`import-validation` command before marking SPRT status and resuming.

External validation proposals can be submitted with
`./loop.sh enqueue --margins 0,35,158,553,754 --alias valbo-v1 --note
"validation-bo-offline-v1"`. This writes a revisioned request under
`control.json.validation_requests`, using the control lock, not the active
loop-state transaction. Requests are consumed at a phase boundary, retaining
alias/provenance and scheduling full validation without dev selection. Pending
or validated tuples are not reprobed. Dimension, monotonicity, max-margin and
BO bounds are checked; the proven base is unchanged. Requests during validation
never modify that frozen batch; they enter a following batch. Existing state
and control files need no manual migration.

Installing this controller upgrade requires a graceful stop with
`stopped=true, active=null`; never replace code during an active BO phase.
`scripts/install_futility_loop_upgrade.py` accepts receipt-bound known script
hashes, checks package integrity and the loop contract under its lock, preserves
old files, and updates package receipts/checksums. It changes neither venv,
config, data nor state. After installation, enqueue and explicitly resume;
no numerical requalification is needed for this controller-only change.
Future enqueue commands can be issued while the loop runs.

`scripts/package_futility_bo_loop.py` prepares a small Linux upgrade package
with the pinned tinibo runtime and complete Python import closure. Its setup
reads the live old config and stopped checkpoint, retains initialization,
selectors and SPRT history, and changes only the development search settings.
It imports pilot4-bo0001's completed batch and leaves the loop stopped for an
explicit operator resume. All four pilots and completed loop development cycles
seed BO; the expected current minimum is 284 unique SR4 measurements. The old
cron command must be disabled before the new package's command is enabled.

The agreed next experiment is a 2–3 day BO loop run, a separate local SPRT of
`pilot4-bo0001` against spsa150b, and a separate offline validation-target BO
study. The production loop continues to train only on SR4 labels. Any model
using pooled validation labels is an explicitly separate analysis, with
held-out predictive checks and no assumed proxy-to-Elo exchange rates. The
SPRT build must use the same engine basis as spsa150b, not unrelated newer
search/move-ordering changes from the working checkout.

The upgrade package is `~/Tune/futility/futility-loop-bo-d5-linux.tgz`
(Chilo source `680bfd8`, tinibo `c7afbbbf`). Disable the old cron entry, wait
for a stopped boundary, then unpack as ubuntu and run `bash setup.sh` (no
sudo). Start explicitly with `nohup ./loop.sh resume > loop.log 2>&1 <
/dev/null &`; enable only the new package's cron `run.sh`. Use `./loop.sh stop`
after the intended 2–3 days; the current phase will finish. The package README
contains the full commands and checks. Numerical replay and staged imports
passed locally; setup repeats qualification in the cloud's pinned environment.

Pilot4-bo0001's local SPRT identity is `bo4-p0001`, loop tuple ID
`t-ca00778ec42198a28c7168ac`, margins `[20,23,315,512,810]`. The Linux engine
uses clean archived source `98dbfdc364b65cd4735f307d3eab35302f53e70c`, matching
the spsa150b build receipt. Its build receipt is in the backed-up
`validation/evaluations/sprt/bo4-p0001.build-receipt.json`. The short-control
test started against spsa150b at 6+0.1, two workers, normalized SPRT `[0,2]`
Elo, alpha/beta 0.05, at most 52,000 games. Evidence and the wrapper log are
`~/fastchess/sprt-runs/bo4-p0001/` and `~/fastchess/logs/bo4-p0001.log`.
It is running, not an accepted candidate. After importing its validation on
the cloud, mark this tuple running explicitly; no loop base change is implied.

### Separate validation-target BO study — 2026-10-05

`scripts/analyze_futility_validation_bo.py` is read-only with respect to the
loop and never launches probes. It merges matching full-population validation
labels, optionally using a hash-verified newer BO observations manifest. SR4
data supplies **coordinates only** for an unvalidated proposal pool, never
validation-target labels. It retains provenance, training rows, disjoint
five-fold predictions, model diagnostics and alternative LCB proposals.

The first study has 33 unique five-margin labels over exactly 141,099 trusted
positions, and 252 unvalidated, already-SR4-measured tuples to choose from.
Held-out RMSE is `0.000042777` for isotropic Matérn-5/2 and `0.000035816`
for ARD, against `0.000078153` for a training-mean constant predictor
(ratios 0.547 and 0.458). Both use scaled fitting, learned noise, eight
coverage restarts and the same folds. ARD is the exploratory winner.

LCB kappa 0, 0.2 and 0.5 all choose `[0,35,158,553,754]`, with predicted
validation mean regret `0.01416257` and posterior standard deviation
`0.00003365`. These are three alternative policies, **not** three sequential
BO steps. The nominal improvement over spsa150b is smaller than that
uncertainty; one fitted length scale reaches its lower bound. Adaptive sampling
and the small labelled set also limit the predictive claim. No new validation
or SPRT was launched for this proposal, and it does not change the production
loop. Results and the source loop snapshot are backed up under
`validation/evaluations/validation-bo-offline-v1/`.

BO uses mean normalized regret on SR4 only. Its initial settings reproduce the
tested pilot policy: ARD Matérn-5/2, scaled GP with learned noise, LCB
(`acquisition: "ucb"`, `kappa: 0.5`), eight coverage restarts, a 10,000-point
fully local pool, radius 80, ten best development centers plus the manually
designated SPRT base, and bounds `[0,1200]` at each coordinate. There is no
automatic exploration schedule. `search.max_proposals` remains the per-cycle
budget; BO requires `search.workers: 1`. Native BLAS threads should also be one.

For an existing loop, preserve the evaluation contract, loop ID and the exact
`initialization` block; edit only the search settings at a graceful stop:
`scripts/futility_loop_bo.example.json` is an illustrative full config, not a
replacement for the existing initialization or selector policies.

```json
"search": {
  "backend": "bo", "max_proposals": 15, "workers": 1,
  "seed": 20261005, "max_margin": 1200,
  "bo": {
    "import_bo_runs": [
      "bo-d5-pilot1", "bo-d5-pilot2", "bo-d5-pilot3-lcb05",
      "bo-d5-pilot4-ard-lcb05"
    ],
    "pool_size": 10000, "local_fraction": 1.0,
    "local_radius": 80, "local_centers": 10,
    "bounds": [[0,1200],[0,1200],[0,1200],[0,1200],[0,1200]],
    "model": {"gp_ard": true, "kernel": "matern52",
              "acquisition": "ucb", "kappa": 0.5}
  }
}
```

Stop and wait until `stopped=true` and `active=null`, then install the matching
committed script closure and pinned tinibo runtime, configure Python/NumPy,
edit the config, and run `reconfigure`, followed by `resume`. Use the existing
command interface and process lock; subsequent cron invocations use `run`.
Disable the old cron entry while replacing the package/command, then register
only the new command with the numerical runtime available. Switching back to
Pareto uses the same boundary procedure: set `backend: "pareto"` and remove
`search.bo`. Neither switch resets the validation archive or SPRT statuses.
Keep one fixed tuple length/max futility depth per loop.

All completed compatible legacy development cycles and explicitly listed BO
pilots seed the first BO phase (284 unique tuples with the current evidence).
Every completed BO cycle, including its poor proposals, seeds later phases.
The adapter validates raw hashes, coverage, measured targets and recomputed
score/risk diagnostics; conflicts fail instead of being averaged. Validation
and Elo never become model labels. The SPRT base must already have a compatible
completed development measurement. Imported observations are frozen for each
phase, in order, with raw provenance; previously measured tuples are excluded
from candidate pools even if they were never selected for validation.
Stable producer IDs resolve relocated raw evidence; absolute cloud paths in
older provenance are informational when the matching local producer exists.

Each BO phase has `cycles/NNNNNN/search/{manifest,observations,state}.json`,
raw `probes/` and `logs/`. Its manifest pins settings, code, Python/NumPy/BLAS,
the evaluation contract and the observation receipt. `state.json` contains the
v3 tinibo checkpoint, pool RNG, pending proposal, acquisition diagnostics and
completed measurements. The pending tuple is saved before the probe; complete
raw output is reused after interruption, and each committed result is told
exactly once. Finishing a phase twice after a controller crash is idempotent.
The existing development selector receives that cycle's new measurements and
the measured SPRT base; it does not send the entire warm history to validation.

Changing numerical code/runtime during an active phase fails closed: finish
using its original package before reconfiguring. A stopped boundary can start
a fresh numerical model epoch from all retained measured labels, with changed
model/kappa settings. Do not relabel old checkpoints. The manual `set-base`
command still controls the next development cycle; the best SR4 tuple does not
silently replace the SPRT best. No cloud job is started by this integration.

#### Offline exploration/exploitation comparison

`scripts/compare_futility_bo_lcb.py` compares kappa 0, 0.2 and 0.5 with the same
ARD model, matched shuffled warm starts and measured coordinate pools. Defaults
are seeds 0–4, warm sizes 40/120 and 15 reveals; it reports best target and
optimization regret at prefixes 5/10/15, paired wins/ties/losses, and separates
cases where the optimum was already warm. Hidden labels are revealed only
after selection. This is a finite measured-pool check, not evidence for novel
tuples or validation/game strength. The complete sweep is an explicit separate
task; implementation tests use a small synthetic run and real-data proposal
replay without engine searches.

To use all 284 currently measured tuples, combine the frozen 279-row tinibo
fixture with the five pilot-4 completed measurements:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
PYTHONPATH=../tinibo .venv/bin/python scripts/compare_futility_bo_lcb.py \
  --observations ../tinibo/benchmarks/futility_surrogates_20261005/development.jsonl \
  --completed /home/nicu/Tune/futility/validation/evaluations/bo-d5-pilot4-ard-lcb05/state.json \
  --output /tmp/futility-lcb-284.json
```

#### Ten-seed matched LCB results — 2026-10-05

After committing the integration as `ff24c98`, ran the planned comparison on
all **284 measured SR4 tuples** (full 22,825 trusted positions, 120k candidate
nodes, matching per-root reference contract). Frozen runtime source was tinibo
`c7afbbb`; its numerical code is unchanged from `c103340`. Used one BLAS
thread, seeds 0–9, warm sizes 40/120, kappa 0/0.2/0.5 and 15 reveals: **60
trajectories, 900 fits, 1,050.5 seconds (17m30.5s)**. No engine probes ran.

Retained evidence:
`~/Tune/futility/validation/evaluations/bo-lcb-284-10seeds-20261005/`, including
`results.json`, `analysis.json`, `report.md`, frozen observations/development
contract, code, replay scripts, manifest, timing log and completion/hash
receipts. Verified all revealed labels, warm-start assignments, prefix scores,
paired statistics and input/code identities. No selection or Elo labels were
used; this is finite measured-pool screening, not novel-tuple qualification.

Exclude starts already containing the global measured optimum from the table:
40-observation starts have 9/10 informative seeds; 120-observation starts have
5/10. All 60 trajectories remain in the raw results. Values below are the
mean best normalized regret after 15 reveals; lower is better.

| Kappa | Warm 40 mean best | Optimum hits | Warm 120 mean best | Optimum hits |
|---:|---:|---:|---:|---:|
| 0 | 0.013933173 | 1/9 | 0.013897421 | 3/5 |
| 0.2 | 0.013929456 | 1/9 | 0.013888654 | 5/5 |
| 0.5 | 0.013931891 | 0/9 | 0.013888654 | 5/5 |

For warm 40, kappa 0.2 versus 0.5 has two wins, five ties and two losses;
its small mean advantage is not broad seed-wise superiority. For warm 120,
0.2 and 0.5 tie at step 15, while 0.5 is faster by step 10 (mean best
0.013890413 versus 0.013903546). Greedy kappa 0 loses to 0.5 on two rich-warm
seeds and ties on three. Thus 0.2 is a plausible alternative, but this small,
adaptively collected measured pool does not establish a clear replacement.
**Retain the configured 0.5 policy; no defaults changed.** Novel proposals and
full selection/SPRT evidence remain separate decisions.

#### Scaling, exploration and future refitting — 2026-10-05

Tinibo currently refits the full dense GP for every proposal; it does not use
an incremental rank-one fitting update. Let `n` be all retained compatible
measurements, `d` the tuple length and `M` the proposal-pool size (currently
10,000). Cholesky factorization and likelihood-gradient work have cubic time
components in `n`, repeated during hyperparameter fitting (currently eight
restarts, up to 100 iterations each). ARD training memory is approximately
`O(d*n^2)` because pairwise coordinate/gradient arrays coexist with several
dense matrices. Pool prediction costs approximately `O(M*n^2)` and is chunked
at 1,024 points to limit temporary memory. Starting a new cycle does not reset
`n`: all compatible imported observations still count.

Planning estimates, **not measured capacity limits**:

| Retained measurements | Planning guidance |
|---:|---|
| 300–500 | Expected to be comfortable |
| Around 1,000 | Probably practical; benchmark before reaching this size |
| Around 2,000 | Full refitting may become a significant overhead |
| 5,000+ | Consider local/subset or sparse models rather than assuming global dense refitting remains practical |

Doubling `n` roughly quadruples matrix memory and multiplies the cubic fitting
component by eight; these are scaling laws, not whole-run timing predictions.
The ten-seed timings above used 40/120 warm observations plus at most 15
reveals, so they do not establish fitting time at 1,000 or 2,000 observations.
Before choosing a retention/model policy, benchmark single-proposal wall time
and peak memory at 500/1,000/2,000 observations with the actual ARD settings,
10k pool, one BLAS thread and target hardware. Include fitting and prediction
separately and compare their combined cost with an engine probe. Moving from
five to seven coordinates increases ARD array/model costs; the exponential
coverage difficulty of higher-dimensional search is a separate issue.

For a short budget seeking improvement near an already good tuple, broad
exploration becomes harder to justify as dimensions increase. This is not a
general rule that higher dimension requires a smaller exploration multiplier:
it also increases the risk of missing useful basins. Restricting/adapting the
search neighbourhood is another lever. Our fully local pool already provides
geographic restriction; a future trust-region policy could adapt its radius
and restart after stagnation. See [TuRBO](https://arxiv.org/abs/1910.01739) for
local BO rather than globally overemphasized exploration.

LCB minimizes `mean - kappa * latent_std`. Even with fixed `kappa`, posterior
uncertainty changes as evidence accumulates. With fixed kernel/noise settings,
additional observations reduce uncertainty; repeated hyperparameter fitting
means this need not be monotonic everywhere in our runs. An explicit schedule
is possible but is not a universally preferable SGD-like decay. Theoretical
[GP-UCB schedules](https://www.dna.caltech.edu/Papers/Srinivas-2010-regret-ICML.pdf)
can increase the confidence multiplier over time while uncertainty shrinks.
The current implementation has no automatic schedule. Keep `kappa=0.5` for
now, based on the matched comparison above; test lower kappa, a schedule or
adaptive neighbourhoods as distinct policies before changing the default.

When engine/search/evaluation changes require retuning, distinguish a new
numerical fit from a new measurement contract. Model/acquisition changes can
reuse compatible measured labels at a stopped phase boundary via a fresh
model epoch. A changed probe, net, corpus, node budget or scoring/reference
contract must pass compatibility checks; do not mix old targets into the new
fit just to retain a large history. Re-evaluate suitable seed tuples under the
new contract and keep the old evidence historical. Retain the separate
development, pooled validation and SPRT decisions after any refit.

### Tinibo collaboration and release procedure

This is the maintained procedure for numerical-library changes and new BO
experiments. Work is split between two repositories, normally sibling
checkouts at `~/Sources/chilo` and `~/Sources/tinibo`; tinibo is not vendored
into the Chilo source repository or installed as an untracked large subsystem.
Only a committed copy of its runtime modules is vendored into each remote
pilot package.

| Owner | Responsibilities | Durable evidence |
|---|---|---|
| Chilo | Engine probes, regret scoring, artifact/corpus contracts, cache, adapters, execution and promotion | `futility-tuning.md`, scripts/configs, `~/Tune/futility/validation/evaluations/<run_id>/` |
| tinibo | Generic NumPy GP/acquisition/API/checkpoints and offline comparisons | Handover documents, versioned benchmark fixtures, `benchmarks/results/<experiment>/` |
| Operator | Authorize runs, designate the SPRT-best base, transfer results and decide validation/SPRT | Frozen package receipts and returned raw probe evidence; SPRT registry separately |

#### 1. Prepare a Chilo-to-tinibo handover

Start from accepted, verified Chilo evidence. State the problem and what would
count as success before requesting optimizer changes. Include the exact
objective, fixed maximum futility depth, integer/monotonic constraints and
bounds, control tuple, probe/net/corpus/node/reference identities, feasible
pool construction, seed, observation order, and numerical environments. Specify
the public API and checkpoint requirements, regression controls, comparison
protocol and acceptance criteria. Distinguish a suspected model/acquisition
problem from a demonstrated execution bug.

Place a detailed Markdown handover **in tinibo**, so an agent working there
has the complete task without relying on a Chilo conversation. The first
handover is `FUTILITY_BO_REQUIREMENTS.md`; the real-pilot follow-up is
`FUTILITY_BO_PILOT_FOLLOWUP.md`. Use a new dated document or an explicitly
versioned update for later investigations; retain the earlier decision trail.

Supply a small, standalone, development-only fixture: unique tuples and
measured mean regret, diagnostic metrics, source/probe hashes, chronological
groups, ordered warm observations, proposal predictions/fit diagnostics and
pool/RNG traces when available. Preserve unsuccessful evaluations. Keep original
snapshots unchanged and reject conflicting labels for duplicate tuples.
Reference/corpus changes or different maximum depths require separate compatible
datasets, not silent pooling. Never merge full-selection or Elo labels into
the development training fixture.

The current examples are `benchmarks/futility_cloud/` (original 264 points)
and `benchmarks/futility_pilots_20261004/` (274 points plus both pilot traces).
The latter's `export_fixture.py` validates canonical evidence and writes to a
**new** output directory; `verify_fixture.py` checks hashes and histories.
These are concrete snapshot exporters, not automatic discovery of every future
pilot: extend or version the exporter for later runs. The fixture must be usable
without engine binaries, FEN corpora, cloud access or importing Chilo modules.

#### 2. Investigate and qualify inside tinibo

Use a focused tinibo branch and its NumPy environment. Commit the comparison
protocol before sweeping settings. Compare current-preset and random controls
with matched warm starts/seeds/budgets; reveal an unseen measured-pool label
only after choosing its coordinate. Retain temporal/grouped checks, individual
seed traces, failures and fit diagnostics. Do not manufacture labels for unknown
tuples from surrogate predictions. Keep timing-only synthetic rows out of
quality evidence. Fixed-corpus measurements are deterministic; learned GP noise
is not probe-rerun noise or Elo uncertainty.

Implement only generic numerical/API work there. Preserve default behavior
unless evidence justifies changing it, test public `tell`/`ask` and replay,
and explicitly document checkpoint schema compatibility. Record source hashes,
revision, Python/NumPy/BLAS settings, fixtures, protocol and result hashes.
Run numerical comparisons with one BLAS thread unless an experiment explicitly
declares otherwise. No engine searches or Chilo deployment are part of this step.

#### 3. Receive the tinibo handback

Require a committed, clean tinibo revision and a results directory containing
a readable `README.md`, a Chilo-facing `HANDBACK.md`, and auditable machine-readable
evidence. The handback must give exact optimizer settings, option semantics and
units, defaults, pass/fail outcomes, limitations, tests, environment, schema
migration/rejection instructions and Chilo integration requirements. If another
pilot is proposed, include its machine-readable settings and proposal-only
diagnostics; identify unmeasured targets as unknown.

The completed example is `benchmarks/results/futility-followup-2026-10-04/`.
From the tinibo root, audit it without fitting models or running engines:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python -B -m benchmarks.verify_pilot_followup benchmarks/results/futility-followup-2026-10-04
```

This audit is specific to that report/protocol; use the corresponding verifier
for a future report. Read the full qualification outcome, not just the proposed
preset. A conditional experimental setting is not a qualified replacement.
Finite-pool/model quality is not validation or playing-strength evidence.

#### 4. Integrate and freeze a Chilo pilot

Review the handback here. Change the adapter's allowed options/validation and
tests as needed, but call tinibo's public API rather than duplicating GP or
acquisition mathematics in Chilo. Test measurement import, defaults, invalid
options, checkpoint compatibility, pending-work resume and proposal-only replay.
Keep v1 measurements reusable in a new v2 run without rewriting old checkpoints.
Do not update an active package in place.

Commit accepted Chilo and tinibo changes before packaging. Use
`scripts/package_futility_bo_pilot.py` with an explicit config, `--tinibo-root`,
a verified source loop state or BO manifest as `--source-state`, and a fresh
`--output-dir` under `~/Tune/futility`. Set `PYTHONPATH` to the chosen tinibo
checkout, so the imported backend is exactly the one copied into the package.
The builder refuses dirty repositories and pins both revisions, the complete
Chilo import closure, vendor code/config hashes and external evaluation contract.
It references the established cloud store rather than resending populations.

Explicitly list **all** completed BO runs to reuse in `import_bo_runs`;
imports are not recursive and carry measurements, not producer GP/RNG state.
With the source loop unchanged, pilot 3 imports pilots 1 and 2 for 274 points.
Once pilot 3 completes, a continuation must also list `bo-d5-pilot3-lcb05` to
reuse its new evaluations. Use a new run ID for changed config/model/code.

Verify staged imports, archive contents/hashes and configured numerical replay
before transfer. Use the FTP-transfer skill and `PUBLIC/transf`, without putting
credentials in scripts or receipts. The normal route is workstation FTP/WebDAV
staging, then operator SCP/SSH to the cloud; do not assume the cloud can reach
the private LAN FTP endpoint. Archive upload does not authorize starting a run.

The operator keeps the old loop stopped, runs `bash setup.sh` as the normal
cloud user, and starts the package's `run.sh` with nohup or cron. Setup checks
the pinned numerical runtime and effective contract without engine work. Reuse
the same untouched package to resume. Inspect its README for exact commands,
run ID, imports, log/output paths and result-collection instructions.

#### 5. Return measurements and begin the next decision cycle

After completion, use the package's `collect.sh` to return the whole small
pilot: manifests, frozen observations, authoritative state, raw candidate JSONL,
results/report/nominee, logs/cache receipts, package and numerical receipts.
Do not send the venv, shared cache, populations or unrelated campaigns. Transfer
the `<run_id>-results.tgz` archive through `PUBLIC/transf` for local review.

Verify archive integrity, frozen contracts, raw-output hashes/coverage and
completed observation history before accepting it. Retain the accepted archive
under `~/Tune/futility` and useful evidence under
`~/Tune/futility/validation/evaluations/<run_id>/`; the cloud's equivalent path
is `~/futility-validation/evals/<run_id>/`. Recompute development statistics
from raw evidence, compare with the same control/budget/population, and separate
structural replay from tolerance-based cross-runtime prediction agreement.
Record facts, negative outcomes and the next decision in this document.

Valid new measurements, including poor ones, remain reusable. If numerical
behavior needs investigation, export a new fixture and handover back to tinibo.
If an actually measured development nominee merits promotion, run full pooled
selection evaluation separately, then decide on SPRT. Do not automatically
replace the continuous loop's backend or SPRT-best tuple from a short pilot.

Push each repository's accepted source branch from its own project context.
Pushing Chilo backs up its code/docs, not tinibo's unpushed commits, external
fixtures/packages or raw `~/Tune` evidence; retain their separate repository
and filesystem backups. Nothing in this procedure changes a running package
or retroactively upgrades historical evidence.

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

### Full-development Pareto search v4 — 2026-09-01

The initially implemented sampled relative-risk v3 contract is superseded
without being run. `scripts/optimize_futility_gated.py` now writes the
separate `chilo.futility_pareto_search.v4` manifest/state contract and refuses
to resume v1/v2/v3 state or manifests. Its retained name is only operator
continuity; it is neither a fixed-gate optimizer nor a single-incumbent hill
climb.

Every proposal is evaluated on the complete fixed SR4 development population.
The initial tuple is evaluated once and retained. Thereafter each proposal
needs one full probe; it is compared with the current numeric Pareto archive,
not a freshly re-probed incumbent. This is about 2.5 times the steady-state
cost of the former two-20%-probe step, but removes development-sampling drift.

The archive minimizes three primary metrics: mean normalized regret,
reference-relative mean squared regret, and reference-relative CVaR-1%. A
proposal is discarded only when an archived tuple is no worse on all three
and strictly better on at least one; otherwise it is admitted and removes any
tuples it strictly dominates. Thus the archive is a set of development
trade-offs, not an implicitly scalar-ranked winner.

Workers are part of the search contract. For each batch, every worker samples
one parent uniformly from the same frozen archive snapshot, creates its
deterministic perturbation, and evaluates it in parallel. A generated tuple
that was already evaluated, or is already queued in that batch, is dismissed
and deterministically replaced before any probe is started; its dismissal
count is retained with the proposal record. Completed proposals are then
applied to the archive in proposal-index order; the next batch sees the
resulting archive.

After the fixed `max_proposals` budget, configured secondary semantic metrics
decimate the final primary frontier sequentially. Each filter requests a
fraction of the worst current survivors (for example, 25% by
`winning_mate_missed`); all candidates tied at the cutoff are retained. The
supported direct-reference counts are `winning_mate_missed`,
`nonlosing_to_losing`, `clear_advantage_to_nonpositive`, and
`clear_advantage_lost`. These filters mechanically reduce candidates for
SR3-R2M without claiming that the semantic counts define a total order.

`scripts/analyze_futility_gated_calibration.py` is the required read-only
preflight. Its config explicitly maps every retained v1/v2 run to a matching
anchor and every promoted tuple to its completed full-development and
selection outputs. It validates the state-recorded attempt JSONL identities,
recomputes their direct-reference paired deltas, and writes JSON plus a short
Markdown report. It reports empirical distributions only; it deliberately
does not generate a runnable Pareto configuration or recommend thresholds.
See `scripts/futility_gated_calibration.example.json` and
`scripts/futility_gated_hillclimb.example.json` for schemas, not approved
numeric settings.

Every Windows/Linux package for this Pareto optimizer must also contain the
untouched SR3-R2M input, its exact per-root anchor and certified mate-rescue
sidecars, and a selection-evaluation launcher. After the SR4 search finishes,
the launcher may automatically evaluate the mechanically retained shortlist;
it must also allow an operator to name any other final numeric-frontier ID
for a separate SR3-R2M run. This manual path is necessary when a small
frontier is reviewed and an otherwise semantically filtered candidate is
deliberately retained. Selection output must live outside the optimizer's
existing `run/` directory and be resumable candidate-by-candidate without
overwriting completed probe JSONL.

Implementation does not authorize a package, optimizer run, full evaluation,
or SPRT. Review the source/weights/anchor contract and the exact proposal
budget before any new development-only experiment.

### Future: empirical recursive futility bounds

The Pareto work optimizes a score-regret proxy and can trade tactical mistakes
against average score. A separate, deliberately conservative experiment is to
measure a margin at which a quiet-move futility decision is non-losing for the
current evaluator and search. It is not a replacement for score-regret or an
SPRT: even a locally non-losing quiet-move rule can reduce the root depth that
discovers an important tactic.

The intended procedure is sequential by residual depth. First establish the
largest safe depth-1 margin using exact, full-window searches of each relevant
quiet move. Then enable that established depth-1 rule while measuring depth 2,
and continue through the chosen maximum depth. Each stage therefore tests the
same recursive search policy that the following stage will actually use. The
margin analysis uses broad normal-game search traffic rather than the
quiet-position NNUE training shards used by SR4 and SR3-R2M.

`futility_site_collect` is the opt-in collection half of that work. It sweeps
root FENs from an external broad-game corpus at a fixed depth, with futility
disabled, and writes plain canonical parent FEN occurrences. It deliberately
does **not** write a move, alpha, beta, static evaluation, margin, or residual
depth: the same position can later be useful with a new evaluator or at a
different iterative-deepening depth. Occurrences are retained; a repeated
opening or endgame position represents repeated exposure in the source games.

A parent is reported once per internal node only after normal move ordering
has reached a later (`i > 0`) quiet candidate that does not give check. The
parent itself must be non-root, non-PV, not in check, have non-pawn material
for the moving side, have remaining depth in `1..--site-max-depth`, and satisfy
the explicit strict non-losing guard `beta > --min-beta`. Reporting happens
before static evaluation and before the alpha-plus-margin gate, so it neither
depends on the current NNUE score nor presupposes a futility tuple. The
collector is compiled with `CHILO_FUTILITY_SITE_COLLECT` into separate object
files; normal UCI and probe builds contain none of its callback path.

Build and run it only with an explicit runtime NNUE file:

```bash
make futility_site_collect_avx2
build/futility-site-collect-avx2/futility_site_collect \
  --input /data/broad-game-roots.fen \
  --weights /data/chilo-net.bin \
  --output /data/futility-sites.fen \
  --depth 7 --site-max-depth 5 --min-beta <chosen-cp-floor> \
  --max-roots <N> --root-seed <seed> \
  --max-sites 0 --report-every 100
```

`--input` is repeatable and accepts plain FEN rows (or a CSV whose first field
is the FEN). `--min-beta` is required rather than silently choosing a safety
policy, and `--depth` must exceed `--site-max-depth` so the deepest requested
site is actually reachable. `--max-roots 0` searches every valid input
occurrence. A positive `--max-roots` requires `--root-seed`; the collector
makes one cheap read-only pass over the input to retain a uniform reservoir of
root occurrences, then searches only that reservoir. It does not create an
intermediate root file. Every eligible site occurrence is first spooled to a
temporary file, then the collector invokes an external `sort -u` over exact
canonical FENs; the final output is therefore unique by default without a
large in-memory hash set. `--max-sites 0` keeps every unique FEN. A positive
cap uses the separate `--seed` reservoir *after* that deduplication, so it is
uniform over unique FENs. The raw spool and sort intermediates are deleted only
after successful finalization; existing temporary paths are protected just like
the output and adjacent `*.manifest.json`. The manifest locks input/output and
NNUE SHA-256 identities, source revision/dirty state, search settings,
eligibility contract, both sampling seeds and limits, deduplication method,
and raw/unique/final collection counts. `make futility_site_collect_tests`
checks the callback's ordinary, disabled-depth, strict-beta, and
non-pawn-material gates without changing normal-engine test coverage.

`futility_margin_analysis` is the ordB prefix-rescue oracle. For every selected
parent FEN it makes one ordinary root PVS search at `target_depth`, with the
supplied established margins enabled only below the target depth. The
target-depth rule remains disabled. It intentionally has no inherited TT,
killer/history, or alpha context: a bare FEN cannot supply those. Root ordering
is therefore deterministic ordB with no preferred move: non-negative SEE
captures, every promotion (including a negative-SEE capture-promotion), then
killer/ordinary quiet moves, then remaining negative-SEE captures.

The analyzer uses normal PVS throughout, not a full-window search per move. It
snapshots the exact root alpha `C` after the capture/promotion prefix, then
continues the same root PVS from that alpha. It retains an observation only
when the final best move is a quiet, non-checking move with exact score `Q >
C`. A tuple with proposed target margin `M` would prune this quiet rescue when
`static_eval + M <= C`; its local loss is `Q - C`. This is deliberately a
measured rescue trade-off, not a claim that the target-depth rule is lossless.

The analyzer excludes a parent that is in check or has no non-pawn material for
the moving side. It emits no record when there is no prefix, the final best move
is not an eligible quiet move, or the quiet does not improve `C`. A quiet rescue
with a mate score is written to `mate-risks.jsonl`, never folded into the finite
tail; it retains the same prefix context.

Build the matching analyzer, copy
`scripts/futility_margin_analysis.example.json`, set its three artifact paths
and stage settings, then create a run directory:

```bash
make futility_margin_analysis_avx2
python3 scripts/run_futility_margin_analysis.py \
  --config scripts/futility_margin_analysis.example.json \
  --run-dir ~/Tune/futility/margin-analysis/g4-alpha21-d1 \
  --new
```

`max_fens: 0` keeps the complete corpus; a positive value uses the documented
deterministic reservoir selected by `sample_seed`. The runner requires the
collector's adjacent `sites.fen.manifest.json` and verifies its output hash
before it selects FENs. It freezes the exact selected FENs and identities of
the input, collector manifest, analyzer, weights, and config in
`analysis_manifest.json`. Restart an interrupted matching run with:

```bash
python3 scripts/run_futility_margin_analysis.py \
  --config scripts/futility_margin_analysis.example.json \
  --run-dir ~/Tune/futility/margin-analysis/g4-alpha21-d1 \
  --resume
```

`completed.indices` is the authoritative resume journal. Each line also stores
the committed byte lengths of the two JSONL streams. Each index is added only
after all of its finite records and any separate mate records have been
flushed; a restart trims unjournaled trailing bytes before continuing. A resume
rejects changed artifacts or settings rather than mixing evidence.

Each finite `positions.jsonl` record has schema
`chilo.futility_margin_rescue.v1` and includes `fen`, `static_eval`,
`prefix_move`, `prefix_score`, `prefix_count`, `quiet_move`, `quiet_piece`,
`quiet_score`, `prefix_delta`, and `quiet_gain`. For an ad-hoc inspection:

```bash
jq -c . \
  ~/Tune/futility/margin-analysis/g4-alpha21-d1/positions.jsonl

jq -c 'select(.quiet_gain >= 100)' \
  ~/Tune/futility/margin-analysis/g4-alpha21-d1/positions.jsonl

jq -c . ~/Tune/futility/margin-analysis/g4-alpha21-d1/mate-risks.jsonl
```

For a complete multi-gigabyte finite stream, use the native read-only tail
scanner instead of repeatedly parsing it with `jq`. It applies a proposed
margin, classifies each would-prune rescue by an accepted local-loss limit, and
ranks the remaining local losses. Its existing predicate filters remain
available before this classification. A passed-pawn advance is defined on the
pre-move FEN as having no opposing pawn ahead on the same or adjacent file. The
destination rank is relative to the pawn's side: Black `d3d2`, for example,
reaches rank seven.

```bash
make futility_margin_tail
build/release/futility_margin_tail \
  --input ~/Tune/futility/margin-analysis/g4-alpha21-d1/positions.jsonl \
  --margin 100 \
  --rescue-limit 0 \
  --passed-pawn-min-destination-rank 7 \
  --top 20 > tail-rank7.json
```

`--passed-pawn-min-destination-rank 0` disables that filter. The scanner writes
one JSON report with each predicate exclusion count, retained records,
would-prune count, rescues within the limit, unrescued count, and maximum/top
unrescued events. It uses no NNUE weights and performs no engine search. It is
exploratory only: do not add a corresponding live futility exemption until the
retained tail evidence has stabilized.

The scanner can additionally restrict inspection to the near-equality regime
without rerunning the analyzer:

```bash
build/release/futility_margin_tail \
  --input ~/Tune/futility/margin-analysis/g4-alpha21-d1/positions.jsonl \
  --margin 100 \
  --rescue-limit 25 \
  --passed-pawn-min-destination-rank 7 \
  --static-eval-limit 400 \
  --top 20 > tail-rank7-near-equal.json
```

`--static-eval-limit L` retains exactly `-L < static_eval <= L`, reports the
low and high exclusions separately, and is disabled by default. It and the
passed-pawn predicate are diagnostic filters, not live-search rules.

### Rescue-margin decision — 2026-09-03

The earlier static-score maximum and its lossless interpretation are
superseded. The useful comparison is the quiet rescue `Q - C` after the actual
ordB non-quiet prefix has established alpha, not `Q - static_eval`. A node with
no such prefix emits no event; it must not be treated as a safe non-quiet
rescue. The method still omits TT/killer/history context by design, because the
FEN corpus does not carry it. That makes the resulting distribution a
conservative, deterministic FEN-only calibration rather than a replay of one
particular historical search path.

Current normal ordering in version `0.7.6` is the TT/preferred move, good SEE
captures, all promotions, killer quiets, ordinary quiets, then remaining
negative-SEE captures. The generic promotion branch precedes the remaining
capture branch, so a negative-SEE capture-promotion is in the promotion group.
The fixed-depth experiment selecting this ordB order is recorded in
`engine-decisions.md`. Negative-SEE captures remain later tactical
possibilities and cannot be assumed harmless merely because they occur after a
quiet candidate.

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

## Consolidated Futility SPRT Evidence

The machine-readable registry is kept with the backed-up validation archive at
`~/Tune/futility/validation/evaluations/sprt/registry.json`. The raw game
evidence remains in `~/fastchess/sprt-runs/`; the registry records each raw-run
path and the relevant build receipt without duplicating PGNs. It contains the
completed decisions and explicitly marks interrupted runs as incomplete.

The registry keeps raw W/L/D counts for every run. Fastchess's displayed
Elo/error/LOS report was persisted only for `loop1-c01-p0013` in the retained
wrapper log; its `reported` object contains those exact values. The other
`reported` objects are intentionally null and must be filled manually from the
historical Excel record when it is recovered. Do not replace those values with
new SPRT runs merely to recreate a report.

The tested selection chain is:

`source -> f01 -> f21 -> spsa150b`

`f01`, `f21`, and `spsa150b` all accepted H1 in their successive comparisons.
The direct 30+0.5 spsa150b-versus-f21 comparison was run twice; both runs
accepted H1. `d3-0009` and loop candidate `loop1-c01-p0013` both accepted H0
against spsa150b. The old f11 test and the current loop c06 test stopped before
an SPRT boundary and are not strength results. SPRT decisions, not proxy
metrics or point scores, establish playing strength.

| Candidate | Opponent | Control | Games | Status |
|---|---|---:|---:|---|
| `f01` | source `g4t1-64x8` | 6+0.1 | 38,358 | H1 accepted |
| `f21` | `f01` | 6+0.1 | 30,652 | H1 accepted |
| `f21` | source `0.7.4` futility | 30+0.5 | 4,460 | H1 accepted |
| `spsa150b` | `f21` | 30+0.5 | 4,800 + 3,528 | H1 accepted in both runs |
| `d3-0009` | `spsa150b` | 6+0.1 | 9,084 | H0 accepted |
| `loop1-c01-p0013` | `spsa150b` | 6+0.1 | 34,984 | H0 accepted |
| `f11` | `f01` | 6+0.1 | 1,680 | incomplete |
| `loop1-c06-p0012` | `spsa150b` | 6+0.1 | 380 | incomplete |

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
