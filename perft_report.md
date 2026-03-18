# Perft Implementation Report

## Current State

### Compilation
- Release: `g++ -O2 -o perft perft.cpp`
- Debug: `g++ -O0 -g -o perft perft.cpp` (enables assert checks)

### Usage
```bash
./perft "<fen>" <depth>
```

### Test Results (After All Fixes)

| Position | Depth 1 | Depth 2 | Depth 3 | Depth 4 | Depth 5 |
|----------|---------|---------|---------|---------|---------|
| **1. Starting Position** (`rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1`) |
| Expected | 20 | 400 | 8902 | 197281 | 4865609 |
| Actual | 20 ✓ | 400 ✓ | 8902 ✓ | 197281 ✓ | - |
| **Position 2** (`8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1`) |
| Expected | 14 | 191 | 2812 | 43238 | 674624 |
| Actual | 14 ✓ | 191 ✓ | 2812 ✓ | 43238 ✓ | - |
| **Position 3** (`r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1`) |
| Expected | 6 | 264 | 9467 | 422333 | 15833292 |
| Actual | 6 ✓ | 264 ✓ | 9566 | 417443 | - |
| Diff | 0 | 0 | +99 | -4890 | - |
| **Position 4** (`r2q1rk1/pP1p2pp/Q4n2/bbp1p3/Np6/1B3NBn/pPPP1PPP/R3K2R b KQ - 0 1`) |
| Expected | 6 | 264 | 9467 | 422333 | 15833292 |
| Actual | 6 ✓ | 264 ✓ | 9467 ✓ | 423461 | - |
| Diff | 0 | 0 | 0 | +1128 | - |
| **Position 5** (`rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8`) |
| Expected | 44 | 1486 | 62379 | 2103487 | 89941194 |
| Actual | 44 ✓ | 1486 ✓ | 62379 ✓ | - | - |

## Refactoring Complete

### Files:

1. **chess.h** - Shared chess engine library containing all common logic
2. **perft.cpp** - Main program (includes chess.h + main())
3. **perft_tests.cpp** - Test suite (5 tests)

## Bugs Fixed

### 1. FEN Parser (parseFEN)
Original code started from position 0 (a1) but FEN notation starts from rank 8 (a8).
- Fixed: Changed to `int rank = 7, file = 0;` with proper rank/file tracking

### 2. Pawn Direction (genMoves)
Original: `dir = us == WHITE ? -1 : 1` (white moves toward rank 0)
- Fixed: `dir = us == WHITE ? 1 : -1` (white moves toward rank 7)

### 3. Check Detection (perft)
Original: `inCheck(pos, pos.sideToMove)` checked after doMove() swapped sideToMove
- Fixed: Save color before doMove: `Color us = pos.sideToMove;`

### 4. Castling Rank (genMoves)
Original: `int kr = us == WHITE ? 7 : 0` (backwards)
- Fixed: `int kr = us == WHITE ? 0 : 7`

### 5. En Passant Square (doMove)
Original: `int epR = pos.sideToMove == WHITE ? R(mv.from) - 1 : R(mv.from) + 1`
- Fixed: `int epR = pos.sideToMove == WHITE ? R(mv.from) + 1 : R(mv.from) - 1`
- White pawn from rank 1→3 should set EP at rank 2, not rank 0

### 6. En Passant Capture (doMove)
Original: `capR = pos.sideToMove == WHITE ? epR + 1 : epR - 1` (wrong direction)
- Fixed: `capR = pos.sideToMove == WHITE ? epR - 1 : epR + 1`

### 7. En Passant Capture (undo)
Same bug as #6 - fixed with same correction.

### 8. Queenside Castling Path (genMoves)
Original: Checked 3 squares (b, c, d files) for queenside castling
- Fixed: Only check 2 squares (c and d files). b file is not part of the path.

### 9. Rook Existence for Castling (genMoves)
Original: Only checked castling flag in FEN, not whether rook still existed
- Fixed: Added check `pos.board[kr*8+7] == ourRook` and `pos.board[kr*8+0] == ourRook`

### 10. King Capture Prevention (genMoves)
Move generation allowed capturing opponent's king (treated as regular piece).
- Fixed: Added `&& pt(tp) != 6` to all capture checks for knights, bishops, rooks, queens, and pawns.

## Assertions Added

Using debug compilation (`-O0 -g`), the following asserts catch bugs:

1. **findKing**: Asserts king is found on board (line 74)
2. **doMove en passant**: Asserts captured pawn exists at EP capture square (line 234)
3. **doMove castling kingside**: Asserts rook exists at h1/h8 (line 240)
4. **doMove castling queenside**: Asserts rook exists at a1/a8 (line 245)
5. **undo en passant**: Asserts square is empty before restoring pawn (line 273)
6. **undo castling**: Asserts rook exists before moving back (lines 279, 283)

## Test Suite Results

```
=== Color/Side-to-Move Bug Tests ===

Test 1: Mirror Position Test
  D1: pos5=6, pos6=6, expected=6 PASS
  D2: pos5=264, pos6=264, expected=264 PASS
  D3: pos5=9566, pos6=9467, expected=9467 FAIL
  D4: pos5=417443, pos6=423461, expected=422333 FAIL

Test 2: Color Swap Test - PASS
Test 3: En Passant Test - PASS
Test 4: Castling Rights Test - PASS
Test 5: In Check After Move Test - PASS

=== Summary ===
1 test(s) FAILED (mirror position at D3+)
```

## Remaining Issues

### Position 3 (D3+)
- Expected: 9467, Got: 9566 (+99)
- Expected: 422333, Got: 417443 (-4890)
- Likely: Other edge case bugs in complex positions

### Position 4 (D4)
- Expected: 422333, Got: 423461 (+1128)
- This is the mirror of Position 3 - different results suggest asymmetry bug

### Likely Causes
1. Complex piece interactions not handled correctly
2. Edge cases in special moves (en passant, castling)
3. Move legality issues in certain scenarios

## Summary

- Starting position passes D1-D4 correctly
- Position 2 passes D1-D4 correctly
- Position 4 passes D1-D3 correctly (D4 was previously wrong)
- Position 5 passes D1-D3 correctly
- Positions 3-4 at deeper depths still have discrepancies
- All asserts working correctly in debug builds
