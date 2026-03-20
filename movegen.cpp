#include "engine.h"

#include <cassert>

namespace {

void pushMove(Move* moves, int& count, int from, int to, Piece promotion, bool isEnPassant, bool isCastle,
              bool isDoublePush) {
    assert(count < MAX_MOVES);
    moves[count++] = {from, to, promotion, isEnPassant, isCastle, isDoublePush};
}

int popLsb(uint64_t& bits) {
    assert(bits != 0);
    int sq = __builtin_ctzll(bits);
    bits &= bits - 1;
    return sq;
}

void genPawnMoves(const Position& pos, Color us, Move* moves, int& count) {
    uint64_t pawns = pos.pieceBitboards[us][pieceTypeIndex(us == WHITE ? W_PAWN : B_PAWN)];
    const AttackTables& tables = attackTables();
    uint64_t occAll = pos.occupancyAll;
    Color them = us == WHITE ? BLACK : WHITE;
    uint64_t enemyNonKingOcc = pos.occupancy[them] &
                               ~pos.pieceBitboards[them][pieceTypeIndex(them == WHITE ? W_KING : B_KING)];
    while (pawns) {
        int from = popLsb(pawns);
        int to = tables.pawnPush[us][from];
        if (to != -1 && (occAll & bitAt(to)) == 0) {
            if (tables.promotion[us][to]) {
                Piece promos[] = {
                    us == WHITE ? W_QUEEN : B_QUEEN,
                    us == WHITE ? W_ROOK : B_ROOK,
                    us == WHITE ? W_BISHOP : B_BISHOP,
                    us == WHITE ? W_KNIGHT : B_KNIGHT
                };
                for (Piece pr : promos) pushMove(moves, count, from, to, pr, false, false, false);
            } else {
                pushMove(moves, count, from, to, EMPTY, false, false, false);
                int t2 = tables.pawnDoublePush[us][from];
                if (t2 != -1 && (occAll & bitAt(t2)) == 0) {
                    pushMove(moves, count, from, t2, EMPTY, false, false, true);
                }
            }
        }
        uint64_t attacks = tables.pawnAttackers[us == WHITE ? BLACK : WHITE][from];
        while (attacks) {
            int cap = popLsb(attacks);
            if (enemyNonKingOcc & bitAt(cap)) {
                if (tables.promotion[us][cap]) {
                    Piece promos[] = {
                        us == WHITE ? W_QUEEN : B_QUEEN,
                        us == WHITE ? W_ROOK : B_ROOK,
                        us == WHITE ? W_BISHOP : B_BISHOP,
                        us == WHITE ? W_KNIGHT : B_KNIGHT
                    };
                    for (Piece pr : promos) pushMove(moves, count, from, cap, pr, false, false, false);
                } else {
                    pushMove(moves, count, from, cap, EMPTY, false, false, false);
                }
            }
            if (pos.enPassant != -1 && cap == pos.enPassant) pushMove(moves, count, from, cap, EMPTY, true, false, false);
        }
    }
}

void genKnightMoves(const Position& pos, Color us, Move* moves, int& count) {
    uint64_t pieces = pos.pieceBitboards[us][pieceTypeIndex(us == WHITE ? W_KNIGHT : B_KNIGHT)];
    uint64_t ownOcc = pos.occupancy[us];
    Color them = us == WHITE ? BLACK : WHITE;
    uint64_t occAll = pos.occupancyAll;
    uint64_t enemyNonKingOcc = pos.occupancy[them] &
                               ~pos.pieceBitboards[them][pieceTypeIndex(them == WHITE ? W_KING : B_KING)];
    while (pieces) {
        int from = popLsb(pieces);
        uint64_t attacks = attackTables().knight[from] & ~ownOcc;
        uint64_t quietTargets = attacks & ~occAll;
        uint64_t captureTargets = attacks & enemyNonKingOcc;
        while (quietTargets) pushMove(moves, count, from, popLsb(quietTargets), EMPTY, false, false, false);
        while (captureTargets) pushMove(moves, count, from, popLsb(captureTargets), EMPTY, false, false, false);
    }
}

void genSlidingMoves(const Position& pos, uint64_t pieces, bool bishopLike, Move* moves, int& count) {
    Color us = pos.sideToMove;
    Color them = us == WHITE ? BLACK : WHITE;
    uint64_t ownOcc = pos.occupancy[us];
    uint64_t enemyNonKingOcc = pos.occupancy[them] &
                               ~pos.pieceBitboards[them][pieceTypeIndex(them == WHITE ? W_KING : B_KING)];
    while (pieces) {
        int from = popLsb(pieces);
        uint64_t attacks = bishopLike ? bishopAttacks(from, pos.occupancyAll) : rookAttacks(from, pos.occupancyAll);
        uint64_t quietTargets = attacks & ~pos.occupancyAll;
        uint64_t captureTargets = attacks & enemyNonKingOcc & ~ownOcc;
        while (quietTargets) pushMove(moves, count, from, popLsb(quietTargets), EMPTY, false, false, false);
        while (captureTargets) pushMove(moves, count, from, popLsb(captureTargets), EMPTY, false, false, false);
    }
}

void genKingMoves(const Position& pos, Color us, Move* moves, int& count) {
    int from = pos.kingSq[us];
    Color them = us == WHITE ? BLACK : WHITE;
    uint64_t attacks = attackTables().king[from] & ~pos.occupancy[us];
    uint64_t quietTargets = attacks & ~pos.occupancyAll;
    uint64_t captureTargets = attacks & (pos.occupancy[them] &
                                         ~pos.pieceBitboards[them][pieceTypeIndex(them == WHITE ? W_KING : B_KING)]);
    while (quietTargets) pushMove(moves, count, from, popLsb(quietTargets), EMPTY, false, false, false);
    while (captureTargets) pushMove(moves, count, from, popLsb(captureTargets), EMPTY, false, false, false);
    int fr = R(from), fc = F(from);
    int kr = us == WHITE ? 0 : 7, ki = us == WHITE ? 0 : 2, qi = us == WHITE ? 1 : 3;
    uint64_t rookBitboard = pos.pieceBitboards[us][pieceTypeIndex(us == WHITE ? W_ROOK : B_ROOK)];
    if (fr == kr && fc == 4 && pos.castling[ki] && (rookBitboard & bitAt(kr * 8 + 7))) {
        if ((pos.occupancyAll & (bitAt(kr * 8 + 5) | bitAt(kr * 8 + 6))) == 0) {
            if (!attacked(pos, kr * 8 + 4, them) && !attacked(pos, kr * 8 + 5, them) && !attacked(pos, kr * 8 + 6, them)) {
                pushMove(moves, count, from, kr * 8 + 6, EMPTY, false, true, false);
            }
        }
    }
    if (fr == kr && fc == 4 && pos.castling[qi] && (rookBitboard & bitAt(kr * 8 + 0))) {
        if ((pos.occupancyAll & (bitAt(kr * 8 + 1) | bitAt(kr * 8 + 2) | bitAt(kr * 8 + 3))) == 0) {
            if (!attacked(pos, kr * 8 + 4, them) && !attacked(pos, kr * 8 + 3, them) && !attacked(pos, kr * 8 + 2, them)) {
                pushMove(moves, count, from, kr * 8 + 2, EMPTY, false, true, false);
            }
        }
    }
}

}  // namespace

int genMoves(const Position& pos, Move* moves) {
    int count = 0;
    Color us = pos.sideToMove;

    genPawnMoves(pos, us, moves, count);
    genKnightMoves(pos, us, moves, count);

    uint64_t bishops = pos.pieceBitboards[us][pieceTypeIndex(us == WHITE ? W_BISHOP : B_BISHOP)];
    uint64_t rooks = pos.pieceBitboards[us][pieceTypeIndex(us == WHITE ? W_ROOK : B_ROOK)];
    uint64_t queens = pos.pieceBitboards[us][pieceTypeIndex(us == WHITE ? W_QUEEN : B_QUEEN)];

    genSlidingMoves(pos, bishops, true, moves, count);
    genSlidingMoves(pos, rooks, false, moves, count);
    genSlidingMoves(pos, queens, true, moves, count);
    genSlidingMoves(pos, queens, false, moves, count);

    genKingMoves(pos, us, moves, count);

    return count;
}

int genLegalMoves(const Position& pos, Move* moves) {
    Move pseudoMoves[MAX_MOVES];
    int pseudoCount = genMoves(pos, pseudoMoves);
    int legalCount = 0;
    Color us = pos.sideToMove;
    Position tmp = pos;
#ifdef CHESS_VALIDATE_STATE
    Position startPos = pos;
#endif
    for (int i = 0; i < pseudoCount; i++) {
        const Move& mv = pseudoMoves[i];
        UndoState undoState;
        doMove(tmp, mv, undoState);
        if (!inCheck(tmp, us)) moves[legalCount++] = mv;
        undo(tmp, mv, undoState);
#ifdef CHESS_VALIDATE_STATE
        assert(positionsEqual(startPos, tmp));
#endif
    }
    return legalCount;
}

bool hasAnyLegalMove(const Position& pos) {
    Move legalMoves[MAX_MOVES];
    return genLegalMoves(pos, legalMoves) > 0;
}

bool isCheckmate(const Position& pos) {
    return inCheck(pos, pos.sideToMove) && !hasAnyLegalMove(pos);
}

bool isStalemate(const Position& pos) {
    return !inCheck(pos, pos.sideToMove) && !hasAnyLegalMove(pos);
}

bool parseUCIMove(const Position& pos, const std::string& uci, Move& outMove) {
    Move legalMoves[MAX_MOVES];
    int moveCount = genLegalMoves(pos, legalMoves);
    for (int i = 0; i < moveCount; i++) {
        if (moveToUCI(legalMoves[i]) == uci) {
            outMove = legalMoves[i];
            return true;
        }
    }
    return false;
}

bool applyUCIMove(Position& pos, const std::string& uci) {
    Move mv;
    if (!parseUCIMove(pos, uci, mv)) return false;
    UndoState undoState;
    doMove(pos, mv, undoState);
    return true;
}
