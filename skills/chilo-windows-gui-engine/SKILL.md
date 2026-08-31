---
name: chilo-windows-gui-engine
description: Build a named Windows AVX2 Chilo engine and matching NNUE sidecar for UCI GUI inspection. Use when a futility candidate needs a directly runnable Windows engine, not for Linux SPRT builds.
---

# Chilo Windows GUI engine

Produce one directly usable GUI pair: `<identity>.exe` and `<identity>.bin`.
The sidecar name must match the executable basename exactly, so Chilo locates
the intended runtime NNUE weights through its same-basename sidecar rule.

## Build contract

- Confirm the exact source revision, requested short identity, futility margin
  tuple, and weights artifact before building. An identity is an experiment
  label, not evidence that the binary has the requested tuple.
- Use the isolated variant build workflow in
  `scripts/build_futility_variants.py` and the Windows AVX2 target. Do not
  reuse a generic `build/win64-avx2` binary when compile-time margins differ.
- Keep normal source defaults unchanged. Candidate margins belong only in the
  isolated variant build.
- Copy the selected runtime `.bin` beside the resulting `.exe`, renaming it to
  the same basename. Do not rely on the compiled fallback net for GUI testing.

## Delivery

- Use a clear name such as `chilo-<version>-<identity>-avx2.exe`; avoid spaces
  and do not overwrite an existing engine or sidecar without explicit user
  permission.
- Place the pair in the requested GUI/engine directory.
- Write a small build receipt beside or with the pair: Git revision, margins,
  source weights path, and SHA-256 hashes of both files.
- Report the two final paths and the tuple. A Windows cross-build need not be
  executed on this Linux host; validate its build output and receipt instead.
