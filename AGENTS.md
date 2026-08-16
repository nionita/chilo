# Chilo Agent Notes

## Project Snapshot

`chilo` is now a small playable chess engine, not just a perft sandbox. The current tree includes:

- stable move generation and make/undo with perft regression coverage
- iterative-deepening alpha-beta search with TT, PVS, null move, LMR, futility, killer/history, and QS
- a tiny embedded NNUE-style evaluator
- a UCI binary
- self-play data collection
- a Python training/export pipeline for the NNUE weights

## What Matters

- `engine.h` is the public engine API. Start there.
- `chess.h` is only a compatibility umbrella include.
- `chess_position.h` and `chess_tables.h` are relatively stable low-level layers.
- Most engine work should happen in `.cpp` files behind `engine.h`.
- Perft correctness and full-state restoration are still the main safety rails. Do not treat search strength as a reason to weaken those checks.
- `engine-decisions.md` records non-obvious rationale, historical experiments,
  and rejected approaches; current source and current-state notes still win on
  any conflict.

## Current Layout

```text
/home/nicu/Sources/chilo/
├── engine.h
├── chess.h
├── chess_position.h
├── chess_tables.h
├── attack.cpp
├── movegen.cpp
├── make_unmake.cpp
├── perft_lib.cpp
├── eval.cpp
├── search.cpp
├── chilo.cpp
├── selfplay_collect.cpp
├── eval_fen.cpp
├── futility_probe.cpp
├── perft.cpp
├── perft_diag.cpp
├── engine_tests.cpp
├── generated/
│   ├── generated_nnue_weights.h
│   └── generated_nnue_manifest.json
├── build/
│   ├── release/
│   ├── release-avx2/
│   ├── debug/
│   ├── validate/
│   ├── win64/
│   └── win64-avx2/
├── scripts/
│   ├── benchmark_fixed_depth.py
│   ├── dedup_training_csv.py
│   ├── fastchess_sprt_config.example.json
│   ├── nnue_contract.json
│   ├── nnue_common.py
│   ├── prepare_nnue_dataset.py
│   ├── run_fastchess_sprt.py
│   ├── run_nnue_workflow.py
│   ├── test_nnue_pipeline.py
│   ├── test_tune_futility.py
│   ├── tune_futility.py
│   ├── train_nnue.py
│   ├── export_nnue.py
│   ├── verify_nnue_workflow.py
│   └── setup_python_env.sh
├── requirements-nnue.txt
└── Makefile
```

## Important Specifics

- The evaluator is no longer the old handcrafted tapered eval. `eval.cpp` runs inference only. The compiled engine has a built-in fallback net from `generated/generated_nnue_weights.h`, but it can also load a runtime `.bin` weights artifact with a different hidden size.
- Search now uses per-ply NNUE accumulator frames. Each searched child starts from a capacity-reused copy of the parent accumulator and applies its move delta once, so returning from the child does not need NNUE undo work. Low-piece children at or below `NNUE_REBUILD_PIECE_THRESHOLD` skip accumulator-frame preparation entirely and reuse rebuild eval for the whole subtree. `evaluate(pos)` remains the full-rebuild reference path for tools and tests, and `performance.md` contains the branch-local before/after profiling for these changes.
- The training/export contract is explicit. Keep `eval.cpp`, `generated/generated_nnue_weights.h`, `generated/generated_nnue_manifest.json`, and `scripts/nnue_contract.json` in sync.
- Integer export is scale-driven now. `scripts/export_nnue.py` writes input, hidden, and output quantization scales plus hidden sizes into the generated manifest/header or runtime `.bin`, and `eval.cpp` must use the same shift-based clipped math as the Python parity path.
- The Tiny NNUE stores white/black perspective accumulators and feeds them to dense inference as active/passive (side to move / opponent); raw board pieces are remapped to relative friendly/enemy planes at inference/training time.
- `eval_fen.cpp` exists mainly for Python-to-C++ NNUE parity checks.
- Fixed-node search preserves the last fully completed iterative-deepening result. `SearchResult.nodes` and diagnostics include interrupted-iteration work; `completedNodes`, depth, score, best move, and PV do not. `futility_probe.cpp` uses this contract with isolated TT state to emit per-position JSON Lines for external margin-tuple analysis.
- `scripts/tune_futility.py` expands explicit, linear, and power margin candidates, fingerprints long-running probe sweeps for explicit resume, and produces a Pareto shortlist. Its move-agreement/loss/depth metrics are screening proxies; only SPRT establishes strength.
- `selfplay_collect.cpp` is the training-data collector. It records evaluated leaf positions, skips noisy leaves that are terminal or in check, prints progress/ETA during long runs, and only requests exact all-root scores during the opening stochastic sampling window; later plies use normal root PVS plus best-move leaf retention.
- `selfplay_collect.cpp` refuses to overwrite existing output/debug-output files. If `--seed` is not provided, it derives a seed from time and process id and prints it so runs can be reproduced later.
- The dataset pipeline is sharded now. Do not assume one CSV in and one `samples.npy` out.
- `dedup_training_csv.py` is the scalable exact-row dedup step for raw collector CSVs. Keep dedup outside the trainer and preprocessor; do not collapse by FEN alone unless that policy changes explicitly.
- `prepare_nnue_dataset.py` takes many CSVs and writes a dataset directory with `manifest.json` plus shard `.npy` files. It accepts both normal headered collector CSVs and headerless `sort | uniq` outputs. Hidden size is not part of dataset preparation.
- `train_nnue.py` streams shards instead of loading one monolithic dataset, and hidden size is chosen there. The contract default hidden size is currently `64`.
- `export_nnue.py` validates against the sharded dataset manifest before generating the built-in C++ header and/or a runtime-loadable `.bin` weights file.
- Runtime `.bin` exports use the same feature contract but can have a different hidden size than the built-in fallback. Explicit `--weights` load failures are fatal; same-basename sidecar load failures fall back to built-in weights.
- `run_nnue_workflow.py` is the operator wrapper for dedup -> prepare -> train -> export, with optional temporary engine verification against the exported weights.
- `run_nnue_workflow.py` uses a pragmatic default export tolerance (`256`) so short real-data training runs can usually produce a first quantized export without extra flags.
- `run_fastchess_sprt.py` is the operator wrapper for two-engine fastchess SPRT tests. Keep fixed tournament settings in a JSON config and put each run in a dedicated directory with the standard `fastchess_state.json` autosave/resume file. It accepts `opening.format=fen` and materializes a normalized EPD book in the run directory, clamping invalid fullmove counters below `1` to avoid bogus fastchess PGN numbering. `--concurrency`, `--force-concurrency`, and `--no-force-concurrency` override config defaults for new wrapper runs. If `--config` is omitted, the wrapper falls back to `FASTCHESS_SPRT_CONFIG`. The config may define `engine_root`, `weights_root`, and a stable `engine_b` block; CLI engine/net overrides still win. `--resume-state /path/to/fastchess_state.json` recovers the full wrapper context from `fastchess_command.json`.
- The repo keeps a checked-in generated NNUE export so the engine builds without running Python first.
- C++ build outputs now live under `build/`, split by mode. Do not put new binaries or object-file targets back in the repo root.

## Build And Test Shortcuts

- `make` builds release binaries.
- `make release-avx2` builds Linux release binaries with `-DCHILO_AVX2 -mavx2`; these require AVX2-capable CPUs.
- `make debug` builds debug binaries.
- `make validate` builds with expensive state-restoration checks.
- `make windows64` cross-builds Windows release binaries.
- `make windows64-avx2` cross-builds Windows release binaries with `-DCHILO_AVX2 -mavx2`; these require AVX2-capable CPUs.
- `make python-env` creates `.venv` and installs CPU-only PyTorch plus Python requirements.
- `make nnue-python-tests` runs the Python smoke tests, including the NNUE pipeline and fastchess wrapper tests.
- `make nnue-verify` runs preprocess -> train -> export -> rebuild -> C++/Python parity verification.
- Built artifacts land under `build/release`, `build/release-avx2`, `build/debug`, `build/validate`, `build/win64`, and `build/win64-avx2`.

## Environment Gotchas

- This workspace often fails basic shell commands inside the sandbox with `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. If that happens, rerun the command with escalation instead of wasting time debugging the command itself.
- The repo root may still contain stale legacy build outputs from older layouts. Prefer the files under `build/`.
- `.venv/` is local-only. Use it for the NNUE scripts; do not depend on system `torch`.
- `generated/generated_nnue_weights.h` is generated data for the built-in fallback net. Runtime `.bin` files can override it at startup via `--weights` or a same-basename sidecar.

## Likely Next Work

- improve the NNUE architecture and training targets
- add stronger UCI/options support
- continue search/eval tuning without breaking perft or undo-state guarantees
