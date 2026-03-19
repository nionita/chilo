#include "chess.h"

#include <algorithm>
#include <iostream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

struct DivideEntry {
    std::string uci;
    uint64_t nodes;
};

std::vector<std::string> splitPath(const std::string& path) {
    std::vector<std::string> parts;
    if (path.empty()) return parts;
    std::stringstream ss(path);
    std::string item;
    while (std::getline(ss, item, ',')) {
        if (!item.empty()) parts.push_back(item);
    }
    return parts;
}

bool findLegalMove(Position& pos, const std::string& uci, Move& outMove) {
    Move moves[MAX_MOVES];
    int moveCount = genMoves(pos, moves);
    Color us = pos.sideToMove;
    for (int i = 0; i < moveCount; i++) {
        const Move& mv = moves[i];
        if (moveToUCI(mv) != uci) continue;
        UndoState undoState;
        doMove(pos, mv, undoState);
        bool legal = !inCheck(pos, us);
        undo(pos, mv, undoState);
        if (legal) {
            outMove = mv;
            return true;
        }
    }
    return false;
}

std::vector<std::string> legalMoveList(Position& pos) {
    Move moves[MAX_MOVES];
    int moveCount = genMoves(pos, moves);
    Color us = pos.sideToMove;
    std::vector<std::string> legal;
    for (int i = 0; i < moveCount; i++) {
        const Move& mv = moves[i];
        UndoState undoState;
        doMove(pos, mv, undoState);
        bool legalMove = !inCheck(pos, us);
        undo(pos, mv, undoState);
        if (legalMove) legal.push_back(moveToUCI(mv));
    }
    std::sort(legal.begin(), legal.end());
    return legal;
}

bool applyPath(Position& pos, const std::vector<std::string>& path) {
    for (const std::string& uci : path) {
        Move mv;
        if (!findLegalMove(pos, uci, mv)) {
            std::cerr << "Illegal or unavailable move in path: " << uci << "\n";
            std::cerr << "Legal moves from current position:";
            for (const std::string& legal : legalMoveList(pos)) std::cerr << " " << legal;
            std::cerr << "\n";
            return false;
        }
        UndoState undoState;
        doMove(pos, mv, undoState);
    }
    return true;
}

std::vector<DivideEntry> computeDivide(Position& pos, int depth) {
    std::vector<DivideEntry> entries;
    Move moves[MAX_MOVES];
    int moveCount = genMoves(pos, moves);
    Color us = pos.sideToMove;
    for (int i = 0; i < moveCount; i++) {
        const Move& mv = moves[i];
        UndoState undoState;
        doMove(pos, mv, undoState);
        if (!inCheck(pos, us)) {
            uint64_t nodes = perft(pos, depth - 1);
            entries.push_back({moveToUCI(mv), nodes});
        }
        undo(pos, mv, undoState);
    }
    std::sort(entries.begin(), entries.end(), [](const DivideEntry& a, const DivideEntry& b) {
        return a.uci < b.uci;
    });
    return entries;
}

int main(int argc, char* argv[]) {
    if (argc < 3 || argc > 4) {
        std::cerr << "Usage: " << argv[0] << " <fen> <depth> [move1,move2,...]\n";
        return 1;
    }

    Position pos = parseFEN(argv[1]);
    int depth = std::stoi(argv[2]);
    if (depth < 1) {
        std::cerr << "Depth must be at least 1 for divide diagnostics\n";
        return 1;
    }

    std::vector<std::string> path = argc == 4 ? splitPath(argv[3]) : std::vector<std::string>{};
    if (!applyPath(pos, path)) return 2;

    std::vector<DivideEntry> divide = computeDivide(pos, depth);
    uint64_t total = 0;
    if (!path.empty()) {
        std::cout << "Path:";
        for (const std::string& step : path) std::cout << " " << step;
        std::cout << "\n";
    }
    for (const DivideEntry& entry : divide) {
        std::cout << entry.uci << ": " << entry.nodes << "\n";
        total += entry.nodes;
    }
    std::cout << "Depth " << depth << ": " << total << "\n";
    return 0;
}
