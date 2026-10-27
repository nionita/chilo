---
name: chilo-futility-package
description: Prepare a self-contained, provenance-checked Chilo futility run package for a Windows or Linux machine. Use for remote or secondary-machine anchors, probes, full evaluations, mate rescues, or optimizer runs; do not use to start a run.
---

# Chilo futility run packaging

Package a run so that another machine can execute it without relying on paths,
uncommitted source, or unstated artifacts from this workstation. For this user's
cloud/secondary-machine workflow, package preparation includes uploading the
finished archive through `chilo-ftp-transfer`, unless the user requests local-only
preparation. Preparing or uploading a package does not authorize starting an
expensive run or installing a cron entry.

## Select and stage artifacts

- Choose the smallest payload for the actual next operation. For BO bootstrap,
  include a compact verified export, not historical game journals. For returning
  results for comparison, include summaries/state, config/receipts, manifests
  and useful lightweight logs; no `collect` step or full journals by default.
  Full-evidence archival, raw-statistic recalculation and disaster recovery are
  separate purposes: include only their missing required data when in scope.
  Keep authoritative raw evidence on its current host until retention is decided.
- Start from a committed source revision. If the requested behaviour depends on
  uncommitted work, stop and ask whether to commit it or deliberately include a
  recorded patch.
- Stage a fresh package directory. Never package a broad build tree, `.venv`,
  unrelated old outputs, or an existing run directory by accident.
- Include required scripts/configuration and only execution artifacts missing
  at the destination. Reuse the exact executable, weights, inputs and references
  already there after hash verification; bind their external paths/hashes in
  the receipt. Resolve each dependency either inside the package or to a verified
  external artifact, rather than resending it to make every path package-local.
- Include the complete local Python import closure of every packaged entry
  point, including modules imported only by a post-probe analysis step. Before
  archiving, import the staged entry points with `PYTHONPATH` set to the staged
  `scripts/` directory and run their dry validation where available.
- Generate a manifest containing the Git revision, run purpose, command,
  candidate identities/margins, and SHA-256 hashes of the executable, scripts,
  config, inputs, reference, baseline when applicable, and weights.
- Preserve the raw reference map: a candidate package must use the exact
  matching `reference.jsonl`; it must not silently substitute another corpus or
  reference contract.

## Target launchers

- For **Windows**, create a `.cmd` launcher. Use `python`, not `py -3`: the
  Windows Miniconda environment used for these runs may not provide `py`.
- For **Linux**, create `run.sh`. When the user asks for disconnect-safe remote
  execution, provide the `nohup` command, log path, and PID-file convention;
  do not launch it unless explicitly requested.
- Make the launcher fail on missing artifacts and write results below a new
  `run/` directory. It must not overwrite an existing result directory.

For continuous Linux dev/selection work, use `scripts/run_futility_loop.py`
and `scripts/futility_loop.example.json`; its operator procedure is in
`futility-tuning.md`, under "Continuous development/selection loop". This mode
uses the established external store and writes to `store_root/evals/<loop_id>`
instead of package-local `run/`. Bind the external population and probe/net
artifacts in the package receipt; do not ship duplicate populations when the
target store already has them. Include the loop's full import closure and its
cron launcher. Preserve an existing loop's immutable initialization/contract;
parameter changes require a graceful stop and explicit reconfiguration. A
stopped loop remains stopped under cron until `resume`; it never launches SPRT.

For `search.backend: "bo"`, also read "BO in the continuous loop" and "Tinibo
collaboration and release procedure" in `futility-tuning.md`. Use
`scripts/futility_loop_bo.example.json` only as a configuration guide. Include
the committed tinibo runtime/import closure and pin Python/NumPy/BLAS in the
receipt; do not ship a workstation `.venv`. Preserve the numerical runtime of
an active phase, use one BO worker, and distinguish compatible observation
imports from restoring an exact checkpoint. Old engine-contract targets must
not silently seed a changed probe/net/budget/corpus run.

## Small cloud upgrades and match-based BO

- When a target already has a verified package/runtime/store, prefer a small
  upgrade bound to its exact artifacts instead of copying binaries, nets,
  opening books, journals or wheels again. Record every external dependency,
  package/artifact hash and location in the receipt, and make setup verify them
  before preparing a fresh run. Never treat a rebuilt executable as identical
  to a frozen binary solely because the version name matches.
- For game-outcome BO, read **Standalone game-outcome BO** in
  `futility-tuning.md` and use `chilo-selfplay-bo-preparation` for additive
  collection and fresh configs. Do not mix this with regret-proxy observations.
  Keep all referenced old packages/stores until their evidence and artifacts
  have verified independent replacements. Respect stopped/pending-match checks;
  do not edit an old config/checkpoint to bypass resume fingerprints.
- Reuse the target's pinned Python/NumPy/tinibo environment where possible.
  Upgrade setup should not invoke apt/sudo or reinstall a working environment.
  If a genuinely new dependency is needed, make it explicit rather than adding
  an unexpected privileged installation. Qualify staged setup with compatible
  fixtures and dry validation without playing real matches.
- Archive an explicit payload or clean staging tree. Exclude generated
  qualification runs, workstation-bound configs/runtime receipts, `.venv`,
  `__pycache__` and logs. If setup generates the real config from remote state,
  record its template/overrides in the package manifest and write the resolved
  config hash/provenance receipt on the target.

## Finish

- Archive Windows packages as `.zip` and Linux packages as `.tgz`.
- Verify the payload and archive integrity once at creation. After transfer,
  compare bytes/hashes; do not replay already verified experiment journals or
  recompute scientific results merely to check a copy.
- Keep the package and transferred-result archive in `~/Tune/futility` as
  durable provenance once the run is accepted. Treat `/tmp` only as a transfer
  or inspection area.
- Read/use `chilo-ftp-transfer` to upload the finished archive to
  `/PUBLIC/transf`; verify the received content against the source SHA-256.
  If no trustworthy server-side hash is available, download back once to a fresh
  path and compare hashes/bytes. Do not add repeated download/audit rounds after
  equality is established. Report failure or skipped local-only transfer honestly;
  do not report packaging-and-delivery complete merely because a local archive
  exists. Do not overwrite or delete existing remote archives without approval.
- For the cloud, assume the operator copies tar archives to `/tmp`. Provide a
  single-line extraction command such as
  `tar -xzf /tmp/package.tgz -C /home/ubuntu`, followed by separate setup/start
  commands using the permanent extracted folder. Check the intended extraction
  target first when possible; never unpack over an active/previous run. Keep
  archives in `/tmp`, but run directories, artifacts and evidence in permanent
  locations. Result-collection instructions should also put the outgoing
  archive under `/tmp` and include `sha256sum`.
- Print the local archive path, remote FTP filename, SHA-256 and verification
  status, cloud extraction/setup/start commands, log path and expected result
  files. Preparation/setup must not start expensive work implicitly; let the
  operator execute the separately identified start command.

For current corpus/contract choices and the active experimental state, read
`futility-tuning.md` before selecting artifacts.
