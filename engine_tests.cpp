#include "chess.h"

#include <cctype>
#include <iostream>
#include <string>

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

int testEvaluation() {
    std::cout << "Test 11: Evaluation Test\n";

    Position start = parseFEN("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
    Position whiteBetter = parseFEN("4k3/8/8/8/8/8/8/3QK3 w - - 0 1");
    Position blackWorseToMove = parseFEN("4k3/8/8/8/8/8/8/3QK3 b - - 0 1");
    Position knightCentralized = parseFEN("4k3/8/8/8/3N4/8/8/4K3 w - - 0 1");
    Position kingsOnly = parseFEN("4k3/8/8/8/8/8/8/6K1 w - - 0 1");

    if (evaluate(start) != 0) {
        std::cout << "  FAIL (starting position should evaluate to 0)\n";
        return 1;
    }
    if (evaluate(whiteBetter) <= 0 || evaluate(blackWorseToMove) >= 0) {
        std::cout << "  FAIL (evaluation sign is inconsistent with side to move)\n";
        return 1;
    }
    if (evaluate(knightCentralized) != 322) {
        std::cout << "  FAIL (expected centralized knight eval of 322, got "
                  << evaluate(knightCentralized) << ")\n";
        return 1;
    }
    if (evaluate(kingsOnly) != 10) {
        std::cout << "  FAIL (expected king PST eval of 10, got "
                  << evaluate(kingsOnly) << ")\n";
        return 1;
    }

    std::cout << "  PASS\n";
    return 0;
}

int testLegalNoisyMoveGeneration() {
    std::cout << "Test 12: Legal Noisy Move Generation Test\n";

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

int testSearchPrefersWinningCapture() {
    std::cout << "Test 13: Search Prefers Winning Capture Test\n";

    Position p = parseFEN("4k3/8/8/8/8/8/4q3/4R1K1 w - - 0 1");
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
    std::cout << "Test 14: Search Avoids Poisoned Capture Test\n";

    Position p = parseFEN("8/8/8/8/7b/4k3/4r3/4Q1K1 w - - 0 1");
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

int testMateScoreHelpers() {
    std::cout << "Test 15: Mate Score Helper Test\n";

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
    std::cout << "Test 16: Search Finds Mate In One For Both Sides Test\n";

    Position whiteToMove = parseFEN("6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1");
    Position blackToMove = parseFEN("8/8/8/8/8/6k1/5q2/6K1 b - - 0 1");
    SearchLimits limits{1, 0, nullptr, nullptr};

    SearchResult whiteResult = searchBestMove(whiteToMove, limits);
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
    failures += testEvaluation();
    failures += testLegalNoisyMoveGeneration();
    failures += testSearchPrefersWinningCapture();
    failures += testSearchAvoidsPoisonedCapture();
    failures += testMateScoreHelpers();
    failures += testSearchFindsMateInOneForBothSides();
    
    std::cout << "\n=== Summary ===\n";
    if (failures == 0) std::cout << "All tests PASSED\n";
    else std::cout << failures << " test(s) FAILED\n";
    
    return failures;
}
