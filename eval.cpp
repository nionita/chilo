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

#if defined(CHILO_AVX2)
#if !defined(__AVX2__)
#error "CHILO_AVX2 requires compiling with AVX2 enabled"
#endif
#include <immintrin.h>
#endif

namespace {

using chilo::nnue_generated::TinyNnueData;

constexpr char WEIGHTS_BIN_MAGIC[] = "CHNNUEB4";
constexpr std::size_t WEIGHTS_BIN_TEXT_FIELD_SIZE = 64;
constexpr int BYTE_ACTIVATION_SCALE = 127;

struct RuntimeNnue {
    std::string contractId;
    std::string contractSha256;
    int version = 0;
    int hiddenSize = 0;
    int hidden2Size = 0;
    int clipMax = 0;
    int inputScale = 0;
    int hiddenScale = 0;
    int outputScale = 0;
    int activationScale = 0;
    int perspectiveCount = 0;
    int piecePlaneCount = 0;
    int squareCount = 0;
    std::vector<int16_t> inputWeights;
    std::vector<int16_t> hiddenBias;
    std::vector<int8_t> hidden2Weights;
    std::vector<int32_t> hidden2Bias;
    std::vector<int8_t> outputWeights;
    int32_t outputBias = 0;
};

struct WeightsBinHeader {
    char magic[8];
    uint32_t hiddenSize;
    uint32_t hidden2Size;
    uint32_t clipMax;
    uint32_t inputScale;
    uint32_t hiddenScale;
    uint32_t outputScale;
    uint32_t activationScale;
    uint32_t perspectiveCount;
    uint32_t piecePlaneCount;
    uint32_t squareCount;
    char contractId[WEIGHTS_BIN_TEXT_FIELD_SIZE];
    char contractSha256[WEIGHTS_BIN_TEXT_FIELD_SIZE];
};

static_assert(std::string_view(chilo::nnue_generated::kContractId) == "chilo.tiny_nnue.v4",
              "Unexpected generated NNUE contract id");
static_assert(chilo::nnue_generated::kVersion == 4, "Unexpected generated NNUE contract version");
static_assert(chilo::nnue_generated::kActivationScale == BYTE_ACTIVATION_SCALE,
              "Unexpected generated NNUE activation scale");
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
    runtime.hidden2Size = chilo::nnue_generated::kHidden2Size;
    runtime.clipMax = chilo::nnue_generated::kClipMax;
    runtime.inputScale = chilo::nnue_generated::kInputScale;
    runtime.hiddenScale = chilo::nnue_generated::kHiddenScale;
    runtime.outputScale = chilo::nnue_generated::kOutputScale;
    runtime.activationScale = chilo::nnue_generated::kActivationScale;
    runtime.perspectiveCount = chilo::nnue_generated::kPerspectiveCount;
    runtime.piecePlaneCount = chilo::nnue_generated::kPiecePlaneCount;
    runtime.squareCount = chilo::nnue_generated::kSquareCount;
    runtime.inputWeights.assign(&builtIn.inputWeights[0][0][0],
                                &builtIn.inputWeights[0][0][0] +
                                    runtime.piecePlaneCount * runtime.squareCount * runtime.hiddenSize);
    runtime.hiddenBias.assign(&builtIn.hiddenBias[0], &builtIn.hiddenBias[0] + runtime.hiddenSize);
    runtime.hidden2Weights.assign(&builtIn.hidden2Weights[0][0],
                                  &builtIn.hidden2Weights[0][0] +
                                      runtime.hidden2Size * 2 * runtime.hiddenSize);
    runtime.hidden2Bias.assign(&builtIn.hidden2Bias[0], &builtIn.hidden2Bias[0] + runtime.hidden2Size);
    runtime.outputWeights.assign(&builtIn.outputWeights[0],
                                 &builtIn.outputWeights[0] + chilo::nnue_generated::kOutputSize);
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
    if (net.hiddenSize <= 0 || net.hidden2Size <= 0 || net.inputScale <= 0 || net.hiddenScale <= 0 ||
        net.outputScale <= 0 || net.activationScale <= 0 || net.activationScale > BYTE_ACTIVATION_SCALE) {
        error = "NNUE metadata contains non-positive hidden size or scales";
        return false;
    }
    std::string productError;
    std::size_t inputCount = checkedProduct({net.piecePlaneCount, net.squareCount, net.hiddenSize}, productError);
    if (!productError.empty()) {
        error = productError;
        return false;
    }
    if (net.inputWeights.size() != inputCount) {
        error = "NNUE input weight payload size is inconsistent";
        return false;
    }
    std::size_t hidden2WeightCount = checkedProduct({net.hidden2Size, 2 * net.hiddenSize}, productError);
    if (!productError.empty()) {
        error = productError;
        return false;
    }
    if (net.hiddenBias.size() != static_cast<std::size_t>(net.hiddenSize) ||
        net.hidden2Weights.size() != hidden2WeightCount ||
        net.hidden2Bias.size() != static_cast<std::size_t>(net.hidden2Size) ||
        net.outputWeights.size() != static_cast<std::size_t>(net.hidden2Size)) {
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
    net.hidden2Size = static_cast<int>(header.hidden2Size);
    net.clipMax = static_cast<int>(header.clipMax);
    net.inputScale = static_cast<int>(header.inputScale);
    net.hiddenScale = static_cast<int>(header.hiddenScale);
    net.outputScale = static_cast<int>(header.outputScale);
    net.activationScale = static_cast<int>(header.activationScale);
    net.perspectiveCount = static_cast<int>(header.perspectiveCount);
    net.piecePlaneCount = static_cast<int>(header.piecePlaneCount);
    net.squareCount = static_cast<int>(header.squareCount);

    std::string productError;
    std::size_t inputCount = checkedProduct({net.piecePlaneCount, net.squareCount, net.hiddenSize}, productError);
    if (!productError.empty()) {
        error = productError;
        return false;
    }

    net.inputWeights.resize(inputCount);
    net.hiddenBias.resize(static_cast<std::size_t>(net.hiddenSize));
    std::size_t hidden2WeightCount = checkedProduct({net.hidden2Size, 2 * net.hiddenSize}, productError);
    if (!productError.empty()) {
        error = productError;
        return false;
    }
    net.hidden2Weights.resize(hidden2WeightCount);
    net.hidden2Bias.resize(static_cast<std::size_t>(net.hidden2Size));
    net.outputWeights.resize(static_cast<std::size_t>(net.hidden2Size));
    if (!readExactBytes(input, net.inputWeights.data(), net.inputWeights.size() * sizeof(int16_t)) ||
        !readExactBytes(input, net.hiddenBias.data(), net.hiddenBias.size() * sizeof(int16_t)) ||
        !readExactBytes(input, net.hidden2Weights.data(), net.hidden2Weights.size() * sizeof(int8_t)) ||
        !readExactBytes(input, net.hidden2Bias.data(), net.hidden2Bias.size() * sizeof(int32_t)) ||
        !readExactBytes(input, net.outputWeights.data(), net.outputWeights.size() * sizeof(int8_t)) ||
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

int roundDividePositive(int64_t value, int64_t divisor) {
    assert(value >= 0);
    assert(divisor > 0);
    return static_cast<int>((value + divisor / 2) / divisor);
}

uint8_t byteActivationFromScaledValue(int64_t value, int64_t scaledClipMax, int activationScale) {
    int64_t clipped = std::clamp<int64_t>(value, 0, scaledClipMax);
    int activated = roundDividePositive(clipped * activationScale, scaledClipMax);
    return static_cast<uint8_t>(std::clamp(activated, 0, activationScale));
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

std::size_t inputWeightOffset(const RuntimeNnue& net, Color color, Piece piece, int sq) {
    int relativePiece = relativePiecePlane(piece, color);
    int relativeSquare = normalizeSquareForColor(sq, color);
    return ((static_cast<std::size_t>(relativePiece) * net.squareCount +
             static_cast<std::size_t>(relativeSquare)) *
            net.hiddenSize);
}

std::size_t accumulatorOffset(const RuntimeNnue& net, Color color) {
    return static_cast<std::size_t>(color) * net.hiddenSize;
}

std::size_t accumulatorValueCount(const RuntimeNnue& net) {
    return static_cast<std::size_t>(net.perspectiveCount) * net.hiddenSize;
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

void addWeightsToLane(int32_t* lane, const int16_t* weights, int hiddenSize) {
#if defined(CHILO_AVX2)
    int i = 0;
    for (; i + 8 <= hiddenSize; i += 8) {
        const __m128i packedWeights = _mm_loadu_si128(reinterpret_cast<const __m128i*>(weights + i));
        const __m256i expandedWeights = _mm256_cvtepi16_epi32(packedWeights);
        __m256i laneValues = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(lane + i));
        laneValues = _mm256_add_epi32(laneValues, expandedWeights);
        _mm256_storeu_si256(reinterpret_cast<__m256i*>(lane + i), laneValues);
    }
    for (; i < hiddenSize; ++i) lane[i] += weights[i];
#else
    for (int i = 0; i < hiddenSize; ++i) lane[i] += weights[i];
#endif
}

void subWeightsFromLane(int32_t* lane, const int16_t* weights, int hiddenSize) {
#if defined(CHILO_AVX2)
    int i = 0;
    for (; i + 8 <= hiddenSize; i += 8) {
        const __m128i packedWeights = _mm_loadu_si128(reinterpret_cast<const __m128i*>(weights + i));
        const __m256i expandedWeights = _mm256_cvtepi16_epi32(packedWeights);
        __m256i laneValues = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(lane + i));
        laneValues = _mm256_sub_epi32(laneValues, expandedWeights);
        _mm256_storeu_si256(reinterpret_cast<__m256i*>(lane + i), laneValues);
    }
    for (; i < hiddenSize; ++i) lane[i] -= weights[i];
#else
    for (int i = 0; i < hiddenSize; ++i) lane[i] -= weights[i];
#endif
}

void buildDenseInput(const int32_t* first, const int32_t* second, uint8_t* denseInput, int hiddenSize,
                     int scaledClipMax, int activationScale) {
    for (int i = 0; i < hiddenSize; ++i) {
        denseInput[i] = byteActivationFromScaledValue(first[i], scaledClipMax, activationScale);
        denseInput[hiddenSize + i] = byteActivationFromScaledValue(second[i], scaledClipMax, activationScale);
    }
}

int32_t dotByteDenseInput(const uint8_t* input, const int8_t* weights, int inputSize) {
    int32_t sum = 0;
#if defined(CHILO_AVX2)
    int i = 0;
    const __m256i ones = _mm256_set1_epi16(1);
    __m256i acc = _mm256_setzero_si256();
    for (; i + 32 <= inputSize; i += 32) {
        const __m256i values = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(input + i));
        const __m256i packedWeights = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(weights + i));
        const __m256i product16 = _mm256_maddubs_epi16(values, packedWeights);
        const __m256i product32 = _mm256_madd_epi16(product16, ones);
        acc = _mm256_add_epi32(acc, product32);
    }
    const __m128i sum128 = _mm_add_epi32(_mm256_castsi256_si128(acc), _mm256_extracti128_si256(acc, 1));
    const __m128i sum64 = _mm_add_epi32(sum128, _mm_shuffle_epi32(sum128, _MM_SHUFFLE(1, 0, 3, 2)));
    const __m128i sum32 = _mm_add_epi32(sum64, _mm_shuffle_epi32(sum64, _MM_SHUFFLE(2, 3, 0, 1)));
    sum = _mm_cvtsi128_si32(sum32);
    for (; i < inputSize; ++i) sum += static_cast<int32_t>(input[i]) * weights[i];
#else
    for (int i = 0; i < inputSize; ++i) sum += static_cast<int32_t>(input[i]) * weights[i];
#endif
    return sum;
}

void updateAccumulatorFeatureUnchecked(const RuntimeNnue& net, NnueAccumulator& acc, Piece piece, int sq, bool add) {
    assert(piece != EMPTY);
    assert(net.perspectiveCount == 2);
    assert(net.piecePlaneCount == 13);
    assert(net.squareCount == 64);

    const int hiddenSize = net.hiddenSize;
    const std::size_t hidden = static_cast<std::size_t>(hiddenSize);
    const std::size_t planeStride = static_cast<std::size_t>(net.squareCount) * hidden;

    const int whitePlane = relativePiecePlane(piece, WHITE);
    const int blackPlane = relativePiecePlane(piece, BLACK);
    const int whiteSquare = normalizeSquareForColor(sq, WHITE);
    const int blackSquare = normalizeSquareForColor(sq, BLACK);
    const int16_t* input = net.inputWeights.data();

    const int16_t* whiteWeights =
        input + static_cast<std::size_t>(whitePlane) * planeStride + static_cast<std::size_t>(whiteSquare) * hidden;
    const int16_t* blackWeights =
        input + static_cast<std::size_t>(blackPlane) * planeStride + static_cast<std::size_t>(blackSquare) * hidden;

    int32_t* values = acc.values.data();
    int32_t* whiteLane = values;
    int32_t* blackLane = values + hidden;

    if (add) {
        addWeightsToLane(whiteLane, whiteWeights, hiddenSize);
        addWeightsToLane(blackLane, blackWeights, hiddenSize);
    } else {
        subWeightsFromLane(whiteLane, whiteWeights, hiddenSize);
        subWeightsFromLane(blackLane, blackWeights, hiddenSize);
    }
}

void appendDelta(NnueMoveDelta& delta, Piece piece, int sq, int sign) {
    assert(piece != EMPTY);
    assert(sq >= 0 && sq < 64);
    assert(sign == 1 || sign == -1);
    assert(delta.count < 4);
    delta.changes[delta.count++] = NnueFeatureDelta{piece, static_cast<uint8_t>(sq), static_cast<int8_t>(sign)};
}

NnueMoveDelta buildMoveDelta(const Position& pos, const Move& move) {
    NnueMoveDelta delta{};
    Piece movingPiece = pieceAt(pos, move.from);
    assert(movingPiece != EMPTY);

    appendDelta(delta, movingPiece, move.from, -1);

    if (move.isEnPassant) {
        int capR = pos.sideToMove == WHITE ? R(move.to) - 1 : R(move.to) + 1;
        int capSq = capR * 8 + F(move.to);
        Piece capturedPawn = pos.sideToMove == WHITE ? B_PAWN : W_PAWN;
        appendDelta(delta, capturedPawn, capSq, -1);
    } else {
        Piece capturedPiece = pieceAt(pos, move.to);
        if (capturedPiece != EMPTY) appendDelta(delta, capturedPiece, move.to, -1);
    }

    Piece placedPiece = move.promotion != EMPTY ? move.promotion : movingPiece;
    appendDelta(delta, placedPiece, move.to, 1);

    if (move.isCastle) {
        int rank = R(move.to);
        Piece rook = pos.sideToMove == WHITE ? W_ROOK : B_ROOK;
        if (F(move.to) == 6) {
            appendDelta(delta, rook, rank * 8 + 7, -1);
            appendDelta(delta, rook, rank * 8 + 5, 1);
        } else if (F(move.to) == 2) {
            appendDelta(delta, rook, rank * 8 + 0, -1);
            appendDelta(delta, rook, rank * 8 + 3, 1);
        }
    }

    return delta;
}

int64_t scoreFromLanes(const int32_t* first, const int32_t* second) {
    const RuntimeNnue& net = currentNnue();

    const int scaledClipMax = net.clipMax * net.inputScale;
    const int64_t scaledHidden2ClipMax = static_cast<int64_t>(net.clipMax) * net.hiddenScale;
    int64_t score = net.outputBias;
    const int denseInputSize = 2 * net.hiddenSize;
    thread_local std::vector<uint8_t> denseInput;
    denseInput.resize(static_cast<std::size_t>(denseInputSize));
    buildDenseInput(first, second, denseInput.data(), net.hiddenSize, scaledClipMax, net.activationScale);

    for (int h = 0; h < net.hidden2Size; ++h) {
        const int8_t* weights =
            net.hidden2Weights.data() + static_cast<std::size_t>(h) * static_cast<std::size_t>(denseInputSize);
        int64_t hidden2Value = net.hidden2Bias[static_cast<std::size_t>(h)];
        hidden2Value += dotByteDenseInput(denseInput.data(), weights, denseInputSize);
        const uint8_t hidden2Activation =
            byteActivationFromScaledValue(hidden2Value, scaledHidden2ClipMax, net.activationScale);
        score += static_cast<int32_t>(hidden2Activation) * net.outputWeights[static_cast<std::size_t>(h)];
    }
    return score;
}

void buildAccumulatorLane(const Position& pos, Color color, std::vector<int32_t>& hidden) {
    const RuntimeNnue& net = currentNnue();
    hidden.assign(net.hiddenBias.begin(), net.hiddenBias.end());

    uint64_t occupied = pos.occupancyAll;
    while (occupied) {
        int sq = popLsb(occupied);
        Piece piece = pieceAt(pos, sq);
        const int16_t* weights = net.inputWeights.data() + inputWeightOffset(net, color, piece, sq);
        for (int i = 0; i < net.hiddenSize; ++i) hidden[static_cast<std::size_t>(i)] += weights[i];
    }
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
        int32_t* lane = acc.values.data() + accumulatorOffset(net, color);
        for (int i = 0; i < net.hiddenSize; ++i) lane[i] = net.hiddenBias[static_cast<std::size_t>(i)];
    }

    uint64_t occupied = pos.occupancyAll;
    while (occupied) {
        int sq = popLsb(occupied);
        Piece piece = pieceAt(pos, sq);
        updateAccumulatorFeatureUnchecked(net, acc, piece, sq, true);
    }
}

NnueMoveDelta makeNnueMoveDelta(const Position& pos, const Move& move) {
    return buildMoveDelta(pos, move);
}

void applyNnueDelta(NnueAccumulator& acc, const NnueMoveDelta& delta) {
    const RuntimeNnue& net = currentNnue();
    if (!accumulatorMatchesCurrentNet(acc, net)) return;

    for (int i = 0; i < delta.count; ++i) {
        const NnueFeatureDelta& change = delta.changes[i];
        updateAccumulatorFeatureUnchecked(net, acc, change.piece, change.square, change.sign > 0);
    }
}

void undoNnueDelta(NnueAccumulator& acc, const NnueMoveDelta& delta) {
    const RuntimeNnue& net = currentNnue();
    if (!accumulatorMatchesCurrentNet(acc, net)) return;

    for (int i = static_cast<int>(delta.count) - 1; i >= 0; --i) {
        const NnueFeatureDelta& change = delta.changes[i];
        updateAccumulatorFeatureUnchecked(net, acc, change.piece, change.square, change.sign < 0);
    }
}

void applyNnueMove(const Position& pos, const Move& move, NnueAccumulator& acc) {
    applyNnueDelta(acc, makeNnueMoveDelta(pos, move));
}

void undoNnueMove(const Position& pos, const Move& move, NnueAccumulator& acc) {
    undoNnueDelta(acc, makeNnueMoveDelta(pos, move));
}

int evaluateWithAccumulator(const Position& pos, const NnueAccumulator& acc) {
    const RuntimeNnue& net = currentNnue();
    if (!accumulatorMatchesCurrentNet(acc, net)) {
        return evaluate(pos);
    }

    const Color passiveSide = oppositeColor(pos.sideToMove);
    const int32_t* activeHidden = acc.values.data() + accumulatorOffset(net, pos.sideToMove);
    const int32_t* passiveHidden = acc.values.data() + accumulatorOffset(net, passiveSide);
    int64_t score = scoreFromLanes(activeHidden, passiveHidden);
    return roundDivide(score, net.outputScale);
}

int evaluate(const Position& pos) {
    const RuntimeNnue& net = currentNnue();
    thread_local std::vector<int32_t> whiteHidden;
    thread_local std::vector<int32_t> blackHidden;
    buildAccumulatorLane(pos, WHITE, whiteHidden);
    buildAccumulatorLane(pos, BLACK, blackHidden);
    const int32_t* activeHidden = pos.sideToMove == WHITE ? whiteHidden.data() : blackHidden.data();
    const int32_t* passiveHidden = pos.sideToMove == WHITE ? blackHidden.data() : whiteHidden.data();
    int64_t score = scoreFromLanes(activeHidden, passiveHidden);
    return roundDivide(score, net.outputScale);
}
