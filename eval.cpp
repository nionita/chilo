#include "engine.h"

#include <algorithm>
#include <cstdint>

namespace {

constexpr int NNUE_HIDDEN_SIZE = 16;
constexpr int NNUE_CLIP_MAX = 255;
constexpr int FRIENDLY_COUNT_BASE = 0;
constexpr int ENEMY_COUNT_BASE = 5;
constexpr int FRIENDLY_PST_UNIT = 10;
constexpr int ENEMY_PST_UNIT = 11;
constexpr int FRIENDLY_PAWN_ADVANCE_UNIT = 12;
constexpr int ENEMY_PAWN_ADVANCE_UNIT = 13;
constexpr int FRIENDLY_BISHOP_PAIR_UNIT = 14;
constexpr int ENEMY_BISHOP_PAIR_UNIT = 15;

struct TinyNnue {
    int16_t inputWeights[2][13][64][NNUE_HIDDEN_SIZE]{};
    int16_t hiddenBias[NNUE_HIDDEN_SIZE]{};
    int16_t outputWeights[NNUE_HIDDEN_SIZE]{};
    int16_t outputBias = 0;
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

int normalizedSquare(Piece piece, int sq) {
    return wh(piece) ? sq : mirrorSquare(sq);
}

int fileCentrality(int sq) {
    int file = F(sq);
    int distance = std::min(std::abs(file - 3), std::abs(file - 4));
    return 3 - distance;
}

int rankCentrality(int sq) {
    int rank = R(sq);
    int distance = std::min(std::abs(rank - 3), std::abs(rank - 4));
    return 3 - distance;
}

int centrality(int sq) {
    return fileCentrality(sq) + rankCentrality(sq);
}

int pieceSquareWeight(int pieceType, int sq) {
    switch (pieceType) {
        case 1:
            return R(sq) * 4 + fileCentrality(sq) * 2 - (R(sq) == 1 ? 2 : 0);
        case 2:
            return centrality(sq) * 8 - 12;
        case 3:
            return centrality(sq) * 5 + R(sq) * 2 - 10;
        case 4:
            return R(sq) * 2 + fileCentrality(sq) * 2 - 6;
        case 5:
            return centrality(sq) * 3 + R(sq) - 8;
        case 6:
            return (7 - R(sq)) * 4 + (fileCentrality(sq) == 0 ? 6 : 0) - centrality(sq) * 2 - 10;
        default:
            return 0;
    }
}

int pawnAdvanceWeight(int sq) {
    return R(sq) * 4;
}

TinyNnue initTinyNnue() {
    TinyNnue net{};
    net.hiddenBias[FRIENDLY_PST_UNIT] = 128;
    net.hiddenBias[ENEMY_PST_UNIT] = 128;
    net.hiddenBias[FRIENDLY_PAWN_ADVANCE_UNIT] = 128;
    net.hiddenBias[ENEMY_PAWN_ADVANCE_UNIT] = 128;
    net.hiddenBias[FRIENDLY_BISHOP_PAIR_UNIT] = -64;
    net.hiddenBias[ENEMY_BISHOP_PAIR_UNIT] = -64;

    net.outputWeights[FRIENDLY_COUNT_BASE + 0] = 100;
    net.outputWeights[FRIENDLY_COUNT_BASE + 1] = 320;
    net.outputWeights[FRIENDLY_COUNT_BASE + 2] = 330;
    net.outputWeights[FRIENDLY_COUNT_BASE + 3] = 500;
    net.outputWeights[FRIENDLY_COUNT_BASE + 4] = 900;
    net.outputWeights[ENEMY_COUNT_BASE + 0] = -100;
    net.outputWeights[ENEMY_COUNT_BASE + 1] = -320;
    net.outputWeights[ENEMY_COUNT_BASE + 2] = -330;
    net.outputWeights[ENEMY_COUNT_BASE + 3] = -500;
    net.outputWeights[ENEMY_COUNT_BASE + 4] = -900;
    net.outputWeights[FRIENDLY_PST_UNIT] = 1;
    net.outputWeights[ENEMY_PST_UNIT] = -1;
    net.outputWeights[FRIENDLY_PAWN_ADVANCE_UNIT] = 1;
    net.outputWeights[ENEMY_PAWN_ADVANCE_UNIT] = -1;
    net.outputWeights[FRIENDLY_BISHOP_PAIR_UNIT] = 1;
    net.outputWeights[ENEMY_BISHOP_PAIR_UNIT] = -1;

    for (int perspective = 0; perspective < 2; ++perspective) {
        for (int pieceValue = W_PAWN; pieceValue <= B_KING; ++pieceValue) {
            Piece piece = static_cast<Piece>(pieceValue);
            bool friendly = pieceColor(piece) == static_cast<Color>(perspective);
            int pieceType = pt(piece);

            for (int sq = 0; sq < 64; ++sq) {
                int normalizedSq = normalizedSquare(piece, sq);
                int16_t* weights = net.inputWeights[perspective][pieceValue][sq];

                if (pieceType >= 1 && pieceType <= 5) {
                    int unit = friendly ? FRIENDLY_COUNT_BASE + (pieceType - 1)
                                        : ENEMY_COUNT_BASE + (pieceType - 1);
                    weights[unit] = 1;
                }

                int pstUnit = friendly ? FRIENDLY_PST_UNIT : ENEMY_PST_UNIT;
                weights[pstUnit] += static_cast<int16_t>(pieceSquareWeight(pieceType, normalizedSq));

                if (pieceType == 1) {
                    int pawnUnit = friendly ? FRIENDLY_PAWN_ADVANCE_UNIT : ENEMY_PAWN_ADVANCE_UNIT;
                    weights[pawnUnit] += static_cast<int16_t>(pawnAdvanceWeight(normalizedSq));
                }

                if (pieceType == 3) {
                    int pairUnit = friendly ? FRIENDLY_BISHOP_PAIR_UNIT : ENEMY_BISHOP_PAIR_UNIT;
                    weights[pairUnit] += 64;
                }
            }
        }
    }

    return net;
}

const TinyNnue& tinyNnue() {
    static const TinyNnue net = initTinyNnue();
    return net;
}

int clippedRelu(int value) {
    return std::clamp(value, 0, NNUE_CLIP_MAX);
}

int perspectiveScore(const Position& pos, Color perspective) {
    const TinyNnue& net = tinyNnue();
    int hidden[NNUE_HIDDEN_SIZE];
    for (int i = 0; i < NNUE_HIDDEN_SIZE; ++i) hidden[i] = net.hiddenBias[i];

    uint64_t occupied = pos.occupancyAll;
    while (occupied) {
        int sq = popLsb(occupied);
        Piece piece = pieceAt(pos, sq);
        const int16_t* weights = net.inputWeights[perspective][piece][sq];
        for (int i = 0; i < NNUE_HIDDEN_SIZE; ++i) hidden[i] += weights[i];
    }

    int score = net.outputBias;
    for (int i = 0; i < NNUE_HIDDEN_SIZE; ++i) score += clippedRelu(hidden[i]) * net.outputWeights[i];
    return score;
}

}  // namespace

int evaluate(const Position& pos) {
    int whitePerspective = perspectiveScore(pos, WHITE);
    int blackPerspective = perspectiveScore(pos, BLACK);
    int score = (whitePerspective - blackPerspective) / 2;
    return pos.sideToMove == WHITE ? score : -score;
}
