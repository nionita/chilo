# Engine Development Notes

This project started as a small chess perft driver used to validate move generation, debug legality issues, and measure search performance while the engine core evolved. It now also includes a minimal playable engine loop with static evaluation, alpha-beta search, and a UCI interface.

## Current Structure

- `engine.h`: public engine interface for attack detection, move generation, move execution/undo, and perft
- `attack.cpp`: attack detection and check queries
- `movegen.cpp`: pseudo-legal move generation
- `make_unmake.cpp`: move execution and undo
- `perft_lib.cpp`: perft and perft divide library logic
- `eval.cpp`: static evaluation
- `search.cpp`: iterative-deepening alpha-beta search
- `chilo.cpp`: UCI engine front-end
- `chess.h`: compatibility umbrella that includes `engine.h`
- `chess_position.h`: stable position/types layer, FEN parsing, UCI formatting, and representation validation
- `chess_tables.h`: stable precomputed attack-table layer, including magic constants and slider lookup setup
- `perft.cpp`: CLI for running perft and perft divide
- `perft_diag.cpp`: subtree divide helper for debugging against external references
- `engine_tests.cpp`: lightweight regression test program
- `scripts/benchmark_fixed_depth.py`: helper for fixed-depth search benchmarks between two UCI binaries
- `Makefile`: build targets for optimized, debug, and validation builds
- `README.md`: build and usage guide

## Build Modes

The recommended build entry point is `make`.

- `make`: optimized `perft`, `engine_tests`, and `chilo` using `-O3 -DNDEBUG`
- `make debug`: `perft_debug`, `engine_tests_debug`, and `chilo_debug` using `-O0 -g`
- `make validate`: `perft_validate`, `engine_tests_validate`, and `chilo_validate` using `-O0 -g -DCHESS_VALIDATE_STATE`
- `make windows64`: cross-compiled Windows x64 release `.exe` binaries using MinGW-w64 POSIX tools

`CHESS_VALIDATE_STATE` enables an expensive full-state restoration check after every `doMove()` / `undo()` pair. It is useful for debugging but not for benchmarking.

Windows x64 cross-build prerequisites on Ubuntu:

```bash
sudo apt update
sudo apt install gcc-mingw-w64-x86-64-posix g++-mingw-w64-x86-64-posix
```

The Windows release target links statically and strips symbols at link time so the shipped `.exe` files stay self-contained without being larger than necessary.

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

UCI engine usage:

```bash
./chilo
```

Supported UCI commands:

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
- storing `Move` in a compact 4-byte representation
- maintaining parallel bitboards and occupancy masks
- using bitboards for attack detection and move generation
- using occupancy and piece masks instead of square-array reads for more hot-path attack and move-generation checks
- precomputing slider rays and pawn push/promotion data to reduce repeated inner-loop square arithmetic
- keeping `board[64]` only as a validation/debug mirror while normal builds run from bitboards and metadata

This keeps move making and debugging simple while shifting the hot path onto bitboards.

### Source layout cleanup

After the bitboard and magic-bitboard work stabilized, the engine was split so future work does not need to keep all engine logic in a single header:

- `chess_position.h` now holds the low-churn representation layer and helper utilities
- `chess_tables.h` now holds the large, low-churn attack-table and magic-bitboard setup
- `engine.h` now declares the engine API used by frontends and tests
- `attack.cpp`, `movegen.cpp`, `make_unmake.cpp`, and `perft_lib.cpp` now hold the engine implementation
- `chess.h` remains as a compatibility include for existing entrypoints

This is still a maintenance refactor, but it also establishes proper translation-unit boundaries for future engine work. The project no longer compiles each executable from a single implementation header; instead, the frontends link shared engine object files built from the new `.cpp` units.

### First engine-play feature slice

The next project step after the source split was to add a minimal engine loop without overcommitting to advanced search features. That slice now exists:

- `eval.cpp` provides a cheap deterministic evaluation based on material and piece-square tables
- `search.cpp` provides legal-move generation helpers, terminal-state detection, and iterative-deepening negamax alpha-beta search
- `chilo.cpp` exposes the engine through a separate UCI binary so GUI integration does not interfere with the perft tools

This is intentionally a baseline engine only. It does not yet include quiescence, a transposition table, repetition detection, or UCI options.

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

Status: further advanced. Piece-list storage and maintenance were removed from runtime state, and `board[64]` is now retained only in validation builds as a mirrored debug representation while normal builds run board-less. Validation still focuses on representation integrity and exact undo restoration.

### Recommended next implementation step

The safest first steps were to add parallel bitboards, then convert `attacked()`, then convert `genMoves()` while keeping validation parity checks. Those are now in place, piece-list maintenance has been removed, the transitional slow reference generators are gone, and normal builds now run without stored square-array state.

The next useful work is still performance-focused, but the first profiling-driven recovery step is now implemented. `gprof` showed the old `rayAttacked()` wrapper fanout consuming about half of sampled runtime, so the slider portion of `attacked()` was rewritten to:

- precompute rook-or-queen and bishop-or-queen attacker unions once per call
- replace eight `rayAttacked()` calls with two direct helpers for rook-like and bishop-like directions

On the reference benchmark FEN
`rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8`
at depth 5, that change improved performance from roughly `8.20 s` / `10.97M nps` to `4.21923 s` / `21.316989M nps`.

The next profiling-guided refinement adds a maintained `pieceAtSquare[64]` cache in all builds. Bitboards remain authoritative for attack detection and move generation, but move making, undo, and perft capture bookkeeping no longer identify square contents by scanning all piece bitboards. Validation now checks that this cache, the occupancy masks, and the piece bitboards stay in sync. On the same reference FEN at depth 5, that change improved performance again to `3.27296 s` / `27.480038M nps`.

The next cleanup pass moved pre-move restoration data into a compact `UndoState` filled by `doMove()` and consumed by `undo()`. That simplified callers in perft, diagnostics, and tests, and removed repeated caller-side save/restore boilerplate. It preserved correctness, but on the same reference FEN at depth 5 it was effectively neutral to slightly slower at `3.31075 s` / `27.166374M nps`, so this change should be treated as an API/maintenance improvement rather than a confirmed speed win.

The next measured pass targeted sliding move generation by replacing the old generic ray-masking path with direct directional emission. It preserved correctness, but it regressed the same reference FEN benchmark to `3.50684 s` / `25.647377M nps`, so that approach is not a speed win in its current form and should not be treated as the preferred slider path without another profiling pass.

The next slider pass replaced both ray-based slider attack detection and slider move generation with magic-bitboard lookups using checked-in precomputed magic constants. The runtime tables are built once from those committed constants during static initialization. On the same reference FEN at depth 5, that change improved performance to `2.69737 s` / `33.344056M nps`, making it clearly faster than both the ray-scan path and the best recent pre-magic baseline.

The next maintenance pass moved the mutable engine implementation out of headers into separate source files. `engine.h` now provides the public interface, while `attack.cpp`, `movegen.cpp`, `make_unmake.cpp`, and `perft_lib.cpp` contain the implementation used by `perft`, `perft_diag`, and tests. `chess_position.h` and `chess_tables.h` remain header-defined for their small helper functions, but those helpers are now explicitly `inline` so the project links cleanly across multiple translation units.

The next representation pass compacted `Move` from 16 bytes down to 4 bytes by shrinking `Piece` and `Color` to byte-sized enums and packing the move flags. A fixed-depth search benchmark against the previous commit used one warm-up plus five measured `go depth 6` runs on `startpos`, one middlegame, and one tactical position. That benchmark showed the compact move to be effectively neutral: about `+0.17%` NPS on `startpos`, `+1.43%` NPS on the middlegame, and `0%` on the tactical position. The change is therefore reasonable to keep for data compactness and future transposition-table work, but it should not be treated as a confirmed speed breakthrough on its own.

To support that investigation, the project now includes a separate `perft_diag` helper that can:

- print sorted divide counts at the root or at any descendant reached by a legal UCI move path
- validate that each requested path move is legal before descending
- make it practical to compare one subtree at a time against an external trusted reference

## Test Status

Current regression checks in `engine_tests` pass for:

- mirror-position comparisons
- color-flip sanity
- basic en passant sanity
- castling move generation counts
- legal-move filtering through check detection
- build/link correctness across multiple translation units through the shared engine object-file build
- FEN halfmove/fullmove parsing
- terminal-state helpers for checkmate and stalemate
- UCI move parsing/application helpers
- evaluation sign sanity
- shallow search preference for an obvious winning capture

Reference perft totals currently match for the standard positions already exercised by the existing tests, including:

- starting position through depth 5
- kiwipete through depth 4
- position 3 through depth 5
- position 4 through depth 4
- mirrored position 4 through depth 5

All five current reference perft positions now match through their exercised depths.

The recent ray-table and pawn-table cleanup preserved correctness, but it did not improve benchmark speed in its current form. Moving normal builds to a board-less runtime also preserved correctness but initially pushed the benchmark down to roughly 10.97M NPS on the current reference FEN. The first profiling-guided fix recovered that loss and more by simplifying slider attack detection, and the next measured step keeps the bitboard generator while reintroducing a cheap square cache for move-state queries. That reinforces that future tuning should be measurement-driven rather than assuming more abstraction is automatically faster in this codebase.

## Recommended Workflow

- Use `make` and `./perft` for benchmarking.
- Use `python3 scripts/benchmark_fixed_depth.py` for repeatable fixed-depth search benchmarks between two engine binaries.
- Use `make debug` when stepping through logic.
- Use `make validate` only when chasing state-corruption or move-restoration bugs.
- Use `make windows64` when you need Windows 64-bit `.exe` outputs from Linux.
- Treat perft node-count correctness as the gate before trusting any performance result.
- Add new engine features as `.cpp` files behind `engine.h` unless a helper is intentionally tiny and performance-critical enough to justify `inline` header placement.
- Use `./chilo` or `./chilo_validate` for UCI testing and shallow engine behavior checks.
