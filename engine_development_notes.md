# Engine Development Notes

This file is a compact current-state note, not a full chronological bug log. For day-to-day usage, start with `README.md`; for agent-specific project rules, use `AGENTS.md`. See `engine-decisions.md` for the durable rationale behind non-obvious choices and rejected experiments.

## Current Engine Shape

- `engine.h` is the public API used by frontends, tests, and tools.
- `chess_position.h` owns position representation, FEN/UCI helpers, draw-history helpers, and validation utilities.
- `chess_tables.h` owns low-level attack tables and magic-bitboard setup.
- `attack.cpp`, `movegen.cpp`, `make_unmake.cpp`, and `perft_lib.cpp` implement the move-generation/perft core.
- `search.cpp` implements iterative-deepening negamax alpha-beta with TT, PVS, null move, LMR, futility, killer/history ordering, SEE capture handling, repetition/50-move draw handling, and QS.
- `eval.cpp` is NNUE inference only. The old handcrafted tapered evaluator is no longer the active evaluator.
- `chilo.cpp`, `selfplay_collect.cpp`, `eval_fen.cpp`, `futility_probe.cpp`, `perft.cpp`, and `perft_diag.cpp` are separate frontends over the shared engine objects.

Normal C++ build outputs live under `build/release`, `build/debug`, `build/validate`, and `build/win64`.
Optional AVX2-specific release outputs live under `build/release-avx2` and `build/win64-avx2`; those binaries require AVX2-capable CPUs.

## NNUE State

The active evaluator is `TinyNnue` with white/black perspective accumulators:

- the two accumulator lanes are stored as white perspective and black perspective
- inference orders them as side-to-move first, opponent second
- raw board pieces are remapped to friendly/enemy input planes per perspective
- square normalization mirrors black perspectives
- the clipped accumulator pair feeds a second ClippedReLU hidden layer before the scalar output

Search uses per-ply NNUE accumulator frames. Each searched child frame is copied
from the parent frame with capacity-preserving storage reuse, then the move
delta is applied once before entering the child. Returning from the child does
not require NNUE undo work. Low-piece children at or below
`NNUE_REBUILD_PIECE_THRESHOLD` skip child-frame preparation and use rebuilt
evaluation throughout that subtree. `evaluate(pos)` remains the full-rebuild
reference path for tools, parity tests, and fallback cases.

The feature/model contract is `scripts/nnue_contract.json`. Keep it consistent with `eval.cpp`, `scripts/nnue_common.py`, `scripts/train_nnue.py`, `scripts/export_nnue.py`, and the checked-in generated files under `generated/`.

The engine always has built-in fallback weights from `generated/generated_nnue_weights.h`. It can also load a runtime `.bin` export:

- `chilo --weights /path/to/weights.bin` or `eval_fen --weights /path/to/weights.bin` loads an explicit file
- without `--weights`, both tools check for a same-basename sidecar `.bin` next to the executable
- explicit weight-load failure is fatal for `chilo`/`eval_fen`; sidecar load failure falls back to built-in weights
- runtime `.bin` files may use a different hidden size as long as the feature contract, clip value, dimensions, and scales match

Integer export uses the `byte_dense_shift_v1` format: feature-transformer weights
and accumulator bias stay `int16`, accumulator and hidden-layer activations are
requantized to `0..127`, dense/output weights are `int8`, and dense/output
biases are `int32`. Activation requantization is shift-only, so export scales
must be powers of two. Runtime `.bin` files use the `CHNNUEB5` magic and export
manifests use `chilo.nnue_export.v8`.

Runtime NNUE tensors, accumulator frames, and dense scratch buffers use
32-byte-aligned storage. AVX2 builds use aligned accumulator updates,
byte-dense dot products, and vectorized accumulator-to-byte activation when
alignment permits; generic builds keep scalar fallbacks and exact parity.

## UCI Search Threading Note

The normal UCI frontend uses asynchronous search: the input thread stays
available for `stop`, `quit`, and `isready`, while a search worker computes the
current `go` command. This is the correct long-term shape, especially before
adding true multi-threaded search.

On Windows MinGW builds, the per-search worker-thread lifecycle has exposed a
timing-dependent failure with the faster small NNUE v3 runtime net
(`g3hl2c`, 16 -> 8). Fastchess and at least one GUI can receive `bestmove`,
send `isready` immediately, and then the engine stalls or terminates while the
frontend is joining the just-finished search thread. The older/larger
64 -> 32 test net was slower and did not reliably expose this race. Linux
generic and AVX2 builds did not reproduce the failure.

Current workaround:

- Windows builds default to synchronous search, avoiding per-move worker-thread
  creation and join.
- `--sync-search` forces the same path on any platform.
- `--async-search` forces the asynchronous path and is mainly useful for
  debugging the Windows issue.

The cost of synchronous search is reduced UCI responsiveness: `stop` and `quit`
are only processed after the current search returns. This is acceptable for
short fixed-depth tests and normal clock-limited games, but it is not a final
UCI design. The intended durable fix is a persistent search worker/search
manager that is started once, receives search jobs, supports `stop`, and is not
created and joined for every move.

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

## Search-Tuning Constraint

Futility margins, reductions, and related selectivity are coupled to the
active NNUE and its scale. Treat the current constants as the tested baseline,
not universal values: measure candidate nets with the existing diagnostics and
fixed-depth benchmarks, then require SPRT evidence before claiming strength.

`SearchLimits` supports a cumulative hard node limit and per-search futility
parameters. Iterative deepening keeps the move, score, PV, depth, and
`completedNodes` from the last complete iteration; `nodes` and search
diagnostics include work performed in an interrupted iteration. This avoids
treating a partially searched root move list as a completed result.

Use `futility_probe`, not UCI options or tuning loops inside `search.cpp`, to
compare margin tuples over a position corpus. The probe isolates TT state per
position, accepts FEN or first-column CSV input, and emits JSON Lines suitable
for `scripts/tune_futility.py`. The tuner runs a full-window, all-root-score
reference plus a candidate-budget baseline as a reusable anchor, then ranks
candidates by normalized reference-root score regret. P90 regret, move
agreement, depth, and raw-score/mate figures remain diagnostics. The anchor
manifest fingerprints the probe, net, corpus, budgets, and baseline margins;
candidate-family changes can reuse it safely. See `futility-tuning.md` for
current filtered candidates and SPRT status. The probe's separate
`futility_prunes_in_check` counters intentionally expose current behavior for
analysis; changing whether in-check nodes may prune is a separate search
experiment.

## Useful Workflows

- `make` builds optimized release binaries and the release test binary.
- `make release-avx2` builds optimized Linux binaries with `-DCHILO_AVX2 -mavx2`.
- `make debug` builds debug binaries.
- `make validate` builds validation binaries with `CHESS_VALIDATE_STATE`.
- `make windows64` cross-builds Windows `.exe` binaries with MinGW-w64.
- `make windows64-avx2` cross-builds Windows `.exe` binaries with `-DCHILO_AVX2 -mavx2`.
- `make nnue-python-tests` runs Python pipeline unit tests.
- `make nnue-verify` runs preprocess -> train -> export -> rebuild -> C++/Python parity verification.
- `python3 scripts/benchmark_fixed_depth.py` compares two UCI binaries at fixed depth.
- `python3 scripts/tune_futility.py --config ... --dry-run` validates and expands a futility sweep without starting searches.

The TT replacement experiment is still available with:

```bash
make clean
make EXTRA_CPPFLAGS=-DCHILO_TT_ALWAYS_OVERWRITE=1
```
