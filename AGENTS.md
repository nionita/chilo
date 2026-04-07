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
├── perft.cpp
├── perft_diag.cpp
├── engine_tests.cpp
├── generated/
│   ├── generated_nnue_weights.h
│   └── generated_nnue_manifest.json
├── build/
│   ├── release/
│   ├── debug/
│   ├── validate/
│   └── win64/
├── scripts/
│   ├── benchmark_fixed_depth.py
│   ├── nnue_contract.json
│   ├── nnue_common.py
│   ├── prepare_nnue_dataset.py
│   ├── train_nnue.py
│   ├── export_nnue.py
│   ├── verify_nnue_workflow.py
│   └── setup_python_env.sh
├── requirements-nnue.txt
└── Makefile
```

## Important Specifics

- The evaluator is no longer the old handcrafted tapered eval. `eval.cpp` runs inference only; the embedded weights come from `generated/generated_nnue_weights.h`.
- The training/export contract is explicit. Keep `eval.cpp`, `generated/generated_nnue_weights.h`, `generated/generated_nnue_manifest.json`, and `scripts/nnue_contract.json` in sync.
- `eval_fen.cpp` exists mainly for Python-to-C++ NNUE parity checks.
- `selfplay_collect.cpp` is the training-data collector. It records evaluated leaf positions, skips noisy leaves that are terminal or in check, and prints progress/ETA during long runs.
- The dataset pipeline is sharded now. Do not assume one CSV in and one `samples.npy` out:
- `prepare_nnue_dataset.py` takes many CSVs and writes a dataset directory with `manifest.json` plus shard `.npy` files
- `train_nnue.py` streams shards instead of loading one monolithic dataset
- `export_nnue.py` validates against the sharded dataset manifest before generating C++ weights
- The repo keeps a checked-in generated NNUE export so the engine builds without running Python first.
- C++ build outputs now live under `build/`, split by mode. Do not put new binaries or object-file targets back in the repo root.

## Build And Test Shortcuts

- `make` builds release binaries.
- `make debug` builds debug binaries.
- `make validate` builds with expensive state-restoration checks.
- `make windows64` cross-builds Windows release binaries.
- `make python-env` creates `.venv` and installs CPU-only PyTorch plus Python requirements.
- `make nnue-python-tests` runs the Python pipeline smoke tests.
- `make nnue-verify` runs preprocess -> train -> export -> rebuild -> C++/Python parity verification.
- Built artifacts land under `build/release`, `build/debug`, `build/validate`, and `build/win64`.

## Environment Gotchas

- This workspace often fails basic shell commands inside the sandbox with `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. If that happens, rerun the command with escalation instead of wasting time debugging the command itself.
- The repo root may still contain stale legacy build outputs from older layouts. Prefer the files under `build/`.
- `.venv/` is local-only. Use it for the NNUE scripts; do not depend on system `torch`.
- `generated/generated_nnue_weights.h` is generated data. If the model contract changes, regenerate it instead of editing numbers by hand.

## Likely Next Work

- improve the NNUE architecture and training targets
- add stronger UCI/options support
- continue search/eval tuning without breaking perft or undo-state guarantees
