---
name: chilo-cloud-storage-cleanup
description: Review and safely reduce Chilo storage on the cloud Linux server, preserving canonical futility data, resumable-loop state, and unique experiment evidence.
---

# Chilo cloud storage cleanup

Use this skill when auditing storage on the Chilo cloud server, especially
`~/futility-validation` and old `g3-*` or `futility-*` run directories. This is
for inventory, retention decisions, and explicitly requested archival or
cleanup. It does not authorize remote changes by itself. If the server is not
directly accessible, ask the user for read-only command output and base
recommendations on that evidence.

## Canonical cloud store

The durable working store is `~/futility-validation`, organized like this:

| Path | Purpose | Default disposition |
|---|---|---|
| `populations/` | Immutable raw development/selection populations, inputs, references, and rescue data | Keep; do not rewrite or delete as cleanup |
| `artifacts/` | Frozen probe binaries and weights identified by hashes | Keep while any evaluation or resumable run depends on them |
| `evals/` | Search, candidate, validation, and loop evidence | Keep unique evidence; inspect manifests and completion receipts before archiving |
| `candidate-probe-cache/` | Content-addressed normal-PVS candidate outputs reusable across runs | Preserve while loops may use it; pruning saves space but can require expensive reprobes |

The local counterpart is `~/Tune/futility/validation/`; consult its `README.md`
for the population and evidence contract. The cloud store and local registry
have corresponding populations, cache, evaluations, and frozen artifacts, but
do not assume every cloud evaluation has already been copied locally.

### Loop data inside `evals/`

For `evals/futility-loop-v1/`:

- `loop_state.json`, `control.json`, and loop manifests are operational state;
  do not replace or edit them during cleanup.
- `cycles/` contains per-cycle search state and raw candidate evidence. The
  loop's reconfiguration path rereads completed cycle evidence, so retain it
  if future selector reconfiguration or auditability matters.
- `validation/` contains self-contained validation batches. Each candidate
  directory can hold large raw probes; the small `results.json` and `report.md`
  are summaries, not substitutes for raw evidence.
- `candidate-probe-cache/` entries may duplicate raw outputs held by campaigns,
  but are an acceleration layer. The standard cache backfill scans manifests
  directly under the store's top-level `evals/`; it does not recursively
  reconstruct every nested loop cycle. Do not assume the cache is trivially
  reproducible or safe to remove wholesale.

If a loop or probe is active, do not move, compress in place, or delete its
store, current cycle, validation batch, cache, artifacts, or run package. Check
processes and scheduled jobs first. Even completed cycle data can be needed by
future reconfiguration.

## Other cloud directories

The home directory may also contain:

- `futility-loop-*`: runner/package directories, sometimes including the
  Python environment and exact scripts/config needed to resume a loop. Retain
  while active or resumable; check process command lines, cron entries, and
  store references before removal.
- `futility-bo-*` and `evals/bo-*`: BO pilots and validation runs. Inspect their
  manifests, raw outputs, and canonical copies; names or age do not establish
  that results are redundant.
- `g3-sr*` and `g3-sr4-*`: historical anchor, rescue, optimizer, or full-eval
  packages. Some are launch packages, some contain unique results. Compare
  contents against `futility-validation/evals/`, returned archives, and local
  evidence before proposing deletion.
- `futility-populations-*-linux`: population synchronization/import staging
  packages. They may be removable after successful installation is verified
  and a matching archive or canonical installed copy is confirmed.
- `Tune/extract/`: training source corpora, not futility-validation output.
  Large CSVs may compress well, but confirm no training job uses them and
  preserve a verified recoverable copy before removing originals.
- `NNUE/`, `SPRT/`, and unrelated user directories: outside routine futility
  cleanup unless the user explicitly includes them.

These are categories, not a current inventory. Recheck names, size, contents,
processes, cron configuration, and manifests every time; remote contents
change.

## Audit workflow

1. Confirm the target host and scope. Do not assume SSH, credentials, or a
   previous connection is available. Do not expose credentials in commands or
   logs.
2. Gather a current read-only inventory: top-level `du`, largest nested
   directories, relevant `find` listings, process command lines, and scheduled
   jobs. Keep output scoped to Chilo-related paths.
3. Classify each target as **canonical/keep**, **active**, **unique historical
   evidence**, **verified duplicate**, or **unresolved**. Ground the category
   in manifests, checksums, completion receipts, and path dependencies—not
   just age, names, or matching sizes.
4. For oversized evaluation batches, inspect per-candidate directory sizes.
   A large total can simply be many complete candidate probes; preserve the
   raw evidence unless a verified archive is the intended retained copy.
5. For proposed archives, preserve relative paths; verify archive integrity
   and compare contents before treating it as a replacement. Record the
   archive path, checksum, and restore location. Do not delete originals merely
   because an upload or archive command succeeded.
6. If the user asked only for review, make no remote changes. Before an
   explicitly requested deletion, show the exact targets and confirm the
   recoverable copy or duplicate. Never use broad recursive deletion or
   unchecked wildcards.

Useful read-only starting points (adjust paths to the current target):

```bash
du -h --max-depth=1 ~/futility-validation ~/futility-validation/evals | sort -h
du -h --max-depth=2 ~/futility-validation/evals/futility-loop-v1 | sort -h | tail -30
pgrep -af 'run_futility_loop.py|futility_probe|tune_futility.py'
crontab -l
```

For a completed batch, inspect its `complete.json`, `batch_manifest.json`,
`results.json`, `report.md`, and candidate subdirectory sizes. A summary report
does not replace raw probe evidence.
