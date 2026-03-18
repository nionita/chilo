# Perft Implementation Report

## Current State

### Compilation
The program compiles successfully with `g++ -O2 -o perft perft.cpp`.

### Usage
```bash
./perft "<fen>" <depth>
```

### Test Results

| Position | Depth 1 | Depth 2 | Depth 3 | Depth 4 | Depth 5 |
|----------|---------|---------|---------|---------|---------|
| **1. Starting Position** (`rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1`) |
| Expected | 20 | 400 | 8902 | 197281 | 4865609 |
| Actual | 20 ✓ | 400 ✓ | 8902 ✓ | 197281 ✓ | 4865644 |
| Diff | 0 | 0 | 0 | 0 | +35 |
| **Position 2** (`8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1`) |
| Expected | 14 | 191 | 2812 | 43238 | 674624 |
| Actual | 15 | 230 | 3576 | - | - |
| Diff | +1 | +39 | +764 | - | - |
| **Position 3** (`r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1`) |
| Expected | 6 | 264 | 9467 | 422333 | 15833292 |
| Actual | 6 ✓ | 264 ✓ | 9566 | 417908 | - |
| Diff | 0 | 0 | +99 | -4425 | - |
| **Position 4** (`r2q1rk1/pP1p2pp/Q4n2/bbp1p3/Np6/1B3NBn/pPPP1PPP/R3K2R b KQ - 0 1`) |
| Expected | 6 | 264 | 9467 | 422333 | 15833292 |
| Actual | 6 ✓ | 264 ✓ | 9467 ✓ | 423920 | - |
| Diff | 0 | 0 | 0 | +1587 | - |
| **Position 5** (`rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8`) |
| Expected | 44 | 1486 | 62379 | 2103487 | 89941194 |
| Actual | 44 ✓ | 1525 | 64342 | 2212786 | - |
| Diff | 0 | +39 | +1963 | +109299 | - |

## Findings

### Critical Bug Fixed

The most significant bug was in the `perft()` function. The original code:

```cpp
doMove(pos, mv);
if (!inCheck(pos, pos.sideToMove)) n += perft(pos, d - 1);
```

This was incorrect because `doMove()` already swaps `pos.sideToMove` to the opponent's color. The code was checking if the **opponent's** king was in check, not if the **mover's** king was left in check.

**Fix:**
```cpp
Color us = pos.sideToMove;
for (const Move& mv : moves) {
    doMove(pos, mv);
    if (!inCheck(pos, us)) n += perft(pos, d - 1);  // Check mover's color
    undo(pos, mv, cap);
}
```

This single fix corrected depth 3 from 8890→8902 and depth 4 from 196980→197281.

### Remaining Issues

1. **Depth 5 (starting position)**: Off by 35 nodes (0.0007% error)
2. **Position 2**: All depths off significantly (15 vs 14 expected at D1)
3. **Positions 3-5**: Off at deeper depths

### Suspected Root Causes

1. **En Passant handling**: The implementation may not correctly handle en passant capture/undo in all scenarios
2. **Castling state tracking**: Castling rights may not be properly preserved across move sequences
3. **Move generation edge cases**: Potential issues with:
   - Underpromotion handling
   - Castling legality (checking if squares are attacked)
   - Edge cases in sliding piece move generation

## Next Steps for Improvement

### Priority 1: Debug En Passant
- Add debug output to trace en passant move generation and execution
- Test with positions that have en passant captures
- Verify undo correctly restores the captured pawn

### Priority 2: Debug Castling
- Add debug output to trace castling move generation
- Verify the attacked square checks are working correctly
- Consider adding proper castling right tracking (store/restore)

### Priority 3: Compare with Reference
- Find a known-correct perft implementation to compare move-by-move
- Use perft divide (move counts at depth 1) to identify specific incorrect moves

### Priority 4: Edge Cases
- Test positions with underpromotion
- Test positions where castling is only legal under specific conditions
- Test complex positions with multiple special moves

## Conclusion

The implementation now correctly handles the starting position through depth 4. The critical bug was checking the wrong color for check detection after making a move. The remaining discrepancies at deeper depths or different positions are likely due to incomplete handling of special moves (en passant, castling).
