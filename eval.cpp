#include "engine.h"

namespace {

constexpr int PAWN_VALUE = 100;
constexpr int KNIGHT_VALUE = 320;
constexpr int BISHOP_VALUE = 330;
constexpr int ROOK_VALUE = 500;
constexpr int QUEEN_VALUE = 900;

constexpr int pawnTable[64] = {
      0,   0,   0,   0,   0,   0,   0,   0,
     50,  50,  50,  50,  50,  50,  50,  50,
     10,  10,  20,  30,  30,  20,  10,  10,
      5,   5,  10,  25,  25,  10,   5,   5,
      0,   0,   0,  20,  20,   0,   0,   0,
      5,  -5, -10,   0,   0, -10,  -5,   5,
      5,  10,  10, -20, -20,  10,  10,   5,
      0,   0,   0,   0,   0,   0,   0,   0
};

constexpr int knightTable[64] = {
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20,   0,   5,   5,   0, -20, -40,
    -30,   5,  10,  15,  15,  10,   5, -30,
    -30,   0,  15,  20,  20,  15,   0, -30,
    -30,   5,  15,  20,  20,  15,   5, -30,
    -30,   0,  10,  15,  15,  10,   0, -30,
    -40, -20,   0,   0,   0,   0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50
};

constexpr int bishopTable[64] = {
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10,   5,   0,   0,   0,   0,   5, -10,
    -10,  10,  10,  10,  10,  10,  10, -10,
    -10,   0,  10,  10,  10,  10,   0, -10,
    -10,   5,   5,  10,  10,   5,   5, -10,
    -10,   0,   5,  10,  10,   5,   0, -10,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -20, -10, -10, -10, -10, -10, -10, -20
};

constexpr int rookTable[64] = {
      0,   0,   5,  10,  10,   5,   0,   0,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
      5,  10,  10,  10,  10,  10,  10,   5,
      0,   0,   5,  10,  10,   5,   0,   0
};

constexpr int queenTable[64] = {
    -20, -10, -10,  -5,  -5, -10, -10, -20,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -10,   0,   5,   5,   5,   5,   0, -10,
     -5,   0,   5,   5,   5,   5,   0,  -5,
      0,   0,   5,   5,   5,   5,   0,  -5,
    -10,   5,   5,   5,   5,   5,   0, -10,
    -10,   0,   5,   0,   0,   0,   0, -10,
    -20, -10, -10,  -5,  -5, -10, -10, -20
};

constexpr int kingTable[64] = {
    -300, -400, -400, -500, -500, -400, -400, -300,
    -300, -400, -400, -500, -500, -400, -400, -300,
    -300, -400, -400, -500, -500, -400, -400, -300,
    -300, -400, -400, -500, -500, -400, -400, -300,
    -200, -300, -300, -400, -400, -300, -300, -200,
    -100, -200, -200, -200, -200, -200, -200, -100,
     200,  200,    0,    0,    0,    0,  200,  200,
     200,  300,  100,    0,    0,  100,  300,  200
};

int popLsb(uint64_t& bits) {
    assert(bits != 0);
    int sq = __builtin_ctzll(bits);
    bits &= bits - 1;
    return sq;
}

int mirrorSquare(int sq) {
    return (7 - R(sq)) * 8 + F(sq);
}

int pieceBaseValue(Piece piece) {
    static constexpr int pieceValues[] = {
        0,
        PAWN_VALUE, KNIGHT_VALUE, BISHOP_VALUE, ROOK_VALUE, QUEEN_VALUE, 0,
        PAWN_VALUE, KNIGHT_VALUE, BISHOP_VALUE, ROOK_VALUE, QUEEN_VALUE, 0
    };
    return pieceValues[piece];
}

int pieceSquareValue(Piece piece, int sq) {
    int tableSq = wh(piece) ? sq : mirrorSquare(sq);
    switch (pt(piece)) {
        case 1: return pawnTable[tableSq];
        case 2: return knightTable[tableSq];
        case 3: return bishopTable[tableSq];
        case 4: return rookTable[tableSq];
        case 5: return queenTable[tableSq];
        case 6: return kingTable[tableSq];
        default: return 0;
    }
}

}  // namespace

int evaluate(const Position& pos) {
    int whiteMaterial = 0;
    int blackMaterial = 0;
    int whitePstTenths = 0;
    int blackPstTenths = 0;

    uint64_t occupied = pos.occupancyAll;
    while (occupied) {
        int sq = popLsb(occupied);
        Piece piece = pos.pieceAtSquare[sq];
        int material = pieceBaseValue(piece);
        int pstTenths = pieceSquareValue(piece, sq);
        if (wh(piece)) {
            whiteMaterial += material;
            whitePstTenths += pstTenths;
        } else {
            blackMaterial += material;
            blackPstTenths += pstTenths;
        }
    }

    int whiteScore = whiteMaterial + whitePstTenths / 10;
    int blackScore = blackMaterial + blackPstTenths / 10;
    int score = whiteScore - blackScore;
    return pos.sideToMove == WHITE ? score : -score;
}
