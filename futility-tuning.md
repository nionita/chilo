# Futility Margin Tuning

This is the persistent record for futility-margin experiments. The current
source defaults remain `120,320,550` through depth three. Proxy tuning only
selects SPRT candidates; it does not establish playing strength.

## Accepted SPRT Basis

`f01` is the current practical basis for future futility SPRTs:

| Binary | Margins | Status |
|---|---|---|
| `chilo-0.7.5-f01-avx2` | `120,240,360` | Previous SPRT accepted it at more than +3 Elo. Do not overwrite this binary. |

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

The active 6+0.1 SPRT compares `f21` with accepted control `f01`, not with the
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
the 40k or 120k regret differences directly into Elo; the running SPRT remains
the strength decision.

## Procedure: Fresh Corpus and Remote High-Depth Anchor — 2026-08-23

G3-SR3 starts a new, independent 25,000-position corpus and uses a much
deeper all-root reference before any new family is considered. This is a
single-corpus procedure; it deliberately makes no provision for combining or
managing multiple shards.

### 1. Collect one new FEN-disjoint corpus

Use `scripts/sample_futility_positions.py` on a headered collector CSV with
the fields `eval_fen,score,result`. It takes one prior corpus as `--exclude`,
does a deterministic reservoir sample, rejects previously selected FENs, and
refuses to overwrite either output. It writes the CSV plus a provenance JSON
containing source and output hashes, seed, counts, and the zero-overlap check.

The G3-SR3 corpus was made from the same G3 source as G3-SR2:

```bash
python3 scripts/sample_futility_positions.py \
  --source ~/Tune/extract/2026/chilo-g3/chilo-1.csv \
  --exclude ~/Tune/futility/g3-25k-seed990317.csv \
  --output ~/Tune/futility/g3-25k-seed990318.csv \
  --metadata ~/Tune/futility/g3-25k-seed990318.json \
  --seed 990318 \
  --count 25000
```

The result has 25,000 unique FENs and no overlap with G3-SR2. Keep the CSV
and its adjacent provenance JSON together. Select a new deterministic seed
for a later fresh corpus and pass the immediately relevant prior corpus as the
single exclusion input; do not add multi-shard handling here without a
separate design decision.

### 2. Prepare a self-contained remote anchor package

Create a new local run directory with a reviewed `tune.json`, then make a
portable `.tgz` containing:

- the exact AVX2 `futility_probe`, NNUE weights, input CSV, and input metadata;
- `SHA256SUMS` for every packed artifact;
- a `README.md` with return/install instructions;
- `run-anchor.sh`, which runs the full-root reference and then the baseline
  serially; and
- `start-anchor.sh`, which writes a PID file and starts the runner through
  `nohup` with a durable log.

The runner must validate/reuse a completed JSONL by its final matching summary
and rerun only an incomplete artifact. It must use one probe process at a time:
the remote server has two CPUs, and the full-root search benefits from no
contention. Never start a second launcher while its PID is live.

For G3-SR3 the local config is `~/Tune/futility/g3-sr3/tune.json`: accepted
control f01 (`120,240,360`) is both the 120,000-node baseline and the
10,240,000-node all-root reference. The packaged runner emits
`output/reference.jsonl` with `--all-root-scores`, followed by
`output/baseline.jsonl` without that flag. Using f01 for both makes the anchor
directly relevant to the current SPRT basis.

### 3. Run remotely and install the finished anchor

On the remote server:

```bash
tar -xzf g3-sr3-anchor.tgz
cd g3-sr3-anchor
sha256sum -c SHA256SUMS
./start-anchor.sh
tail -f logs/runner.log
```

After completion, copy `output/reference.jsonl` and `output/baseline.jsonl`
back into the local run directory under `probes/`, then materialize the local
manifest without rerunning completed probes:

```bash
mkdir -p ~/Tune/futility/g3-sr3/probes
cp output/reference.jsonl ~/Tune/futility/g3-sr3/probes/reference.jsonl
cp output/baseline.jsonl  ~/Tune/futility/g3-sr3/probes/baseline.jsonl

cd ~/Sources/chilo
python3 scripts/tune_futility.py \
  --config ~/Tune/futility/g3-sr3/tune.json \
  --run-dir ~/Tune/futility/g3-sr3 \
  --phase anchor
```

The local input must be byte-identical to the packed one. The probe records a
remote `source` path in both JSONLs; that is acceptable because it remains the
same stable `(source, line, FEN)` key for reference and baseline. The local
anchor manifest records the effective local probe, input, and weights hashes.
Only after this anchor is complete should a reviewed config add families and
run `--phase candidates`; those candidate choices can change without rerunning
the retained root-score reference.

## Per-root Reference Contract — 2026-08-25

New reference experiments use a different contract from the still-running
G3-SR3 cloud reference. The cloud run remains a valid total-position-budget
reference and is analysed on branch `futility-score-regret`; do not mix its
JSONL with a per-root anchor.

For the new contract, each input position is handled in one combined anchor
probe: f01 is first searched at the candidate budget and completes at depth
`B`. Every legal root move is then searched independently with a full window,
its own cumulative cap `R`, and target root depth `B + gap`. The reference
accepts the position only if every root completes that target. It rejects the
position on the first failed root and records the FEN, baseline/target depths,
legal and completed root counts, failed move, failed depth/nodes, and reason.
No partial score map is retained.

The first planned Windows anchor uses f01 `120,240,360`, baseline `120k`,
`R = 480k` nodes per legal root move, `gap = 2`, and reference progress every
100 positions. Progress reports processed/total, completed/rejected/terminal
counts, nodes, elapsed time, rate, and ETA on stderr; the tuner streams it to
both the terminal and `logs/reference.log`.

G3-SR4 uses `~/Tune/extract/2026/chilo-g3/chilo-2.csv` and seed `990319`.
Because the sampler intentionally remains single-exclusion-input, a one-off
CSV `~/Tune/futility/g3-exclude-sr2-sr3.csv` was made by merging the FENs from
G3-SR2 (`seed990317`) and G3-SR3 (`seed990318`). Its provenance JSON records
the two input hashes; it contains 49,996 unique FENs and has SHA-256
`9cf16193456f489a362addea41fb2ead7a432346e14cb9aa9dfa56229520e081`.
Sampling against it produced `g3-25k-seed990319.csv`: 25,000 unique FENs,
zero overlap, SHA-256
`ca60ed4bf656d2a86f5ccce7a6740b8ceacf8a4bc639919de488ebe16a0c1e19`.
The merged exclusion is only a collection-time artifact, not a new
multi-shard tuning feature.

This contract intentionally measures score regret on completed references only.
Depth remains a reference-quality gate, not a candidate ranking objective.

## G3-SR1 Candidate Results (continued)

Median normalized regret was `0` for every one of the 30 tuples, so it did not
distinguish candidates. The following three independent metric winners advance
to SPRT against accepted basis `f01`:

| Code | Proxy winner | Margins | Mean regret | P90 regret | Move agreement | Mean completed depth |
|---|---|---|---:|---:|---:|---:|
| `f11` | Mean regret | `100,283,520` | 0.008820 | 0.019906 | 70.552% | 7.506 |
| `f12` | P90 regret | `100,260,420` | 0.008851 | 0.019852 | 70.564% | 7.520 |
| `f13` | Move agreement | `100,283,520,800,1118` | 0.008888 | 0.019913 | 70.576% | 7.562 |

The mean-depth winner (`75,212,390,600,839`, depth 7.639) was not advanced:
it ranked 24th by mean regret and had lower move agreement.

## SPRT Queue

### G3-SR2

| Order | Candidate | Opponent | Status |
|---:|---|---|---|
| 1 | `f21` | `f01` | Built; first G3-SR2 SPRT candidate. |
| 2 | `f22` | `f01` | Built; pending `f21` result. |
| 3 | `f23` | `f01` | Built; pending `f22` result. |

### G3-SR1 (historical)

| Order | Candidate | Opponent | Status |
|---:|---|---|---|
| 1 | `f11` | `f01` | Interrupted after two games; resumable state retained, but superseded by G3-SR2. |
| 2 | `f12` | `f01` | Not started; superseded by G3-SR2. |
| 3 | `f13` | `f01` | Not started; superseded by G3-SR2. |

The built candidate mapping and hashes are recorded externally in
`~/Tune/futility/g3-sr1-sprt.json` and its adjacent build receipt. Use the
SPRT wrapper with explicit engine names and the shared `chilo-g4t1-64x8.bin`
weights for both sides.

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

1. Finish the current static `f21`/`f22`/`f23` SPRTs against `f01` at 6+0.1.
2. Test promising static tuples at at least one much shorter and one much
   longer control, for example 1+0.01, 6+0.1, and 30+0.3. Keep the net,
   openings, adjudication, and other tournament settings fixed across those
   comparisons.
3. Only if different tuples show repeatable wins in different budget ranges,
   implement a two-threshold short/normal/long selector at root-search setup.
4. Test the adaptive engine against the strongest fixed tuple at each target
   control, then against that fixed basis over a representative mixed control
   set. SPRT remains the strength gate.
