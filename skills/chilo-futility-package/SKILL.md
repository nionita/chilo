---
name: chilo-futility-package
description: Prepare a self-contained, provenance-checked Chilo futility run package for a Windows or Linux machine. Use for remote or secondary-machine anchors, probes, full evaluations, mate rescues, or optimizer runs; do not use to start a run.
---

# Chilo futility run packaging

Package a run so that another machine can execute it without relying on paths,
uncommitted source, or unstated artifacts from this workstation. Preparing a
package does not authorize starting an expensive run.

## Select and stage artifacts

- Start from a committed source revision. If the requested behaviour depends on
  uncommitted work, stop and ask whether to commit it or deliberately include a
  recorded patch.
- Stage a fresh package directory. Never package a broad build tree, `.venv`,
  unrelated old outputs, or an existing run directory by accident.
- Include the exact executable probe for the target architecture, its Python
  scripts and configuration, every selected input/reference/anchor artifact,
  and the runtime weights when the probe needs them. Resolve every config path
  inside the staged package.
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

## Finish

- Archive Windows packages as `.zip` and Linux packages as `.tgz`.
- Verify the archive contents and print its SHA-256, unpack/run command, and
  expected result files.
- Keep the package and transferred-result archive in `~/Tune/futility` as
  durable provenance once the run is accepted. Treat `/tmp` only as a transfer
  or inspection area.

For current corpus/contract choices and the active experimental state, read
`futility-tuning.md` before selecting artifacts.
