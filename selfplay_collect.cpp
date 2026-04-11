#include "engine.h"

#include <cctype>
#include <algorithm>
#include <cmath>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>
#include <string>
#include <vector>

namespace {

struct Options {
    std::string fenFilePath;
    std::string outputPath;
    std::string debugOutputPath;
    int gamesPerFen = 1;
    int depth = 6;
    int movetimeMs = 0;
    int minSampleDepth = 6;
    int sampleWindowCp = 30;
    int samplePlies = 10;
    int maxPlies = 300;
    double temperatureCp = 15.0;
    uint64_t seed = 1;
};

struct PendingSample {
    std::string rootFen;
    std::string evalFen;
    int depth = 0;
    int score = 0;
    Color evalSideToMove = WHITE;
};

constexpr int PROGRESS_REPORT_INTERVAL_GAMES = 100;

std::string trim(const std::string& text) {
    std::size_t start = 0;
    while (start < text.size() && std::isspace(static_cast<unsigned char>(text[start]))) start++;

    std::size_t end = text.size();
    while (end > start && std::isspace(static_cast<unsigned char>(text[end - 1]))) end--;
    return text.substr(start, end - start);
}

bool movesEqual(const Move& a, const Move& b) {
    return a.from == b.from && a.to == b.to && a.promotion == b.promotion &&
           a.isEnPassant == b.isEnPassant && a.isCastle == b.isCastle && a.isDoublePush == b.isDoublePush;
}

void printUsage() {
    std::cout
        << "Usage: selfplay_collect --fen-file <path> --output <path> [options]\n"
        << "Options:\n"
        << "  --games-per-fen <N>      Number of self-play games per input FEN (default: 1)\n"
        << "  --depth <N>              Fixed search depth when --movetime is not set (default: 6)\n"
        << "  --movetime <ms>          Fixed movetime per move instead of fixed depth\n"
        << "  --min-sample-depth <N>   Only keep samples from searches at or above this depth (default: 6)\n"
        << "  --sample-window-cp <N>   Root-score window for stochastic move choice (default: 30)\n"
        << "  --temperature-cp <X>     Softmax temperature in centipawns (default: 15)\n"
        << "  --sample-plies <N>       Only sample root moves for the first N plies (default: 10)\n"
        << "  --max-plies <N>          Declare a draw after this many plies (default: 300)\n"
        << "  --seed <N>               RNG seed for reproducible self-play (default: 1)\n"
        << "  --debug-output <path>    Optional richer CSV: root_fen,eval_fen,depth,score,result\n";
}

bool parseInt(const std::string& text, int& value) {
    try {
        value = std::stoi(text);
        return true;
    } catch (...) {
        return false;
    }
}

bool parseUInt64(const std::string& text, uint64_t& value) {
    try {
        value = std::stoull(text);
        return true;
    } catch (...) {
        return false;
    }
}

bool parseDouble(const std::string& text, double& value) {
    try {
        value = std::stod(text);
        return true;
    } catch (...) {
        return false;
    }
}

bool parseArgs(int argc, char** argv, Options& options) {
    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        auto requireValue = [&](const char* name) -> const char* {
            if (i + 1 >= argc) {
                std::cerr << "Missing value for " << name << "\n";
                return nullptr;
            }
            return argv[++i];
        };

        if (arg == "--fen-file") {
            const char* value = requireValue("--fen-file");
            if (value == nullptr) return false;
            options.fenFilePath = value;
        } else if (arg == "--output") {
            const char* value = requireValue("--output");
            if (value == nullptr) return false;
            options.outputPath = value;
        } else if (arg == "--debug-output") {
            const char* value = requireValue("--debug-output");
            if (value == nullptr) return false;
            options.debugOutputPath = value;
        } else if (arg == "--games-per-fen") {
            const char* value = requireValue("--games-per-fen");
            if (value == nullptr || !parseInt(value, options.gamesPerFen) || options.gamesPerFen <= 0) return false;
        } else if (arg == "--depth") {
            const char* value = requireValue("--depth");
            if (value == nullptr || !parseInt(value, options.depth) || options.depth <= 0) return false;
        } else if (arg == "--movetime") {
            const char* value = requireValue("--movetime");
            if (value == nullptr || !parseInt(value, options.movetimeMs) || options.movetimeMs <= 0) return false;
        } else if (arg == "--min-sample-depth") {
            const char* value = requireValue("--min-sample-depth");
            if (value == nullptr || !parseInt(value, options.minSampleDepth) || options.minSampleDepth < 0) return false;
        } else if (arg == "--sample-window-cp") {
            const char* value = requireValue("--sample-window-cp");
            if (value == nullptr || !parseInt(value, options.sampleWindowCp) || options.sampleWindowCp < 0) return false;
        } else if (arg == "--temperature-cp") {
            const char* value = requireValue("--temperature-cp");
            if (value == nullptr || !parseDouble(value, options.temperatureCp) || options.temperatureCp < 0.0) return false;
        } else if (arg == "--sample-plies") {
            const char* value = requireValue("--sample-plies");
            if (value == nullptr || !parseInt(value, options.samplePlies) || options.samplePlies < 0) return false;
        } else if (arg == "--max-plies") {
            const char* value = requireValue("--max-plies");
            if (value == nullptr || !parseInt(value, options.maxPlies) || options.maxPlies <= 0) return false;
        } else if (arg == "--seed") {
            const char* value = requireValue("--seed");
            if (value == nullptr || !parseUInt64(value, options.seed)) return false;
        } else if (arg == "--help" || arg == "-h") {
            printUsage();
            return false;
        } else {
            std::cerr << "Unknown argument: " << arg << "\n";
            return false;
        }
    }

    if (options.fenFilePath.empty() || options.outputPath.empty()) return false;
    return true;
}

std::vector<std::string> loadFens(const std::string& path) {
    std::ifstream input(path);
    std::vector<std::string> fens;
    std::string line;

    while (std::getline(input, line)) {
        line = trim(line);
        if (line.empty() || line[0] == '#') continue;
        fens.push_back(line);
    }
    return fens;
}

const RootMoveResult* findRootMoveResult(const SearchResult& result, const Move& move) {
    for (const RootMoveResult& rootMove : result.rootMoveResults) {
        if (movesEqual(rootMove.move, move)) return &rootMove;
    }
    return nullptr;
}

Move chooseMove(const SearchResult& result, int ply, const Options& options, std::mt19937_64& rng) {
    if (!result.hasMove) return Move{};
    if (ply >= options.samplePlies || result.rootMoveResults.empty()) return result.bestMove;

    int bestScore = result.rootMoveResults.front().score;
    for (const RootMoveResult& rootMove : result.rootMoveResults) {
        if (rootMove.score > bestScore) bestScore = rootMove.score;
    }

    std::vector<const RootMoveResult*> candidates;
    std::vector<double> weights;
    for (const RootMoveResult& rootMove : result.rootMoveResults) {
        if (bestScore - rootMove.score > options.sampleWindowCp) continue;
        candidates.push_back(&rootMove);
        if (options.temperatureCp <= 0.0) {
            weights.push_back(rootMove.score == bestScore ? 1.0 : 0.0);
        } else {
            weights.push_back(std::exp((rootMove.score - bestScore) / options.temperatureCp));
        }
    }

    if (candidates.empty()) return result.bestMove;
    if (options.temperatureCp <= 0.0) {
        for (const RootMoveResult* candidate : candidates) {
            if (candidate->score == bestScore) return candidate->move;
        }
        return result.bestMove;
    }

    std::discrete_distribution<std::size_t> distribution(weights.begin(), weights.end());
    return candidates[distribution(rng)]->move;
}

bool classifyTerminal(const Position& pos, bool moveLimitReached, int& whiteResult) {
    if (moveLimitReached || isDrawByFiftyMove(pos) || isDrawByRepetition(pos)) {
        whiteResult = 0;
        return true;
    }

    Move legalMoves[MAX_MOVES];
    int moveCount = genLegalMoves(pos, legalMoves);
    if (moveCount != 0) return false;

    if (inCheck(pos, pos.sideToMove)) {
        whiteResult = pos.sideToMove == WHITE ? -1 : 1;
    } else {
        whiteResult = 0;
    }
    return true;
}

int sampleResultFromPerspective(int whiteResult, Color perspective) {
    return perspective == WHITE ? whiteResult : -whiteResult;
}

bool shouldKeepSample(const RootMoveResult& rootMove) {
    return rootMove.hasEval && !rootMove.evalInCheck && !rootMove.evalIsTerminal;
}

bool shouldKeepBestMoveSample(const SearchResult& result) {
    return result.bestMoveHasEval && !result.bestMoveEvalInCheck && !result.bestMoveEvalIsTerminal;
}

std::string formatDuration(std::chrono::seconds duration) {
    long long totalSeconds = duration.count();
    long long hours = totalSeconds / 3600;
    long long minutes = (totalSeconds % 3600) / 60;
    long long seconds = totalSeconds % 60;

    std::ostringstream out;
    out << std::setfill('0') << std::setw(2) << hours
        << ":" << std::setw(2) << minutes
        << ":" << std::setw(2) << seconds;
    return out.str();
}

std::string formatRate(double value) {
    std::ostringstream out;
    out << std::fixed << std::setprecision(2) << value;
    return out.str();
}

void printProgress(int completedGames, int totalGames, int totalSamples,
                   std::chrono::steady_clock::time_point startTime) {
    using namespace std::chrono;

    auto elapsed = duration_cast<seconds>(steady_clock::now() - startTime);
    double elapsedSeconds = std::max(1.0, static_cast<double>(elapsed.count()));
    double gamesPerSecond = completedGames / elapsedSeconds;
    double samplesPerSecond = totalSamples / elapsedSeconds;

    std::string eta = "unknown";
    if (gamesPerSecond > 0.0 && totalGames >= completedGames) {
        int remainingGames = totalGames - completedGames;
        auto etaSeconds = seconds(static_cast<long long>(std::llround(remainingGames / gamesPerSecond)));
        eta = formatDuration(etaSeconds);
    }

    std::cout << "Progress: " << completedGames << "/" << totalGames
              << " games, " << totalSamples << " samples, elapsed "
              << formatDuration(elapsed)
              << ", " << formatRate(gamesPerSecond) << " games/s"
              << ", " << formatRate(samplesPerSecond) << " samples/s"
              << ", ETA " << eta << "\n";
}

}  // namespace

int main(int argc, char** argv) {
    Options options;
    if (!parseArgs(argc, argv, options)) {
        printUsage();
        return 1;
    }

    std::vector<std::string> fens = loadFens(options.fenFilePath);
    if (fens.empty()) {
        std::cerr << "No input FENs found in " << options.fenFilePath << "\n";
        return 1;
    }

    std::ofstream output(options.outputPath);
    if (!output) {
        std::cerr << "Failed to open output file " << options.outputPath << "\n";
        return 1;
    }
    output << "eval_fen,score,result\n";

    std::ofstream debugOutput;
    if (!options.debugOutputPath.empty()) {
        debugOutput.open(options.debugOutputPath);
        if (!debugOutput) {
            std::cerr << "Failed to open debug output file " << options.debugOutputPath << "\n";
            return 1;
        }
        debugOutput << "root_fen,eval_fen,depth,score,result\n";
    }

    std::mt19937_64 rng(options.seed);
    int totalGames = 0;
    int totalSamples = 0;
    const int scheduledGames = static_cast<int>(fens.size()) * options.gamesPerFen;
    auto startTime = std::chrono::steady_clock::now();

    for (const std::string& fen : fens) {
        for (int gameIndex = 0; gameIndex < options.gamesPerFen; gameIndex++) {
            Position pos = parseFEN(fen);
            resetDrawHistory(pos);

            std::vector<PendingSample> gameSamples;
            int whiteResult = 0;
            bool finished = false;

            for (int ply = 0; ply < options.maxPlies; ply++) {
                if (classifyTerminal(pos, false, whiteResult)) {
                    finished = true;
                    break;
                }

                SearchLimits searchLimits{options.depth, options.movetimeMs, nullptr, nullptr};
                searchLimits.minSampleDepth = options.minSampleDepth;
                searchLimits.collectRootMoveResults = ply < options.samplePlies;
                searchLimits.collectBestMoveLeaf = true;
                SearchResult result = searchBestMove(pos, searchLimits);
                if (!result.hasMove) {
                    if (!classifyTerminal(pos, false, whiteResult)) whiteResult = 0;
                    finished = true;
                    break;
                }

                Move chosenMove = chooseMove(result, ply, options, rng);
                const bool sampledRootChoice = ply < options.samplePlies;
                if (sampledRootChoice) {
                    const RootMoveResult* chosenRoot = findRootMoveResult(result, chosenMove);
                    if (chosenRoot != nullptr &&
                        shouldKeepSample(*chosenRoot) &&
                        result.depth >= options.minSampleDepth) {
                        gameSamples.push_back({positionToFEN(pos), chosenRoot->evalFen, result.depth,
                                               chosenRoot->evalScore, chosenRoot->evalSideToMove});
                    }
                } else if (shouldKeepBestMoveSample(result) &&
                           result.depth >= options.minSampleDepth) {
                    gameSamples.push_back({positionToFEN(pos), result.bestMoveEvalFen, result.depth,
                                           result.bestMoveEvalScore, result.bestMoveEvalSideToMove});
                }

                Position before = pos;
                UndoState undoState;
                doMove(pos, chosenMove, undoState);
                recordRealMoveForDrawHistory(before, chosenMove, pos);
            }

            if (!finished) classifyTerminal(pos, true, whiteResult);

            for (const PendingSample& sample : gameSamples) {
                int resultLabel = sampleResultFromPerspective(whiteResult, sample.evalSideToMove);
                output << sample.evalFen << "," << sample.score << "," << resultLabel << "\n";
                if (debugOutput) {
                    debugOutput << sample.rootFen << "," << sample.evalFen << "," << sample.depth
                                << "," << sample.score << "," << resultLabel << "\n";
                }
            }

            totalGames++;
            totalSamples += static_cast<int>(gameSamples.size());
            if (totalGames % PROGRESS_REPORT_INTERVAL_GAMES == 0) {
                printProgress(totalGames, scheduledGames, totalSamples, startTime);
            }
        }
    }

    auto totalElapsed = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::steady_clock::now() - startTime);
    std::cout << "Completed " << totalGames << " game(s), wrote " << totalSamples
              << " sample row(s), elapsed " << formatDuration(totalElapsed) << "\n";
    return 0;
}
