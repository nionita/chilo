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

| Order | Candidate | Opponent | Status |
|---:|---|---|---|
| 1 | `f11` | `f01` | Running as `futility-f11-f01`. |
| 2 | `f12` | `f01` | Pending `f11` result. |
| 3 | `f13` | `f01` | Pending `f12` result. |

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

1. Finish the current static `f11`/`f12`/`f13` SPRTs against `f01` at 6+0.1.
2. Test promising static tuples at at least one much shorter and one much
   longer control, for example 1+0.01, 6+0.1, and 30+0.3. Keep the net,
   openings, adjudication, and other tournament settings fixed across those
   comparisons.
3. Only if different tuples show repeatable wins in different budget ranges,
   implement a two-threshold short/normal/long selector at root-search setup.
4. Test the adaptive engine against the strongest fixed tuple at each target
   control, then against that fixed basis over a representative mixed control
   set. SPRT remains the strength gate.
