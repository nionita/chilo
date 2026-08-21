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
