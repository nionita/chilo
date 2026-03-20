#include "engine.h"

#include <algorithm>
#include <atomic>
#include <chrono>

namespace {

constexpr int INF_SCORE = 30000;
constexpr int MATE_SCORE = 29000;

std::atomic<bool> g_stopRequested{false};
std::chrono::steady_clock::time_point g_deadline;
bool g_useDeadline = false;

bool movesEqual(const Move& a, const Move& b) {
    return a.from == b.from && a.to == b.to && a.promotion == b.promotion &&
           a.isEnPassant == b.isEnPassant && a.isCastle == b.isCastle && a.isDoublePush == b.isDoublePush;
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

bool shouldStop() {
    if (g_stopRequested.load(std::memory_order_relaxed)) return true;
    if (g_useDeadline && std::chrono::steady_clock::now() >= g_deadline) {
        g_stopRequested.store(true, std::memory_order_relaxed);
        return true;
    }
    return false;
}

int moveOrderScore(const Position& pos, const Move& move, const Move* preferredMove) {
    if (preferredMove != nullptr && movesEqual(move, *preferredMove)) return 1000000;

    int score = 0;
    Piece movingPiece = pieceAt(pos, move.from);
    Piece capturedPiece = move.isEnPassant
                              ? (pos.sideToMove == WHITE ? B_PAWN : W_PAWN)
                              : pieceAt(pos, move.to);
    if (capturedPiece != EMPTY) score += 100000 + 10 * moveValueGuess(capturedPiece) - moveValueGuess(movingPiece);
    if (move.promotion != EMPTY) score += 50000 + moveValueGuess(move.promotion);
    if (move.isCastle) score += 1000;
    return score;
}

void orderMoves(const Position& pos, Move* moves, int count, const Move* preferredMove) {
    int scores[MAX_MOVES];
    for (int i = 0; i < count; i++) scores[i] = moveOrderScore(pos, moves[i], preferredMove);

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
    if (inCheck(pos, pos.sideToMove)) return -MATE_SCORE + ply;
    return 0;
}

int alphaBeta(Position& pos, int depth, int ply, int alpha, int beta, uint64_t& nodes) {
    if (shouldStop()) return evaluate(pos);

    nodes++;
    if (depth == 0) return evaluate(pos);

    Move moves[MAX_MOVES];
    int moveCount = genLegalMoves(pos, moves);
    if (moveCount == 0) return terminalScore(pos, ply);

    orderMoves(pos, moves, moveCount, nullptr);

    for (int i = 0; i < moveCount; i++) {
        const Move& move = moves[i];
        UndoState undoState;
        doMove(pos, move, undoState);
        int score = -alphaBeta(pos, depth - 1, ply + 1, -beta, -alpha, nodes);
        undo(pos, move, undoState);

        if (shouldStop()) return alpha;
        if (score >= beta) return beta;
        if (score > alpha) alpha = score;
    }

    return alpha;
}

}  // namespace

SearchResult searchBestMove(Position& pos, const SearchLimits& limits) {
    g_stopRequested.store(false, std::memory_order_relaxed);
    g_useDeadline = limits.movetimeMs > 0;
    if (g_useDeadline) g_deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(limits.movetimeMs);

    SearchResult result{{-1, -1, EMPTY, false, false, false}, 0, 0, 0, true, false};

    Move rootMoves[MAX_MOVES];
    int rootCount = genLegalMoves(pos, rootMoves);
    if (rootCount == 0) {
        result.score = terminalScore(pos, 0);
        return result;
    }

    result.bestMove = rootMoves[0];
    result.hasMove = true;

    int maxDepth = limits.depth > 0 ? limits.depth : 64;
    Move preferredMove = result.bestMove;

    for (int depth = 1; depth <= maxDepth; depth++) {
        if (shouldStop()) break;

        Move iterationMoves[MAX_MOVES];
        for (int i = 0; i < rootCount; i++) iterationMoves[i] = rootMoves[i];
        orderMoves(pos, iterationMoves, rootCount, &preferredMove);

        int alpha = -INF_SCORE;
        int beta = INF_SCORE;
        int bestScore = -INF_SCORE;
        Move bestMove = iterationMoves[0];
        uint64_t iterationNodes = 0;
        bool interrupted = false;

        for (int i = 0; i < rootCount; i++) {
            const Move& move = iterationMoves[i];
            UndoState undoState;
            doMove(pos, move, undoState);
            int score = -alphaBeta(pos, depth - 1, 1, -beta, -alpha, iterationNodes);
            undo(pos, move, undoState);

            if (shouldStop()) {
                interrupted = true;
                break;
            }
            if (score > bestScore) {
                bestScore = score;
                bestMove = move;
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
        result.score = bestScore;
        result.depth = depth;
        result.completed = true;
    }

    return result;
}

void requestSearchStop() {
    g_stopRequested.store(true, std::memory_order_relaxed);
}
