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
