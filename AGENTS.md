# Chess Engine Status Summary

## Goal

The project started as a perft-focused move-generation testbed. It now has a first playable-engine slice on top of that foundation: static evaluation, iterative-deepening alpha-beta search, and a basic UCI binary.

Completed goals included:
1. Implementing `perftDivide` to show individual move counts
2. Finding and fixing move-generation and undo-state bugs with perft regression testing
3. Adding assertions and full-state restoration checks
4. Refactoring the engine into a small public API plus `.cpp` implementation files
5. Adding a baseline evaluation/search/UCI path without disturbing the existing perft tools

## Instructions

- `engine.h` is now the public engine API header
- Engine implementation has been split across `.cpp` files and linked into the CLI/test programs
- `chess.h` remains only as a compatibility umbrella include
- Perft correctness and state-restoration validation remain the primary regression gate
- `chilo` is now the separate UCI executable for engine integration

## Discoveries

1. **Bug #11 - Black Promotion**: Promotion move generation always used WHITE pieces (`W_QUEEN`, `W_ROOK`, etc.) regardless of which side was was to move. Fixed by using `us == WHITE ? W_QUEEN : B_QUEEN`, etc.

2. **Bug in undo()**: The position equality assertion revealed `undo()` was not restoring:
   - `halfMove` counter
   - `fullMove` counter
   - `enPassant` square
   Fixed by passing original values to undo and restoring them

3. **perftDivide bug**: Original implementation only ran depth 1 when divide flag was set, fixed to run requested depth

## Accomplished

- ✅ Implemented perftDivide feature with UCI move format output
- ✅ Fixed black promotion bug (Bug #11)
- ✅ Fixed undo() restoration bugs
- ✅ Added 5 input validation assertions (doMove coordinates, attacked square, undo coordinates, FEN validation, promotion piece)
- ✅ Added positionsEqual() function to compare full position state
- ✅ Added position restoration assertion in perft/perftDivide loops
- ✅ All 5 standard perft positions now pass (depths 1-5)
- ✅ Updated engine_development_notes.md with findings
- ✅ Refactored stable engine code out of `chess.h` into private headers to keep active work focused
- ✅ Split engine implementation into translation units: `attack.cpp`, `movegen.cpp`, `make_unmake.cpp`, `perft_lib.cpp`
- ✅ Added `engine.h` as the declarations-only engine interface
- ✅ Updated the `Makefile` to compile and link shared engine object files
- ✅ Added `eval.cpp` with material + piece-square-table evaluation, later rescaled so non-king PST stays a small correction term
- ✅ Added `search.cpp` with legal-move helpers, terminal detection, and iterative-deepening alpha-beta
- ✅ Added incremental Zobrist hashing to `Position` / `UndoState` for hash-based search features
- ✅ Added a transposition table with TT-move ordering and mate-score normalization
- ✅ TT probe now happens before the quiescence handoff, and TT replacement policy can be benchmarked via `EXTRA_CPPFLAGS=-DCHILO_TT_ALWAYS_OVERWRITE=1`
- ✅ Added killer/history move ordering, PVS, null-move pruning, LMR, and shallow futility pruning
- ✅ Added practical draw handling for repetition and the 50-move rule, including real-game hash history from UCI `position ... moves ...`
- ✅ Added SEE-based capture classification for main-search ordering and non-check QS filtering
- ✅ Added `chilo.cpp` with support for `uci`, `isready`, `ucinewgame`, `position`, `go depth`, `go movetime`, clock-based `go` limits, `stop`, and `quit`
- ✅ Compacted `Move` from 16 bytes to 4 bytes while keeping the existing semantics and most call sites unchanged
- ✅ Added `scripts/benchmark_fixed_depth.py` for repeatable fixed-depth UCI benchmarks between two engine binaries
- ✅ Added `make windows64` for MinGW-w64-based Windows x64 release builds alongside the existing Linux targets
- ✅ Windows x64 `.exe` outputs are now stripped static builds for simpler shipping with smaller file size

## Relevant files / directories

```
/home/nicu/Sources/chilo/
├── engine.h               # Public engine API declarations
├── chess.h                # Compatibility umbrella include for existing code
├── chess_position.h       # Stable position/types layer: Piece/Color/Move/UndoState/Position, helpers, FEN, UCI, validation
├── chess_tables.h         # Stable attack-table layer: knight/king/pawn tables, magic constants, magic lookup setup
├── attack.cpp             # attacked(), inCheck()
├── movegen.cpp            # move generation implementation
├── make_unmake.cpp        # doMove()/undo()
├── perft_lib.cpp          # perft()/perftDivide()
├── eval.cpp               # Static evaluation
├── search.cpp             # Search + legal move helpers
├── chilo.cpp              # UCI engine binary
├── perft.cpp              # CLI for perft testing with divide option
├── perft_diag.cpp         # Divide/debug helper for drilling into specific move paths
├── engine_tests.cpp       # Test suite for perft, legal-move helpers, eval, search, and UCI-related scenarios
├── scripts/               # Benchmark and other helper scripts
└── engine_development_notes.md # Documentation of bugs found, fixes, structure, and performance notes
```

## Interface map

- `engine.h` is the main header to include for engine behavior.
- `chess.h` is only a compatibility wrapper around `engine.h`.
- `chess_position.h` contains code that is relatively stable:
  - core enums and structs
  - square/piece helpers
  - position mutation helpers (`initPosition`, `addPiece`, `removePiece`, `movePiece`)
  - representation validation (`bitboardsConsistent`, `representationConsistent`, `positionsEqual`)
  - castling-right packing helpers
  - `parseFEN()` and `moveToUCI()`
- `chess_tables.h` contains code that is relatively stable:
  - `AttackTables`
  - checked-in rook/bishop magic constants and shifts
  - attack-table construction
  - magic lookup helpers (`rookAttacks`, `bishopAttacks`)
- Engine behavior now lives in `.cpp` files:
  - `attack.cpp`
  - `movegen.cpp`
  - `make_unmake.cpp`
  - `perft_lib.cpp`
  - `eval.cpp`
  - `search.cpp`

This means future engine features should normally be implemented as additional `.cpp` files behind `engine.h`, while the private headers can usually be ignored unless the task touches representation setup or attack-table internals. The separate `chilo` binary is now the right place for UCI/protocol-facing work.

## What's next

Recent work moved the engine to a bitboard-first runtime with magic bitboards for sliders and then split the implementation into proper translation units so the project can grow beyond perft without relying on a monolithic implementation header.

Potential areas for future work:
- Richer evaluation
- Stronger UCI support (`setoption`, ponder, `go infinite`)
- Windows debug/validate target parity if it becomes useful
