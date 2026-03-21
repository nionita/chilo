#include "engine.h"

#include <algorithm>

namespace {

struct EvalScore {
    int mg;
    int eg;
};

constexpr EvalScore SCORE_ZERO{0, 0};

constexpr uint64_t FILE_MASKS[8] = {
    0x0101010101010101ULL, 0x0202020202020202ULL, 0x0404040404040404ULL, 0x0808080808080808ULL,
    0x1010101010101010ULL, 0x2020202020202020ULL, 0x4040404040404040ULL, 0x8080808080808080ULL
};

constexpr EvalScore PIECE_VALUES[13] = {
    {0, 0},
    {100, 120}, {330, 310}, {350, 330}, {520, 540}, {980, 940}, {0, 0},
    {100, 120}, {330, 310}, {350, 330}, {520, 540}, {980, 940}, {0, 0}
};

constexpr int GAME_PHASE_WEIGHTS[13] = {
    0,
    0, 1, 1, 2, 4, 0,
    0, 1, 1, 2, 4, 0
};

constexpr int MAX_PHASE = 24;

constexpr int pawnTableMg[64] = {
      0,   0,   0,   0,   0,   0,   0,   0,
     50,  50,  50,  50,  50,  50,  50,  50,
     10,  10,  20,  30,  30,  20,  10,  10,
      5,   5,  10,  25,  25,  10,   5,   5,
      0,   0,   0,  20,  20,   0,   0,   0,
      5,  -5, -10,   0,   0, -10,  -5,   5,
      5,  10,  10, -20, -20,  10,  10,   5,
      0,   0,   0,   0,   0,   0,   0,   0
};

constexpr int pawnTableEg[64] = {
      0,   0,   0,   0,   0,   0,   0,   0,
     80,  80,  80,  80,  80,  80,  80,  80,
     50,  50,  55,  60,  60,  55,  50,  50,
     30,  30,  35,  45,  45,  35,  30,  30,
     20,  20,  25,  30,  30,  25,  20,  20,
     10,  10,  12,  15,  15,  12,  10,  10,
      5,   5,   5, -10, -10,   5,   5,   5,
      0,   0,   0,   0,   0,   0,   0,   0
};

constexpr int knightTableMg[64] = {
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20,   0,   5,   5,   0, -20, -40,
    -30,   5,  10,  15,  15,  10,   5, -30,
    -30,   0,  15,  20,  20,  15,   0, -30,
    -30,   5,  15,  20,  20,  15,   5, -30,
    -30,   0,  10,  15,  15,  10,   0, -30,
    -40, -20,   0,   0,   0,   0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50
};

constexpr int knightTableEg[64] = {
    -40, -30, -20, -20, -20, -20, -30, -40,
    -30, -10,   0,   5,   5,   0, -10, -30,
    -20,   5,  15,  20,  20,  15,   5, -20,
    -20,  10,  20,  25,  25,  20,  10, -20,
    -20,  10,  20,  25,  25,  20,  10, -20,
    -20,   5,  15,  20,  20,  15,   5, -20,
    -30, -10,   0,   5,   5,   0, -10, -30,
    -40, -30, -20, -20, -20, -20, -30, -40
};

constexpr int bishopTableMg[64] = {
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10,   5,   0,   0,   0,   0,   5, -10,
    -10,  10,  10,  10,  10,  10,  10, -10,
    -10,   0,  10,  10,  10,  10,   0, -10,
    -10,   5,   5,  10,  10,   5,   5, -10,
    -10,   0,   5,  10,  10,   5,   0, -10,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -20, -10, -10, -10, -10, -10, -10, -20
};

constexpr int bishopTableEg[64] = {
    -10,  -5,  -5,  -5,  -5,  -5,  -5, -10,
     -5,   5,   0,   0,   0,   0,   5,  -5,
     -5,  10,  10,  10,  10,  10,  10,  -5,
     -5,   5,  10,  15,  15,  10,   5,  -5,
     -5,   5,  10,  15,  15,  10,   5,  -5,
     -5,   5,  10,  10,  10,  10,   5,  -5,
     -5,   5,   0,   0,   0,   0,   5,  -5,
    -10,  -5,  -5,  -5,  -5,  -5,  -5, -10
};

constexpr int rookTableMg[64] = {
      0,   0,   5,  10,  10,   5,   0,   0,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
      5,  10,  10,  10,  10,  10,  10,   5,
      0,   0,   5,  10,  10,   5,   0,   0
};

constexpr int rookTableEg[64] = {
      0,   0,   5,  10,  10,   5,   0,   0,
      0,   5,   5,  10,  10,   5,   5,   0,
      0,   5,   5,  10,  10,   5,   5,   0,
      0,   5,   5,  10,  10,   5,   5,   0,
      0,   5,   5,  10,  10,   5,   5,   0,
      0,   5,   5,  10,  10,   5,   5,   0,
      5,  10,  10,  15,  15,  10,  10,   5,
      0,   0,   5,  10,  10,   5,   0,   0
};

constexpr int queenTableMg[64] = {
    -20, -10, -10,  -5,  -5, -10, -10, -20,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -10,   0,   5,   5,   5,   5,   0, -10,
     -5,   0,   5,   5,   5,   5,   0,  -5,
      0,   0,   5,   5,   5,   5,   0,  -5,
    -10,   5,   5,   5,   5,   5,   0, -10,
    -10,   0,   5,   0,   0,   0,   0, -10,
    -20, -10, -10,  -5,  -5, -10, -10, -20
};

constexpr int queenTableEg[64] = {
    -10,  -5,  -5,  -2,  -2,  -5,  -5, -10,
     -5,   0,   0,   2,   2,   0,   0,  -5,
     -5,   0,   5,   5,   5,   5,   0,  -5,
     -2,   2,   5,   6,   6,   5,   2,  -2,
     -2,   2,   5,   6,   6,   5,   2,  -2,
     -5,   0,   5,   5,   5,   5,   0,  -5,
     -5,   0,   0,   2,   2,   0,   0,  -5,
    -10,  -5,  -5,  -2,  -2,  -5,  -5, -10
};

constexpr int kingTableMg[64] = {
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -10, -20, -20, -20, -20, -20, -20, -10,
     20,  20,   0,   0,   0,   0,  20,  20,
     20,  30,  10,   0,   0,  10,  30,  20
};

constexpr int kingTableEg[64] = {
    -30, -20, -10,  -5,  -5, -10, -20, -30,
    -20, -10,   0,   5,   5,   0, -10, -20,
    -10,   0,  10,  15,  15,  10,   0, -10,
     -5,   5,  15,  20,  20,  15,   5,  -5,
     -5,   5,  15,  20,  20,  15,   5,  -5,
    -10,   0,  10,  15,  15,  10,   0, -10,
    -20, -10,   0,   5,   5,   0, -10, -20,
    -30, -20, -10,  -5,  -5, -10, -20, -30
};

constexpr EvalScore MOBILITY_BONUS[7] = {
    {0, 0},
    {0, 0},
    {4, 3},
    {5, 4},
    {3, 6},
    {2, 4},
    {0, 0}
};

constexpr EvalScore BISHOP_PAIR_BONUS{30, 45};
constexpr EvalScore DOUBLED_PAWN_PENALTY{-12, -18};
constexpr EvalScore ISOLATED_PAWN_PENALTY{-10, -14};
constexpr EvalScore ROOK_OPEN_FILE_BONUS{20, 12};
constexpr EvalScore ROOK_SEMIOPEN_FILE_BONUS{10, 8};
constexpr EvalScore KING_SHIELD_PAWN_FRONT{8, 0};
constexpr EvalScore KING_SHIELD_PAWN_BACK{4, 0};
constexpr EvalScore KING_SHIELD_MISSING{-12, 0};
constexpr EvalScore PASSED_BLOCKER_PENALTY{-12, -18};
constexpr EvalScore PASSED_PATH_DEFENDED_BONUS{2, 4};
constexpr EvalScore PASSED_PATH_ATTACKED_PENALTY{-3, -6};

constexpr EvalScore KING_ZONE_ATTACK_UNIT[7] = {
    {0, 0},
    {0, 0},
    {-12, -2},
    {-12, -2},
    {-18, -3},
    {-8, -1},
    {0, 0}
};

constexpr EvalScore PASSED_PAWN_RANK_BONUS[8] = {
    {0, 0}, {0, 0}, {10, 20}, {20, 35}, {35, 60}, {55, 90}, {80, 140}, {0, 0}
};

constexpr int TEMPO_BONUS = 12;

int popLsb(uint64_t& bits) {
    assert(bits != 0);
    int sq = __builtin_ctzll(bits);
    bits &= bits - 1;
    return sq;
}

int mirrorSquare(int sq) {
    return (7 - R(sq)) * 8 + F(sq);
}

int tableSquare(Piece piece, int sq) {
    return wh(piece) ? sq : mirrorSquare(sq);
}

int popcount(uint64_t bits) {
    return __builtin_popcountll(bits);
}

Color opposite(Color side) {
    return side == WHITE ? BLACK : WHITE;
}

EvalScore operator+(EvalScore a, EvalScore b) {
    return {a.mg + b.mg, a.eg + b.eg};
}

EvalScore operator*(EvalScore score, int factor) {
    return {score.mg * factor, score.eg * factor};
}

void addToSide(Color side, EvalScore term, int& whiteMg, int& whiteEg, int& blackMg, int& blackEg) {
    if (side == WHITE) {
        whiteMg += term.mg;
        whiteEg += term.eg;
    } else {
        blackMg += term.mg;
        blackEg += term.eg;
    }
}

EvalScore pieceSquareValue(Piece piece, int sq) {
    int tableSq = tableSquare(piece, sq);
    switch (pt(piece)) {
        case 1: return {pawnTableMg[tableSq], pawnTableEg[tableSq]};
        case 2: return {knightTableMg[tableSq], knightTableEg[tableSq]};
        case 3: return {bishopTableMg[tableSq], bishopTableEg[tableSq]};
        case 4: return {rookTableMg[tableSq], rookTableEg[tableSq]};
        case 5: return {queenTableMg[tableSq], queenTableEg[tableSq]};
        case 6: return {kingTableMg[tableSq], kingTableEg[tableSq]};
        default: return SCORE_ZERO;
    }
}

EvalScore pieceValue(Piece piece) {
    return PIECE_VALUES[piece];
}

int gamePhase(const Position& pos) {
    int phase = 0;
    uint64_t occupied = pos.occupancyAll;
    while (occupied) {
        int sq = popLsb(occupied);
        phase += GAME_PHASE_WEIGHTS[pos.pieceAtSquare[sq]];
    }
    return std::min(phase, MAX_PHASE);
}

int pawnAdvance(Color side, int sq) {
    return side == WHITE ? R(sq) : 7 - R(sq);
}

uint64_t pawnsInAdjacentFiles(uint64_t pawns, int file) {
    uint64_t result = 0;
    if (file > 0) result |= pawns & FILE_MASKS[file - 1];
    if (file < 7) result |= pawns & FILE_MASKS[file + 1];
    return result;
}

bool isPassedPawn(const Position& pos, Color side, int sq) {
    Color enemy = opposite(side);
    uint64_t enemyPawns = pos.pieceBitboards[enemy][pieceTypeIndex(enemy == WHITE ? W_PAWN : B_PAWN)];
    int file = F(sq);
    for (int f = std::max(0, file - 1); f <= std::min(7, file + 1); ++f) {
        uint64_t candidates = enemyPawns & FILE_MASKS[f];
        while (candidates) {
            int enemySq = popLsb(candidates);
            if ((side == WHITE && enemySq > sq) || (side == BLACK && enemySq < sq)) return false;
        }
    }
    return true;
}

EvalScore passedPawnBonus(const Position& pos, Color side, int sq) {
    EvalScore score = PASSED_PAWN_RANK_BONUS[pawnAdvance(side, sq)];
    Color enemy = opposite(side);
    int step = side == WHITE ? 8 : -8;
    for (int pathSq = sq + step; pathSq >= 0 && pathSq < 64; pathSq += step) {
        if (pieceAt(pos, pathSq) != EMPTY) {
            score = score + PASSED_BLOCKER_PENALTY;
            break;
        }
        if (attacked(pos, pathSq, side)) score = score + PASSED_PATH_DEFENDED_BONUS;
        if (attacked(pos, pathSq, enemy)) score = score + PASSED_PATH_ATTACKED_PENALTY;
    }
    return score;
}

EvalScore mobilityBonus(const Position& pos, Color side, Piece piece, int sq) {
    uint64_t attacks = 0;
    uint64_t ownOcc = pos.occupancy[side];
    const AttackTables& tables = attackTables();
    switch (pt(piece)) {
        case 2:
            attacks = tables.knight[sq] & ~ownOcc;
            break;
        case 3:
            attacks = bishopAttacks(sq, pos.occupancyAll) & ~ownOcc;
            break;
        case 4:
            attacks = rookAttacks(sq, pos.occupancyAll) & ~ownOcc;
            break;
        case 5:
            attacks = (bishopAttacks(sq, pos.occupancyAll) | rookAttacks(sq, pos.occupancyAll)) & ~ownOcc;
            break;
        default:
            return SCORE_ZERO;
    }
    return MOBILITY_BONUS[pt(piece)] * popcount(attacks);
}

EvalScore rookFileBonus(const Position& pos, Color side, int sq) {
    int file = F(sq);
    uint64_t fileMask = FILE_MASKS[file];
    uint64_t ownPawns = pos.pieceBitboards[side][pieceTypeIndex(side == WHITE ? W_PAWN : B_PAWN)] & fileMask;
    uint64_t enemyPawns = pos.pieceBitboards[opposite(side)][pieceTypeIndex(side == WHITE ? B_PAWN : W_PAWN)] & fileMask;
    if (ownPawns == 0 && enemyPawns == 0) return ROOK_OPEN_FILE_BONUS;
    if (ownPawns == 0) return ROOK_SEMIOPEN_FILE_BONUS;
    return SCORE_ZERO;
}

EvalScore kingShieldBonus(const Position& pos, Color side) {
    int kingSq = pos.kingSq[side];
    int forward = side == WHITE ? 1 : -1;
    int baseRank = R(kingSq) + forward;
    int secondRank = baseRank + forward;
    EvalScore score = SCORE_ZERO;
    Piece pawn = side == WHITE ? W_PAWN : B_PAWN;

    for (int df = -1; df <= 1; ++df) {
        int file = F(kingSq) + df;
        if (file < 0 || file > 7) continue;

        bool found = false;
        if (baseRank >= 0 && baseRank < 8 && pieceAt(pos, baseRank * 8 + file) == pawn) {
            score = score + KING_SHIELD_PAWN_FRONT;
            found = true;
        } else if (secondRank >= 0 && secondRank < 8 && pieceAt(pos, secondRank * 8 + file) == pawn) {
            score = score + KING_SHIELD_PAWN_BACK;
            found = true;
        }

        if (!found) score = score + KING_SHIELD_MISSING;
    }

    return score;
}

EvalScore kingZonePressure(const Position& pos, Color side) {
    Color enemy = opposite(side);
    int kingSq = pos.kingSq[side];
    uint64_t zone = attackTables().king[kingSq] | bitAt(kingSq);
    EvalScore score = SCORE_ZERO;

    auto addZoneHits = [&](uint64_t pieces, Piece samplePiece) {
        while (pieces) {
            int sq = popLsb(pieces);
            uint64_t attacks = 0;
            switch (pt(samplePiece)) {
                case 2: attacks = attackTables().knight[sq]; break;
                case 3: attacks = bishopAttacks(sq, pos.occupancyAll); break;
                case 4: attacks = rookAttacks(sq, pos.occupancyAll); break;
                case 5: attacks = bishopAttacks(sq, pos.occupancyAll) | rookAttacks(sq, pos.occupancyAll); break;
                default: break;
            }
            int hits = popcount(attacks & zone);
            score = score + (KING_ZONE_ATTACK_UNIT[pt(samplePiece)] * hits);
        }
    };

    addZoneHits(pos.pieceBitboards[enemy][pieceTypeIndex(enemy == WHITE ? W_KNIGHT : B_KNIGHT)],
                enemy == WHITE ? W_KNIGHT : B_KNIGHT);
    addZoneHits(pos.pieceBitboards[enemy][pieceTypeIndex(enemy == WHITE ? W_BISHOP : B_BISHOP)],
                enemy == WHITE ? W_BISHOP : B_BISHOP);
    addZoneHits(pos.pieceBitboards[enemy][pieceTypeIndex(enemy == WHITE ? W_ROOK : B_ROOK)],
                enemy == WHITE ? W_ROOK : B_ROOK);
    addZoneHits(pos.pieceBitboards[enemy][pieceTypeIndex(enemy == WHITE ? W_QUEEN : B_QUEEN)],
                enemy == WHITE ? W_QUEEN : B_QUEEN);

    return score;
}

void evaluatePawns(const Position& pos, Color side, int& whiteMg, int& whiteEg, int& blackMg, int& blackEg) {
    Piece pawn = side == WHITE ? W_PAWN : B_PAWN;
    uint64_t pawns = pos.pieceBitboards[side][pieceTypeIndex(pawn)];
    int fileCounts[8] = {};

    uint64_t tmp = pawns;
    while (tmp) fileCounts[F(popLsb(tmp))]++;

    for (int file = 0; file < 8; ++file) {
        if (fileCounts[file] > 1) addToSide(side, DOUBLED_PAWN_PENALTY * (fileCounts[file] - 1), whiteMg, whiteEg, blackMg, blackEg);
    }

    tmp = pawns;
    while (tmp) {
        int sq = popLsb(tmp);
        int file = F(sq);
        if (pawnsInAdjacentFiles(pawns, file) == 0) {
            addToSide(side, ISOLATED_PAWN_PENALTY, whiteMg, whiteEg, blackMg, blackEg);
        }
        if (isPassedPawn(pos, side, sq)) {
            addToSide(side, passedPawnBonus(pos, side, sq), whiteMg, whiteEg, blackMg, blackEg);
        }
    }
}

void evaluatePieces(const Position& pos, Color side, int& whiteMg, int& whiteEg, int& blackMg, int& blackEg) {
    uint64_t occupied = pos.occupancy[side];
    while (occupied) {
        int sq = popLsb(occupied);
        Piece piece = pieceAt(pos, sq);
        addToSide(side, pieceValue(piece), whiteMg, whiteEg, blackMg, blackEg);
        addToSide(side, pieceSquareValue(piece, sq), whiteMg, whiteEg, blackMg, blackEg);
        addToSide(side, mobilityBonus(pos, side, piece, sq), whiteMg, whiteEg, blackMg, blackEg);
        if (pt(piece) == 4) addToSide(side, rookFileBonus(pos, side, sq), whiteMg, whiteEg, blackMg, blackEg);
    }

    Piece bishop = side == WHITE ? W_BISHOP : B_BISHOP;
    if (popcount(pos.pieceBitboards[side][pieceTypeIndex(bishop)]) >= 2) {
        addToSide(side, BISHOP_PAIR_BONUS, whiteMg, whiteEg, blackMg, blackEg);
    }

    addToSide(side, kingShieldBonus(pos, side), whiteMg, whiteEg, blackMg, blackEg);
    addToSide(side, kingZonePressure(pos, side), whiteMg, whiteEg, blackMg, blackEg);
}

}  // namespace

int evaluate(const Position& pos) {
    int whiteMg = 0;
    int whiteEg = 0;
    int blackMg = 0;
    int blackEg = 0;

    evaluatePieces(pos, WHITE, whiteMg, whiteEg, blackMg, blackEg);
    evaluatePieces(pos, BLACK, whiteMg, whiteEg, blackMg, blackEg);
    evaluatePawns(pos, WHITE, whiteMg, whiteEg, blackMg, blackEg);
    evaluatePawns(pos, BLACK, whiteMg, whiteEg, blackMg, blackEg);

    int phase = gamePhase(pos);
    int mgScore = whiteMg - blackMg;
    int egScore = whiteEg - blackEg;
    int blended = (mgScore * phase + egScore * (MAX_PHASE - phase)) / MAX_PHASE;
    return pos.sideToMove == WHITE ? blended + TEMPO_BONUS : -blended + TEMPO_BONUS;
}
