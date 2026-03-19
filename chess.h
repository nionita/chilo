#ifndef CHESS_H
#define CHESS_H

#include "chess_position.h"
#include "chess_tables.h"

#include <iostream>
#include <cassert>
bool attacked(const Position& pos, int sq, Color att) {
    assert(sq >= 0 && sq < 64);
    const AttackTables& tables = attackTables();
    bool result = false;

    int pawnType = pieceTypeIndex(att == WHITE ? W_PAWN : B_PAWN);
    if (pos.pieceBitboards[att][pawnType] & tables.pawnAttackers[att][sq]) result = true;

    if (!result) {
        int knightType = pieceTypeIndex(att == WHITE ? W_KNIGHT : B_KNIGHT);
        if (pos.pieceBitboards[att][knightType] & tables.knight[sq]) result = true;
    }

    if (!result) {
        int kingType = pieceTypeIndex(att == WHITE ? W_KING : B_KING);
        if (pos.pieceBitboards[att][kingType] & tables.king[sq]) result = true;
    }

    if (!result) {
        int rookType = pieceTypeIndex(att == WHITE ? W_ROOK : B_ROOK);
        int bishopType = pieceTypeIndex(att == WHITE ? W_BISHOP : B_BISHOP);
        int queenType = pieceTypeIndex(att == WHITE ? W_QUEEN : B_QUEEN);
        uint64_t rookQueenAttackers = pos.pieceBitboards[att][rookType] | pos.pieceBitboards[att][queenType];
        uint64_t bishopQueenAttackers = pos.pieceBitboards[att][bishopType] | pos.pieceBitboards[att][queenType];
        result = (rookAttacks(sq, pos.occupancyAll) & rookQueenAttackers) != 0 ||
                 (bishopAttacks(sq, pos.occupancyAll) & bishopQueenAttackers) != 0;
    }

    return result;
}

bool inCheck(const Position& pos, Color col) {
    int k = pos.kingSq[col];
    assert(k >= 0 && k < 64);
    return attacked(pos, k, col == WHITE ? BLACK : WHITE);
}

void pushMove(Move* moves, int& count, int from, int to, Piece promotion, bool isEnPassant, bool isCastle, bool isDoublePush) {
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

void doMove(Position& pos, const Move& mv, UndoState& undo) {
    assert(mv.from >= 0 && mv.from < 64);
    assert(mv.to >= 0 && mv.to < 64);
    assert(pieceAt(pos, mv.from) != EMPTY);

    Piece pc = pieceAt(pos, mv.from);
    undo.captured = pieceAt(pos, mv.to);
    undo.halfMove = pos.halfMove;
    undo.fullMove = pos.fullMove;
    undo.enPassant = pos.enPassant;
    undo.castling = packCastling(pos);

    if (undo.captured != EMPTY) {
        clearCastlingForSquare(pos, mv.to);
        removePiece(pos, mv.to);
    }
    if (mv.isEnPassant) {
        int epR = R(mv.to);
        int capR = pos.sideToMove == WHITE ? epR - 1 : epR + 1;
        int capSq = capR * 8 + F(mv.to);
        assert(hasPiece(pos, capSq, W_PAWN) || hasPiece(pos, capSq, B_PAWN));
        removePiece(pos, capSq);
    }

    if (pc == W_KING) {
        pos.castling[0] = false;
        pos.castling[1] = false;
    } else if (pc == B_KING) {
        pos.castling[2] = false;
        pos.castling[3] = false;
    } else if (pc == W_ROOK || pc == B_ROOK) {
        clearCastlingForSquare(pos, mv.from);
    }

    movePiece(pos, mv.from, mv.to);

    if (mv.promotion != EMPTY) {
        assert((mv.promotion >= W_PAWN && mv.promotion <= W_KING) ||
               (mv.promotion >= B_PAWN && mv.promotion <= B_KING));
        removePiece(pos, mv.to);
        addPiece(pos, mv.to, mv.promotion);
    }

    if (mv.isCastle) {
        int rr = R(mv.to);
        if (F(mv.to) == 6) {
            assert(hasPiece(pos, rr * 8 + 7, rr == 0 ? W_ROOK : B_ROOK));
            movePiece(pos, rr * 8 + 7, rr * 8 + 5);
        } else if (F(mv.to) == 2) {
            assert(hasPiece(pos, rr * 8 + 0, rr == 0 ? W_ROOK : B_ROOK));
            movePiece(pos, rr * 8 + 0, rr * 8 + 3);
        }
    }

    pos.enPassant = -1;
    if (mv.isDoublePush) {
        int epR = pos.sideToMove == WHITE ? R(mv.from) + 1 : R(mv.from) - 1;
        pos.enPassant = epR * 8 + F(mv.from);
    }
    if (pt(pc) == 1 || undo.captured != EMPTY || mv.isEnPassant) pos.halfMove = 0;
    else pos.halfMove++;
    pos.sideToMove = pos.sideToMove == WHITE ? BLACK : WHITE;
    if (pos.sideToMove == WHITE) pos.fullMove++;
#ifdef CHESS_VALIDATE_STATE
    assert(representationConsistent(pos));
#endif
}

void undo(Position& pos, const Move& mv, const UndoState& undo) {
    assert(mv.from >= 0 && mv.from < 64);
    assert(mv.to >= 0 && mv.to < 64);

    pos.sideToMove = pos.sideToMove == WHITE ? BLACK : WHITE;
    pos.halfMove = undo.halfMove;
    pos.fullMove = undo.fullMove;
    pos.enPassant = undo.enPassant;
    restoreCastling(pos, undo.castling);

    if (mv.isCastle) {
        int rr = R(mv.to);
        if (F(mv.to) == 6) {
            assert(hasPiece(pos, rr * 8 + 5, W_ROOK) || hasPiece(pos, rr * 8 + 5, B_ROOK));
            movePiece(pos, rr * 8 + 5, rr * 8 + 7);
        } else if (F(mv.to) == 2) {
            assert(hasPiece(pos, rr * 8 + 3, W_ROOK) || hasPiece(pos, rr * 8 + 3, B_ROOK));
            movePiece(pos, rr * 8 + 3, rr * 8 + 0);
        }
    }

    if (mv.promotion != EMPTY) {
        removePiece(pos, mv.to);
        addPiece(pos, mv.to, pos.sideToMove == WHITE ? W_PAWN : B_PAWN);
    }

    movePiece(pos, mv.to, mv.from);

    if (mv.isEnPassant) {
        int epR = R(mv.to);
        int capR = pos.sideToMove == WHITE ? epR - 1 : epR + 1;
        int capSq = capR * 8 + F(mv.to);
        Piece restoredPawn = pos.sideToMove == WHITE ? B_PAWN : W_PAWN;
        assert(pieceAt(pos, capSq) == EMPTY);
        addPiece(pos, capSq, restoredPawn);
    } else if (undo.captured != EMPTY) {
        assert(pieceAt(pos, mv.to) == EMPTY);
        addPiece(pos, mv.to, undo.captured);
    }
#ifdef CHESS_VALIDATE_STATE
    assert(representationConsistent(pos));
#endif
}

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

#endif
