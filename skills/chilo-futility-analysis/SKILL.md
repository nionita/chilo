---
name: chilo-futility-analysis
description: Analyse Chilo futility-proxy results while preserving corpus, reference-contract, and development-versus-selection boundaries. Use for newly received probe archives, candidate comparisons, and durable futility conclusions; not for launching tuning runs.
---

# Chilo futility analysis

Use raw manifests and JSONL as the authority; use `futility-tuning.md` as the
maintained operator narrative. Copy a newly received archive into a uniquely
named `/tmp` inspection directory first, validate its contents and manifest,
then retain the accepted archive under `~/Tune/futility`.

## Comparison boundaries

- The current per-root reference contract is the only contract for current
  regret ranking. Do not pool it with legacy `shared_budget_v1` outputs.
- `g3-sr4` is the development population. Current selection is the disjoint
  union of `g3-sr3-r2m`, SR3V production, and SR3V smoke (141,099 trusted
  positions under the compatible per-root contract). A candidate found on SR4
  needs matching normal-PVS evidence across the applicable selection shards;
  call it *full current selection* only after all three components are covered.
- Historical `g3-sr1`, `g3-sr2`, and the older G3-SR3 shared-budget artifacts
  may explain prior decisions such as f21, but cannot establish a current
  per-root ranking.
- Verify that reference records have the required complete root-score map and
  that candidate probes remain normal PVS probes before calculating regret.

## Report evidence

- Compare candidates on the same complete population and exact node budget.
  State the corpus, accepted-position count, reference contract, probe/weights
  hashes, and whether the result is a subset/sample or full evaluation.
- Mean normalized score regret remains the optimization objective. Report
  reference-relative squared regret, P95/P99, and CVaR-1% as tail-risk
  diagnostics; do not confuse older f01-relative gates with these values.
- Retain completed depth, move agreement, elapsed time, and futility counts as
  diagnostics only. SPRT, rather than a proxy result, establishes playing
  strength.
- Use f01 and the SPRT-validated f21 as known controls only when their probes
  match the evaluated population and budget.
- Mean regret, move agreement, and squared regret can be pooled by trusted
  position count. P90, P95/P99, and CVaR are order statistics: calculate them
  from one merged raw regret population, never by averaging shard summaries.

## Preserve the decision trail

- Do not promote an optimizer sample or best sub-sample without a full
  development evaluation and selection evaluation.
- Add factual outcomes, commands, artifact names, and rejected hypotheses to
  `futility-tuning.md`. Keep raw reference maps, manifests, result tables, and
  accepted remote-result archives; do not delete them as a side effect of
  analysis.
- The canonical local data root is `~/Tune/futility/validation/`; read its
  `README.md` before locating raw populations or candidate outputs. Existing
  top-level corpus names may be compatibility symlinks. Raw populations belong
  below `populations/per-root-v1/`; candidate JSONL and derived reports belong
  below `evaluations/`.
