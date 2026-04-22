#ifndef ENGINE_H
#define ENGINE_H

#include <cstdint>
#include <string>
#include <vector>

#include "chess_position.h"
#include "chess_tables.h"

constexpr int MAX_SEARCH_DEPTH = 64;
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

struct NnueAccumulator {
    uint64_t generation = 0;
    int hiddenSize = 0;
    bool valid = false;
    std::vector<int32_t> values;
};

void initNnueAccumulator(const Position& pos, NnueAccumulator& acc);
void applyNnueMove(const Position& pos, const Move& move, NnueAccumulator& acc);
void undoNnueMove(const Position& pos, const Move& move, NnueAccumulator& acc);
int evaluateWithAccumulator(const Position& pos, const NnueAccumulator& acc);

int staticExchangeEval(const Position& pos, const Move& move);
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
    Color evalSideToMove;
    bool hasEval;
    bool evalInCheck;
    bool evalIsTerminal;
    std::string evalFen;
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
};

struct SearchResult {
    Move bestMove;
    Move pv[MAX_SEARCH_DEPTH];
    int pvLength;
    int score;
    int depth;
    uint64_t nodes;
    uint64_t elapsedMs;
    bool completed;
    bool hasMove;
    int bestMoveEvalScore;
    Color bestMoveEvalSideToMove;
    bool bestMoveHasEval;
    bool bestMoveEvalInCheck;
    bool bestMoveEvalIsTerminal;
    std::string bestMoveEvalFen;
    std::vector<RootMoveResult> rootMoveResults;
};

SearchResult searchBestMove(Position& pos, const SearchLimits& limits);
void requestSearchStop();

uint64_t perft(Position& pos, int d);
uint64_t perftDivide(Position& pos, int d);

#endif
