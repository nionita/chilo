# Chilo

Small chess engine project with:

- a perft driver and diagnostics for move-generation validation
- a tiny embedded NNUE evaluator and alpha-beta search
- a basic UCI engine binary for GUI integration
- a self-play training-data collector
- a Python NNUE training/export pipeline

## Files

- `engine.h`: public engine API
- `chess.h`: compatibility umbrella include
- `chess_position.h`, `chess_tables.h`: position/types layer and precomputed attack tables
- `attack.cpp`, `movegen.cpp`, `make_unmake.cpp`, `perft_lib.cpp`: move-generation and perft core
- `eval.cpp`: NNUE static evaluation, generated fallback weights, and runtime weight loading
- `search.cpp`: iterative-deepening alpha-beta search
- `chilo.cpp`: UCI engine binary entry point
- `selfplay_collect.cpp`: self-play training-data collector
- `eval_fen.cpp`: tiny CLI for evaluating one or more FENs with the compiled engine
- `perft.cpp`: CLI entry point for running perft
- `perft_diag.cpp`: subtree divide helper for isolating perft mismatches
- `engine_tests.cpp`: regression-style test program for engine behavior
- `scripts/benchmark_fixed_depth.py`: fixed-depth UCI benchmark helper for comparing two binaries
- `scripts/dedup_training_csv.py`: exact-row CSV dedup for large collector outputs using external `sort`
- `scripts/fastchess_sprt_config.example.json`: example config for SPRT runs
- `scripts/nnue_contract.json`: feature/model contract shared by training, export, and C++ inference
- `scripts/prepare_nnue_dataset.py`: sharded NNUE dataset preprocessor
- `scripts/run_fastchess_sprt.py`: fastchess SPRT wrapper for testing binaries or runtime NNUE nets
- `scripts/train_nnue.py`: PyTorch NNUE trainer for sharded datasets; hidden size is chosen here, not in dataset prep
- `scripts/export_nnue.py`: scaled quantized export to the generated C++ header and/or a runtime-loadable `.bin` artifact
- `scripts/run_nnue_workflow.py`: orchestration helper for dedup -> prepare -> train -> export
- `scripts/verify_nnue_workflow.py`: end-to-end smoke check for preprocess -> train -> export -> C++
- `engine_development_notes.md`: compact current-state notes and workflow reminders
- `Makefile`: build targets for release, AVX2 release, debug, validation, Windows, and NNUE workflow checks

Build outputs live under `build/`, and the checked-in NNUE export lives under `generated/`.
The built-in generated export is the fallback default; the engine can also load an explicit `--weights` file or a same-basename sidecar `.bin` beside the executable.

## Build

The project uses `g++` and `make`.

Windows x64 cross-compilation from Linux uses the MinGW-w64 POSIX toolchain:

```bash
sudo apt update
sudo apt install gcc-mingw-w64-x86-64-posix g++-mingw-w64-x86-64-posix
```

### Optimized build

Build the fast binaries used for normal perft runs:

```bash
make
```

This builds under `build/release/`:

- `perft`
- `perft_diag`
- `engine_tests`
- `chilo`
- `selfplay_collect`
- `eval_fen`

These targets use:

- `-O3`
- `-DNDEBUG`

That means assertions are disabled and the binaries are suitable for performance measurement.

### AVX2 optimized build

Build Linux release binaries for newer x86-64 CPUs with AVX2:

```bash
make release-avx2
```

This builds under `build/release-avx2/` and uses:

- `-O3`
- `-DNDEBUG`
- `-DCHILO_AVX2`
- `-mavx2`

These binaries are not generic x64 binaries. They require an AVX2-capable CPU and may fail with an illegal-instruction error on older machines.

### Debug build

Build non-optimized binaries with debug symbols:

```bash
make debug
```

This builds under `build/debug/`:

- `perft_debug`
- `perft_diag_debug`
- `engine_tests_debug`
- `chilo_debug`
- `selfplay_collect_debug`
- `eval_fen_debug`

These targets use:

- `-O0`
- `-g`

Use this when debugging logic or stepping through the code.

### Validation build

Build binaries with the expensive full-state restoration check enabled:

```bash
make validate
```

This builds under `build/validate/`:

- `perft_validate`
- `perft_diag_validate`
- `engine_tests_validate`
- `chilo_validate`
- `selfplay_collect_validate`
- `eval_fen_validate`

These targets use:

- `-O0`
- `-g`
- `-DCHESS_VALIDATE_STATE`

Use this only for deep correctness debugging. It is much slower because it verifies that `doMove()` and `undo()` restore the complete position state after each recursive move.

### Windows x64 cross-build

Build Windows 64-bit release binaries from Linux:

```bash
make windows64
```

This builds under `build/win64/`:

- `perft.exe`
- `perft_diag.exe`
- `engine_tests.exe`
- `chilo.exe`
- `selfplay_collect.exe`
- `eval_fen.exe`

These targets use the MinGW-w64 POSIX cross-compiler and try to produce self-contained `.exe` files.
They are also stripped at link time to keep the shipped binaries smaller.

Build Windows 64-bit AVX2 release binaries from Linux:

```bash
make windows64-avx2
```

This builds under `build/win64-avx2/`. These `.exe` files require an AVX2-capable CPU.

## Run

### Perft CLI

```bash
build/release/perft "<fen>" <depth> [divide]
```

Examples:

```bash
build/release/perft "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1" 5
build/release/perft "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1" 2 divide
```

The output includes:

- node count per depth
- elapsed time
- nodes per second

### Divide diagnostics

Use the diagnostic helper to print sorted divide counts at any node reachable by a legal UCI move path:

```bash
build/release/perft_diag "<fen>" <depth> [move1,move2,...]
```

Examples:

```bash
build/release/perft_diag "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8" 2
build/release/perft_diag "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8" 2 c4f7
build/release/perft_diag "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8" 2 c4f7,e8f7
```

This is intended for isolating a bad subtree by comparing one branch at a time against a trusted reference.

### UCI Engine

Run the UCI engine:

```bash
build/release/chilo
```

Optional command-line helpers:

```bash
build/release/chilo --weights /path/to/weights.bin
build/release/chilo --version
```

If no explicit `--weights` path is given, `chilo` checks for a same-basename `.bin` sidecar in the executable directory, for example `chilo.exe` -> `chilo.bin`.

Supported commands:

- `uci`
- `isready`
- `ucinewgame`
- `position startpos moves ...`
- `position fen <fen> moves ...`
- `go depth N`
- `go movetime N`
- `go wtime WT btime BT [winc WI] [binc BI] [movestogo MTG]`
- `stop`
- `quit`

Current engine behavior:

- legal-move filtering on top of the existing pseudo-legal generator
- compact 4-byte `Move` representation
- Tiny NNUE evaluation with generated fallback weights from `generated/`
- optional runtime NNUE `.bin` loading with the same feature contract and arbitrary hidden size
- generated NNUE exports use configurable scaled integer quantization; the chosen scales and hidden size are recorded in `generated/generated_nnue_manifest.json`
- NNUE perspectives are active/passive (side to move / opponent), not fixed white/black
- iterative-deepening negamax alpha-beta
- transposition table with hash-based cutoffs and TT-move ordering
- TT probe before the quiescence handoff so deeper stored entries can skip frontier QS
- killer/history quiet-move ordering plus SEE-based capture bucketing
- PVS, null-move pruning, 3-tier LMR, and futility pruning through depth 3
- repetition-draw detection in main search and 50-move draw detection in main search + QS
- quiescence search with SEE-filtered captures and MVV-LVA ordering
- no UCI `setoption` options yet

### Self-Play Collection

`selfplay_collect` reads one FEN per line, runs self-play from each start position, and writes `eval_fen,score,result` rows.

Example:

```bash
build/release/selfplay_collect \
  --fen-file data/start.fen \
  --output data/selfplay.csv \
  --depth 6 \
  --games-per-fen 1
```

Important behavior:

- it records evaluated leaf positions rather than the root position
- it skips noisy leaves that are terminal or in check
- it refuses to overwrite an existing output or debug-output file
- if `--seed` is omitted, it uses a time/process-derived RNG seed and prints it at startup
- it uses exact all-root scores only during the opening stochastic sampling window (`--sample-plies`)
- after that window it returns to normal root PVS and records only the chosen move's evaluated leaf
- it prints periodic progress lines with games, collected samples, elapsed time, rate, and ETA

### Eval CLI

Evaluate one or more FENs directly with the compiled engine:

```bash
build/release/eval_fen "4k3/8/8/8/8/8/8/3QK3 w - - 0 1"
build/release/eval_fen --weights /path/to/weights.bin "4k3/8/8/8/8/8/8/3QK3 w - - 0 1"
```

Like `chilo`, `eval_fen` also checks for a same-basename sidecar `.bin` if no explicit `--weights` path is given.

### Tests

Run the optimized test binary:

```bash
build/release/engine_tests
```

Run the validation test binary:

```bash
build/validate/engine_tests_validate
```

### Search Benchmarking

Compare two UCI binaries at a fixed search depth:

```bash
python3 scripts/benchmark_fixed_depth.py \
  --baseline /path/to/old/chilo \
  --candidate /path/to/new/chilo \
  --depth 6 \
  --runs 5 \
  --warmups 1 \
  --output-dir /tmp/chilo-bench/results
```

### Fastchess SPRT

Use `scripts/run_fastchess_sprt.py` to run resumable two-engine SPRT matches through `fastchess`.
Most fixed settings live in a JSON config; command-line options usually only select the two engines, optional runtime NNUE nets, names, run directory, and SPRT profile.

Start from the example config:

```bash
cp scripts/fastchess_sprt_config.example.json /tmp/chilo-sprt-config.json
```

Then edit paths and common match settings in that copy.

Example dry-run:

```bash
python3 scripts/run_fastchess_sprt.py \
  --config /tmp/chilo-sprt-config.json \
  --run-dir /tmp/chilo-sprt/g2t1-vs-base \
  --engine-a build/release-avx2/chilo \
  --engine-b build/release-avx2/chilo \
  --net-a /path/to/base.bin \
  --net-b /path/to/candidate.bin \
  --name-a base \
  --name-b candidate \
  --sprt normal \
  --dry-run
```

Remove `--dry-run` to start the match. The run directory is created if needed and uses fixed filenames:

- `fastchess_state.json` for fastchess autosave/resume state
- `games.pgn` for PGN output when enabled in the config
- `fastchess.log` for fastchess logs when enabled in the config
- `fastchess_command.json` for the exact command and resolved inputs

By default, the wrapper resumes when `fastchess_state.json` exists and starts a new run otherwise. Use `--new` to require a fresh run, `--resume` to require an existing state file, or `--force-new` to archive old run files and start over.

### NNUE Python Workflow

Create the local Python environment with CPU-only PyTorch:

```bash
make python-env
source .venv/bin/activate
```

For raw collector outputs, optional exact-row dedup is handled as a separate external-sort step:

```bash
.venv/bin/python scripts/dedup_training_csv.py \
  --input data/run1.csv data/run2.csv \
  --output data/merged-dedup.csv \
  --sort-buffer-size 50% \
  --overwrite
```

This keeps dedup outside the trainer/preprocessor and scales better for large multi-file corpora. It removes only exact duplicate `eval_fen,score,result` rows; it does not collapse positions by FEN alone.

Preprocess one or more collector CSV files into a sharded dataset:

```bash
.venv/bin/python scripts/prepare_nnue_dataset.py \
  --input data/run1.csv data/run2.csv \
  --output-dir data/nnue_dataset \
  --samples-per-shard 1000000 \
  --validation-fraction 0.05 \
  --overwrite
```

The preprocessor accepts both normal headered collector CSVs and headerless `sort | uniq` outputs that still have raw `eval_fen,score,result` rows.

Train the current tiny NNUE on the sharded dataset:

```bash
.venv/bin/python scripts/train_nnue.py \
  --dataset data/nnue_dataset \
  --output-dir data/nnue_training \
  --epochs 8 \
  --batch-size 256 \
  --hidden-size 64
```

The default hidden size comes from `scripts/nnue_contract.json` and is currently `64`. Prepared datasets are feature caches and are not tied to a hidden size; checkpoints and exported weights are.

Export the best checkpoint back into generated C++ fallback weights and/or a runtime-loadable `.bin`:

```bash
.venv/bin/python scripts/export_nnue.py \
  --checkpoint data/nnue_training/best.pt \
  --dataset-dir data/nnue_dataset \
  --validation-samples 256 \
  --tolerance 256 \
  --output-header generated/generated_nnue_weights.h \
  --output-manifest generated/generated_nnue_manifest.json \
  --output-bin data/nnue_training/weights.bin
```

Run the Python smoke tests and the end-to-end training/export/C++ verification:

```bash
make nnue-python-tests
make nnue-verify
```

For repeated operator runs, use the orchestration wrapper instead of typing each phase manually:

```bash
.venv/bin/python scripts/run_nnue_workflow.py \
  --input /tmp/chilo-uniq.csv \
  --output-root /tmp/chilo-train1 \
  --dedup-mode none \
  --samples-per-shard 1000000 \
  --epochs 2 \
  --batch-size 256 \
  --device cpu
```

It can also:

- reuse an existing prepared dataset via `--dataset`
- run exact-row dedup first via `--dedup-mode exact-row`
- export to custom locations via `--output-header` / `--output-manifest`
- temporarily swap the generated engine weights and run `engine_tests_debug` via `--verify-engine`

The workflow wrapper defaults to a looser export drift tolerance (`--tolerance 256`) than the low-level exporter so short real-data training runs can still complete a first quantized export.

`make nnue-verify` uses the current default parity positions:
- `startpos`
- one complex middlegame
- one tactical position

To benchmark the alternate TT replacement policy, rebuild with:

```bash
make clean
make EXTRA_CPPFLAGS=-DCHILO_TT_ALWAYS_OVERWRITE=1
```

## Common Targets

```bash
make                 # optimized release binaries plus release tests
make release-avx2    # optimized Linux binaries requiring AVX2
make debug           # debug binaries
make validate        # debug binaries with full state validation
make windows64       # Windows x64 release binaries (.exe) via MinGW-w64
make windows64-avx2  # Windows x64 release binaries (.exe) requiring AVX2
make selfplay_collect # build only the release self-play collector
make clean           # remove build artifacts
```

## Notes

- Use `build/release/perft` for benchmarking.
- Use `build/release-avx2/chilo` or `build/win64-avx2/chilo.exe` only on AVX2-capable machines.
- Use `scripts/benchmark_fixed_depth.py` when comparing fixed-depth search speed between engine versions.
- Use `scripts/run_fastchess_sprt.py` for longer fastchess SPRT tests between versions or runtime NNUE nets.
- Use `build/debug/perft_debug` for ordinary debugging.
- Use `build/validate/perft_validate` only when investigating `doMove()` / `undo()` state corruption or move-generation bugs.
- Use `build/release/chilo` or `build/validate/chilo_validate` when testing UCI integration or shallow playing strength.
- Use `file build/win64/chilo.exe` after `make windows64` if you want a quick confirmation that the output is a PE32+ Windows binary.
- Use `file build/win64-avx2/chilo.exe` after `make windows64-avx2` for the AVX2 Windows binary.
