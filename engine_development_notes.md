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
5. Queenside castling originally checked only `c` and `d` for emptiness; it now correctly requires `b`, `c`, and `d` to be empty while only `e`, `d`, and `c` must be attack-free.

### Validation work

- Added assertions for move bounds, attacked-square inputs, and promotion sanity.
- Added full-position restoration validation to catch `doMove()` / `undo()` mismatches.
- After the position representation was optimized, the heavy restore check was moved behind `CHESS_VALIDATE_STATE` because running it at every recursive node made perft dramatically slower.

### Performance work

The initial representation scanned all 64 squares for move generation and found kings by rescanning the board in `inCheck()`.

The current version improves that by:

- caching king squares in `Position`
- generating moves into a fixed stack buffer instead of allocating `std::vector<Move>` at every node
- maintaining parallel bitboards and occupancy masks
- using bitboards for attack detection and move generation
- using occupancy and piece masks instead of square-array reads for more hot-path attack and move-generation checks
- precomputing slider rays and pawn push/promotion data to reduce repeated inner-loop square arithmetic
- keeping `board[64]` as helper/debug state while removing transitional piece-list maintenance

This keeps move making and debugging simple while shifting the hot path onto bitboards.

## Bitboard Migration Plan

Bitboards are the next major representation upgrade, but the migration should stay staged so the current board-array path remains available for debugging while correctness is preserved.

### Stage 1: Parallel bitboard state

- add 12 piece bitboards plus white, black, and combined occupancy bitboards to `Position`
- maintain them in `parseFEN()`, `addPiece()`, `removePiece()`, and `movePiece()`
- validate that board array, piece-lists, king squares, and bitboards describe the same position
- keep `attacked()` and `genMoves()` unchanged

Status: implemented.

### Stage 2: Bitboards as first-class move state

- ensure `doMove()` and `undo()` are validated explicitly against the new bitboard state for all move types
- use validation builds to catch any representation drift before attack generation changes

### Stage 3: Bitboard attack detection

- rewrite `attacked()` around bitboards and precomputed king/knight/pawn attack masks
- keep slider attacks simple at first, using occupancy-aware stepping rather than advanced tables

Status: implemented. Validation now relies on representation-consistency checks rather than parity against the old square-array attack logic.

### Stage 4: Bitboard move generation

- migrate `genMoves()` piece class by piece class to bit iteration
- keep the existing `Move` type and fixed move buffer interface
- remove dependence on piece-lists only after perft parity is stable

Status: implemented. Transitional move-set comparison against the old generator has been retired.

### Stage 5: Representation cleanup

- decide whether `board[64]` remains as debug/helper state or becomes validation-only
- remove piece-list maintenance if bitboards fully replace it

Status: further advanced. Piece-list storage and maintenance were removed from runtime state, `board[64]` remains as permanent helper/debug state, and validation now focuses on representation integrity and exact undo restoration instead of duplicate attack and move generators.

### Recommended next implementation step

The safest first steps were to add parallel bitboards, then convert `attacked()`, then convert `genMoves()` while keeping validation parity checks. Those are now in place, piece-list maintenance has been removed, the transitional slow reference generators are gone, and hot-path attack/move generation now leans more heavily on occupancy, piece masks, precomputed rays, and pawn tables. The next implementation step should be either a larger board-less runtime refactor or a later performance-focused pass that measures and selectively reworks the bitboard helpers that still regress NPS.

To support that investigation, the project now includes a separate `perft_diag` helper that can:

- print sorted divide counts at the root or at any descendant reached by a legal UCI move path
- validate that each requested path move is legal before descending
- make it practical to compare one subtree at a time against an external trusted reference

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
- mirrored position 4 through depth 5

All five current reference perft positions now match through their exercised depths.

The recent ray-table and pawn-table cleanup preserved correctness, but it did not improve benchmark speed in its current form. That means future work should treat performance tuning as a separate measurement-driven pass rather than assuming more bitboard abstraction is automatically faster in this codebase.

## Recommended Workflow

- Use `make` and `./perft` for benchmarking.
- Use `make debug` when stepping through logic.
- Use `make validate` only when chasing state-corruption or move-restoration bugs.
- Treat perft node-count correctness as the gate before trusting any performance result.
