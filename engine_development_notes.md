# Engine Development Notes

This project is a small chess perft driver used to validate move generation, debug legality issues, and measure search performance while the engine core evolves.

## Current Structure

- `chess.h`: position representation, move generation, attack detection, move execution/undo, perft
- `perft.cpp`: CLI for running perft and perft divide
- `perft_tests.cpp`: lightweight regression test program
- `Makefile`: build targets for optimized, debug, and validation builds
- `README.md`: build and usage guide

## Build Modes

The recommended build entry point is `make`.

- `make`: optimized `perft` and `perft_tests` using `-O3 -DNDEBUG`
- `make debug`: `perft_debug` and `perft_tests_debug` using `-O0 -g`
- `make validate`: `perft_validate` and `perft_tests_validate` using `-O0 -g -DCHESS_VALIDATE_STATE`

`CHESS_VALIDATE_STATE` enables an expensive full-state restoration check after every `doMove()` / `undo()` pair. It is useful for debugging but not for benchmarking.

## CLI Features

Usage:

```bash
./perft "<fen>" <depth> [divide]
```

Capabilities:

- perft totals for each depth from `1..N`
- divide output in UCI move format
- elapsed wall-clock time for each reported depth
- nodes-per-second (NPS) reporting

Example:

```bash
$ ./perft "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1" 2
Depth 1: 20 (1.0567e-05 s, 4163906 nps)
Depth 2: 400 (0.000157677 s, 9424329 nps)
```

## Major Development Findings

### Correctness bugs that were fixed

1. Black promotions originally created white pieces.
2. `undo()` originally failed to restore `halfMove`, `fullMove`, and `enPassant`.
3. Perft legality checking originally used the wrong side after `doMove()`.
4. Multiple move-generation issues were fixed around FEN parsing, pawn direction, en passant, castling path checks, rook presence for castling, and king-capture prevention.

### Validation work

- Added assertions for move bounds, attacked-square inputs, and promotion sanity.
- Added full-position restoration validation to catch `doMove()` / `undo()` mismatches.
- After the position representation was optimized, the heavy restore check was moved behind `CHESS_VALIDATE_STATE` because running it at every recursive node made perft dramatically slower.

### Performance work

The initial representation scanned all 64 squares for move generation and found kings by rescanning the board in `inCheck()`.

The current version improves that by:

- caching king squares in `Position`
- keeping piece-lists plus square-to-list indices
- generating moves into a fixed stack buffer instead of allocating `std::vector<Move>` at every node
- iterating the active side's actual pieces instead of scanning all 64 squares

This keeps the simple board-array model while removing several obvious hot-path costs.

## Test Status

Current regression checks in `perft_tests` pass for:

- mirror-position comparisons
- color-flip sanity
- basic en passant sanity
- castling move generation counts
- legal-move filtering through check detection

Reference perft totals currently match for the standard positions already exercised by the existing tests, including:

- starting position through depth 5
- kiwipete through depth 4
- position 3 through depth 5
- position 4 through depth 4

One known issue remains:

- position 5 at depth 5 is still high by `12,283` nodes (`89,953,477` vs expected `89,941,194`)

That discrepancy predates the performance refactor and still needs separate investigation.

## Recommended Workflow

- Use `make` and `./perft` for benchmarking.
- Use `make debug` when stepping through logic.
- Use `make validate` only when chasing state-corruption or move-restoration bugs.
- Treat perft node-count correctness as the gate before trusting any performance result.
