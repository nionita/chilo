# Chilo

Small chess engine project with:

- a perft driver and diagnostics for move-generation validation
- a minimal evaluation and alpha-beta search
- a basic UCI engine binary for GUI integration

## Files

- `engine.h`: public engine API
- `attack.cpp`, `movegen.cpp`, `make_unmake.cpp`, `perft_lib.cpp`: move-generation and perft core
- `eval.cpp`: static evaluation
- `search.cpp`: iterative-deepening alpha-beta search
- `chilo.cpp`: UCI engine binary entry point
- `perft.cpp`: CLI entry point for running perft
- `perft_diag.cpp`: subtree divide helper for isolating perft mismatches
- `engine_tests.cpp`: regression-style test program for engine behavior
- `scripts/benchmark_fixed_depth.py`: fixed-depth UCI benchmark helper for comparing two binaries
- `engine_development_notes.md`: implementation history, findings, and performance notes
- `Makefile`: build targets for optimized, debug, and validation builds

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

This builds:

- `perft`
- `perft_diag`
- `engine_tests`
- `chilo`

These targets use:

- `-O3`
- `-DNDEBUG`

That means assertions are disabled and the binaries are suitable for performance measurement.

### Debug build

Build non-optimized binaries with debug symbols:

```bash
make debug
```

This builds:

- `perft_debug`
- `perft_diag_debug`
- `engine_tests_debug`
- `chilo_debug`

These targets use:

- `-O0`
- `-g`

Use this when debugging logic or stepping through the code.

### Validation build

Build binaries with the expensive full-state restoration check enabled:

```bash
make validate
```

This builds:

- `perft_validate`
- `perft_diag_validate`
- `engine_tests_validate`
- `chilo_validate`

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

This builds:

- `perft.exe`
- `perft_diag.exe`
- `engine_tests.exe`
- `chilo.exe`

These targets use the MinGW-w64 POSIX cross-compiler and try to produce self-contained `.exe` files.
They are also stripped at link time to keep the shipped binaries smaller.

## Run

### Perft CLI

```bash
./perft "<fen>" <depth> [divide]
```

Examples:

```bash
./perft "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1" 5
./perft "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1" 2 divide
```

The output includes:

- node count per depth
- elapsed time
- nodes per second

### Divide diagnostics

Use the diagnostic helper to print sorted divide counts at any node reachable by a legal UCI move path:

```bash
./perft_diag "<fen>" <depth> [move1,move2,...]
```

Examples:

```bash
./perft_diag "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8" 2
./perft_diag "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8" 2 c4f7
./perft_diag "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8" 2 c4f7,e8f7
```

This is intended for isolating a bad subtree by comparing one branch at a time against a trusted reference.

### UCI Engine

Run the UCI engine:

```bash
./chilo
```

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
- material plus piece-square-table evaluation, with non-king PST as a small correction term
- iterative-deepening negamax alpha-beta
- transposition table with hash-based cutoffs and TT-move ordering
- TT probe before the quiescence handoff so deeper stored entries can skip frontier QS
- killer/history quiet-move ordering
- PVS, null-move pruning, LMR, and shallow futility pruning
- repetition-draw detection in main search and 50-move draw detection in main search + QS
- quiescence search with MVV-LVA ordering in QS
- no UCI options yet

### Tests

Run the optimized test binary:

```bash
./engine_tests
```

Run the validation test binary:

```bash
./engine_tests_validate
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

If no custom positions are provided, the script uses the current default set:
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
make                 # optimized perft + diagnostics + tests
make debug           # debug binaries
make validate        # debug binaries with full state validation
make windows64       # Windows x64 release binaries (.exe) via MinGW-w64
make clean           # remove build artifacts
```

## Notes

- Use `perft` for benchmarking.
- Use `scripts/benchmark_fixed_depth.py` when comparing fixed-depth search speed between engine versions.
- Use `perft_debug` for ordinary debugging.
- Use `perft_validate` only when investigating `doMove()` / `undo()` state corruption or move-generation bugs.
- Use `chilo` or `chilo_validate` when testing UCI integration or shallow playing strength.
- Use `file chilo.exe` after `make windows64` if you want a quick confirmation that the output is a PE32+ Windows binary.
