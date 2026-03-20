#include "engine.h"

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
