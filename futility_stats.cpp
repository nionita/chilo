#include "engine.h"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <random>
#include <sstream>
#include <string>
#include <vector>

#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

namespace {

struct Options {
    std::vector<std::string> inputPaths;
    std::string weightsPath;
    std::string outputPath;
    int minPieces = 5;
    double sampleRate = 1.0;
    uint64_t maxPositions = 0;
    uint64_t seed = 0;
    bool seedProvided = false;
    bool helpRequested = false;
};

struct Histogram {
    std::map<int, uint64_t> counts;
    uint64_t samples = 0;
    long double sum = 0.0;
    long double sumSquares = 0.0;

    void add(int value) {
        counts[value]++;
        samples++;
        sum += value;
        sumSquares += static_cast<long double>(value) * value;
    }

    bool empty() const {
        return samples == 0;
    }

    int min() const {
        return counts.empty() ? 0 : counts.begin()->first;
    }

    int max() const {
        return counts.empty() ? 0 : counts.rbegin()->first;
    }

    double mean() const {
        return samples == 0 ? 0.0 : static_cast<double>(sum / samples);
    }

    double stddev() const {
        if (samples == 0) return 0.0;
        long double avg = sum / samples;
        long double variance = sumSquares / samples - avg * avg;
        if (variance < 0.0) variance = 0.0;
        return std::sqrt(static_cast<double>(variance));
    }

    int percentile(double p) const {
        if (samples == 0) return 0;
        uint64_t rank = static_cast<uint64_t>(std::ceil((p / 100.0) * samples));
        if (rank == 0) rank = 1;
        uint64_t seen = 0;
        for (const auto& [value, count] : counts) {
            seen += count;
            if (seen >= rank) return value;
        }
        return counts.rbegin()->first;
    }

    uint64_t countGreaterThan(int threshold) const {
        uint64_t result = 0;
        for (auto it = counts.upper_bound(threshold); it != counts.end(); ++it) {
            result += it->second;
        }
        return result;
    }
};

struct GroupStats {
    std::string name;
    uint64_t positions = 0;
    Histogram gains;

    GroupStats(const char* groupName) : name(groupName) {}
};

struct RunStats {
    uint64_t files = 0;
    uint64_t lines = 0;
    uint64_t sampledRows = 0;
    uint64_t parsedPositions = 0;
    uint64_t acceptedPositions = 0;
    uint64_t skippedBySampling = 0;
    uint64_t skippedByMinPieces = 0;
    uint64_t parseErrors = 0;
    uint64_t terminalPositions = 0;
    GroupStats nonCheckAll{"non_check_all"};
    GroupStats inCheckAll{"in_check_all"};
    std::vector<GroupStats> nonCheckBuckets{
        {"non_check_5_7"},
        {"non_check_8_15"},
        {"non_check_16_23"},
        {"non_check_24_32"},
    };
    std::vector<GroupStats> inCheckBuckets{
        {"in_check_5_7"},
        {"in_check_8_15"},
        {"in_check_16_23"},
        {"in_check_24_32"},
    };
};

uint64_t splitmix64(uint64_t value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31);
}

uint64_t currentProcessId() {
#ifdef _WIN32
    return static_cast<uint64_t>(_getpid());
#else
    return static_cast<uint64_t>(getpid());
#endif
}

uint64_t generateDefaultSeed() {
    auto wall = std::chrono::system_clock::now().time_since_epoch().count();
    auto steady = std::chrono::steady_clock::now().time_since_epoch().count();
    uint64_t seed = static_cast<uint64_t>(wall);
    seed ^= splitmix64(static_cast<uint64_t>(steady));
    seed ^= splitmix64(currentProcessId());
    return splitmix64(seed);
}

std::string trim(const std::string& text) {
    std::size_t start = 0;
    while (start < text.size() && std::isspace(static_cast<unsigned char>(text[start]))) start++;
    std::size_t end = text.size();
    while (end > start && std::isspace(static_cast<unsigned char>(text[end - 1]))) end--;
    return text.substr(start, end - start);
}

void printUsage() {
    std::cout
        << "Usage: futility_stats [options] <input-file> [more-input-files...]\n"
        << "Options:\n"
        << "  -w, --weights <path>       Load external NNUE weights; failure is fatal\n"
        << "  -p, --min-pieces <N>       Skip positions with fewer than N pieces (default: 5, 0 disables)\n"
        << "  -r, --sample-rate <P>      Randomly keep input rows with probability P (default: 1.0)\n"
        << "  -n, --max-positions <N>    Stop after N accepted positions (default: 0 = unlimited)\n"
        << "  -s, --seed <N>             RNG seed for row sampling (default: time/process-derived)\n"
        << "  -o, --output <path>        Optional TSV summary output\n"
        << "  -h, --help                 Show this help\n";
}

bool parseInt(const std::string& text, int& value) {
    try {
        std::size_t consumed = 0;
        value = std::stoi(text, &consumed);
        return consumed == text.size();
    } catch (...) {
        return false;
    }
}

bool parseDouble(const std::string& text, double& value) {
    try {
        std::size_t consumed = 0;
        value = std::stod(text, &consumed);
        return consumed == text.size();
    } catch (...) {
        return false;
    }
}

bool parseUInt64(const std::string& text, uint64_t& value) {
    try {
        std::size_t consumed = 0;
        value = std::stoull(text, &consumed);
        return consumed == text.size();
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

        if (arg == "--help" || arg == "-h") {
            options.helpRequested = true;
            printUsage();
            return false;
        } else if (arg == "--weights" || arg == "-w") {
            const char* value = requireValue("--weights");
            if (value == nullptr) return false;
            options.weightsPath = value;
        } else if (arg == "--min-pieces" || arg == "-p") {
            const char* value = requireValue("--min-pieces");
            if (value == nullptr || !parseInt(value, options.minPieces) ||
                options.minPieces < 0 || options.minPieces > 32) {
                return false;
            }
        } else if (arg == "--sample-rate" || arg == "-r") {
            const char* value = requireValue("--sample-rate");
            if (value == nullptr || !parseDouble(value, options.sampleRate) ||
                options.sampleRate <= 0.0 || options.sampleRate > 1.0) {
                return false;
            }
        } else if (arg == "--max-positions" || arg == "-n") {
            const char* value = requireValue("--max-positions");
            if (value == nullptr || !parseUInt64(value, options.maxPositions)) return false;
        } else if (arg == "--seed" || arg == "-s") {
            const char* value = requireValue("--seed");
            if (value == nullptr || !parseUInt64(value, options.seed)) return false;
            options.seedProvided = true;
        } else if (arg == "--output" || arg == "-o") {
            const char* value = requireValue("--output");
            if (value == nullptr) return false;
            options.outputPath = value;
        } else if (!arg.empty() && arg[0] == '-') {
            std::cerr << "Unknown argument: " << arg << "\n";
            return false;
        } else {
            options.inputPaths.push_back(arg);
        }
    }

    if (options.inputPaths.empty()) {
        std::cerr << "At least one input file is required\n";
        return false;
    }
    return true;
}

std::string extractFenField(const std::string& line) {
    std::string text = trim(line);
    std::size_t comma = text.find(',');
    if (comma != std::string::npos) text = text.substr(0, comma);
    if (text.size() >= 2 && text.front() == '"' && text.back() == '"') {
        text = text.substr(1, text.size() - 2);
    }
    return trim(text);
}

bool isHeaderField(const std::string& field) {
    return field == "fen" || field == "eval_fen" || field == "root_fen";
}

std::vector<std::string> splitFields(const std::string& text) {
    std::istringstream input(text);
    std::vector<std::string> fields;
    std::string field;
    while (input >> field) fields.push_back(field);
    return fields;
}

bool isPieceToken(char ch) {
    switch (ch) {
        case 'p':
        case 'n':
        case 'b':
        case 'r':
        case 'q':
        case 'k':
        case 'P':
        case 'N':
        case 'B':
        case 'R':
        case 'Q':
        case 'K':
            return true;
        default:
            return false;
    }
}

bool looksLikeFen(const std::string& fen) {
    std::vector<std::string> fields = splitFields(fen);
    if (fields.size() < 4) return false;
    if (fields[1] != "w" && fields[1] != "b") return false;
    if (fields[3] != "-") {
        if (fields[3].size() != 2) return false;
        if (fields[3][0] < 'a' || fields[3][0] > 'h') return false;
        if (fields[3][1] < '1' || fields[3][1] > '8') return false;
    }

    int rankCount = 1;
    int fileCount = 0;
    int whiteKings = 0;
    int blackKings = 0;
    for (char ch : fields[0]) {
        if (ch == '/') {
            if (fileCount != 8) return false;
            rankCount++;
            fileCount = 0;
            continue;
        }
        if (ch >= '1' && ch <= '8') {
            fileCount += ch - '0';
        } else if (isPieceToken(ch)) {
            fileCount++;
            if (ch == 'K') whiteKings++;
            if (ch == 'k') blackKings++;
        } else {
            return false;
        }
        if (fileCount > 8) return false;
    }

    return rankCount == 8 && fileCount == 8 && whiteKings == 1 && blackKings == 1;
}

int pieceCount(const Position& pos) {
    return __builtin_popcountll(pos.occupancyAll);
}

Piece capturedPieceForMove(const Position& pos, const Move& move) {
    if (move.isEnPassant) return pos.sideToMove == WHITE ? B_PAWN : W_PAWN;
    return pieceAt(pos, move.to);
}

bool isCaptureMove(const Position& pos, const Move& move) {
    return capturedPieceForMove(pos, move) != EMPTY;
}

bool isMeasuredQuietMove(const Position& pos, const Move& move) {
    return !isCaptureMove(pos, move) && move.promotion == EMPTY && !move.isCastle;
}

int bucketIndex(int pieces) {
    if (pieces <= 7) return 0;
    if (pieces <= 15) return 1;
    if (pieces <= 23) return 2;
    return 3;
}

void addQuietGains(Position& pos, GroupStats& allGroup, GroupStats& bucketGroup) {
    allGroup.positions++;
    bucketGroup.positions++;

    int before = evaluate(pos);
    Move moves[MAX_MOVES];
    int moveCount = genLegalMoves(pos, moves);
    if (moveCount == 0) return;

    for (int i = 0; i < moveCount; i++) {
        const Move& move = moves[i];
        if (!isMeasuredQuietMove(pos, move)) continue;

        UndoState undoState;
        doMove(pos, move, undoState);
        int after = -evaluate(pos);
        undo(pos, move, undoState);

        int gain = after - before;
        allGroup.gains.add(gain);
        bucketGroup.gains.add(gain);
    }
}

void processPosition(Position& pos, RunStats& stats, const Options& options) {
    stats.parsedPositions++;
    int pieces = pieceCount(pos);
    if (options.minPieces > 0 && pieces < options.minPieces) {
        stats.skippedByMinPieces++;
        return;
    }

    Move moves[MAX_MOVES];
    int moveCount = genLegalMoves(pos, moves);
    if (moveCount == 0) {
        stats.terminalPositions++;
        return;
    }

    stats.acceptedPositions++;
    bool check = inCheck(pos, pos.sideToMove);
    int bucket = bucketIndex(pieces);
    if (check) {
        addQuietGains(pos, stats.inCheckAll, stats.inCheckBuckets[bucket]);
    } else {
        addQuietGains(pos, stats.nonCheckAll, stats.nonCheckBuckets[bucket]);
    }
}

bool shouldStop(const RunStats& stats, const Options& options) {
    return options.maxPositions > 0 && stats.acceptedPositions >= options.maxPositions;
}

void processFile(const std::string& path, RunStats& stats, const Options& options,
                 std::mt19937_64& rng, std::uniform_real_distribution<double>& distribution) {
    std::ifstream input(path);
    if (!input) {
        std::cerr << "warning: failed to open input file " << path << "\n";
        return;
    }

    stats.files++;
    std::string line;
    while (!shouldStop(stats, options) && std::getline(input, line)) {
        stats.lines++;
        std::string text = trim(line);
        if (text.empty() || text[0] == '#') continue;

        if (options.sampleRate < 1.0 && distribution(rng) >= options.sampleRate) {
            stats.skippedBySampling++;
            continue;
        }
        stats.sampledRows++;

        std::string fen = extractFenField(text);
        if (isHeaderField(fen)) continue;
        if (!looksLikeFen(fen)) {
            stats.parseErrors++;
            continue;
        }

        Position pos = parseFEN(fen);
        resetDrawHistory(pos);
        processPosition(pos, stats, options);
    }
}

void printGroup(std::ostream& out, const GroupStats& group) {
    const Histogram& h = group.gains;
    out << group.name
        << " positions=" << group.positions
        << " quiet_moves=" << h.samples;
    if (h.empty()) {
        out << "\n";
        return;
    }

    out << std::fixed << std::setprecision(3)
        << " mean=" << h.mean()
        << " std=" << h.stddev()
        << " min=" << h.min()
        << " p50=" << h.percentile(50.0)
        << " p90=" << h.percentile(90.0)
        << " p95=" << h.percentile(95.0)
        << " p99=" << h.percentile(99.0)
        << " p99.5=" << h.percentile(99.5)
        << " p99.9=" << h.percentile(99.9)
        << " max=" << h.max();

    constexpr int thresholds[] = {50, 80, 100, 120, 150, 200};
    for (int threshold : thresholds) {
        uint64_t count = h.countGreaterThan(threshold);
        double fraction = h.samples == 0 ? 0.0 : static_cast<double>(count) / h.samples;
        out << " gt" << threshold << "=" << count
            << " gt" << threshold << "_frac=" << fraction;
    }
    out << "\n";
}

void writeGroupTsv(std::ostream& out, const GroupStats& group) {
    const Histogram& h = group.gains;
    constexpr int thresholds[] = {50, 80, 100, 120, 150, 200};

    out << group.name << '\t'
        << group.positions << '\t'
        << h.samples << '\t'
        << h.mean() << '\t'
        << h.stddev() << '\t'
        << h.min() << '\t'
        << h.percentile(50.0) << '\t'
        << h.percentile(90.0) << '\t'
        << h.percentile(95.0) << '\t'
        << h.percentile(99.0) << '\t'
        << h.percentile(99.5) << '\t'
        << h.percentile(99.9) << '\t'
        << h.max();
    for (int threshold : thresholds) {
        uint64_t count = h.countGreaterThan(threshold);
        double fraction = h.samples == 0 ? 0.0 : static_cast<double>(count) / h.samples;
        out << '\t' << count << '\t' << fraction;
    }
    out << '\n';
}

void printReport(const RunStats& stats, const Options& options) {
    std::cout << "files=" << stats.files
              << " lines=" << stats.lines
              << " sampled_rows=" << stats.sampledRows
              << " parsed_positions=" << stats.parsedPositions
              << " accepted_positions=" << stats.acceptedPositions
              << " skipped_by_sampling=" << stats.skippedBySampling
              << " skipped_by_min_pieces=" << stats.skippedByMinPieces
              << " terminal_positions=" << stats.terminalPositions
              << " parse_errors=" << stats.parseErrors
              << " min_pieces=" << options.minPieces
              << " sample_rate=" << options.sampleRate
              << " max_positions=" << options.maxPositions
              << " seed=" << options.seed
              << "\n";

    printGroup(std::cout, stats.nonCheckAll);
    printGroup(std::cout, stats.inCheckAll);
    for (const GroupStats& group : stats.nonCheckBuckets) printGroup(std::cout, group);
    for (const GroupStats& group : stats.inCheckBuckets) printGroup(std::cout, group);
}

bool writeTsv(const std::string& path, const RunStats& stats) {
    std::ofstream output(path);
    if (!output) return false;

    output << "group\tpositions\tquiet_moves\tmean\tstd\tmin\tp50\tp90\tp95\tp99\tp99_5\tp99_9\tmax"
           << "\tgt50\tgt50_frac\tgt80\tgt80_frac\tgt100\tgt100_frac"
           << "\tgt120\tgt120_frac\tgt150\tgt150_frac\tgt200\tgt200_frac\n";
    writeGroupTsv(output, stats.nonCheckAll);
    writeGroupTsv(output, stats.inCheckAll);
    for (const GroupStats& group : stats.nonCheckBuckets) writeGroupTsv(output, group);
    for (const GroupStats& group : stats.inCheckBuckets) writeGroupTsv(output, group);
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    Options options;
    if (!parseArgs(argc, argv, options)) {
        if (!options.helpRequested) printUsage();
        return options.helpRequested ? 0 : 1;
    }

    if (!options.weightsPath.empty()) {
        std::string error;
        if (!loadNnueWeightsFile(options.weightsPath, error)) {
            std::cerr << "fatal: failed to load NNUE weights from " << options.weightsPath << ": "
                      << error << "\n";
            return 1;
        }
        std::cerr << "info string loaded NNUE weights from " << options.weightsPath << "\n";
    }

    if (!options.seedProvided) {
        options.seed = generateDefaultSeed();
    }
    std::cout << "Using RNG seed " << options.seed << "\n";

    RunStats stats;
    std::mt19937_64 rng(options.seed);
    std::uniform_real_distribution<double> distribution(0.0, 1.0);

    for (const std::string& path : options.inputPaths) {
        if (shouldStop(stats, options)) break;
        processFile(path, stats, options, rng, distribution);
    }

    if (stats.acceptedPositions == 0) {
        std::cerr << "warning: no accepted positions processed\n";
    }

    printReport(stats, options);

    if (!options.outputPath.empty()) {
        if (!writeTsv(options.outputPath, stats)) {
            std::cerr << "fatal: failed to write output " << options.outputPath << "\n";
            return 1;
        }
        std::cout << "wrote_tsv=" << options.outputPath << "\n";
    }

    return stats.acceptedPositions == 0 ? 1 : 0;
}
