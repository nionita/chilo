#include "engine.h"

#include <cassert>
#include <iostream>

uint64_t perft(Position& pos, int d);

uint64_t perftDivide(Position& pos, int d) {
    Move moves[MAX_MOVES];
    int moveCount = genMoves(pos, moves);
    uint64_t total = 0;
    Color us = pos.sideToMove;
#ifdef CHESS_VALIDATE_STATE
    Position startPos = pos;
#endif
    for (int i = 0; i < moveCount; i++) {
        const Move& mv = moves[i];
        UndoState undoState;
        doMove(pos, mv, undoState);
        if (!inCheck(pos, us)) {
            uint64_t count = perft(pos, d - 1);
            std::cout << moveToUCI(mv) << ": " << count << "\n";
            total += count;
        }
        undo(pos, mv, undoState);
#ifdef CHESS_VALIDATE_STATE
        assert(positionsEqual(startPos, pos));
#endif
    }
    return total;
}

uint64_t perft(Position& pos, int d) {
    if (d == 0) return 1;
    Move moves[MAX_MOVES];
    int moveCount = genMoves(pos, moves);
    uint64_t n = 0;
    Color us = pos.sideToMove;
#ifdef CHESS_VALIDATE_STATE
    Position startPos = pos;
#endif
    for (int i = 0; i < moveCount; i++) {
        const Move& mv = moves[i];
        UndoState undoState;
        doMove(pos, mv, undoState);
        if (!inCheck(pos, us)) n += perft(pos, d - 1);
        undo(pos, mv, undoState);
#ifdef CHESS_VALIDATE_STATE
        assert(positionsEqual(startPos, pos));
#endif
    }
    return n;
}
