#include "engine.h"

#include <atomic>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace {

const char* STARTPOS_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

std::vector<std::string> tokenize(const std::string& line) {
    std::vector<std::string> tokens;
    std::istringstream iss(line);
    std::string token;
    while (iss >> token) tokens.push_back(token);
    return tokens;
}

std::string bestMoveString(const SearchResult& result) {
    return result.hasMove ? moveToUCI(result.bestMove) : "0000";
}

bool applyPositionCommand(const std::vector<std::string>& tokens, Position& pos) {
    if (tokens.size() < 2) return false;

    std::size_t moveStart = tokens.size();
    if (tokens[1] == "startpos") {
        pos = parseFEN(STARTPOS_FEN);
        moveStart = 2;
    } else if (tokens[1] == "fen") {
        if (tokens.size() < 8) return false;
        std::string fen;
        for (std::size_t i = 2; i < 8; i++) {
            if (!fen.empty()) fen += ' ';
            fen += tokens[i];
        }
        pos = parseFEN(fen);
        moveStart = 8;
    } else {
        return false;
    }

    if (moveStart < tokens.size()) {
        if (tokens[moveStart] != "moves") return false;
        for (std::size_t i = moveStart + 1; i < tokens.size(); i++) {
            if (!applyUCIMove(pos, tokens[i])) return false;
        }
    }

    return true;
}

SearchLimits parseGoCommand(const std::vector<std::string>& tokens) {
    SearchLimits limits{0, 0};
    for (std::size_t i = 1; i + 1 < tokens.size(); i++) {
        if (tokens[i] == "depth") {
            limits.depth = std::stoi(tokens[i + 1]);
            i++;
        } else if (tokens[i] == "movetime") {
            limits.movetimeMs = std::stoi(tokens[i + 1]);
            i++;
        }
    }
    if (limits.depth <= 0 && limits.movetimeMs <= 0) limits.depth = 4;
    return limits;
}

}  // namespace

int main() {
    Position currentPos = parseFEN(STARTPOS_FEN);
    std::thread searchThread;
    std::atomic<bool> searchRunning{false};

    auto stopAndJoinSearch = [&]() {
        if (searchRunning.load()) requestSearchStop();
        if (searchThread.joinable()) searchThread.join();
        searchRunning.store(false);
    };

    std::string line;
    while (std::getline(std::cin, line)) {
        std::vector<std::string> tokens = tokenize(line);
        if (tokens.empty()) continue;

        const std::string& command = tokens[0];
        if (command == "uci") {
            std::cout << "id name Chilo\n";
            std::cout << "id author OpenAI Codex\n";
            std::cout << "uciok\n";
            std::cout.flush();
        } else if (command == "isready") {
            std::cout << "readyok\n";
            std::cout.flush();
        } else if (command == "ucinewgame") {
            stopAndJoinSearch();
            currentPos = parseFEN(STARTPOS_FEN);
        } else if (command == "position") {
            stopAndJoinSearch();
            if (!applyPositionCommand(tokens, currentPos)) {
                std::cerr << "info string invalid position command\n";
                std::cerr.flush();
            }
        } else if (command == "go") {
            stopAndJoinSearch();
            SearchLimits limits = parseGoCommand(tokens);
            Position searchPos = currentPos;
            searchRunning.store(true);
            searchThread = std::thread([searchPos, limits, &searchRunning]() mutable {
                SearchResult result = searchBestMove(searchPos, limits);
                std::cout << "info depth " << result.depth
                          << " score cp " << result.score
                          << " nodes " << result.nodes << "\n";
                std::cout << "bestmove " << bestMoveString(result) << "\n";
                std::cout.flush();
                searchRunning.store(false);
            });
        } else if (command == "stop") {
            stopAndJoinSearch();
        } else if (command == "quit") {
            stopAndJoinSearch();
            break;
        }
    }

    stopAndJoinSearch();
    return 0;
}
