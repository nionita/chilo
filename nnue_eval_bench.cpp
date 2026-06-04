#include "engine.h"

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>
#include <string_view>
#include <vector>

namespace {

constexpr const char* DEFAULT_FENS[] = {
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
    "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
    "2r2rk1/1p1bqppp/p2ppn2/8/2P1P3/1PN1B3/P2N1PPP/R2Q1RK1 w - - 0 14",
    "4rrk1/1pp2ppp/p1np1q2/8/2P1P3/1PN1B3/P2Q1PPP/2RR2K1 b - - 0 18",
    "8/2p2pk1/1p1p2p1/p2P3p/P1P1P3/1P3KP1/5P1P/8 w - - 0 35",
    "7k/8/8/8/8/8/8/KQ6 w - - 0 1",
    "7k/8/8/8/8/8/p7/KQ6 w - - 0 1",
};

enum class Mode {
    Rebuilt,
    Incremental,
    Both,
};

struct Options {
    std::string weightsPath;
    std::string fenFile;
    std::uint64_t passes = 200000;
    Mode mode = Mode::Both;
};

struct BenchPosition {
    Position pos;
    NnueAccumulator accumulator;
    int expected = 0;
};

std::string trim(const std::string& text) {
    std::size_t first = text.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return {};
    std::size_t last = text.find_last_not_of(" \t\r\n");
    return text.substr(first, last - first + 1);
}

std::string stripComment(const std::string& line) {
    std::size_t comment = line.find('#');
    return trim(line.substr(0, comment));
}

bool parseUnsigned(const std::string& text, std::uint64_t& value) {
    try {
        std::size_t used = 0;
        value = std::stoull(text, &used);
        return used == text.size() && value > 0;
    } catch (...) {
        return false;
    }
}

bool parseMode(const std::string& text, Mode& mode) {
    if (text == "rebuilt") {
        mode = Mode::Rebuilt;
        return true;
    }
    if (text == "incremental") {
        mode = Mode::Incremental;
        return true;
    }
    if (text == "both") {
        mode = Mode::Both;
        return true;
    }
    return false;
}

void printUsage(const char* argv0) {
    std::cerr << "Usage: " << argv0
              << " [--weights <path>] [--fen-file <path>] [--passes <n>]"
                 " [--mode rebuilt|incremental|both]\n";
}

bool parseOptions(int argc, char** argv, Options& options) {
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--weights" || arg == "--fen-file" || arg == "--passes" || arg == "--mode") {
            if (i + 1 >= argc) {
                std::cerr << "fatal: " << arg << " requires a value\n";
                return false;
            }
            std::string value = argv[++i];
            if (arg == "--weights") {
                options.weightsPath = value;
            } else if (arg == "--fen-file") {
                options.fenFile = value;
            } else if (arg == "--passes") {
                if (!parseUnsigned(value, options.passes)) {
                    std::cerr << "fatal: --passes must be a positive integer\n";
                    return false;
                }
            } else if (!parseMode(value, options.mode)) {
                std::cerr << "fatal: --mode must be rebuilt, incremental, or both\n";
                return false;
            }
        } else {
            std::cerr << "fatal: unknown argument: " << arg << "\n";
            return false;
        }
    }
    return true;
}

bool loadWeights(const std::string& path) {
    if (path.empty()) return true;
    std::string error;
    if (!loadNnueWeightsFile(path, error)) {
        std::cerr << "fatal: failed to load NNUE weights from " << path << ": " << error << "\n";
        return false;
    }
    return true;
}

bool loadFens(const std::string& path, std::vector<std::string>& fens) {
    if (path.empty()) {
        fens.assign(std::begin(DEFAULT_FENS), std::end(DEFAULT_FENS));
        return true;
    }

    std::ifstream input(path);
    if (!input) {
        std::cerr << "fatal: failed to open FEN file: " << path << "\n";
        return false;
    }

    std::string line;
    while (std::getline(input, line)) {
        std::string fen = stripComment(line);
        if (!fen.empty()) fens.push_back(std::move(fen));
    }
    if (fens.empty()) {
        std::cerr << "fatal: no FEN positions found in " << path << "\n";
        return false;
    }
    return true;
}

bool preparePositions(const std::vector<std::string>& fens, std::vector<BenchPosition>& positions) {
    positions.reserve(fens.size());
    for (const std::string& fen : fens) {
        BenchPosition item;
        item.pos = parseFEN(fen);
        initNnueAccumulator(item.pos, item.accumulator);
        item.expected = evaluate(item.pos);
        int incremental = evaluateWithAccumulator(item.pos, item.accumulator);
        if (incremental != item.expected) {
            std::cerr << "fatal: rebuilt/incremental mismatch for FEN: " << fen
                      << " rebuilt=" << item.expected << " incremental=" << incremental << "\n";
            return false;
        }
        positions.push_back(std::move(item));
    }
    return true;
}

template <typename Evaluate>
void runBenchmark(std::string_view name, const std::vector<BenchPosition>& positions, std::uint64_t passes,
                  Evaluate evaluatePosition) {
    std::uint64_t checksum = 0;
    const auto start = std::chrono::steady_clock::now();
    for (std::uint64_t pass = 0; pass < passes; ++pass) {
        for (std::size_t i = 0; i < positions.size(); ++i) {
            int score = evaluatePosition(positions[i]);
            checksum += static_cast<std::uint64_t>(static_cast<std::int64_t>(score) + 32768) * (i + 1);
        }
    }
    const auto end = std::chrono::steady_clock::now();
    const double seconds = std::chrono::duration<double>(end - start).count();
    const std::uint64_t evaluations = passes * positions.size();
    const double evaluationsPerSecond = static_cast<double>(evaluations) / seconds;

    std::cout << std::fixed << std::setprecision(3)
              << "mode=" << name << " positions=" << positions.size() << " passes=" << passes
              << " evaluations=" << evaluations << " seconds=" << seconds
              << " evaluations_per_second=" << evaluationsPerSecond << " checksum=" << checksum << "\n";
}

}  // namespace

int main(int argc, char** argv) {
    Options options;
    if (!parseOptions(argc, argv, options)) {
        printUsage(argv[0]);
        return 1;
    }
    if (!loadWeights(options.weightsPath)) return 1;

    std::vector<std::string> fens;
    if (!loadFens(options.fenFile, fens)) return 1;

    std::vector<BenchPosition> positions;
    if (!preparePositions(fens, positions)) return 1;

    if (options.mode == Mode::Rebuilt || options.mode == Mode::Both) {
        runBenchmark("rebuilt", positions, options.passes, [](const BenchPosition& item) {
            return evaluate(item.pos);
        });
    }
    if (options.mode == Mode::Incremental || options.mode == Mode::Both) {
        runBenchmark("incremental", positions, options.passes, [](const BenchPosition& item) {
            return evaluateWithAccumulator(item.pos, item.accumulator);
        });
    }
    return 0;
}
