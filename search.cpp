#include "engine.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <utility>
#include <vector>

namespace {

constexpr int INF_SCORE = 30000;
constexpr int DELTA_MARGIN = 200;
constexpr int NULL_MOVE_REDUCTION = 2;
constexpr int DEEP_NULL_MOVE_REDUCTION = 3;
constexpr int LMR_LEVEL1_MOVE_INDEX = 2;
constexpr int LMR_LEVEL2_MOVE_INDEX = 6;
constexpr int LMR_LEVEL3_MOVE_INDEX = 12;
constexpr int FUTILITY_MARGIN[4] = {0, 120, 320, 550};
constexpr std::size_t TT_SIZE = 1u << 20;

#ifndef CHILO_TT_ALWAYS_OVERWRITE
#define CHILO_TT_ALWAYS_OVERWRITE 0
#endif

enum TTFlag : uint8_t { TT_NONE, TT_EXACT, TT_LOWER, TT_UPPER };

struct TTEntry {
    uint64_t key = 0;
    Move bestMove{};
    int16_t score = 0;
    uint8_t depth = 0;
    uint8_t flag = TT_NONE;
    uint8_t generation = 0;
};

struct NullMoveState {
    int enPassant;
    int halfMove;
    int fullMove;
    uint64_t hashKey;
};

struct HistoryMoveInfo {
    Piece movingPiece;
    Piece capturedPiece;
    uint8_t castlingBefore;
};

struct SeeState {
    uint64_t pieces[2][PIECE_TYPE_COUNT];
    uint64_t occupancy[2];
    uint64_t occupancyAll;
};

struct SearchLeaf {
    Position pos{};
    int score = 0;
    bool valid = false;
    bool inCheck = false;
    bool terminal = false;
};

std::atomic<bool> g_stopRequested{false};
std::chrono::steady_clock::time_point g_deadline;
bool g_useDeadline = false;
std::vector<TTEntry> g_tt(TT_SIZE);
uint8_t g_ttGeneration = 0;
Move g_killers[MAX_SEARCH_DEPTH][2];
int g_history[2][64][64] = {};
uint64_t g_drawHistory[MAX_DRAW_HISTORY] = {};
int g_lastIrreversible = 0;
int g_lastReal = 0;
int g_lastValid = 0;
bool g_drawHistoryInitialized = false;

bool movesEqual(const Move& a, const Move& b) {
    return a.from == b.from && a.to == b.to && a.promotion == b.promotion &&
           a.isEnPassant == b.isEnPassant && a.isCastle == b.isCastle && a.isDoublePush == b.isDoublePush;
}

bool isValidMove(const Move& move) {
    return move.from != move.to || move.promotion != EMPTY || move.isEnPassant || move.isCastle || move.isDoublePush;
}

void setLeaf(SearchLeaf* leaf, const Position& pos, int score, bool inCheck = false, bool terminal = false) {
    if (leaf == nullptr) return;
    leaf->pos = pos;
    leaf->score = score;
    leaf->valid = true;
    leaf->inCheck = inCheck;
    leaf->terminal = terminal;
}

Color opposite(Color side) {
    return side == WHITE ? BLACK : WHITE;
}

int moveValueGuess(Piece piece) {
    switch (pt(piece)) {
        case 1: return 100;
        case 2: return 320;
        case 3: return 330;
        case 4: return 500;
        case 5: return 900;
        default: return 0;
    }
}

Piece capturedPieceForMove(const Position& pos, const Move& move) {
    if (move.isEnPassant) return pos.sideToMove == WHITE ? B_PAWN : W_PAWN;
    return pieceAt(pos, move.to);
}

bool isCaptureMove(const Position& pos, const Move& move) {
    return capturedPieceForMove(pos, move) != EMPTY;
}

bool isTacticalMove(const Position& pos, const Move& move) {
    return isCaptureMove(pos, move) || move.promotion != EMPTY;
}

bool isQuietMove(const Position& pos, const Move& move) {
    return !isTacticalMove(pos, move) && !move.isCastle;
}

int promotionGain(const Move& move) {
    if (move.promotion == EMPTY) return 0;
    return moveValueGuess(move.promotion) - moveValueGuess(W_PAWN);
}

Piece pieceFor(Color side, int type) {
    static constexpr Piece whitePieces[PIECE_TYPE_COUNT] = {
        W_PAWN, W_KNIGHT, W_BISHOP, W_ROOK, W_QUEEN, W_KING
    };
    static constexpr Piece blackPieces[PIECE_TYPE_COUNT] = {
        B_PAWN, B_KNIGHT, B_BISHOP, B_ROOK, B_QUEEN, B_KING
    };
    return side == WHITE ? whitePieces[type] : blackPieces[type];
}

bool promotionSquare(Color side, int sq) {
    return side == WHITE ? R(sq) == 7 : R(sq) == 0;
}

void initSeeState(const Position& pos, SeeState& state) {
    for (int color = 0; color < 2; color++) {
        state.occupancy[color] = pos.occupancy[color];
        for (int type = 0; type < PIECE_TYPE_COUNT; type++) {
            state.pieces[color][type] = pos.pieceBitboards[color][type];
        }
    }
    state.occupancyAll = pos.occupancyAll;
}

void removeSeePiece(SeeState& state, Color side, Piece piece, int sq) {
    int type = pieceTypeIndex(piece);
    uint64_t bit = bitAt(sq);
    state.pieces[side][type] &= ~bit;
    state.occupancy[side] &= ~bit;
    state.occupancyAll &= ~bit;
}

void addSeePiece(SeeState& state, Color side, Piece piece, int sq) {
    int type = pieceTypeIndex(piece);
    uint64_t bit = bitAt(sq);
    state.pieces[side][type] |= bit;
    state.occupancy[side] |= bit;
    state.occupancyAll |= bit;
}

uint64_t attackersToSquare(const SeeState& state, int sq, Color side) {
    const AttackTables& tables = attackTables();
    uint64_t attackers = 0;
    attackers |= state.pieces[side][pieceTypeIndex(pieceFor(side, 0))] & tables.pawnAttackers[side][sq];
    attackers |= state.pieces[side][pieceTypeIndex(pieceFor(side, 1))] & tables.knight[sq];
    attackers |= state.pieces[side][pieceTypeIndex(pieceFor(side, 5))] & tables.king[sq];

    uint64_t bishops = state.pieces[side][pieceTypeIndex(pieceFor(side, 2))];
    uint64_t rooks = state.pieces[side][pieceTypeIndex(pieceFor(side, 3))];
    uint64_t queens = state.pieces[side][pieceTypeIndex(pieceFor(side, 4))];
    attackers |= bishopAttacks(sq, state.occupancyAll) & (bishops | queens);
    attackers |= rookAttacks(sq, state.occupancyAll) & (rooks | queens);
    return attackers;
}

bool pickLeastValuableAttacker(const SeeState& state, Color side, uint64_t attackers, int& fromSq, Piece& piece) {
    for (int type = 0; type < PIECE_TYPE_COUNT; type++) {
        uint64_t candidates = attackers & state.pieces[side][type];
        if (candidates == 0) continue;
        fromSq = __builtin_ctzll(candidates);
        piece = pieceFor(side, type);
        return true;
    }
    return false;
}

int seeGain(SeeState& state, int sq, Color side, Piece targetPiece) {
    uint64_t attackers = attackersToSquare(state, sq, side);
    while (attackers) {
        int fromSq = -1;
        Piece attacker = EMPTY;
        if (!pickLeastValuableAttacker(state, side, attackers, fromSq, attacker)) break;

        Color defendingSide = opposite(side);
        Piece occupant = attacker;
        int immediateGain = moveValueGuess(targetPiece);
        if (pt(attacker) == 1 && promotionSquare(side, sq)) {
            occupant = side == WHITE ? W_QUEEN : B_QUEEN;
            immediateGain += moveValueGuess(occupant) - moveValueGuess(attacker);
        }

        removeSeePiece(state, defendingSide, targetPiece, sq);
        removeSeePiece(state, side, attacker, fromSq);
        addSeePiece(state, side, occupant, sq);

        bool legalKingCapture = true;
        if (pt(attacker) == 6 && attackersToSquare(state, sq, defendingSide) != 0) legalKingCapture = false;

        int gain = 0;
        if (legalKingCapture) gain = std::max(0, immediateGain - seeGain(state, sq, defendingSide, occupant));

        removeSeePiece(state, side, occupant, sq);
        addSeePiece(state, side, attacker, fromSq);
        addSeePiece(state, defendingSide, targetPiece, sq);

        if (legalKingCapture) return gain;
        attackers &= ~bitAt(fromSq);
    }
    return 0;
}

int captureOrderScore(const Position& pos, const Move& move) {
    Piece movingPiece = pieceAt(pos, move.from);
    Piece capturedPiece = capturedPieceForMove(pos, move);
    return 10 * moveValueGuess(capturedPiece) - moveValueGuess(movingPiece) + promotionGain(move);
}

bool shouldStop() {
    if (g_stopRequested.load(std::memory_order_relaxed)) return true;
    if (g_useDeadline && std::chrono::steady_clock::now() >= g_deadline) {
        g_stopRequested.store(true, std::memory_order_relaxed);
        return true;
    }
    return false;
}

bool hasNonPawnMaterial(const Position& pos, Color side) {
    return pos.pieceBitboards[side][pieceTypeIndex(side == WHITE ? W_KNIGHT : B_KNIGHT)] != 0 ||
           pos.pieceBitboards[side][pieceTypeIndex(side == WHITE ? W_BISHOP : B_BISHOP)] != 0 ||
           pos.pieceBitboards[side][pieceTypeIndex(side == WHITE ? W_ROOK : B_ROOK)] != 0 ||
           pos.pieceBitboards[side][pieceTypeIndex(side == WHITE ? W_QUEEN : B_QUEEN)] != 0;
}

HistoryMoveInfo historyMoveInfo(const Position& pos, const Move& move) {
    return {pieceAt(pos, move.from), capturedPieceForMove(pos, move), packCastling(pos)};
}

bool moveIsIrreversible(const HistoryMoveInfo& info, uint8_t castlingAfter) {
    return pt(info.movingPiece) == 1 || info.capturedPiece != EMPTY || info.castlingBefore != castlingAfter;
}

void appendDrawHistory(uint64_t hashKey, bool irreversible, bool realMove) {
    assert(g_lastValid + 1 < MAX_DRAW_HISTORY);
    g_lastValid++;
    g_drawHistory[g_lastValid] = hashKey;
    if (realMove) g_lastReal = g_lastValid;
    if (irreversible) g_lastIrreversible = g_lastValid;
    g_drawHistoryInitialized = true;
}

void pushSearchHistory(uint64_t hashKey, bool irreversible, int& savedLastValid, int& savedLastIrreversible) {
    savedLastValid = g_lastValid;
    savedLastIrreversible = g_lastIrreversible;
    appendDrawHistory(hashKey, irreversible, false);
}

void popSearchHistory(int savedLastValid, int savedLastIrreversible) {
    g_lastValid = savedLastValid;
    g_lastIrreversible = savedLastIrreversible;
}

void doNullMove(Position& pos, NullMoveState& state) {
    state.enPassant = pos.enPassant;
    state.halfMove = pos.halfMove;
    state.fullMove = pos.fullMove;
    state.hashKey = pos.hashKey;

    pos.hashKey ^= enPassantHash(pos.enPassant);
    pos.enPassant = -1;
    pos.sideToMove = pos.sideToMove == WHITE ? BLACK : WHITE;
    pos.halfMove++;
    if (pos.sideToMove == WHITE) pos.fullMove++;
    pos.hashKey ^= sideToMoveHash();
}

void undoNullMove(Position& pos, const NullMoveState& state) {
    pos.sideToMove = pos.sideToMove == WHITE ? BLACK : WHITE;
    pos.enPassant = state.enPassant;
    pos.halfMove = state.halfMove;
    pos.fullMove = state.fullMove;
    pos.hashKey = state.hashKey;
}

int scoreToTT(int score, int ply) {
    if (score > SEARCH_MATE_THRESHOLD) return score + ply;
    if (score < -SEARCH_MATE_THRESHOLD) return score - ply;
    return score;
}

int scoreFromTT(int score, int ply) {
    if (score > SEARCH_MATE_THRESHOLD) return score - ply;
    if (score < -SEARCH_MATE_THRESHOLD) return score + ply;
    return score;
}

TTEntry& ttEntry(uint64_t key) {
    return g_tt[key & (TT_SIZE - 1)];
}

bool probeTT(uint64_t key, int depth, int ply, int alpha, int beta, Move& bestMove, int& score) {
    const TTEntry& entry = ttEntry(key);
    if (entry.key != key) return false;
    if (isValidMove(entry.bestMove)) bestMove = entry.bestMove;
    if (entry.depth < depth) return false;

    score = scoreFromTT(entry.score, ply);
    if (entry.flag == TT_EXACT) return true;
    if (entry.flag == TT_LOWER && score >= beta) return true;
    if (entry.flag == TT_UPPER && score <= alpha) return true;
    return false;
}

void storeTT(uint64_t key, int depth, int ply, int score, TTFlag flag, const Move& bestMove) {
    TTEntry& entry = ttEntry(key);
#if !CHILO_TT_ALWAYS_OVERWRITE
    if (entry.key != key &&
        entry.key != 0 &&
        entry.generation == g_ttGeneration &&
        entry.depth > depth) {
        return;
    }
#endif

    entry.key = key;
    entry.bestMove = bestMove;
    entry.score = static_cast<int16_t>(scoreToTT(score, ply));
    entry.depth = static_cast<uint8_t>(std::max(depth, 0));
    entry.flag = flag;
    entry.generation = g_ttGeneration;
}

void clearSearchHeuristics() {
    for (int ply = 0; ply < MAX_SEARCH_DEPTH; ply++) {
        g_killers[ply][0] = Move{};
        g_killers[ply][1] = Move{};
    }
    for (int color = 0; color < 2; color++) {
        for (int from = 0; from < 64; from++) {
            for (int to = 0; to < 64; to++) g_history[color][from][to] = 0;
        }
    }
}

void noteQuietBetaCutoff(Color side, int ply, const Move& move, int depth) {
    if (ply < MAX_SEARCH_DEPTH && !movesEqual(move, g_killers[ply][0])) {
        g_killers[ply][1] = g_killers[ply][0];
        g_killers[ply][0] = move;
    }

    int& history = g_history[side][move.from][move.to];
    history += depth * depth;
    if (history > 1000000) history = 1000000;
}

int moveOrderScore(const Position& pos, const Move& move, const Move* preferredMove, int ply) {
    if (preferredMove != nullptr && movesEqual(move, *preferredMove)) return 1000000;

    if (isQuietMove(pos, move)) {
        if (ply < MAX_SEARCH_DEPTH && movesEqual(move, g_killers[ply][0])) return 850000;
        if (ply < MAX_SEARCH_DEPTH && movesEqual(move, g_killers[ply][1])) return 800000;
    }

    if (isCaptureMove(pos, move)) {
        int see = staticExchangeEval(pos, move);
        int bucket = see >= 0 ? 700000 : 100000;
        return bucket + captureOrderScore(pos, move);
    }

    if (move.promotion != EMPTY) return 600000 + moveValueGuess(move.promotion);

    int score = 200000;
    if (isQuietMove(pos, move)) {
        score += std::min(g_history[pos.sideToMove][move.from][move.to], 30000);
    }

    if (move.isCastle) score += 1000;
    return score;
}

int qsMoveOrderScore(const Position& pos, const Move& move) {
    if (isCaptureMove(pos, move)) return 100000 + captureOrderScore(pos, move);
    if (move.promotion != EMPTY) return 50000 + moveValueGuess(move.promotion);
    return 0;
}

void orderMoves(const Position& pos, Move* moves, int count, const Move* preferredMove, int ply) {
    int scores[MAX_MOVES];
    for (int i = 0; i < count; i++) scores[i] = moveOrderScore(pos, moves[i], preferredMove, ply);

    for (int i = 1; i < count; i++) {
        Move move = moves[i];
        int score = scores[i];
        int j = i - 1;
        while (j >= 0 && scores[j] < score) {
            moves[j + 1] = moves[j];
            scores[j + 1] = scores[j];
            j--;
        }
        moves[j + 1] = move;
        scores[j + 1] = score;
    }
}

void orderQSMoves(const Position& pos, Move* moves, int count) {
    int scores[MAX_MOVES];
    for (int i = 0; i < count; i++) scores[i] = qsMoveOrderScore(pos, moves[i]);

    for (int i = 1; i < count; i++) {
        Move move = moves[i];
        int score = scores[i];
        int j = i - 1;
        while (j >= 0 && scores[j] < score) {
            moves[j + 1] = moves[j];
            scores[j + 1] = scores[j];
            j--;
        }
        moves[j + 1] = move;
        scores[j + 1] = score;
    }
}

int terminalScore(const Position& pos, int ply) {
    if (inCheck(pos, pos.sideToMove)) return -SEARCH_MATE_SCORE + ply;
    return 0;
}

int quiescence(Position& pos, int ply, int alpha, int beta, uint64_t& nodes, SearchLeaf* leaf) {
    if (shouldStop()) {
        int score = evaluate(pos);
        setLeaf(leaf, pos, score, inCheck(pos, pos.sideToMove), false);
        return score;
    }
    if (isDrawByFiftyMove(pos)) {
        setLeaf(leaf, pos, 0, inCheck(pos, pos.sideToMove), true);
        return 0;
    }

    nodes++;
    bool inCheckNow = inCheck(pos, pos.sideToMove);
    int standPat = 0;
    SearchLeaf bestLeaf{};

    if (!inCheckNow) {
        standPat = evaluate(pos);
        if (standPat >= beta) {
            setLeaf(leaf, pos, standPat, false, false);
            return beta;
        }
        if (standPat > alpha) {
            alpha = standPat;
            setLeaf(&bestLeaf, pos, standPat, false, false);
        }
    }

    Move moves[MAX_MOVES];
    int moveCount = inCheckNow ? genLegalMoves(pos, moves) : genLegalNoisyMoves(pos, moves);
    if (moveCount == 0) {
        if (inCheckNow) {
            int score = terminalScore(pos, ply);
            setLeaf(leaf, pos, score, true, true);
            return score;
        }
        setLeaf(leaf, pos, standPat, false, false);
        return alpha;
    }

    if (!inCheckNow) {
        int filteredCount = 0;
        for (int i = 0; i < moveCount; i++) {
            const Move& move = moves[i];
            if (isCaptureMove(pos, move) && staticExchangeEval(pos, move) < 0) continue;
            moves[filteredCount++] = move;
        }
        moveCount = filteredCount;
        if (moveCount == 0) {
            setLeaf(leaf, pos, standPat, false, false);
            return alpha;
        }
    }

    orderQSMoves(pos, moves, moveCount);

    for (int i = 0; i < moveCount; i++) {
        const Move& move = moves[i];
        if (!inCheckNow) {
            Piece capturedPiece = capturedPieceForMove(pos, move);
            int gainUpperBound = standPat + moveValueGuess(capturedPiece) + promotionGain(move) + DELTA_MARGIN;
            if (gainUpperBound < alpha) continue;
        }

        UndoState undoState;
        doMove(pos, move, undoState);
        SearchLeaf childLeaf{};
        int score = -quiescence(pos, ply + 1, -beta, -alpha, nodes, &childLeaf);
        undo(pos, move, undoState);

        if (shouldStop()) return alpha;
        if (score >= beta) {
            if (leaf != nullptr) {
                if (childLeaf.valid) *leaf = childLeaf;
                else leaf->valid = false;
            }
            return beta;
        }
        if (score > alpha) {
            alpha = score;
            if (childLeaf.valid) bestLeaf = childLeaf;
            else bestLeaf.valid = false;
        }
    }

    if (leaf != nullptr) {
        if (bestLeaf.valid) *leaf = bestLeaf;
        else if (!inCheckNow) setLeaf(leaf, pos, standPat, false, false);
        else leaf->valid = false;
    }
    return alpha;
}

int alphaBeta(Position& pos, int depth, int ply, int alpha, int beta, bool isPv, bool allowNull, bool allowDrawChecks,
              uint64_t& nodes, Move pvTable[MAX_SEARCH_DEPTH][MAX_SEARCH_DEPTH],
              int pvLength[MAX_SEARCH_DEPTH], SearchLeaf* leaf) {
    pvLength[ply] = 0;
    if (shouldStop()) {
        int score = evaluate(pos);
        setLeaf(leaf, pos, score, inCheck(pos, pos.sideToMove), false);
        return score;
    }
    if (allowDrawChecks && (isDrawByFiftyMove(pos) || isDrawByRepetition(pos))) {
        setLeaf(leaf, pos, 0, inCheck(pos, pos.sideToMove), true);
        return 0;
    }

    Move ttMove{};
    int ttScore = 0;
    if (!isPv && probeTT(pos.hashKey, depth, ply, alpha, beta, ttMove, ttScore)) {
        if (leaf != nullptr) leaf->valid = false;
        return ttScore;
    }

    if (depth <= 0) return quiescence(pos, ply, alpha, beta, nodes, leaf);

    nodes++;
    const int alphaOriginal = alpha;
    const bool inCheckNow = inCheck(pos, pos.sideToMove);

    if (allowNull && !isPv && !inCheckNow && depth >= 3 && hasNonPawnMaterial(pos, pos.sideToMove)) {
        NullMoveState nullState;
        doNullMove(pos, nullState);
        int reduction = depth >= 6 ? DEEP_NULL_MOVE_REDUCTION : NULL_MOVE_REDUCTION;
        int score = -alphaBeta(pos, depth - 1 - reduction, ply + 1, -beta, -beta + 1,
                               false, false, false, nodes, pvTable, pvLength, nullptr);
        undoNullMove(pos, nullState);
        if (shouldStop()) return alpha;
        if (score >= beta) {
            storeTT(pos.hashKey, depth, ply, beta, TT_LOWER, ttMove);
            if (leaf != nullptr) leaf->valid = false;
            return beta;
        }
    }

    Move moves[MAX_MOVES];
    int moveCount = genLegalMoves(pos, moves);
    if (moveCount == 0) {
        int score = terminalScore(pos, ply);
        setLeaf(leaf, pos, score, inCheckNow, true);
        return score;
    }

    orderMoves(pos, moves, moveCount, isValidMove(ttMove) ? &ttMove : nullptr, ply);

    Move bestMove = moves[0];
    SearchLeaf bestLeaf{};
    int staticEval = 0;
    bool allowFutility = !isPv && !inCheckNow && depth <= 3;
    if (allowFutility) staticEval = evaluate(pos);

    for (int i = 0; i < moveCount; i++) {
        const Move& move = moves[i];
        bool quiet = isQuietMove(pos, move);
        HistoryMoveInfo moveInfo = historyMoveInfo(pos, move);

        UndoState undoState;
        doMove(pos, move, undoState);
        int savedLastValid = 0;
        int savedLastIrreversible = 0;
        pushSearchHistory(pos.hashKey, moveIsIrreversible(moveInfo, packCastling(pos)),
                          savedLastValid, savedLastIrreversible);
        bool givesCheck = inCheck(pos, pos.sideToMove);

        if (allowFutility && i > 0 && quiet && !givesCheck &&
            staticEval + FUTILITY_MARGIN[depth] <= alpha) {
            popSearchHistory(savedLastValid, savedLastIrreversible);
            undo(pos, move, undoState);
            continue;
        }

        int score = 0;
        int fullDepth = depth - 1;
        int searchDepth = fullDepth;
        bool reduced = false;
        SearchLeaf childLeaf{};

        if (!isPv && !inCheckNow && !givesCheck && quiet && depth >= 3 && i >= LMR_LEVEL1_MOVE_INDEX) {
            int reduction = 1;
            if (depth >= 7 && i >= LMR_LEVEL3_MOVE_INDEX) reduction = 3;
            else if (depth >= 5 && i >= LMR_LEVEL2_MOVE_INDEX) reduction = 2;
            if (searchDepth - reduction > 0) {
                searchDepth -= reduction;
                reduced = true;
            }
        }

        if (i == 0) {
            score = -alphaBeta(pos, fullDepth, ply + 1, -beta, -alpha, isPv, true, allowDrawChecks,
                               nodes, pvTable, pvLength, &childLeaf);
        } else {
            score = -alphaBeta(pos, searchDepth, ply + 1, -alpha - 1, -alpha,
                               false, true, allowDrawChecks, nodes, pvTable, pvLength, &childLeaf);
            if (score > alpha && reduced) {
                score = -alphaBeta(pos, fullDepth, ply + 1, -alpha - 1, -alpha,
                                   false, true, allowDrawChecks, nodes, pvTable, pvLength, &childLeaf);
            }
            if (score > alpha) {
                score = -alphaBeta(pos, fullDepth, ply + 1, -beta, -alpha,
                                   isPv, true, allowDrawChecks, nodes, pvTable, pvLength, &childLeaf);
            }
        }
        popSearchHistory(savedLastValid, savedLastIrreversible);
        undo(pos, move, undoState);

        if (shouldStop()) return alpha;
        if (score > alpha) {
            alpha = score;
            bestMove = move;
            if (childLeaf.valid) bestLeaf = childLeaf;
            else bestLeaf.valid = false;
            pvTable[ply][0] = move;
            for (int j = 0; j < pvLength[ply + 1]; j++) pvTable[ply][j + 1] = pvTable[ply + 1][j];
            pvLength[ply] = pvLength[ply + 1] + 1;
        }
        if (score >= beta) {
            if (quiet) noteQuietBetaCutoff(pos.sideToMove, ply, move, depth);
            storeTT(pos.hashKey, depth, ply, beta, TT_LOWER, move);
            if (leaf != nullptr) {
                if (childLeaf.valid) *leaf = childLeaf;
                else leaf->valid = false;
            }
            return beta;
        }
    }

    TTFlag flag = alpha > alphaOriginal ? TT_EXACT : TT_UPPER;
    storeTT(pos.hashKey, depth, ply, alpha, flag, bestMove);
    if (leaf != nullptr) {
        if (bestLeaf.valid) *leaf = bestLeaf;
        else leaf->valid = false;
    }
    return alpha;
}

}  // namespace

int staticExchangeEval(const Position& pos, const Move& move) {
    Piece capturedPiece = capturedPieceForMove(pos, move);
    if (capturedPiece == EMPTY) return move.promotion != EMPTY ? promotionGain(move) : 0;

    SeeState state{};
    initSeeState(pos, state);

    Color us = pos.sideToMove;
    Color them = opposite(us);
    Piece movingPiece = pieceAt(pos, move.from);
    Piece occupyingPiece = move.promotion != EMPTY ? move.promotion : movingPiece;
    int targetSq = move.to;

    removeSeePiece(state, us, movingPiece, move.from);
    if (move.isEnPassant) {
        int capSq = (us == WHITE ? R(move.to) - 1 : R(move.to) + 1) * 8 + F(move.to);
        removeSeePiece(state, them, capturedPiece, capSq);
    } else {
        removeSeePiece(state, them, capturedPiece, targetSq);
    }
    addSeePiece(state, us, occupyingPiece, targetSq);

    int gain = moveValueGuess(capturedPiece) + promotionGain(move);
    return gain - seeGain(state, targetSq, them, occupyingPiece);
}

SearchResult searchBestMove(Position& pos, const SearchLimits& limits) {
    g_stopRequested.store(false, std::memory_order_relaxed);
    g_useDeadline = limits.movetimeMs > 0;
    if (g_useDeadline) g_deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(limits.movetimeMs);
    auto startTime = std::chrono::steady_clock::now();
    const bool collectRootDetails = limits.collectRootMoveResults || limits.sampleCallback != nullptr;
    const std::string rootFen = collectRootDetails ? positionToFEN(pos) : std::string();

    if (++g_ttGeneration == 0) g_ttGeneration = 1;
    clearSearchHeuristics();
    if (!g_drawHistoryInitialized || g_drawHistory[g_lastReal] != pos.hashKey) resetDrawHistory(pos);
    g_lastValid = g_lastReal;

    SearchResult result{};
    result.bestMove = Move{};
    result.pvLength = 0;
    result.score = 0;
    result.depth = 0;
    result.nodes = 0;
    result.elapsedMs = 0;
    result.completed = true;
    result.hasMove = false;

    Move rootMoves[MAX_MOVES];
    int rootCount = genLegalMoves(pos, rootMoves);
    if (rootCount == 0) {
        result.pvLength = 0;
        result.score = terminalScore(pos, 0);
        return result;
    }

    result.bestMove = rootMoves[0];
    result.hasMove = true;
    result.pv[0] = rootMoves[0];
    result.pvLength = 1;

    int maxDepth = limits.depth > 0 ? limits.depth : MAX_SEARCH_DEPTH;
    if (maxDepth > MAX_SEARCH_DEPTH) maxDepth = MAX_SEARCH_DEPTH;
    Move preferredMove = result.bestMove;
    Move pvTable[MAX_SEARCH_DEPTH + 1][MAX_SEARCH_DEPTH];
    int pvLength[MAX_SEARCH_DEPTH + 1] = {};

    for (int depth = 1; depth <= maxDepth; depth++) {
        if (shouldStop()) break;

        Move iterationMoves[MAX_MOVES];
        for (int i = 0; i < rootCount; i++) iterationMoves[i] = rootMoves[i];
        orderMoves(pos, iterationMoves, rootCount, &preferredMove, 0);

        int alpha = -INF_SCORE;
        int beta = INF_SCORE;
        int bestScore = -INF_SCORE;
        Move bestMove = iterationMoves[0];
        Move bestPv[MAX_SEARCH_DEPTH];
        int bestPvLength = 1;
        uint64_t iterationNodes = 0;
        bool interrupted = false;
        std::vector<RootMoveResult> iterationRootResults;
        if (collectRootDetails) iterationRootResults.reserve(rootCount);

        for (int i = 0; i < rootCount; i++) {
            const Move& move = iterationMoves[i];
            HistoryMoveInfo moveInfo = historyMoveInfo(pos, move);
            UndoState undoState;
            doMove(pos, move, undoState);
            int savedLastValid = 0;
            int savedLastIrreversible = 0;
            pushSearchHistory(pos.hashKey, moveIsIrreversible(moveInfo, packCastling(pos)),
                              savedLastValid, savedLastIrreversible);
            int score;
            SearchLeaf childLeaf{};
            if (collectRootDetails) {
                score = -alphaBeta(pos, depth - 1, 1, -INF_SCORE, INF_SCORE, true, true, true,
                                   iterationNodes, pvTable, pvLength, &childLeaf);
            } else {
                if (i == 0) {
                    score = -alphaBeta(pos, depth - 1, 1, -beta, -alpha, true, true, true,
                                       iterationNodes, pvTable, pvLength, nullptr);
                } else {
                    score = -alphaBeta(pos, depth - 1, 1, -alpha - 1, -alpha, false, true, true,
                                       iterationNodes, pvTable, pvLength, nullptr);
                    if (score > alpha) {
                        score = -alphaBeta(pos, depth - 1, 1, -beta, -alpha, true, true, true,
                                           iterationNodes, pvTable, pvLength, nullptr);
                    }
                }
            }
            popSearchHistory(savedLastValid, savedLastIrreversible);
            undo(pos, move, undoState);

            if (shouldStop()) {
                interrupted = true;
                break;
            }
            if (collectRootDetails) {
                RootMoveResult rootResult{};
                rootResult.move = move;
                rootResult.score = score;
                rootResult.evalScore = childLeaf.score;
                rootResult.evalSideToMove = childLeaf.pos.sideToMove;
                rootResult.hasEval = childLeaf.valid;
                rootResult.evalInCheck = childLeaf.inCheck;
                rootResult.evalIsTerminal = childLeaf.terminal;
                if (childLeaf.valid) rootResult.evalFen = positionToFEN(childLeaf.pos);
                iterationRootResults.push_back(std::move(rootResult));
            }
            if (score > bestScore) {
                bestScore = score;
                bestMove = move;
                bestPv[0] = move;
                bestPvLength = 1;
                for (int j = 0; j < pvLength[1] && j + 1 < MAX_SEARCH_DEPTH; j++) {
                    bestPv[j + 1] = pvTable[1][j];
                    bestPvLength = j + 2;
                }
            }
            if (score > alpha) alpha = score;
        }

        result.nodes += iterationNodes;
        if (interrupted) {
            result.completed = false;
            break;
        }

        preferredMove = bestMove;
        result.bestMove = bestMove;
        for (int i = 0; i < bestPvLength; i++) result.pv[i] = bestPv[i];
        result.pvLength = bestPvLength;
        result.score = bestScore;
        result.depth = depth;
        result.elapsedMs = std::chrono::duration_cast<std::chrono::milliseconds>(
                               std::chrono::steady_clock::now() - startTime)
                               .count();
        result.completed = true;
        result.rootMoveResults = std::move(iterationRootResults);

        storeTT(pos.hashKey, depth, 0, bestScore, TT_EXACT, bestMove);

        if (limits.infoCallback != nullptr) limits.infoCallback(result, limits.infoUserData);
    }

    if (limits.sampleCallback != nullptr &&
        result.completed &&
        result.depth >= limits.minSampleDepth) {
        for (const RootMoveResult& rootMove : result.rootMoveResults) {
            if (!movesEqual(rootMove.move, result.bestMove) || !rootMove.hasEval) continue;
            SearchSample sample{rootFen, rootMove.evalFen, result.depth, rootMove.evalScore};
            limits.sampleCallback(sample, limits.sampleUserData);
            break;
        }
    }

    return result;
}

void requestSearchStop() {
    g_stopRequested.store(true, std::memory_order_relaxed);
}

void resetDrawHistory(const Position& pos) {
    g_drawHistory[0] = pos.hashKey;
    g_lastIrreversible = 0;
    g_lastReal = 0;
    g_lastValid = 0;
    g_drawHistoryInitialized = true;
}

void recordRealMoveForDrawHistory(const Position& before, const Move& move, const Position& after) {
    if (!g_drawHistoryInitialized || g_drawHistory[g_lastReal] != before.hashKey) resetDrawHistory(before);
    HistoryMoveInfo moveInfo = historyMoveInfo(before, move);
    appendDrawHistory(after.hashKey, moveIsIrreversible(moveInfo, packCastling(after)), true);
}

DrawHistoryState getDrawHistoryState() {
    return {g_lastIrreversible, g_lastReal, g_lastValid};
}

bool isDrawByFiftyMove(const Position& pos) {
    return pos.halfMove >= 100;
}

bool isDrawByRepetition(const Position& pos) {
    if (!g_drawHistoryInitialized || g_lastValid - g_lastIrreversible < 2) return false;
    for (int i = g_lastValid - 2; i >= g_lastIrreversible; i -= 2) {
        if (g_drawHistory[i] == pos.hashKey) return true;
    }
    return false;
}
