# Chilo Perft

Small chess perft driver and test suite used to validate move generation and measure search performance.

## Files

- `chess.h`: chess position, move generation, move execution/undo, perft
- `perft.cpp`: CLI entry point for running perft
- `perft_diag.cpp`: subtree divide helper for isolating perft mismatches
- `perft_tests.cpp`: regression-style test program
- `engine_development_notes.md`: implementation history, findings, and performance notes
- `Makefile`: build targets for optimized, debug, and validation builds

## Build

The project uses `g++` and `make`.

### Optimized build

Build the fast binaries used for normal perft runs:

```bash
make
```

This builds:

- `perft`
- `perft_diag`
- `perft_tests`

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
- `perft_tests_debug`

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
- `perft_tests_validate`

These targets use:

- `-O0`
- `-g`
- `-DCHESS_VALIDATE_STATE`

Use this only for deep correctness debugging. It is much slower because it verifies that `doMove()` and `undo()` restore the complete position state after each recursive move.

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

### Tests

Run the optimized test binary:

```bash
./perft_tests
```

Run the validation test binary:

```bash
./perft_tests_validate
```

## Common Targets

```bash
make                 # optimized perft + diagnostics + tests
make debug           # debug binaries
make validate        # debug binaries with full state validation
make clean           # remove build artifacts
```

## Notes

- Use `perft` for benchmarking.
- Use `perft_debug` for ordinary debugging.
- Use `perft_validate` only when investigating `doMove()` / `undo()` state corruption or move-generation bugs.
