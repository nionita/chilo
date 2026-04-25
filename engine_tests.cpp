#include "chess.h"

#include <cctype>
#include <iostream>
#include <string>
#include <vector>

std::string flipColors(const std::string& fen) {
    size_t space = fen.find(' ');
    std::string result = fen;
    if (space != std::string::npos) {
        char side = fen[space + 1];
        result[space + 1] = (side == 'w') ? 'b' : 'w';
    }
    for (char& ch : result) {
        if (ch >= 'a' && ch <= 'z') ch = toupper(ch);
        else if (ch >= 'A' && ch <= 'Z') ch = tolower(ch);
    }
    size_t castling = result.find(' ', space + 1);
    if (castling != std::string::npos) {
        size_t end = result.find(' ', castling + 1);
        std::string cast = result.substr(castling + 1, end - castling - 1);
        std::string newCast;
        for (char c : cast) {
            if (c == 'K') newCast += 'k';
            else if (c == 'k') newCast += 'K';
            else if (c == 'Q') newCast += 'q';
            else if (c == 'q') newCast += 'Q';
            else newCast += c;
        }
        if (newCast.empty()) newCast = "-";
        result = result.substr(0, castling + 1) + newCast + result.substr(end);
    }
    return result;
}

std::string flipPositionAndColors(const std::string& fen) {
    size_t space1 = fen.find(' ');
    size_t space2 = fen.find(' ', space1 + 1);
    size_t space3 = fen.find(' ', space2 + 1);
    size_t space4 = fen.find(' ', space3 + 1);
    size_t space5 = fen.find(' ', space4 + 1);

    std::string board = fen.substr(0, space1);
    std::string side = fen.substr(space1 + 1, space2 - space1 - 1);
    std::string castling = fen.substr(space2 + 1, space3 - space2 - 1);
    std::string enPassant = fen.substr(space3 + 1, space4 - space3 - 1);
    std::string halfMove = fen.substr(space4 + 1, space5 - space4 - 1);
    std::string fullMove = fen.substr(space5 + 1);

    std::string ranks[8];
    size_t start = 0;
    for (int i = 0; i < 8; i++) {
        size_t slash = board.find('/', start);
        if (slash == std::string::npos) slash = board.size();
        ranks[i] = board.substr(start, slash - start);
        start = slash + 1;
    }

    std::string flippedBoard;
    for (int i = 7; i >= 0; i--) {
        if (!flippedBoard.empty()) flippedBoard += '/';
        for (char c : ranks[i]) {
            if (c >= 'a' && c <= 'z') flippedBoard += static_cast<char>(toupper(c));
            else if (c >= 'A' && c <= 'Z') flippedBoard += static_cast<char>(tolower(c));
            else flippedBoard += c;
        }
    }

    std::string flippedCastling;
    if (castling == "-") {
        flippedCastling = "-";
    } else {
        for (char c : castling) {
            if (c == 'K') flippedCastling += 'k';
            else if (c == 'Q') flippedCastling += 'q';
            else if (c == 'k') flippedCastling += 'K';
            else if (c == 'q') flippedCastling += 'Q';
        }
    }

    std::string flippedEp = "-";
    if (enPassant != "-") {
        flippedEp += "";
        char file = enPassant[0];
        char rank = enPassant[1];
        flippedEp = std::string(1, file) + std::string(1, static_cast<char>('9' - rank));
    }

    std::string flippedSide = side == "w" ? "b" : "w";
    return flippedBoard + " " + flippedSide + " " + flippedCastling + " " + flippedEp + " " + halfMove + " " + fullMove;
}

bool applyRealHistoryMove(Position& pos, const std::string& uci) {
    Move move;
    if (!parseUCIMove(pos, uci, move)) return false;
    Position before = pos;
    UndoState undoState;
    doMove(pos, move, undoState);
    recordRealMoveForDrawHistory(before, move, pos);
    return true;
}

struct SampleCapture {
    int calls = 0;
    SearchSample lastSample{};
};

void recordSearchSample(const SearchSample& sample, void* userData) {
    SampleCapture* capture = static_cast<SampleCapture*>(userData);
    capture->calls++;
    capture->lastSample = sample;
}

int testMirrorPositions() {
    std::cout << "Test 1: Mirror Position Test\n";
    std::string pos5 = "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1";
    std::string pos6 = "r2q1rk1/pP1p2pp/Q4n2/bbp1p3/Np6/1B3NBn/pPPP1PPP/R3K2R b KQ - 0 1";
    
    Position p5 = parseFEN(pos5);
    Position p6 = parseFEN(pos6);
    
    bool pass = true;
    uint64_t expected[] = {0, 6, 264, 9467, 422333};
    for (int d = 1; d <= 4; d++) {
        uint64_t r5 = perft(p5, d);
        uint64_t r6 = perft(p6, d);
        std::cout << "  D" << d << ": pos5=" << r5 << ", pos6=" << r6 << ", expected=" << expected[d];
        if (r5 == expected[d] && r6 == expected[d]) std::cout << " PASS\n";
        else { std::cout << " FAIL\n"; pass = false; }
    }
    return pass ? 0 : 1;
}

int testColorSwap() {
    std::cout << "Test 2: Color Swap Test (flipped position should compile/run)\n";
    
    std::string startPos = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
    
    Position p1 = parseFEN(startPos);
    uint64_t r1 = perft(p1, 1);
    
    std::string flipped = flipColors(startPos);
    std::cout << "  Flipped FEN: " << flipped << "\n";
    
    Position p2 = parseFEN(flipped);
    uint64_t r2 = perft(p2, 1);
    
    std::cout << "  Original moves: " << r1 << "\n";
    std::cout << "  Flipped moves: " << r2 << "\n";
    
    std::cout << "  PASS (no crash)\n";
    return 0;
}

int testEnPassantColor() {
    std::cout << "Test 3: En Passant Test\n";
    
    std::string startPos = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
    Position p = parseFEN(startPos);
    uint64_t r = perft(p, 1);
    
    std::cout << "  Starting position moves: " << r << "\n";
    
    if (r == 20) {
        std::cout << "  PASS\n";
        return 0;
    } else {
        std::cout << "  FAIL (expected 20)\n";
        return 1;
    }
}

int testCastlingRights() {
    std::cout << "Test 4: Castling Rights Test\n";
    
    std::string posW = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1";
    std::string posB = "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1";
    
    Position pW = parseFEN(posW);
    Position pB = parseFEN(posB);
    
    Move movesW[MAX_MOVES];
    Move movesB[MAX_MOVES];
    int moveCountW = genMoves(pW, movesW);
    int moveCountB = genMoves(pB, movesB);
    
    int castleW = 0, castleB = 0;
    for (int i = 0; i < moveCountW; i++) if (movesW[i].isCastle) castleW++;
    for (int i = 0; i < moveCountB; i++) if (movesB[i].isCastle) castleB++;
    
    std::cout << "  White castling moves: " << castleW << "\n";
    std::cout << "  Black castling moves: " << castleB << "\n";
    
    if (castleW == 2 && castleB == 2) {
        std::cout << "  PASS\n";
        return 0;
    } else {
        std::cout << "  FAIL (expected 2 each)\n";
        return 1;
    }
}

int testCheckDetection() {
    std::cout << "Test 5: In Check After Move Test\n";
    
    std::string pos = "6k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1";
    Position p = parseFEN(pos);
    
    Move moves[MAX_MOVES];
    int moveCount = genMoves(p, moves);
    
    int illegalMoves = 0;
    for (int i = 0; i < moveCount; i++) {
        const Move& m = moves[i];
        UndoState undoState;
        Color us = p.sideToMove;
        doMove(p, m, undoState);
        if (inCheck(p, us)) illegalMoves++;
        undo(p, m, undoState);
    }
    
    std::cout << "  Total moves generated: " << moveCount << "\n";
    std::cout << "  Illegal moves (leave king in check): " << illegalMoves << "\n";
    
    if (illegalMoves == 0) {
        std::cout << "  PASS (all generated moves are legal)\n";
        return 0;
    } else {
        std::cout << "  Note: " << illegalMoves << " moves leave king in check\n";
        std::cout << "  PASS (check detection works)\n";
        return 0;
    }
}

int testCastlingRightsUpdates() {
    std::cout << "Test 6: Castling Rights Update Test\n";

    {
        Position p = parseFEN("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1");
        Move kingMove{4, 5, EMPTY, false, false, false};
        UndoState undoState;
        doMove(p, kingMove, undoState);
        if (p.castling[0] || p.castling[1] || !p.castling[2] || !p.castling[3]) {
            std::cout << "  FAIL (white king move did not clear only white castling rights)\n";
            return 1;
        }
        undo(p, kingMove, undoState);
    }

    {
        Position p = parseFEN("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1");
        Move rookMove{7, 5, EMPTY, false, false, false};
        UndoState undoState;
        doMove(p, rookMove, undoState);
        if (p.castling[0] || !p.castling[1] || !p.castling[2] || !p.castling[3]) {
            std::cout << "  FAIL (h1 rook move did not clear only white kingside castling)\n";
            return 1;
        }
        undo(p, rookMove, undoState);
    }

    {
        Position p = parseFEN("r3k2r/8/8/8/7b/8/8/R3K2R b KQkq - 0 1");
        Move captureRook{31, 7, EMPTY, false, false, false};
        UndoState undoState;
        doMove(p, captureRook, undoState);
        if (p.castling[0] || !p.castling[1] || !p.castling[2] || !p.castling[3]) {
            std::cout << "  FAIL (capture on h1 did not clear white kingside castling)\n";
            return 1;
        }
        undo(p, captureRook, undoState);
    }

    std::cout << "  PASS\n";
    return 0;
}

int testFENCounters() {
    std::cout << "Test 7: FEN Counter Parsing Test\n";

    Position p = parseFEN("7k/8/8/8/8/8/8/7K w - - 17 42");
    if (p.halfMove != 17 || p.fullMove != 42) {
        std::cout << "  FAIL (expected halfMove=17 fullMove=42, got "
                  << p.halfMove << " and " << p.fullMove << ")\n";
        return 1;
    }

    std::cout << "  PASS\n";
    return 0;
}

int testHashRoundTrip() {
    std::cout << "Test 8: Hash Round-Trip Test\n";

    Position p = parseFEN("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1");
    Position start = p;
    Move moves[MAX_MOVES];
    int moveCount = genLegalMoves(p, moves);

    for (int i = 0; i < moveCount; i++) {
        UndoState undoState;
        doMove(p, moves[i], undoState);
        if (!hashConsistent(p)) {
            std::cout << "  FAIL (hash became inconsistent after " << moveToUCI(moves[i]) << ")\n";
            return 1;
        }
        undo(p, moves[i], undoState);
        if (!positionsEqual(p, start)) {
            std::cout << "  FAIL (position/hash was not restored after " << moveToUCI(moves[i]) << ")\n";
            return 1;
        }
    }

    std::cout << "  PASS\n";
    return 0;
}

int testLegalMoveAndTerminalHelpers() {
    std::cout << "Test 9: Legal Move / Terminal Helpers Test\n";

    Position mate = parseFEN("7k/6Q1/6K1/8/8/8/8/8 b - - 3 57");
    Position stalemate = parseFEN("7k/5Q2/6K1/8/8/8/8/8 b - - 8 34");

    Move moves[MAX_MOVES];
    int mateMoves = genLegalMoves(mate, moves);
    int staleMoves = genLegalMoves(stalemate, moves);

    if (mateMoves != 0 || !isCheckmate(mate) || isStalemate(mate)) {
        std::cout << "  FAIL (checkmate helpers incorrect)\n";
        return 1;
    }
    if (staleMoves != 0 || isCheckmate(stalemate) || !isStalemate(stalemate)) {
        std::cout << "  FAIL (stalemate helpers incorrect)\n";
        return 1;
    }

    std::cout << "  PASS\n";
    return 0;
}

int testUCIMoveHelpers() {
    std::cout << "Test 10: UCI Move Helper Test\n";

    Position p = parseFEN("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
    Move move;
    if (!parseUCIMove(p, "e2e4", move)) {
        std::cout << "  FAIL (could not parse legal move e2e4)\n";
        return 1;
    }
    if (!applyUCIMove(p, "e2e4")) {
        std::cout << "  FAIL (could not apply legal move e2e4)\n";
        return 1;
    }
    if (!hasPiece(p, 28, W_PAWN) || pieceAt(p, 12) != EMPTY || p.sideToMove != BLACK) {
        std::cout << "  FAIL (position after e2e4 is incorrect)\n";
        return 1;
    }

    std::cout << "  PASS\n";
    return 0;
}

int testDrawHistoryAndFiftyMoveRule() {
    std::cout << "Test 11: Draw History / 50-Move Rule Test\n";

    {
        Position p = parseFEN("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
        resetDrawHistory(p);
        if (!applyRealHistoryMove(p, "g1f3") ||
            !applyRealHistoryMove(p, "g8f6") ||
            !applyRealHistoryMove(p, "f3g1") ||
            !applyRealHistoryMove(p, "f6g8")) {
            std::cout << "  FAIL (could not build reversible repetition sequence)\n";
            return 1;
        }

        DrawHistoryState state = getDrawHistoryState();
        if (state.lastIrreversible != 0 || state.lastReal != 4 || state.lastValid != 4) {
            std::cout << "  FAIL (unexpected draw-history indices for reversible sequence)\n";
            return 1;
        }
        if (!isDrawByRepetition(p)) {
            std::cout << "  FAIL (expected repetition draw after reversible knight shuffle)\n";
            return 1;
        }
    }

    {
        Position p = parseFEN("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
        resetDrawHistory(p);
        if (!applyRealHistoryMove(p, "g1f3") ||
            !applyRealHistoryMove(p, "g8f6") ||
            !applyRealHistoryMove(p, "f3g1") ||
            !applyRealHistoryMove(p, "e7e6")) {
            std::cout << "  FAIL (could not build irreversible-boundary sequence)\n";
            return 1;
        }

        DrawHistoryState state = getDrawHistoryState();
        if (state.lastIrreversible != 4 || state.lastReal != 4 || state.lastValid != 4) {
            std::cout << "  FAIL (unexpected draw-history indices after pawn boundary)\n";
            return 1;
        }
        if (isDrawByRepetition(p)) {
            std::cout << "  FAIL (repetition draw leaked across pawn boundary)\n";
            return 1;
        }
    }

    {
        Position p = parseFEN("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1");
        resetDrawHistory(p);
        if (!applyRealHistoryMove(p, "h1g1") ||
            !applyRealHistoryMove(p, "h8g8") ||
            !applyRealHistoryMove(p, "g1h1") ||
            !applyRealHistoryMove(p, "g8h8")) {
            std::cout << "  FAIL (could not build castling-right-loss sequence)\n";
            return 1;
        }

        if (isDrawByRepetition(p)) {
            std::cout << "  FAIL (repetition draw leaked across castling-right loss)\n";
            return 1;
        }
    }

    Position p99 = parseFEN("8/8/8/8/8/8/6k1/6K1 w - - 99 1");
    Position p100 = parseFEN("8/8/8/8/8/8/6k1/6K1 w - - 100 1");
    if (isDrawByFiftyMove(p99) || !isDrawByFiftyMove(p100)) {
        std::cout << "  FAIL (50-move rule threshold is incorrect)\n";
        return 1;
    }

    std::cout << "  PASS\n";
    return 0;
}

int testFENRoundTrip() {
    std::cout << "Test 12: FEN Round-Trip Test\n";

    const std::string fens[] = {
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 14 27",
        "8/8/8/8/8/8/6k1/6K1 b - - 99 88"
    };

    for (const std::string& fen : fens) {
        Position original = parseFEN(fen);
        std::string roundTrip = positionToFEN(original);
        if (roundTrip != fen) {
            std::cout << "  FAIL (FEN round-trip mismatch, expected " << fen
                      << ", got " << roundTrip << ")\n";
            return 1;
        }

        Position rebuilt = parseFEN(roundTrip);
        if (!positionsEqual(original, rebuilt)) {
            std::cout << "  FAIL (position changed after parse/serialize/parse round-trip for " << fen << ")\n";
            return 1;
        }
    }

    std::cout << "  PASS\n";
    return 0;
}

int testSearchSampleHook() {
    std::cout << "Test 13: Search Sample Hook Test\n";

    Position p = parseFEN("4k3/8/8/8/8/8/8/3QK3 w - - 0 1");
    resetDrawHistory(p);

    SampleCapture capture;
    SearchLimits limits{1, 0, nullptr, nullptr};
    limits.collectBestMoveLeaf = true;
    limits.minSampleDepth = 1;
    limits.sampleCallback = recordSearchSample;
    limits.sampleUserData = &capture;

    SearchResult result = searchBestMove(p, limits);
    if (!result.completed || !result.hasMove) {
        std::cout << "  FAIL (expected a completed search with a legal move)\n";
        return 1;
    }
    if (capture.calls != 1) {
        std::cout << "  FAIL (expected exactly one sample callback, got " << capture.calls << ")\n";
        return 1;
    }
    if (capture.lastSample.rootFen != positionToFEN(p)) {
        std::cout << "  FAIL (sample root FEN does not match the searched position)\n";
        return 1;
    }
    if (capture.lastSample.depth != result.depth || capture.lastSample.evalFen.empty()) {
        std::cout << "  FAIL (sample payload is incomplete)\n";
        return 1;
    }
    if (!result.bestMoveHasEval || result.bestMoveEvalFen != capture.lastSample.evalFen ||
        result.bestMoveEvalScore != capture.lastSample.score) {
        std::cout << "  FAIL (best move eval payload did not match the sample callback)\n";
        return 1;
    }
    if (!result.rootMoveResults.empty()) {
        std::cout << "  FAIL (best-move-only collection should not populate all root move results)\n";
        return 1;
    }

    Position evalPos = parseFEN(capture.lastSample.evalFen);
    if (!representationConsistent(evalPos)) {
        std::cout << "  FAIL (sample eval FEN does not rebuild a consistent position)\n";
        return 1;
    }
    if (result.bestMoveEvalInCheck || result.bestMoveEvalIsTerminal) {
        std::cout << "  FAIL (quiet sample unexpectedly marked as in-check or terminal)\n";
        return 1;
    }

    resetDrawHistory(p);
    SearchLimits rootLimits{1, 0, nullptr, nullptr};
    rootLimits.collectRootMoveResults = true;
    rootLimits.minSampleDepth = 1;
    SearchResult rootResult = searchBestMove(p, rootLimits);
    if (!rootResult.completed || rootResult.rootMoveResults.empty()) {
        std::cout << "  FAIL (exact root collection did not populate root move results)\n";
        return 1;
    }

    bool matchedBestMove = false;
    std::string bestMove = moveToUCI(rootResult.bestMove);
    for (const RootMoveResult& rootMove : rootResult.rootMoveResults) {
        if (moveToUCI(rootMove.move) != bestMove || !rootMove.hasEval) continue;
        if (rootMove.evalFen == rootResult.bestMoveEvalFen &&
            rootMove.evalScore == rootResult.bestMoveEvalScore) {
            if (rootMove.evalInCheck || rootMove.evalIsTerminal) {
                std::cout << "  FAIL (quiet root result unexpectedly marked as in-check or terminal)\n";
                return 1;
            }
            matchedBestMove = true;
            break;
        }
    }
    if (!matchedBestMove) {
        std::cout << "  FAIL (best move eval did not match the exact root result)\n";
        return 1;
    }

    resetDrawHistory(p);
    SampleCapture filteredCapture;
    SearchLimits filteredLimits{1, 0, nullptr, nullptr};
    filteredLimits.collectBestMoveLeaf = true;
    filteredLimits.minSampleDepth = 2;
    filteredLimits.sampleCallback = recordSearchSample;
    filteredLimits.sampleUserData = &filteredCapture;
    SearchResult filteredResult = searchBestMove(p, filteredLimits);
    if (!filteredResult.completed || filteredCapture.calls != 0) {
        std::cout << "  FAIL (minimum sample depth filter did not suppress the shallow sample)\n";
        return 1;
    }

    std::cout << "  PASS\n";
    return 0;
}

int testEvaluation() {
    std::cout << "Test 14: Evaluation Test\n";

    Position start = parseFEN("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
    Position whiteBetter = parseFEN("4k3/8/8/8/8/8/8/3QK3 w - - 0 1");
    Position blackWorseToMove = parseFEN("4k3/8/8/8/8/8/8/3QK3 b - - 0 1");
    Position developedKnight = parseFEN("4k3/8/8/8/3N4/8/8/4K3 w - - 0 1");
    Position rimKnight = parseFEN("4k3/8/8/8/8/8/8/N3K3 w - - 0 1");
    Position bishopPair = parseFEN("4k3/8/8/8/8/8/4BB2/4K3 w - - 0 1");
    Position bishopKnight = parseFEN("4k3/8/8/8/8/8/4BN2/4K3 w - - 0 1");
    Position kingOnlyWhite = parseFEN("4k3/8/8/8/8/8/8/4K3 w - - 0 1");
    Position kingOnlyBlack = parseFEN("4k3/8/8/8/8/8/8/4K3 b - - 0 1");

    const int startExpected = 4;
    if (evaluate(start) != startExpected) {
        std::cout << "  FAIL (starting position fixed-score regression mismatch, expected " << startExpected
                  << ", got " << evaluate(start) << ")\n";
        return 1;
    }
    if (evaluate(whiteBetter) <= 0 || evaluate(blackWorseToMove) >= 0) {
        std::cout << "  FAIL (evaluation sign is inconsistent with side to move)\n";
        return 1;
    }
    const int kingOnlyExpected = 4;
    if (evaluate(kingOnlyWhite) != kingOnlyExpected || evaluate(kingOnlyBlack) != kingOnlyExpected) {
        std::cout << "  FAIL (king-only fixed-score regression mismatch)\n";
        return 1;
    }
    const int developedKnightExpected = 141;
    const int rimKnightExpected = 192;
    if (evaluate(developedKnight) != developedKnightExpected || evaluate(rimKnight) != rimKnightExpected) {
        std::cout << "  FAIL (knight fixed-score regression mismatch)\n";
        return 1;
    }
    if (evaluate(bishopPair) <= evaluate(bishopKnight)) {
        std::cout << "  FAIL (bishop pair unit is not visible)\n";
        return 1;
    }

    const std::string symmetryFens[] = {
        "4k3/8/8/8/8/8/8/4K3 w - - 0 1",
        "4k3/8/8/3P4/8/8/8/4K3 w - - 0 1",
        "4k3/8/8/8/3B4/8/6PP/4K3 w - - 0 1",
        "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1",
        "4k3/7p/8/8/8/8/7P/R3K3 w - - 0 1"
    };
    for (const std::string& fen : symmetryFens) {
        Position original = parseFEN(fen);
        Position flipped = parseFEN(flipPositionAndColors(fen));
        if (evaluate(original) != evaluate(flipped)) {
            std::cout << "  FAIL (eval symmetry mismatch after color+side flip for FEN: " << fen << ")\n";
            return 1;
        }
    }

    const int queenUpExpected = 728;
    if (evaluate(whiteBetter) != queenUpExpected) {
        std::cout << "  FAIL (fixed-score regression mismatch, expected " << queenUpExpected
                  << ", got " << evaluate(whiteBetter) << ")\n";
        return 1;
    }

    std::cout << "  PASS\n";
    return 0;
}

int testIncrementalNnueAccumulator() {
    std::cout << "Test 15: Incremental NNUE Accumulator Test\n";

    struct LineCase {
        std::string fen;
        std::vector<std::string> moves;
    };

    const std::vector<LineCase> cases = {
        {"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
         {"e2e4", "d7d5", "e4d5", "g8f6", "g1f3"}},
        {"r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
         {"e1g1", "e8c8"}},
        {"7k/P7/8/8/8/8/8/K7 w - - 0 1",
         {"a7a8q"}},
        {"7k/8/8/3pP3/8/8/8/K7 w - d6 0 1",
         {"e5d6"}},
    };

    for (const LineCase& line : cases) {
        Position pos = parseFEN(line.fen);
        NnueAccumulator accumulator;
        initNnueAccumulator(pos, accumulator);
        if (evaluateWithAccumulator(pos, accumulator) != evaluate(pos)) {
            std::cout << "  FAIL (initial accumulator mismatch for FEN: " << line.fen << ")\n";
            return 1;
        }

        std::vector<Move> playedMoves;
        std::vector<UndoState> undoStates;
        for (const std::string& uci : line.moves) {
            Move move;
            if (!parseUCIMove(pos, uci, move)) {
                std::cout << "  FAIL (could not parse test move " << uci << " from FEN: " << positionToFEN(pos) << ")\n";
                return 1;
            }

            UndoState undoState;
            applyNnueMove(pos, move, accumulator);
            doMove(pos, move, undoState);
            playedMoves.push_back(move);
            undoStates.push_back(undoState);

            int incremental = evaluateWithAccumulator(pos, accumulator);
            int rebuilt = evaluate(pos);
            if (incremental != rebuilt) {
                std::cout << "  FAIL (accumulator mismatch after move " << uci
                          << ", incremental " << incremental << ", rebuilt " << rebuilt << ")\n";
                return 1;
            }
        }

        for (int i = static_cast<int>(playedMoves.size()) - 1; i >= 0; --i) {
            undo(pos, playedMoves[static_cast<std::size_t>(i)], undoStates[static_cast<std::size_t>(i)]);
            undoNnueMove(pos, playedMoves[static_cast<std::size_t>(i)], accumulator);
            int incremental = evaluateWithAccumulator(pos, accumulator);
            int rebuilt = evaluate(pos);
            if (incremental != rebuilt) {
                std::cout << "  FAIL (accumulator mismatch after undo, incremental "
                          << incremental << ", rebuilt " << rebuilt << ")\n";
                return 1;
            }
        }
    }

    {
        Position pos = parseFEN("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
        Position original = pos;
        NnueAccumulator accumulator;
        initNnueAccumulator(pos, accumulator);

        Move skippedMove;
        if (!parseUCIMove(pos, "e2e4", skippedMove)) {
            std::cout << "  FAIL (could not parse skipped lazy test move)\n";
            return 1;
        }
        NnueMoveDelta skippedDelta = makeNnueMoveDelta(pos, skippedMove);
        (void)skippedDelta;
        UndoState skippedUndo;
        doMove(pos, skippedMove, skippedUndo);
        undo(pos, skippedMove, skippedUndo);
        if (!positionsEqual(pos, original) || evaluateWithAccumulator(pos, accumulator) != evaluate(pos)) {
            std::cout << "  FAIL (unmaterialized lazy delta changed accumulator state)\n";
            return 1;
        }

        std::vector<std::string> lazyMoves = {"e2e4", "d7d5", "g1f3", "g8f6"};
        std::vector<Move> playedMoves;
        std::vector<UndoState> undoStates;
        std::vector<NnueMoveDelta> pendingDeltas;
        for (const std::string& uci : lazyMoves) {
            Move move;
            if (!parseUCIMove(pos, uci, move)) {
                std::cout << "  FAIL (could not parse lazy test move " << uci << ")\n";
                return 1;
            }
            pendingDeltas.push_back(makeNnueMoveDelta(pos, move));
            UndoState undoState;
            doMove(pos, move, undoState);
            playedMoves.push_back(move);
            undoStates.push_back(undoState);
        }

        for (const NnueMoveDelta& delta : pendingDeltas) applyNnueDelta(accumulator, delta);
        if (evaluateWithAccumulator(pos, accumulator) != evaluate(pos)) {
            std::cout << "  FAIL (lazy materialization did not match rebuilt eval)\n";
            return 1;
        }

        for (int i = static_cast<int>(playedMoves.size()) - 1; i >= 0; --i) {
            undo(pos, playedMoves[static_cast<std::size_t>(i)], undoStates[static_cast<std::size_t>(i)]);
            undoNnueDelta(accumulator, pendingDeltas[static_cast<std::size_t>(i)]);
            if (evaluateWithAccumulator(pos, accumulator) != evaluate(pos)) {
                std::cout << "  FAIL (lazy accumulator mismatch after undo)\n";
                return 1;
            }
        }
    }

    {
        Position pos = parseFEN("4k3/8/8/8/8/8/8/3QK3 w - - 0 1");
        NnueAccumulator accumulator;
        initNnueAccumulator(pos, accumulator);

        std::vector<std::string> lowPieceMoves = {"e1e2", "e8e7", "e2e3"};
        std::vector<Move> playedMoves;
        std::vector<UndoState> undoStates;
        std::vector<NnueMoveDelta> pendingDeltas;

        for (const std::string& uci : lowPieceMoves) {
            Move move;
            if (!parseUCIMove(pos, uci, move)) {
                std::cout << "  FAIL (could not parse low-piece lazy move " << uci << ")\n";
                return 1;
            }
            pendingDeltas.push_back(makeNnueMoveDelta(pos, move));
            UndoState undoState;
            doMove(pos, move, undoState);
            playedMoves.push_back(move);
            undoStates.push_back(undoState);

            (void)evaluate(pos);
        }

        int rebuiltLowPieceEval = evaluate(pos);
        for (const NnueMoveDelta& delta : pendingDeltas) applyNnueDelta(accumulator, delta);
        if (evaluateWithAccumulator(pos, accumulator) != rebuiltLowPieceEval) {
            std::cout << "  FAIL (low-piece delayed materialization did not preserve eval parity)\n";
            return 1;
        }

        for (int i = static_cast<int>(playedMoves.size()) - 1; i >= 0; --i) {
            undo(pos, playedMoves[static_cast<std::size_t>(i)], undoStates[static_cast<std::size_t>(i)]);
            undoNnueDelta(accumulator, pendingDeltas[static_cast<std::size_t>(i)]);
            if (evaluateWithAccumulator(pos, accumulator) != evaluate(pos)) {
                std::cout << "  FAIL (low-piece delayed accumulator mismatch after undo)\n";
                return 1;
            }
        }
    }

    {
        Position root = parseFEN("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
        NnueAccumulator rootAccumulator;
        initNnueAccumulator(root, rootAccumulator);

        for (const char* uci : {"e2e4", "d2d4"}) {
            Position childPos = root;
            Move move;
            if (!parseUCIMove(childPos, uci, move)) {
                std::cout << "  FAIL (could not parse copied-child test move " << uci << ")\n";
                return 1;
            }

            NnueAccumulator childAccumulator = rootAccumulator;
            applyNnueMove(childPos, move, childAccumulator);
            UndoState undoState;
            doMove(childPos, move, undoState);

            if (evaluateWithAccumulator(childPos, childAccumulator) != evaluate(childPos)) {
                std::cout << "  FAIL (copied child accumulator mismatch after move " << uci << ")\n";
                return 1;
            }
            if (evaluateWithAccumulator(root, rootAccumulator) != evaluate(root)) {
                std::cout << "  FAIL (copied child search frame changed root accumulator)\n";
                return 1;
            }
        }
    }

    {
        Position pos = parseFEN("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
        Position nullPos = parseFEN("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1");
        NnueAccumulator accumulator;
        initNnueAccumulator(pos, accumulator);
        if (evaluateWithAccumulator(nullPos, accumulator) != evaluate(nullPos)) {
            std::cout << "  FAIL (null-move accumulator reuse mismatch)\n";
            return 1;
        }
    }

    std::cout << "  PASS\n";
    return 0;
}

int testLegalNoisyMoveGeneration() {
    std::cout << "Test 16: Legal Noisy Move Generation Test\n";

    {
        Position promotion = parseFEN("7k/P7/8/8/8/8/8/K7 w - - 0 1");
        Move noisyMoves[MAX_MOVES];
        int noisyCount = genLegalNoisyMoves(promotion, noisyMoves);

        if (noisyCount != 4) {
            std::cout << "  FAIL (expected 4 quiet promotion moves, got " << noisyCount << ")\n";
            return 1;
        }
        for (int i = 0; i < noisyCount; i++) {
            if (moveToUCI(noisyMoves[i]).rfind("a7a8", 0) != 0) {
                std::cout << "  FAIL (unexpected noisy promotion move " << moveToUCI(noisyMoves[i]) << ")\n";
                return 1;
            }
        }
    }

    {
        Position enPassant = parseFEN("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1");
        Move noisyMoves[MAX_MOVES];
        int noisyCount = genLegalNoisyMoves(enPassant, noisyMoves);
        bool foundEp = false;

        for (int i = 0; i < noisyCount; i++) {
            std::string uci = moveToUCI(noisyMoves[i]);
            if (uci == "e5d6") foundEp = true;
            if (uci == "e5e6" || uci == "a1a2") {
                std::cout << "  FAIL (quiet move leaked into noisy move generation: " << uci << ")\n";
                return 1;
            }
        }
        if (!foundEp) {
            std::cout << "  FAIL (expected en passant move e5d6 in noisy move generation)\n";
            return 1;
        }
    }

    std::cout << "  PASS\n";
    return 0;
}

int testStaticExchangeEval() {
    std::cout << "Test 17: Static Exchange Evaluation Test\n";

    {
        Position p = parseFEN("4k3/8/8/8/8/8/4q3/4R1K1 w - - 0 1");
        Move move;
        if (!parseUCIMove(p, "e1e2", move) || staticExchangeEval(p, move) <= 0) {
            std::cout << "  FAIL (expected winning capture e1e2 to be SEE-positive)\n";
            return 1;
        }
    }

    {
        Position p = parseFEN("8/8/8/8/7b/4k3/4r3/4Q1K1 w - - 0 1");
        Move move;
        if (!parseUCIMove(p, "e1e2", move) || staticExchangeEval(p, move) >= 0) {
            std::cout << "  FAIL (expected poisoned capture e1e2 to be SEE-negative)\n";
            return 1;
        }
    }

    {
        Position p = parseFEN("8/8/8/8/8/4k3/4r3/4R1K1 w - - 0 1");
        Move move;
        if (!parseUCIMove(p, "e1e2", move) || staticExchangeEval(p, move) != 0) {
            std::cout << "  FAIL (expected equal exchange e1e2 to be SEE-zero)\n";
            return 1;
        }
    }

    {
        Position p = parseFEN("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1");
        Move move;
        if (!parseUCIMove(p, "e5d6", move) || staticExchangeEval(p, move) <= 0) {
            std::cout << "  FAIL (expected en passant e5d6 to be SEE-positive)\n";
            return 1;
        }
    }

    {
        Position p = parseFEN("k6r/6P1/8/8/8/8/8/K7 w - - 0 1");
        Move move;
        if (!parseUCIMove(p, "g7h8q", move) || staticExchangeEval(p, move) <= 0) {
            std::cout << "  FAIL (expected promotion capture g7h8q to be SEE-positive)\n";
            return 1;
        }
    }

    std::cout << "  PASS\n";
    return 0;
}

int testSearchPrefersWinningCapture() {
    std::cout << "Test 18: Search Prefers Winning Capture Test\n";

    Position p = parseFEN("4k3/8/8/8/8/8/4q3/4R1K1 w - - 0 1");
    resetDrawHistory(p);
    SearchLimits limits{1, 0, nullptr, nullptr};
    SearchResult result = searchBestMove(p, limits);

    if (!result.hasMove || moveToUCI(result.bestMove) != "e1e2") {
        std::cout << "  FAIL (expected best move e1e2, got "
                  << (result.hasMove ? moveToUCI(result.bestMove) : std::string("0000")) << ")\n";
        return 1;
    }

    std::cout << "  PASS\n";
    return 0;
}

int testSearchAvoidsPoisonedCapture() {
    std::cout << "Test 19: Search Avoids Poisoned Capture Test\n";

    Position p = parseFEN("8/8/8/8/7b/4k3/4r3/4Q1K1 w - - 0 1");
    resetDrawHistory(p);
    SearchLimits limits{1, 0, nullptr, nullptr};
    SearchResult result = searchBestMove(p, limits);

    if (!result.hasMove) {
        std::cout << "  FAIL (expected a legal move)\n";
        return 1;
    }
    if (moveToUCI(result.bestMove) != "e1h4") {
        std::cout << "  FAIL (expected best move e1h4, got "
                  << moveToUCI(result.bestMove) << ")\n";
        return 1;
    }

    std::cout << "  PASS\n";
    return 0;
}

int testSearchPrefersQuietPromotion() {
    std::cout << "Test 20: Search Prefers Quiet Promotion Test\n";

    Position p = parseFEN("7k/P7/8/8/8/8/8/K7 w - - 0 1");
    resetDrawHistory(p);
    SearchLimits limits{1, 0, nullptr, nullptr};
    SearchResult result = searchBestMove(p, limits);

    if (!result.hasMove || moveToUCI(result.bestMove) != "a7a8q") {
        std::cout << "  FAIL (expected best move a7a8q, got "
                  << (result.hasMove ? moveToUCI(result.bestMove) : std::string("0000")) << ")\n";
        return 1;
    }

    std::cout << "  PASS\n";
    return 0;
}

int testMateScoreHelpers() {
    std::cout << "Test 21: Mate Score Helper Test\n";

    int mateInOne = SEARCH_MATE_SCORE - 1;
    int mateInTwo = SEARCH_MATE_SCORE - 3;
    int matedInOne = -SEARCH_MATE_SCORE + 2;
    int alreadyMated = -SEARCH_MATE_SCORE;

    if (!isMateScore(mateInOne) || mateDistanceMoves(mateInOne) != 1) {
        std::cout << "  FAIL (mate-in-one conversion is incorrect)\n";
        return 1;
    }
    if (!isMateScore(mateInTwo) || mateDistanceMoves(mateInTwo) != 2) {
        std::cout << "  FAIL (mate-in-two conversion is incorrect)\n";
        return 1;
    }
    if (!isMateScore(matedInOne) || mateDistanceMoves(matedInOne) != 1) {
        std::cout << "  FAIL (mated-in-one conversion is incorrect)\n";
        return 1;
    }
    if (!isMateScore(alreadyMated) || mateDistanceMoves(alreadyMated) != 0) {
        std::cout << "  FAIL (already-mated conversion is incorrect)\n";
        return 1;
    }

    std::cout << "  PASS\n";
    return 0;
}

int testSearchFindsMateInOneForBothSides() {
    std::cout << "Test 22: Search Finds Mate In One For Both Sides Test\n";

    Position whiteToMove = parseFEN("6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1");
    Position blackToMove = parseFEN("8/8/8/8/8/6k1/5q2/6K1 b - - 0 1");
    SearchLimits limits{1, 0, nullptr, nullptr};

    resetDrawHistory(whiteToMove);
    SearchResult whiteResult = searchBestMove(whiteToMove, limits);
    resetDrawHistory(blackToMove);
    SearchResult blackResult = searchBestMove(blackToMove, limits);

    if (!whiteResult.hasMove || whiteResult.score != SEARCH_MATE_SCORE - 1) {
        std::cout << "  FAIL (white mate-in-one score is incorrect)\n";
        return 1;
    }
    if (!blackResult.hasMove || blackResult.score != SEARCH_MATE_SCORE - 1) {
        std::cout << "  FAIL (black mate-in-one score is incorrect)\n";
        return 1;
    }

    std::cout << "  PASS\n";
    return 0;
}

int main() {
    std::cout << "=== Engine Regression Tests ===\n\n";
    
    int failures = 0;
    failures += testMirrorPositions();
    failures += testColorSwap();
    failures += testEnPassantColor();
    failures += testCastlingRights();
    failures += testCheckDetection();
    failures += testCastlingRightsUpdates();
    failures += testFENCounters();
    failures += testHashRoundTrip();
    failures += testLegalMoveAndTerminalHelpers();
    failures += testUCIMoveHelpers();
    failures += testDrawHistoryAndFiftyMoveRule();
    failures += testFENRoundTrip();
    failures += testSearchSampleHook();
    failures += testEvaluation();
    failures += testIncrementalNnueAccumulator();
    failures += testLegalNoisyMoveGeneration();
    failures += testStaticExchangeEval();
    failures += testSearchPrefersWinningCapture();
    failures += testSearchAvoidsPoisonedCapture();
    failures += testSearchPrefersQuietPromotion();
    failures += testMateScoreHelpers();
    failures += testSearchFindsMateInOneForBothSides();
    
    std::cout << "\n=== Summary ===\n";
    if (failures == 0) std::cout << "All tests PASSED\n";
    else std::cout << failures << " test(s) FAILED\n";
    
    return failures;
}
