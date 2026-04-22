# Engine Development Notes

This file is a compact current-state note, not a full chronological bug log. For day-to-day usage, start with `README.md`; for agent-specific project rules, use `AGENTS.md`.

## Current Engine Shape

- `engine.h` is the public API used by frontends, tests, and tools.
- `chess_position.h` owns position representation, FEN/UCI helpers, draw-history helpers, and validation utilities.
- `chess_tables.h` owns low-level attack tables and magic-bitboard setup.
- `attack.cpp`, `movegen.cpp`, `make_unmake.cpp`, and `perft_lib.cpp` implement the move-generation/perft core.
- `search.cpp` implements iterative-deepening negamax alpha-beta with TT, PVS, null move, LMR, futility, killer/history ordering, SEE capture handling, repetition/50-move draw handling, and QS.
- `eval.cpp` is NNUE inference only. The old handcrafted tapered evaluator is no longer the active evaluator.
- `chilo.cpp`, `selfplay_collect.cpp`, `eval_fen.cpp`, `perft.cpp`, and `perft_diag.cpp` are separate frontends over the shared engine objects.

Normal C++ build outputs live under `build/release`, `build/debug`, `build/validate`, and `build/win64`.

## NNUE State

The active evaluator is `TinyNnue` with active/passive perspectives:

- perspective `0` is the side to move
- perspective `1` is the opponent
- raw board pieces are remapped to friendly/enemy input planes per perspective
- square normalization mirrors black perspectives
- the score is `(active_perspective - passive_perspective) / 2`

Search evaluates through lazy NNUE accumulators: move deltas are pushed before `doMove`, but hidden sums are only updated when a node actually needs static eval. `evaluate(pos)` remains the full-rebuild reference path for tools, parity tests, and fallback cases.

The feature/model contract is `scripts/nnue_contract.json`. Keep it consistent with `eval.cpp`, `scripts/nnue_common.py`, `scripts/train_nnue.py`, `scripts/export_nnue.py`, and the checked-in generated files under `generated/`.

The engine always has built-in fallback weights from `generated/generated_nnue_weights.h`. It can also load a runtime `.bin` export:

- `chilo --weights /path/to/weights.bin` or `eval_fen --weights /path/to/weights.bin` loads an explicit file
- without `--weights`, both tools check for a same-basename sidecar `.bin` next to the executable
- explicit weight-load failure is fatal for `chilo`/`eval_fen`; sidecar load failure falls back to built-in weights
- runtime `.bin` files may use a different hidden size as long as the feature contract, clip value, dimensions, and scales match

Integer export is scaled `int16` for input weights, hidden bias, and output weights, with `int32` output bias. The input/output scales are export parameters and are recorded in manifests and binary headers.

## Training/Data Pipeline

Raw self-play collection writes `eval_fen,score,result`, where both score and result are from the evaluated position side-to-move perspective. `selfplay_collect` records evaluated leaves, skips terminal/in-check leaves, reports progress/ETA, refuses to overwrite existing output files, and uses a generated time/process-derived RNG seed unless `--seed` is supplied.

The data flow is intentionally staged:

1. `scripts/dedup_training_csv.py` optionally removes exact duplicate CSV rows with external `sort`.
2. `scripts/prepare_nnue_dataset.py` converts one or more CSV files into a sharded dataset directory with `manifest.json` and `shards/*.npy`.
3. `scripts/train_nnue.py` streams shards with PyTorch and chooses the hidden size. Dataset preparation is not tied to hidden size.
4. `scripts/export_nnue.py` exports a checkpoint to generated C++ fallback weights, a runtime `.bin`, or both, and can validate quantization drift against a dataset.
5. `scripts/run_nnue_workflow.py` orchestrates dedup, prepare, train, export, and optional temporary engine verification.

Use `.venv` created by `make python-env` for training/export work. Do not rely on system `torch`.

## Correctness Rails

Perft and full undo-state restoration remain the primary safety rails. Search/eval changes should not weaken:

- legal move generation and king-safety filtering
- exact `doMove()` / `undo()` restoration
- incremental hash restoration
- draw-history behavior for real UCI move sequences
- reference perft coverage in `engine_tests`

Use `make validate` when investigating state corruption. It is intentionally much slower than normal builds.

## Useful Workflows

- `make` builds optimized release binaries and the release test binary.
- `make debug` builds debug binaries.
- `make validate` builds validation binaries with `CHESS_VALIDATE_STATE`.
- `make windows64` cross-builds Windows `.exe` binaries with MinGW-w64.
- `make nnue-python-tests` runs Python pipeline unit tests.
- `make nnue-verify` runs preprocess -> train -> export -> rebuild -> C++/Python parity verification.
- `python3 scripts/benchmark_fixed_depth.py` compares two UCI binaries at fixed depth.

The TT replacement experiment is still available with:

```bash
make clean
make EXTRA_CPPFLAGS=-DCHILO_TT_ALWAYS_OVERWRITE=1
```
