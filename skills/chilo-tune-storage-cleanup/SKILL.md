---
name: chilo-tune-storage-cleanup
description: Audit and reduce Chilo experiment storage under ~/Tune and project-related temporary files while preserving reproducible futility evidence.
---

# Chilo Tune storage cleanup

Use for storage audits and cleanup of Chilo tuning data, especially
`~/Tune/futility`. This skill is for proposing and carrying out scoped local
archival or cleanup, not for transferring files; use `chilo-ftp-transfer` when
the task includes FTP/WebDAV movement.

## Retention boundaries

- Read `~/Tune/futility/validation/README.md` and relevant sections of the
  repository's `futility-tuning.md` before changing futility data. The README
  identifies canonical populations, evaluation evidence, and cleanup policy.
- Preserve canonical raw populations and current candidate evaluation JSONL
  under `~/Tune/futility/validation/`. Keep their established directory layout
  and leave active inputs uncompressed so existing evaluators continue to work.
- Check configs, manifests, scripts, and documentation for path references
  before moving, compressing, or removing a file. Historical root CSVs may
  still be named by old configs even when identical copies exist canonically.
- Keep unique historical results and provenance. Prefer a verified compressed
  archive over discarding the only copy; already compressed `.zip`/`.tgz`
  files rarely benefit from recompression.

## Workflow

1. Inventory sizes and file types in the requested scope. Limit `/tmp` checks
   to Chilo-related names; do not traverse private system temporary folders or
   assume every archive there is disposable.
2. Classify findings as keep, duplicate, archive/compress, or unresolved. For
   suspected duplicates, compare SHA-256 (or `cmp`); same names or sizes are
   not proof. A `/tmp` copy is removable only when a durable matching copy has
   been verified.
3. For a historical directory not needed in the daily workflow, prefer a
   `.tgz` that preserves the original relative paths. Verify `gzip -t`, then
   compare the extracted archive against the source by file contents before
   removing the expanded source. Tar timestamp warnings alone do not establish
   a content mismatch; use a content-only comparison if needed.
4. For an individual text/CSV/JSONL file, check both compression benefit and
   path dependencies. Do not replace an active `.csv`/`.jsonl` with `.gz` if
   scripts expect the plain path. Preserve manifests and checksums as evidence.
5. Remove files only when the user has authorized cleanup and the exact targets
   are confirmed. Use explicit paths, never broad recursive deletion or an
   unchecked wildcard. If the request is only to review or propose, make no
   changes.
6. When an archive replaces a documented directory, add its path and the
   extraction destination to `futility-tuning.md`. Report retained canonical
   data, verified archives, unresolved duplicates, and before/after sizes.

For all futility data decisions, distinguish reusable working inputs from
historical evidence. Do not infer that an experiment is obsolete merely because
it is old or its candidate was not promoted.
