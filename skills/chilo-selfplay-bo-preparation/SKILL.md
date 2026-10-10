---
name: chilo-selfplay-bo-preparation
description: Collect and merge compatible Chilo selfplay match measurements into portable evidence stores and prepare fresh local or cloud game-outcome BO experiments. Use for additive imports, combining machine results, or changing model settings and pair caps; not for regret-proxy analysis or launching matches.
---

# Chilo selfplay BO preparation

Use the repository's `scripts/prepare_selfplay_bo.py`; do not duplicate its
import/verification logic or hand-edit old optimizer state. The skill lives in
the Chilo repo and may be exposed through a `~/.codex/skills` symlink. Locate the
checkout or packaged scripts before executing commands; do not resolve repo
files relative to the symlink's parent.

Before operating, read README's **Reusable measurement collection and
preparation** section and the relevant CLI help. For experiment choices or
historical conditions, read **Standalone game-outcome BO** in
`futility-tuning.md`. Current manifests/configs, not historical example names,
determine the artifacts and settings to use.

## Choose the operation

- **collect** adds verified completed evidence to a store. `--source` accepts
  BO run roots, individual completed match directories, and other evidence
  stores; accept multiple paths or repeat the option. Without `--source`, it
  collects only the template's bootstrap list, not every nearby run. When asked
  to collect all evidence, inventory relevant roots and supply them explicitly.
- **prepare** makes a fresh experiment config and `.preparation.json` receipt
  from the whole store and a machine-local config template. It does not restore
  an old checkpoint, calculate a remaining budget, or start matches.
- For the specific **one stopped run, remaining budget** workflow, retain
  `scripts/prepare_selfplay_bo_followup.py`. Do not substitute that helper for
  a multi-source additive collection.

Use `--config` for a template whose fixed match contract matches the evidence.
`--executable`, `--weights`, `--openings` and `--tinibo-path` override template
paths for this machine before validation. Collection needs standard Python;
preparation needs the intended NumPy/tinibo runtime. Use the experiment's pinned
runtime and one BLAS/OpenMP thread for preparation and subsequent BO execution.

## Evidence boundaries and preservation

- Compatibility requires the exact executable/net/book content hashes, fixed
  opponent margins, nodes/move, opening policy, SPRT and adjudication. Do not
  rebuild a binary, change the base, or mix regret labels to make imports fit.
- Measurement IDs deduplicate the same evidence. Keep independent repeats of
  the same tuple; do not collapse by margins, pick the luckiest observation,
  average labels manually, or invent noise estimates. Different measurements
  sharing an opening seed are rejected.
- Pair caps may differ across imported matches. Each measurement retains its
  actual completed pair count and uncertainty; `--max-pairs` is a cap, not a
  promise that SPRT will always play that many pairs.
- All tuples must fit the template's model domain/depth. Preserve a broad model
  domain when narrowing only the proposal region. Incompatible evidence fails,
  rather than silently being filtered or relabeled.
- An active BO source contributes only committed observations in its atomic
  state, never the pending match. Recollect after it finishes to add the rest;
  collection does not stop or otherwise mutate that source.
- The store contains `index.json`, `store.lock`, and
  `measurements/<id>/{manifest.json,games.jsonl,results.json,status.json}`. Copy
  or back up the **whole store**, not just its index. Its relative paths are
  portable; recorded old source paths are provenance, not dependencies.
- Collection is additive and repeatable. Its OS lock prevents concurrent
  writers; a persistent lock file is not a stale held lock. A fully copied
  orphan from an interrupted index commit is recovered on recollection. If
  corruption or conflict is reported, stop and inspect; do not delete entries,
  rewrite hashes, or overwrite raw evidence to force success.

## Local and cloud workflows

These examples use a machine-local `config/bo.json` and an explicitly chosen
`evidence` store. Run from the checkout or package containing `scripts/` and
replace the source paths with the inventoried actual runs.

Collect one or several runs into the same store:

```sh
python3 scripts/prepare_selfplay_bo.py collect --config config/bo.json --store evidence --source runs/first runs/second
```

For **cloud → local → combined evidence**, collect on the cloud while its old
paths are valid, then archive/transfer the whole store. Extract into a separate
incoming folder on this workstation: do not unpack over the existing local
store. Merge that incoming store and then the local runs into one destination:

```sh
python3 scripts/prepare_selfplay_bo.py collect --config config/bo.json --store evidence --source incoming/cloud-evidence
python3 scripts/prepare_selfplay_bo.py collect --config config/bo.json --store evidence --source runs/local-first runs/local-second
```

The reverse direction is the same process. If only copied BO run folders are
available, use repeated `--path-map /old/root=/new/root` options for observation
paths. All referenced completed bootstrap journals must also exist; path
mapping is not a substitute for missing data. Prefer collecting before transfer.
When transfer or packaging is requested, use `chilo-ftp-transfer` or
`chilo-futility-package` as appropriate; do not infer permission to upload,
install cron entries, delete sources or start runs from a collection request.

For **two fresh BO runs with pooled evidence**, make the combined store available
on both machines and prepare each using its own artifact/runtime paths and a
different seed. Defaults: store at `config parent-parent/evidence`, fresh random
64-bit seed, budget/cap/model from the template, and run directory at
`output parent-parent/runs/output stem`. Override the store explicitly when
different package folders should share one permanent collection.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python scripts/prepare_selfplay_bo.py prepare --config config/bo.json --store evidence --output-config config/next.json --run-dir runs/next --seed 20261020 --measurements 30 --max-pairs 150
```

Change model settings only when requested, using the template or
`--gp-ard`/`--no-gp-ard` and `--gp-length-scale-bounds LOW HIGH`. A later fresh
experiment may use `--max-pairs 1500` while retaining compatible 150-pair
measurements. Previously collected random-match measurements import through the
same mechanism; generating or splitting random tuples is separate, ad hoc work,
not a capability of `collect`/`prepare` or a reason to add a scheduler.

## Hand off

Report collection's added/existing/total counts and store location. For
preparation, report the imported count, seed, new budget/cap/model, config,
receipt, and printed run directory. Existing outputs/nonempty runs are refused;
choose a new experiment name instead of overwriting them. Starting the driver
is a separate authorized action; a `run_selfplay_bo.py run ... --dry-run` can
verify the prepared imports without playing games.

Keep the store: prepared configs reference its copied journals. Adding evidence
to it does not change an already prepared experiment's explicit bootstrap list;
prepare another fresh experiment to include new observations. This workflow
collects measured evidence, not confirmed strength, and does not promote the base.
