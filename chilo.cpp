#include "engine.h"

#include <atomic>
#include <filesystem>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace {

const char* STARTPOS_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const char* CHILO_VERSION = "0.6.0";

struct GoCommandOptions {
    int depth = 0;
    int movetimeMs = 0;
    int wtimeMs = 0;
    int btimeMs = 0;
    int wincMs = 0;
    int bincMs = 0;
    int movesToGo = 0;
    bool hasDepth = false;
    bool hasMovetime = false;
    bool hasWtime = false;
    bool hasBtime = false;
};

std::vector<std::string> tokenize(const std::string& line) {
    std::vector<std::string> tokens;
    std::istringstream iss(line);
    std::string token;
    while (iss >> token) tokens.push_back(token);
    return tokens;
}

std::filesystem::path sidecarWeightsPath(const char* argv0) {
    std::filesystem::path executablePath = std::filesystem::absolute(std::filesystem::path(argv0));
    return executablePath.parent_path() / (executablePath.stem().string() + ".bin");
}

bool loadStartupWeights(const std::string* explicitWeightsPath, const std::filesystem::path& sidecarPath) {
    std::string error;
    if (explicitWeightsPath != nullptr) {
        if (!loadNnueWeightsFile(*explicitWeightsPath, error)) {
            std::cerr << "fatal: failed to load NNUE weights from " << *explicitWeightsPath << ": " << error << "\n";
            return false;
        }
        std::cerr << "info string loaded NNUE weights from " << *explicitWeightsPath << "\n";
        return true;
    }

    std::error_code existsError;
    if (std::filesystem::exists(sidecarPath, existsError) && !existsError) {
        if (!loadNnueWeightsFile(sidecarPath.string(), error)) {
            std::cerr << "info string failed to load sidecar NNUE weights from " << sidecarPath
                      << ": " << error << "; using built-in weights\n";
            return true;
        }
        std::cerr << "info string loaded sidecar NNUE weights from " << sidecarPath << "\n";
    }
    return true;
}

std::string bestMoveString(const SearchResult& result) {
    return result.hasMove ? moveToUCI(result.bestMove) : "0000";
}

void printUCIScore(int score) {
    if (isMateScore(score)) {
        int mateMoves = mateDistanceMoves(score);
        std::cout << "mate " << (score > 0 ? mateMoves : -mateMoves);
        return;
    }
    std::cout << "cp " << score;
}

void printSearchInfo(const SearchResult& result, void*) {
    uint64_t nps = result.elapsedMs > 0 ? (result.nodes * 1000) / result.elapsedMs : 0;
    std::cout << "info depth " << result.depth
              << " score ";
    printUCIScore(result.score);
    std::cout << " nodes " << result.nodes
              << " time " << result.elapsedMs
              << " nps " << nps;
    if (result.pvLength > 0) {
        std::cout << " pv";
        for (int i = 0; i < result.pvLength; i++) std::cout << " " << moveToUCI(result.pv[i]);
    }
    std::cout << "\n";
    std::cout.flush();
}

bool applyPositionCommand(const std::vector<std::string>& tokens, Position& pos) {
    if (tokens.size() < 2) return false;

    Position basePos;
    std::size_t moveStart = tokens.size();
    if (tokens[1] == "startpos") {
        basePos = parseFEN(STARTPOS_FEN);
        moveStart = 2;
    } else if (tokens[1] == "fen") {
        if (tokens.size() < 8) return false;
        std::string fen;
        for (std::size_t i = 2; i < 8; i++) {
            if (!fen.empty()) fen += ' ';
            fen += tokens[i];
        }
        basePos = parseFEN(fen);
        moveStart = 8;
    } else {
        return false;
    }

    std::vector<Move> movesToApply;
    Position tempPos = basePos;
    if (moveStart < tokens.size()) {
        if (tokens[moveStart] != "moves") return false;
        for (std::size_t i = moveStart + 1; i < tokens.size(); i++) {
            Move move;
            if (!parseUCIMove(tempPos, tokens[i], move)) return false;
            UndoState undoState;
            doMove(tempPos, move, undoState);
            movesToApply.push_back(move);
        }
    }

    pos = basePos;
    resetDrawHistory(pos);
    for (const Move& move : movesToApply) {
        Position before = pos;
        UndoState undoState;
        doMove(pos, move, undoState);
        recordRealMoveForDrawHistory(before, move, pos);
    }

    return true;
}

bool parseIntToken(const std::vector<std::string>& tokens, std::size_t index, int& value) {
    if (index >= tokens.size()) return false;
    try {
        value = std::stoi(tokens[index]);
        return true;
    } catch (...) {
        return false;
    }
}

int computeClockBudgetMs(const Position& pos, const GoCommandOptions& options) {
    bool hasSideClock = pos.sideToMove == WHITE ? options.hasWtime : options.hasBtime;
    if (!hasSideClock) return 0;

    int remainingMs = pos.sideToMove == WHITE ? options.wtimeMs : options.btimeMs;
    int incrementMs = pos.sideToMove == WHITE ? options.wincMs : options.bincMs;
    if (incrementMs < 0) incrementMs = 0;

    int reserveMs = 50 + incrementMs / 2;
    int usableMs = remainingMs > reserveMs ? remainingMs - reserveMs : 1;
    int movesDivisor = options.movesToGo > 0 ? options.movesToGo : 25;

    int budgetMs = usableMs / movesDivisor + incrementMs / 2;
    if (budgetMs < 1) budgetMs = 1;
    if (budgetMs > usableMs) budgetMs = usableMs;
    return budgetMs;
}

SearchLimits parseGoCommand(const std::vector<std::string>& tokens, const Position& pos) {
    GoCommandOptions options;
    SearchLimits limits{0, 0, printSearchInfo, nullptr};
    for (std::size_t i = 1; i + 1 < tokens.size(); i++) {
        int value = 0;
        if (tokens[i] == "depth") {
            if (parseIntToken(tokens, i + 1, value)) {
                options.depth = value;
                options.hasDepth = true;
            }
            i++;
        } else if (tokens[i] == "movetime") {
            if (parseIntToken(tokens, i + 1, value)) {
                options.movetimeMs = value;
                options.hasMovetime = true;
            }
            i++;
        } else if (tokens[i] == "wtime") {
            if (parseIntToken(tokens, i + 1, value)) {
                options.wtimeMs = value;
                options.hasWtime = true;
            }
            i++;
        } else if (tokens[i] == "btime") {
            if (parseIntToken(tokens, i + 1, value)) {
                options.btimeMs = value;
                options.hasBtime = true;
            }
            i++;
        } else if (tokens[i] == "winc") {
            if (parseIntToken(tokens, i + 1, value)) options.wincMs = value;
            i++;
        } else if (tokens[i] == "binc") {
            if (parseIntToken(tokens, i + 1, value)) options.bincMs = value;
            i++;
        } else if (tokens[i] == "movestogo") {
            if (parseIntToken(tokens, i + 1, value) && value > 0) options.movesToGo = value;
            i++;
        }
    }

    if (options.hasMovetime) {
        limits.movetimeMs = options.movetimeMs > 0 ? options.movetimeMs : 1;
    } else {
        int budgetMs = computeClockBudgetMs(pos, options);
        if (budgetMs > 0) {
            limits.movetimeMs = budgetMs;
        } else if (options.hasDepth && options.depth > 0) {
            limits.depth = options.depth;
        } else {
            limits.depth = 4;
        }
    }

    return limits;
}

}  // namespace

int main(int argc, char** argv) {
    std::string explicitWeightsPath;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--version" || arg == "-v") {
            std::cout << CHILO_VERSION << "\n";
            return 0;
        }
        if (arg == "--weights") {
            if (i + 1 >= argc) {
                std::cerr << "fatal: --weights requires a file path\n";
                return 1;
            }
            explicitWeightsPath = argv[++i];
        }
    }

    std::filesystem::path sidecarPath = sidecarWeightsPath(argv[0]);
    const std::string* explicitWeights = explicitWeightsPath.empty() ? nullptr : &explicitWeightsPath;
    if (!loadStartupWeights(explicitWeights, sidecarPath)) {
        return 1;
    }

    Position currentPos = parseFEN(STARTPOS_FEN);
    resetDrawHistory(currentPos);
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
            std::cout << "id name Chilo " << CHILO_VERSION << "\n";
            std::cout << "id author Nicu Ionita, Codex & Kilo\n";
            std::cout << "uciok\n";
            std::cout.flush();
        } else if (command == "isready") {
            std::cout << "readyok\n";
            std::cout.flush();
        } else if (command == "ucinewgame") {
            stopAndJoinSearch();
            currentPos = parseFEN(STARTPOS_FEN);
            resetDrawHistory(currentPos);
        } else if (command == "position") {
            stopAndJoinSearch();
            if (!applyPositionCommand(tokens, currentPos)) {
                std::cerr << "info string invalid position command\n";
                std::cerr.flush();
            }
        } else if (command == "go") {
            stopAndJoinSearch();
            SearchLimits limits = parseGoCommand(tokens, currentPos);
            Position searchPos = currentPos;
            searchRunning.store(true);
            searchThread = std::thread([searchPos, limits, &searchRunning]() mutable {
                SearchResult result = searchBestMove(searchPos, limits);
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
