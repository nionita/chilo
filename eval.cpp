#include "engine.h"
#include "generated/generated_nnue_weights.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

namespace {

using chilo::nnue_generated::TinyNnueData;

constexpr char WEIGHTS_BIN_MAGIC[] = "CHNNUEB1";
constexpr std::size_t WEIGHTS_BIN_TEXT_FIELD_SIZE = 64;

struct RuntimeNnue {
    std::string contractId;
    std::string contractSha256;
    int version = 0;
    int hiddenSize = 0;
    int clipMax = 0;
    int inputScale = 0;
    int outputScale = 0;
    int perspectiveCount = 0;
    int piecePlaneCount = 0;
    int squareCount = 0;
    std::vector<int16_t> inputWeights;
    std::vector<int16_t> hiddenBias;
    std::vector<int16_t> outputWeights;
    int32_t outputBias = 0;
};

struct WeightsBinHeader {
    char magic[8];
    uint32_t hiddenSize;
    uint32_t clipMax;
    uint32_t inputScale;
    uint32_t outputScale;
    uint32_t perspectiveCount;
    uint32_t piecePlaneCount;
    uint32_t squareCount;
    char contractId[WEIGHTS_BIN_TEXT_FIELD_SIZE];
    char contractSha256[WEIGHTS_BIN_TEXT_FIELD_SIZE];
};

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

template <typename T>
bool readExact(std::ifstream& input, T& value) {
    input.read(reinterpret_cast<char*>(&value), sizeof(T));
    return input.good();
}

bool readExactBytes(std::ifstream& input, void* buffer, std::size_t size) {
    input.read(reinterpret_cast<char*>(buffer), static_cast<std::streamsize>(size));
    return input.good();
}

std::string trimFixedString(const char* text, std::size_t size) {
    std::size_t length = 0;
    while (length < size && text[length] != '\0') ++length;
    return std::string(text, length);
}

std::size_t checkedProduct(std::initializer_list<int> values, std::string& error) {
    std::size_t result = 1;
    for (int value : values) {
        if (value <= 0) {
            error = "NNUE dimensions must be positive";
            return 0;
        }
        if (result > std::numeric_limits<std::size_t>::max() / static_cast<std::size_t>(value)) {
            error = "NNUE dimensions overflow size_t";
            return 0;
        }
        result *= static_cast<std::size_t>(value);
    }
    return result;
}

RuntimeNnue builtInNnue() {
    const TinyNnueData& builtIn = chilo::nnue_generated::kTinyNnue;
    RuntimeNnue runtime;
    runtime.contractId = chilo::nnue_generated::kContractId;
    runtime.contractSha256 = chilo::nnue_generated::kContractSha256;
    runtime.version = chilo::nnue_generated::kVersion;
    runtime.hiddenSize = chilo::nnue_generated::kHiddenSize;
    runtime.clipMax = chilo::nnue_generated::kClipMax;
    runtime.inputScale = chilo::nnue_generated::kInputScale;
    runtime.outputScale = chilo::nnue_generated::kOutputScale;
    runtime.perspectiveCount = chilo::nnue_generated::kPerspectiveCount;
    runtime.piecePlaneCount = chilo::nnue_generated::kPiecePlaneCount;
    runtime.squareCount = chilo::nnue_generated::kSquareCount;
    runtime.inputWeights.assign(&builtIn.inputWeights[0][0][0][0],
                                &builtIn.inputWeights[0][0][0][0] +
                                    runtime.perspectiveCount * runtime.piecePlaneCount * runtime.squareCount * runtime.hiddenSize);
    runtime.hiddenBias.assign(&builtIn.hiddenBias[0], &builtIn.hiddenBias[0] + runtime.hiddenSize);
    runtime.outputWeights.assign(&builtIn.outputWeights[0], &builtIn.outputWeights[0] + runtime.hiddenSize);
    runtime.outputBias = builtIn.outputBias;
    return runtime;
}

RuntimeNnue& currentNnue() {
    static RuntimeNnue runtime = builtInNnue();
    return runtime;
}

uint64_t& currentNnueGeneration() {
    static uint64_t generation = 1;
    return generation;
}

bool validateRuntimeNnue(const RuntimeNnue& net, std::string& error) {
    if (net.contractId != chilo::nnue_generated::kContractId) {
        error = "NNUE contract id does not match the engine";
        return false;
    }
    if (net.contractSha256 != chilo::nnue_generated::kContractSha256) {
        error = "NNUE contract hash does not match the engine";
        return false;
    }
    if (net.clipMax != chilo::nnue_generated::kClipMax) {
        error = "NNUE clip max does not match the engine";
        return false;
    }
    if (net.perspectiveCount != chilo::nnue_generated::kPerspectiveCount ||
        net.piecePlaneCount != chilo::nnue_generated::kPiecePlaneCount ||
        net.squareCount != chilo::nnue_generated::kSquareCount) {
        error = "NNUE tensor dimensions do not match the engine";
        return false;
    }
    if (net.hiddenSize <= 0 || net.inputScale <= 0 || net.outputScale <= 0) {
        error = "NNUE metadata contains non-positive hidden size or scales";
        return false;
    }
    std::string productError;
    std::size_t inputCount = checkedProduct(
        {net.perspectiveCount, net.piecePlaneCount, net.squareCount, net.hiddenSize},
        productError);
    if (!productError.empty()) {
        error = productError;
        return false;
    }
    if (net.inputWeights.size() != inputCount) {
        error = "NNUE input weight payload size is inconsistent";
        return false;
    }
    if (net.hiddenBias.size() != static_cast<std::size_t>(net.hiddenSize) ||
        net.outputWeights.size() != static_cast<std::size_t>(net.hiddenSize)) {
        error = "NNUE hidden/output payload size is inconsistent";
        return false;
    }
    return true;
}

bool loadRuntimeNnueFromFile(const std::string& path, RuntimeNnue& outNet, std::string& error) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        error = "unable to open NNUE weights file";
        return false;
    }

    WeightsBinHeader header{};
    if (!readExact(input, header)) {
        error = "unable to read NNUE binary header";
        return false;
    }
    if (std::string_view(header.magic, sizeof(header.magic)) != std::string_view(WEIGHTS_BIN_MAGIC, sizeof(header.magic))) {
        error = "NNUE binary magic mismatch";
        return false;
    }

    RuntimeNnue net;
    net.contractId = trimFixedString(header.contractId, sizeof(header.contractId));
    net.contractSha256 = trimFixedString(header.contractSha256, sizeof(header.contractSha256));
    net.version = chilo::nnue_generated::kVersion;
    net.hiddenSize = static_cast<int>(header.hiddenSize);
    net.clipMax = static_cast<int>(header.clipMax);
    net.inputScale = static_cast<int>(header.inputScale);
    net.outputScale = static_cast<int>(header.outputScale);
    net.perspectiveCount = static_cast<int>(header.perspectiveCount);
    net.piecePlaneCount = static_cast<int>(header.piecePlaneCount);
    net.squareCount = static_cast<int>(header.squareCount);

    std::string productError;
    std::size_t inputCount = checkedProduct(
        {net.perspectiveCount, net.piecePlaneCount, net.squareCount, net.hiddenSize},
        productError);
    if (!productError.empty()) {
        error = productError;
        return false;
    }

    net.inputWeights.resize(inputCount);
    net.hiddenBias.resize(static_cast<std::size_t>(net.hiddenSize));
    net.outputWeights.resize(static_cast<std::size_t>(net.hiddenSize));
    if (!readExactBytes(input, net.inputWeights.data(), net.inputWeights.size() * sizeof(int16_t)) ||
        !readExactBytes(input, net.hiddenBias.data(), net.hiddenBias.size() * sizeof(int16_t)) ||
        !readExactBytes(input, net.outputWeights.data(), net.outputWeights.size() * sizeof(int16_t)) ||
        !readExact(input, net.outputBias)) {
        error = "NNUE binary payload is truncated";
        return false;
    }

    char extra = 0;
    if (input.read(&extra, 1)) {
        error = "NNUE binary payload has unexpected trailing bytes";
        return false;
    }
    if (!input.eof()) {
        error = "NNUE binary payload did not finish cleanly";
        return false;
    }

    if (!validateRuntimeNnue(net, error)) return false;
    outNet = std::move(net);
    return true;
}

int clippedRelu(int value, int scaledClipMax) {
    return std::clamp(value, 0, scaledClipMax);
}

Color oppositeColor(Color color) {
    return color == WHITE ? BLACK : WHITE;
}

int normalizeSquareForColor(int sq, Color color) {
    return color == WHITE ? sq : (sq ^ 56);
}

int relativePiecePlane(Piece piece, Color color) {
    assert(piece != EMPTY);
    int baseType = pt(piece);
    return pieceColor(piece) == color ? baseType : baseType + 6;
}

std::size_t inputWeightOffset(const RuntimeNnue& net, int perspective, Color color, Piece piece, int sq) {
    int relativePiece = relativePiecePlane(piece, color);
    int relativeSquare = normalizeSquareForColor(sq, color);
    return (((static_cast<std::size_t>(perspective) * net.piecePlaneCount + static_cast<std::size_t>(relativePiece)) *
                 net.squareCount +
             static_cast<std::size_t>(relativeSquare)) *
            net.hiddenSize);
}

std::size_t accumulatorOffset(const RuntimeNnue& net, Color color, int perspective) {
    return (static_cast<std::size_t>(color) * net.perspectiveCount + static_cast<std::size_t>(perspective)) *
           net.hiddenSize;
}

std::size_t accumulatorValueCount(const RuntimeNnue& net) {
    return static_cast<std::size_t>(net.perspectiveCount) * 2 * net.hiddenSize;
}

bool accumulatorMatchesCurrentNet(const NnueAccumulator& acc, const RuntimeNnue& net) {
    return acc.valid && acc.generation == currentNnueGeneration() && acc.hiddenSize == net.hiddenSize &&
           acc.values.size() == accumulatorValueCount(net);
}

int roundDivide(int64_t value, int64_t divisor) {
    assert(divisor > 0);
    if (value >= 0) return static_cast<int>((value + divisor / 2) / divisor);
    return -static_cast<int>(((-value) + divisor / 2) / divisor);
}

void updateAccumulatorFeature(NnueAccumulator& acc, Piece piece, int sq, int sign) {
    assert(piece != EMPTY);
    assert(sign == 1 || sign == -1);
    const RuntimeNnue& net = currentNnue();
    if (!accumulatorMatchesCurrentNet(acc, net)) return;

    for (int colorValue = WHITE; colorValue <= BLACK; ++colorValue) {
        Color color = static_cast<Color>(colorValue);
        for (int perspective = 0; perspective < net.perspectiveCount; ++perspective) {
            const int16_t* weights = net.inputWeights.data() + inputWeightOffset(net, perspective, color, piece, sq);
            int32_t* lane = acc.values.data() + accumulatorOffset(net, color, perspective);
            for (int i = 0; i < net.hiddenSize; ++i) lane[i] += sign * weights[i];
        }
    }
}

void updateAccumulatorForMove(const Position& pos, const Move& move, NnueAccumulator& acc, int sign) {
    assert(sign == 1 || sign == -1);
    Piece movingPiece = pieceAt(pos, move.from);
    assert(movingPiece != EMPTY);

    updateAccumulatorFeature(acc, movingPiece, move.from, -sign);

    if (move.isEnPassant) {
        int capR = pos.sideToMove == WHITE ? R(move.to) - 1 : R(move.to) + 1;
        int capSq = capR * 8 + F(move.to);
        Piece capturedPawn = pos.sideToMove == WHITE ? B_PAWN : W_PAWN;
        updateAccumulatorFeature(acc, capturedPawn, capSq, -sign);
    } else {
        Piece capturedPiece = pieceAt(pos, move.to);
        if (capturedPiece != EMPTY) updateAccumulatorFeature(acc, capturedPiece, move.to, -sign);
    }

    Piece placedPiece = move.promotion != EMPTY ? move.promotion : movingPiece;
    updateAccumulatorFeature(acc, placedPiece, move.to, sign);

    if (move.isCastle) {
        int rank = R(move.to);
        Piece rook = pos.sideToMove == WHITE ? W_ROOK : B_ROOK;
        if (F(move.to) == 6) {
            updateAccumulatorFeature(acc, rook, rank * 8 + 7, -sign);
            updateAccumulatorFeature(acc, rook, rank * 8 + 5, sign);
        } else if (F(move.to) == 2) {
            updateAccumulatorFeature(acc, rook, rank * 8 + 0, -sign);
            updateAccumulatorFeature(acc, rook, rank * 8 + 3, sign);
        }
    }
}

int64_t scoreFromLane(const int32_t* hidden) {
    const RuntimeNnue& net = currentNnue();

    const int scaledClipMax = net.clipMax * net.inputScale;
    int64_t score = net.outputBias;
    for (int i = 0; i < net.hiddenSize; ++i) {
        score += static_cast<int64_t>(clippedRelu(hidden[i], scaledClipMax)) *
                 net.outputWeights[static_cast<std::size_t>(i)];
    }
    return score;
}

int64_t perspectiveScore(const Position& pos, int perspective) {
    const RuntimeNnue& net = currentNnue();
    thread_local std::vector<int32_t> hidden;
    hidden.assign(net.hiddenBias.begin(), net.hiddenBias.end());

    Color color = perspective == 0 ? pos.sideToMove : oppositeColor(pos.sideToMove);
    uint64_t occupied = pos.occupancyAll;
    while (occupied) {
        int sq = popLsb(occupied);
        Piece piece = pieceAt(pos, sq);
        const int16_t* weights = net.inputWeights.data() + inputWeightOffset(net, perspective, color, piece, sq);
        for (int i = 0; i < net.hiddenSize; ++i) hidden[static_cast<std::size_t>(i)] += weights[i];
    }

    return scoreFromLane(hidden.data());
}

}  // namespace

bool loadNnueWeightsFile(const std::string& path, std::string& error) {
    RuntimeNnue loaded;
    if (!loadRuntimeNnueFromFile(path, loaded, error)) return false;
    currentNnue() = std::move(loaded);
    ++currentNnueGeneration();
    return true;
}

void initNnueAccumulator(const Position& pos, NnueAccumulator& acc) {
    const RuntimeNnue& net = currentNnue();
    acc.generation = currentNnueGeneration();
    acc.hiddenSize = net.hiddenSize;
    acc.valid = true;
    acc.values.resize(accumulatorValueCount(net));

    for (int colorValue = WHITE; colorValue <= BLACK; ++colorValue) {
        Color color = static_cast<Color>(colorValue);
        for (int perspective = 0; perspective < net.perspectiveCount; ++perspective) {
            int32_t* lane = acc.values.data() + accumulatorOffset(net, color, perspective);
            for (int i = 0; i < net.hiddenSize; ++i) lane[i] = net.hiddenBias[static_cast<std::size_t>(i)];
        }
    }

    uint64_t occupied = pos.occupancyAll;
    while (occupied) {
        int sq = popLsb(occupied);
        Piece piece = pieceAt(pos, sq);
        updateAccumulatorFeature(acc, piece, sq, 1);
    }
}

void applyNnueMove(const Position& pos, const Move& move, NnueAccumulator& acc) {
    updateAccumulatorForMove(pos, move, acc, 1);
}

void undoNnueMove(const Position& pos, const Move& move, NnueAccumulator& acc) {
    updateAccumulatorForMove(pos, move, acc, -1);
}

int evaluateWithAccumulator(const Position& pos, const NnueAccumulator& acc) {
    const RuntimeNnue& net = currentNnue();
    if (!accumulatorMatchesCurrentNet(acc, net)) {
        return evaluate(pos);
    }

    Color passiveSide = oppositeColor(pos.sideToMove);
    const int32_t* activeHidden = acc.values.data() + accumulatorOffset(net, pos.sideToMove, 0);
    const int32_t* passiveHidden = acc.values.data() + accumulatorOffset(net, passiveSide, 1);
    int64_t activePerspective = scoreFromLane(activeHidden);
    int64_t passivePerspective = scoreFromLane(passiveHidden);
    int64_t finalDivisor = static_cast<int64_t>(2) * net.inputScale * net.outputScale;
    return roundDivide(activePerspective - passivePerspective, finalDivisor);
}

int evaluate(const Position& pos) {
    const RuntimeNnue& net = currentNnue();
    int64_t activePerspective = perspectiveScore(pos, 0);
    int64_t passivePerspective = perspectiveScore(pos, 1);
    int64_t finalDivisor = static_cast<int64_t>(2) * net.inputScale * net.outputScale;
    return roundDivide(activePerspective - passivePerspective, finalDivisor);
}
