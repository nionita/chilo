#include "engine.h"
#include "generated/generated_nnue_weights.h"

#include <algorithm>
#include <cstdint>
#include <string_view>

namespace {

constexpr int NNUE_HIDDEN_SIZE = chilo::nnue_generated::kHiddenSize;
constexpr int NNUE_CLIP_MAX = chilo::nnue_generated::kClipMax;
constexpr int NNUE_INPUT_SCALE = chilo::nnue_generated::kInputScale;
constexpr int NNUE_OUTPUT_SCALE = chilo::nnue_generated::kOutputScale;
constexpr int NNUE_SCALED_CLIP_MAX = NNUE_CLIP_MAX * NNUE_INPUT_SCALE;
constexpr int64_t NNUE_FINAL_DIVISOR = static_cast<int64_t>(2) * NNUE_INPUT_SCALE * NNUE_OUTPUT_SCALE;

static_assert(std::string_view(chilo::nnue_generated::kContractId) == "chilo.tiny_nnue.v2",
              "Unexpected generated NNUE contract id");
static_assert(chilo::nnue_generated::kVersion == 2, "Unexpected generated NNUE contract version");
static_assert(chilo::nnue_generated::kPerspectiveCount == 2, "Unexpected generated NNUE perspective count");
static_assert(chilo::nnue_generated::kPiecePlaneCount == 13, "Unexpected generated NNUE piece plane count");
static_assert(chilo::nnue_generated::kSquareCount == 64, "Unexpected generated NNUE square count");

int popLsb(uint64_t& bits) {
    assert(bits != 0);
    int sq = __builtin_ctzll(bits);
    bits &= bits - 1;
    return sq;
}

const chilo::nnue_generated::TinyNnueData& tinyNnue() {
    return chilo::nnue_generated::kTinyNnue;
}

int clippedRelu(int value) {
    return std::clamp(value, 0, NNUE_SCALED_CLIP_MAX);
}

Color oppositeColor(Color color) {
    return color == WHITE ? BLACK : WHITE;
}

Color perspectiveColor(const Position& pos, int perspective) {
    return perspective == 0 ? pos.sideToMove : oppositeColor(pos.sideToMove);
}

int normalizeSquareForColor(int sq, Color color) {
    return color == WHITE ? sq : (sq ^ 56);
}

int relativePiecePlane(Piece piece, Color color) {
    assert(piece != EMPTY);
    int baseType = pt(piece);
    return pieceColor(piece) == color ? baseType : baseType + 6;
}

int roundDivide(int64_t value, int64_t divisor) {
    assert(divisor > 0);
    if (value >= 0) return static_cast<int>((value + divisor / 2) / divisor);
    return -static_cast<int>(((-value) + divisor / 2) / divisor);
}

int64_t perspectiveScore(const Position& pos, int perspective) {
    const auto& net = tinyNnue();
    int hidden[NNUE_HIDDEN_SIZE];
    for (int i = 0; i < NNUE_HIDDEN_SIZE; ++i) hidden[i] = net.hiddenBias[i];

    Color color = perspectiveColor(pos, perspective);
    uint64_t occupied = pos.occupancyAll;
    while (occupied) {
        int sq = popLsb(occupied);
        Piece piece = pieceAt(pos, sq);
        int relativePiece = relativePiecePlane(piece, color);
        int relativeSquare = normalizeSquareForColor(sq, color);
        const int16_t* weights = net.inputWeights[perspective][relativePiece][relativeSquare];
        for (int i = 0; i < NNUE_HIDDEN_SIZE; ++i) hidden[i] += weights[i];
    }

    int64_t score = net.outputBias;
    for (int i = 0; i < NNUE_HIDDEN_SIZE; ++i) score += static_cast<int64_t>(clippedRelu(hidden[i])) * net.outputWeights[i];
    return score;
}

}  // namespace

int evaluate(const Position& pos) {
    int64_t activePerspective = perspectiveScore(pos, 0);
    int64_t passivePerspective = perspectiveScore(pos, 1);
    return roundDivide(activePerspective - passivePerspective, NNUE_FINAL_DIVISOR);
}
