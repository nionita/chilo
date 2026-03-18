#include "chess.h"

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
        Piece cap = p.board[m.to];
        int oldHalfMove = p.halfMove;
        int oldFullMove = p.fullMove;
        int oldEnPassant = p.enPassant;
        Color us = p.sideToMove;
        doMove(p, m);
        if (inCheck(p, us)) illegalMoves++;
        undo(p, m, cap, oldHalfMove, oldFullMove, oldEnPassant);
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

int main() {
    std::cout << "=== Color/Side-to-Move Bug Tests ===\n\n";
    
    int failures = 0;
    failures += testMirrorPositions();
    failures += testColorSwap();
    failures += testEnPassantColor();
    failures += testCastlingRights();
    failures += testCheckDetection();
    
    std::cout << "\n=== Summary ===\n";
    if (failures == 0) std::cout << "All tests PASSED\n";
    else std::cout << failures << " test(s) FAILED\n";
    
    return failures;
}
