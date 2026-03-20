#include "engine.h"

#include <algorithm>
#include <atomic>
#include <chrono>

namespace {

constexpr int INF_SCORE = 30000;
constexpr int DELTA_MARGIN = 200;

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

Piece capturedPieceForMove(const Position& pos, const Move& move) {
    if (move.isEnPassant) return pos.sideToMove == WHITE ? B_PAWN : W_PAWN;
    return pieceAt(pos, move.to);
}

bool isNoisyMove(const Position& pos, const Move& move) {
    return capturedPieceForMove(pos, move) != EMPTY || move.promotion != EMPTY;
}

int promotionGain(const Move& move) {
    if (move.promotion == EMPTY) return 0;
    return moveValueGuess(move.promotion) - moveValueGuess(W_PAWN);
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

int qsMoveOrderScore(const Position& pos, const Move& move) {
    Piece movingPiece = pieceAt(pos, move.from);
    Piece capturedPiece = capturedPieceForMove(pos, move);

    if (capturedPiece != EMPTY) {
        return 100000 + 10 * moveValueGuess(capturedPiece) - moveValueGuess(movingPiece) +
               promotionGain(move);
    }
    if (move.promotion != EMPTY) return 50000 + moveValueGuess(move.promotion);
    return 0;
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

int quiescence(Position& pos, int ply, int alpha, int beta, uint64_t& nodes) {
    if (shouldStop()) return evaluate(pos);

    nodes++;
    bool inCheckNow = inCheck(pos, pos.sideToMove);
    int standPat = 0;

    // Stand pat is only valid when we are not in check. In check, QS must search
    // all legal evasions and cannot rely on static eval for pruning.
    if (!inCheckNow) {
        standPat = evaluate(pos);
        if (standPat >= beta) return beta;
        if (standPat > alpha) alpha = standPat;
    }

    Move moves[MAX_MOVES];
    int moveCount = genLegalMoves(pos, moves);
    if (moveCount == 0) return terminalScore(pos, ply);

    // Outside check, QS only searches noisy continuations. In check, the full
    // legal evasion set stays in the list and capture evasions are ordered first.
    if (!inCheckNow) {
        int noisyCount = 0;
        for (int i = 0; i < moveCount; i++) {
            if (isNoisyMove(pos, moves[i])) moves[noisyCount++] = moves[i];
        }
        moveCount = noisyCount;
        if (moveCount == 0) return alpha;
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
        int score = -quiescence(pos, ply + 1, -beta, -alpha, nodes);
        undo(pos, move, undoState);

        if (shouldStop()) return alpha;
        if (score >= beta) return beta;
        if (score > alpha) alpha = score;
    }

    return alpha;
}

int alphaBeta(Position& pos, int depth, int ply, int alpha, int beta, uint64_t& nodes,
              Move pvTable[MAX_SEARCH_DEPTH][MAX_SEARCH_DEPTH], int pvLength[MAX_SEARCH_DEPTH]) {
    pvLength[ply] = 0;
    if (shouldStop()) return evaluate(pos);

    if (depth == 0) return quiescence(pos, ply, alpha, beta, nodes);

    nodes++;

    Move moves[MAX_MOVES];
    int moveCount = genLegalMoves(pos, moves);
    if (moveCount == 0) return terminalScore(pos, ply);

    orderMoves(pos, moves, moveCount, nullptr);

    for (int i = 0; i < moveCount; i++) {
        const Move& move = moves[i];
        UndoState undoState;
        doMove(pos, move, undoState);
        int score = -alphaBeta(pos, depth - 1, ply + 1, -beta, -alpha, nodes, pvTable, pvLength);
        undo(pos, move, undoState);

        if (shouldStop()) return alpha;
        if (score > alpha) {
            // When a move improves alpha, rebuild this ply's PV by prepending the
            // current move to the child PV we just searched.
            alpha = score;
            pvTable[ply][0] = move;
            for (int j = 0; j < pvLength[ply + 1]; j++) pvTable[ply][j + 1] = pvTable[ply + 1][j];
            pvLength[ply] = pvLength[ply + 1] + 1;
        }
        if (score >= beta) return beta;
    }

    return alpha;
}

}  // namespace

SearchResult searchBestMove(Position& pos, const SearchLimits& limits) {
    g_stopRequested.store(false, std::memory_order_relaxed);
    g_useDeadline = limits.movetimeMs > 0;
    if (g_useDeadline) g_deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(limits.movetimeMs);
    auto startTime = std::chrono::steady_clock::now();

    SearchResult result{{0, 0, EMPTY, false, false, false}, {}, 0, 0, 0, 0, 0, true, false};

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

    // Iterative deepening keeps the search usable under time control and gives us
    // a stable best move / PV to report after every completed depth.
    for (int depth = 1; depth <= maxDepth; depth++) {
        if (shouldStop()) break;

        Move iterationMoves[MAX_MOVES];
        for (int i = 0; i < rootCount; i++) iterationMoves[i] = rootMoves[i];
        orderMoves(pos, iterationMoves, rootCount, &preferredMove);

        int alpha = -INF_SCORE;
        int beta = INF_SCORE;
        int bestScore = -INF_SCORE;
        Move bestMove = iterationMoves[0];
        Move bestPv[MAX_SEARCH_DEPTH];
        int bestPvLength = 1;
        uint64_t iterationNodes = 0;
        bool interrupted = false;

        for (int i = 0; i < rootCount; i++) {
            const Move& move = iterationMoves[i];
            UndoState undoState;
            doMove(pos, move, undoState);
            int score = -alphaBeta(pos, depth - 1, 1, -beta, -alpha, iterationNodes, pvTable, pvLength);
            undo(pos, move, undoState);

            if (shouldStop()) {
                interrupted = true;
                break;
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

        if (limits.infoCallback != nullptr) limits.infoCallback(result, limits.infoUserData);
    }

    return result;
}

void requestSearchStop() {
    g_stopRequested.store(true, std::memory_order_relaxed);
}
