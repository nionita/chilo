#ifndef ENGINE_H
#define ENGINE_H

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <new>
#include <string>
#include <vector>

#include "chess_position.h"
#include "chess_tables.h"

constexpr int MAX_SEARCH_DEPTH = 64;
constexpr int MAX_FUTILITY_DEPTH = 7;
constexpr int MAX_DRAW_HISTORY = 600;
constexpr int SEARCH_MATE_SCORE = 29000;
constexpr int SEARCH_MATE_THRESHOLD = SEARCH_MATE_SCORE - MAX_SEARCH_DEPTH;

inline bool isMateScore(int score) {
    return score >= SEARCH_MATE_THRESHOLD || score <= -SEARCH_MATE_THRESHOLD;
}

inline int mateDistancePlies(int score) {
    return score > 0 ? SEARCH_MATE_SCORE - score : SEARCH_MATE_SCORE + score;
}

inline int mateDistanceMoves(int score) {
    int plies = mateDistancePlies(score);
    return score > 0 ? (plies + 1) / 2 : plies / 2;
}

bool attacked(const Position& pos, int sq, Color att);
bool inCheck(const Position& pos, Color col);

int genMoves(const Position& pos, Move* moves);
int genNoisyMoves(const Position& pos, Move* moves);
int genLegalMoves(const Position& pos, Move* moves);
int genLegalNoisyMoves(const Position& pos, Move* moves);
bool hasAnyLegalMove(const Position& pos);
bool isCheckmate(const Position& pos);
bool isStalemate(const Position& pos);

bool parseUCIMove(const Position& pos, const std::string& uci, Move& outMove);
bool applyUCIMove(Position& pos, const std::string& uci);

void doMove(Position& pos, const Move& mv, UndoState& undo);
void undo(Position& pos, const Move& mv, const UndoState& undo);

struct DrawHistoryState {
    int lastIrreversible;
    int lastReal;
    int lastValid;
};

void resetDrawHistory(const Position& pos);
void recordRealMoveForDrawHistory(const Position& before, const Move& move, const Position& after);
DrawHistoryState getDrawHistoryState();
bool isDrawByFiftyMove(const Position& pos);
bool isDrawByRepetition(const Position& pos);

int evaluate(const Position& pos);

template <typename T, std::size_t Alignment>
struct AlignedAllocator {
    using value_type = T;

    AlignedAllocator() noexcept = default;

    template <typename U>
    AlignedAllocator(const AlignedAllocator<U, Alignment>&) noexcept {}

    [[nodiscard]] T* allocate(std::size_t count) {
        if (count > std::numeric_limits<std::size_t>::max() / sizeof(T)) throw std::bad_array_new_length();
        return static_cast<T*>(::operator new(count * sizeof(T), std::align_val_t(Alignment)));
    }

    void deallocate(T* ptr, std::size_t) noexcept {
        ::operator delete(ptr, std::align_val_t(Alignment));
    }

    template <typename U>
    struct rebind {
        using other = AlignedAllocator<U, Alignment>;
    };
};

template <typename T, typename U, std::size_t Alignment>
bool operator==(const AlignedAllocator<T, Alignment>&, const AlignedAllocator<U, Alignment>&) noexcept {
    return true;
}

template <typename T, typename U, std::size_t Alignment>
bool operator!=(const AlignedAllocator<T, Alignment>&, const AlignedAllocator<U, Alignment>&) noexcept {
    return false;
}

struct NnueAccumulator {
    uint64_t generation = 0;
    int hiddenSize = 0;
    bool valid = false;
    std::vector<int32_t, AlignedAllocator<int32_t, 32>> values;
};

struct NnueFeatureDelta {
    Piece piece = EMPTY;
    uint8_t square = 0;
    int8_t sign = 0;
};

struct NnueMoveDelta {
    uint8_t count = 0;
    NnueFeatureDelta changes[4];
};

void initNnueAccumulator(const Position& pos, NnueAccumulator& acc);
NnueMoveDelta makeNnueMoveDelta(const Position& pos, const Move& move);
void applyNnueDelta(NnueAccumulator& acc, const NnueMoveDelta& delta);
void undoNnueDelta(NnueAccumulator& acc, const NnueMoveDelta& delta);
void applyNnueMove(const Position& pos, const Move& move, NnueAccumulator& acc);
void undoNnueMove(const Position& pos, const Move& move, NnueAccumulator& acc);
int evaluateWithAccumulator(const Position& pos, const NnueAccumulator& acc);

int staticExchangeEval(const Position& pos, const Move& move);

enum class MoveOrderingMode {
    Normal,
    Quiescence,
};

struct MoveOrderingEntry {
    Move move;
    Piece movingPiece;
    Piece capturedPiece;
    int see;
    int mvvLvaScore;
    int orderScore;
    bool capture;
    bool promotion;
    bool filteredByQsSee;
};

std::vector<MoveOrderingEntry> collectMoveOrderingDiagnostics(
    const Position& pos,
    MoveOrderingMode mode,
    const Move* preferredMove = nullptr,
    int ply = 0);

bool loadNnueWeightsFile(const std::string& path, std::string& error);

struct SearchResult;
using SearchInfoCallback = void (*)(const SearchResult&, void*);

struct SearchSample {
    std::string rootFen;
    std::string evalFen;
    int depth;
    int score;
};

using SearchSampleCallback = void (*)(const SearchSample&, void*);

struct RootMoveResult {
    Move move;
    int score;
    int evalScore;
    int evalPieceCount;
    Color evalSideToMove;
    bool hasEval;
    bool evalInCheck;
    bool evalIsTerminal;
    std::string evalFen;
};

#ifndef CHILO_FUTILITY_MAX_DEPTH
#define CHILO_FUTILITY_MAX_DEPTH 3
#endif

#ifndef CHILO_FUTILITY_MARGINS
#define CHILO_FUTILITY_MARGINS 0, 120, 320, 550, 0, 0, 0, 0
#endif

static_assert(CHILO_FUTILITY_MAX_DEPTH >= 0 && CHILO_FUTILITY_MAX_DEPTH <= MAX_FUTILITY_DEPTH,
              "CHILO_FUTILITY_MAX_DEPTH must be between 0 and MAX_FUTILITY_DEPTH");

struct SearchParameters {
    int futilityMaxDepth = CHILO_FUTILITY_MAX_DEPTH;
    std::array<int, MAX_FUTILITY_DEPTH + 1> futilityMargins = {CHILO_FUTILITY_MARGINS};
};

struct SearchLimits {
    int depth;
    int movetimeMs;
    SearchInfoCallback infoCallback;
    void* infoUserData;
    bool collectRootMoveResults = false;
    bool collectBestMoveLeaf = false;
    int minSampleDepth = 0;
    SearchSampleCallback sampleCallback = nullptr;
    void* sampleUserData = nullptr;
    uint64_t nodeLimit = 0;
    SearchParameters parameters{};
    bool isolateTranspositionTable = false;
};

struct SearchStats {
    uint64_t qnodes = 0;
    uint64_t qcheckNodes = 0;
    uint64_t qnormalNodes = 0;
    uint64_t qMovesGenerated = 0;
    uint64_t qSeeSkipped = 0;
    uint64_t qDeltaSkipped = 0;
    uint64_t qMovesSearched = 0;
    uint64_t qStandPatCutoffs = 0;
    uint64_t qCutoffs[4] = {};
    uint64_t nonPvCutoffs[4] = {};
    uint64_t nonPvTtCutoffs = 0;
    uint64_t nonPvCaptureCutoffs = 0;
    uint64_t nonPvKillerCutoffs = 0;
    uint64_t nonPvQuietCutoffs = 0;
    uint64_t nonPvPromotionCutoffs = 0;
    uint64_t nonPvOtherCutoffs = 0;
    uint64_t nullMoveTries = 0;
    uint64_t nullMoveCutoffs = 0;
    uint64_t nullMoveTriesD2 = 0;
    uint64_t nullMoveCutoffsD2 = 0;
    uint64_t nullMoveTriesD3 = 0;
    uint64_t nullMoveCutoffsD3 = 0;
    uint64_t nullMoveTriesD4p = 0;
    uint64_t nullMoveCutoffsD4p = 0;
    std::array<uint64_t, MAX_FUTILITY_DEPTH + 1> futilityPrunes{};
    std::array<uint64_t, MAX_FUTILITY_DEPTH + 1> futilityPrunesInCheck{};
};

struct SearchResult {
    Move bestMove;
    Move pv[MAX_SEARCH_DEPTH];
    int pvLength;
    int score;
    int depth;
    uint64_t nodes;
    uint64_t completedNodes;
    SearchStats stats;
    uint64_t elapsedMs;
    uint64_t totalElapsedMs;
    bool completed;
    bool hasMove;
    int bestMoveEvalScore;
    Color bestMoveEvalSideToMove;
    bool bestMoveHasEval;
    bool bestMoveEvalInCheck;
    bool bestMoveEvalIsTerminal;
    int bestMoveEvalPieceCount;
    std::string bestMoveEvalFen;
    std::vector<RootMoveResult> rootMoveResults;
};

SearchResult searchBestMove(Position& pos, const SearchLimits& limits);
void requestSearchStop();

uint64_t perft(Position& pos, int d);
uint64_t perftDivide(Position& pos, int d);

#endif
