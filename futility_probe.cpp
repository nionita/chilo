#include "engine.h"

#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

struct Options {
    std::vector<std::string> inputPaths;
    std::string weightsPath;
    std::string outputPath;
    uint64_t nodeLimit = 0;
    uint64_t reportEvery = 100;
    SearchParameters parameters{};
    bool hasNodeLimit = false;
    bool hasMargins = false;
    bool allRootScores = false;
    bool overwrite = false;
    bool helpRequested = false;
};

struct RunStats {
    uint64_t positions = 0;
    uint64_t terminalPositions = 0;
    uint64_t interruptedSearches = 0;
    uint64_t nodes = 0;
    uint64_t completedNodes = 0;
    uint64_t elapsedMs = 0;
    std::array<uint64_t, MAX_FUTILITY_DEPTH + 1> futilityPrunes{};
    std::array<uint64_t, MAX_FUTILITY_DEPTH + 1> futilityPrunesInCheck{};
};

std::string trim(const std::string& text) {
    std::size_t start = 0;
    while (start < text.size() && std::isspace(static_cast<unsigned char>(text[start]))) start++;
    std::size_t end = text.size();
    while (end > start && std::isspace(static_cast<unsigned char>(text[end - 1]))) end--;
    return text.substr(start, end - start);
}

bool parseUInt64(const std::string& text, uint64_t& value) {
    if (text.empty() || text[0] == '-') return false;
    try {
        std::size_t consumed = 0;
        value = std::stoull(text, &consumed);
        return consumed == text.size();
    } catch (...) {
        return false;
    }
}

bool parseNonNegativeInt(const std::string& text, int& value) {
    if (text.empty() || text[0] == '-') return false;
    try {
        std::size_t consumed = 0;
        value = std::stoi(text, &consumed);
        return consumed == text.size() && value >= 0;
    } catch (...) {
        return false;
    }
}

bool parseMargins(const std::string& text, SearchParameters& parameters) {
    std::istringstream input(text);
    std::string field;
    std::vector<int> margins;
    while (std::getline(input, field, ',')) {
        int margin = 0;
        field = trim(field);
        if (!parseNonNegativeInt(field, margin)) return false;
        margins.push_back(margin);
    }
    if (margins.empty() || margins.size() > MAX_FUTILITY_DEPTH ||
        (!text.empty() && text.back() == ',')) {
        return false;
    }

    parameters.futilityMargins.fill(0);
    parameters.futilityMaxDepth = static_cast<int>(margins.size());
    for (std::size_t i = 0; i < margins.size(); i++) {
        parameters.futilityMargins[i + 1] = margins[i];
    }
    return true;
}

void printUsage() {
    std::cout
        << "Usage: futility_probe --nodes N --futility-margins M1[,M2,...,M7] [options]"
           " <input-file> [more-input-files...]\n"
        << "Options:\n"
        << "  --nodes <N>                 Hard cumulative node limit per position (required)\n"
        << "  --futility-margins <list>   Nonnegative margins for depths 1 through list length (required)\n"
        << "  --all-root-scores            Search every root move with a full window and emit its score\n"
        << "  -w, --weights <path>        Load external NNUE weights; failure is fatal\n"
        << "  -o, --output <path>         Write JSON Lines to this file instead of stdout\n"
        << "  --overwrite                 Permit replacing an existing output file\n"
        << "  --report-every <N>          Progress interval in positions (default: 100; 0 disables)\n"
        << "  -h, --help                  Show this help\n";
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
        }
        if (arg == "--nodes") {
            const char* value = requireValue("--nodes");
            if (value == nullptr || !parseUInt64(value, options.nodeLimit) || options.nodeLimit == 0) {
                std::cerr << "--nodes must be a positive integer\n";
                return false;
            }
            options.hasNodeLimit = true;
        } else if (arg == "--futility-margins") {
            const char* value = requireValue("--futility-margins");
            if (value == nullptr || !parseMargins(value, options.parameters)) {
                std::cerr << "--futility-margins requires 1 to 7 comma-separated nonnegative integers\n";
                return false;
            }
            options.hasMargins = true;
        } else if (arg == "--weights" || arg == "-w") {
            const char* value = requireValue("--weights");
            if (value == nullptr) return false;
            options.weightsPath = value;
        } else if (arg == "--all-root-scores") {
            options.allRootScores = true;
        } else if (arg == "--output" || arg == "-o") {
            const char* value = requireValue("--output");
            if (value == nullptr) return false;
            options.outputPath = value;
        } else if (arg == "--overwrite") {
            options.overwrite = true;
        } else if (arg == "--report-every") {
            const char* value = requireValue("--report-every");
            if (value == nullptr || !parseUInt64(value, options.reportEvery)) {
                std::cerr << "--report-every must be a nonnegative integer\n";
                return false;
            }
        } else if (!arg.empty() && arg[0] == '-') {
            std::cerr << "Unknown argument: " << arg << "\n";
            return false;
        } else {
            options.inputPaths.push_back(arg);
        }
    }

    if (!options.hasNodeLimit) {
        std::cerr << "--nodes is required\n";
        return false;
    }
    if (!options.hasMargins) {
        std::cerr << "--futility-margins is required\n";
        return false;
    }
    if (options.inputPaths.empty()) {
        std::cerr << "At least one input file is required\n";
        return false;
    }
    return true;
}

bool isHeaderField(const std::string& field) {
    return field == "fen" || field == "eval_fen" || field == "root_fen";
}

bool extractFirstField(const std::string& line, std::string& field, std::string& error) {
    std::string text = trim(line);
    if (text.empty()) {
        field.clear();
        return true;
    }
    if (text[0] != '"') {
        std::size_t comma = text.find(',');
        field = trim(text.substr(0, comma));
        return true;
    }

    std::string result;
    std::size_t index = 1;
    bool closed = false;
    while (index < text.size()) {
        char ch = text[index++];
        if (ch != '"') {
            result += ch;
            continue;
        }
        if (index < text.size() && text[index] == '"') {
            result += '"';
            index++;
            continue;
        }
        closed = true;
        break;
    }
    if (!closed) {
        error = "unterminated quoted CSV field";
        return false;
    }
    while (index < text.size() && std::isspace(static_cast<unsigned char>(text[index]))) index++;
    if (index < text.size() && text[index] != ',') {
        error = "unexpected text after quoted CSV field";
        return false;
    }
    field = trim(result);
    return true;
}

std::vector<std::string> splitWhitespace(const std::string& text) {
    std::istringstream input(text);
    std::vector<std::string> fields;
    std::string field;
    while (input >> field) fields.push_back(field);
    return fields;
}

bool isPieceToken(char ch) {
    switch (ch) {
        case 'p': case 'n': case 'b': case 'r': case 'q': case 'k':
        case 'P': case 'N': case 'B': case 'R': case 'Q': case 'K':
            return true;
        default:
            return false;
    }
}

bool looksLikeFen(const std::string& fen) {
    std::vector<std::string> fields = splitWhitespace(fen);
    if ((fields.size() != 4 && fields.size() != 6) ||
        (fields[1] != "w" && fields[1] != "b")) {
        return false;
    }
    if (fields[2] != "-") {
        bool seen[4] = {};
        for (char ch : fields[2]) {
            int index = ch == 'K' ? 0 : ch == 'Q' ? 1 : ch == 'k' ? 2 : ch == 'q' ? 3 : -1;
            if (index < 0 || seen[index]) return false;
            seen[index] = true;
        }
    }
    if (fields[3] != "-") {
        if (fields[3].size() != 2 || fields[3][0] < 'a' || fields[3][0] > 'h' ||
            (fields[3][1] != '3' && fields[3][1] != '6')) {
            return false;
        }
    }
    if (fields.size() == 6) {
        int halfMove = 0;
        int fullMove = 0;
        if (!parseNonNegativeInt(fields[4], halfMove) ||
            !parseNonNegativeInt(fields[5], fullMove) || fullMove == 0) {
            return false;
        }
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
        } else if (ch >= '1' && ch <= '8') {
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

void writeJsonString(std::ostream& output, const std::string& text) {
    output << '"';
    for (unsigned char ch : text) {
        switch (ch) {
            case '"': output << "\\\""; break;
            case '\\': output << "\\\\"; break;
            case '\b': output << "\\b"; break;
            case '\f': output << "\\f"; break;
            case '\n': output << "\\n"; break;
            case '\r': output << "\\r"; break;
            case '\t': output << "\\t"; break;
            default:
                if (ch < 0x20) {
                    static constexpr char HEX[] = "0123456789abcdef";
                    output << "\\u00" << HEX[ch >> 4] << HEX[ch & 0x0f];
                } else {
                    output << static_cast<char>(ch);
                }
        }
    }
    output << '"';
}

void writeMargins(std::ostream& output, const SearchParameters& parameters) {
    output << '[';
    for (int depth = 1; depth <= parameters.futilityMaxDepth; depth++) {
        if (depth > 1) output << ',';
        output << parameters.futilityMargins[depth];
    }
    output << ']';
}

void writeFutilityCounts(std::ostream& output,
                         const std::array<uint64_t, MAX_FUTILITY_DEPTH + 1>& counts) {
    output << '[';
    for (int depth = 1; depth <= MAX_FUTILITY_DEPTH; depth++) {
        if (depth > 1) output << ',';
        output << counts[depth];
    }
    output << ']';
}

void writePosition(std::ostream& output, const std::string& source, uint64_t lineNumber,
                   const std::string& fen, const Options& options, const SearchResult& result) {
    output << "{\"type\":\"position\",\"source\":";
    writeJsonString(output, source);
    output << ",\"line\":" << lineNumber << ",\"fen\":";
    writeJsonString(output, fen);
    output << ",\"futility_margins\":";
    writeMargins(output, options.parameters);
    output << ",\"weights\":";
    writeJsonString(output, options.weightsPath.empty() ? "built-in" : options.weightsPath);
    output << ",\"futility_max_depth\":" << options.parameters.futilityMaxDepth
           << ",\"all_root_scores\":" << (options.allRootScores ? "true" : "false")
           << ",\"node_limit\":" << options.nodeLimit
           << ",\"nodes\":" << result.nodes
           << ",\"completed_nodes\":" << result.completedNodes
           << ",\"completed_depth\":" << result.depth
           << ",\"elapsed_ms\":" << result.totalElapsedMs
           << ",\"iteration_interrupted\":" << (result.completed ? "false" : "true")
           << ",\"terminal\":" << (result.hasMove ? "false" : "true")
           << ",\"has_move\":" << (result.hasMove ? "true" : "false")
           << ",\"bestmove\":";
    writeJsonString(output, result.hasMove ? moveToUCI(result.bestMove) : "0000");
    output << ",\"score\":" << result.score << ",\"pv\":[";
    for (int i = 0; i < result.pvLength; i++) {
        if (i > 0) output << ',';
        writeJsonString(output, moveToUCI(result.pv[i]));
    }
    output << ']';
    if (options.allRootScores && result.hasMove) {
        output << ",\"root_scores\":{";
        for (std::size_t i = 0; i < result.rootMoveResults.size(); i++) {
            if (i > 0) output << ',';
            writeJsonString(output, moveToUCI(result.rootMoveResults[i].move));
            output << ':' << result.rootMoveResults[i].score;
        }
        output << '}';
    }
    output << ",\"futility_prunes\":";
    writeFutilityCounts(output, result.stats.futilityPrunes);
    output << ",\"futility_prunes_in_check\":";
    writeFutilityCounts(output, result.stats.futilityPrunesInCheck);
    output << "}\n";
}

void writeSummary(std::ostream& output, const Options& options, const RunStats& stats) {
    output << "{\"type\":\"summary\",\"futility_margins\":";
    writeMargins(output, options.parameters);
    output << ",\"weights\":";
    writeJsonString(output, options.weightsPath.empty() ? "built-in" : options.weightsPath);
    output << ",\"futility_max_depth\":" << options.parameters.futilityMaxDepth
           << ",\"all_root_scores\":" << (options.allRootScores ? "true" : "false")
           << ",\"node_limit\":" << options.nodeLimit
           << ",\"positions\":" << stats.positions
           << ",\"terminal_positions\":" << stats.terminalPositions
           << ",\"interrupted_searches\":" << stats.interruptedSearches
           << ",\"nodes\":" << stats.nodes
           << ",\"completed_nodes\":" << stats.completedNodes
           << ",\"elapsed_ms\":" << stats.elapsedMs
           << ",\"futility_prunes\":";
    writeFutilityCounts(output, stats.futilityPrunes);
    output << ",\"futility_prunes_in_check\":";
    writeFutilityCounts(output, stats.futilityPrunesInCheck);
    output << "}\n";
}

bool processFile(const std::string& path, const Options& options, RunStats& stats, std::ostream& output) {
    std::ifstream input(path);
    if (!input) {
        std::cerr << "fatal: failed to open input file " << path << "\n";
        return false;
    }

    std::string line;
    uint64_t lineNumber = 0;
    while (std::getline(input, line)) {
        lineNumber++;
        std::string text = trim(line);
        if (text.empty() || text[0] == '#') continue;

        std::string fen;
        std::string parseError;
        if (!extractFirstField(text, fen, parseError)) {
            std::cerr << "fatal: " << path << ':' << lineNumber << ": " << parseError << "\n";
            return false;
        }
        if (isHeaderField(fen)) continue;
        if (!looksLikeFen(fen)) {
            std::cerr << "fatal: " << path << ':' << lineNumber << ": invalid FEN in first field\n";
            return false;
        }

        Position pos = parseFEN(fen);
        resetDrawHistory(pos);
        SearchLimits limits{0, 0, nullptr, nullptr};
        limits.nodeLimit = options.nodeLimit;
        limits.parameters = options.parameters;
        limits.isolateTranspositionTable = true;
        limits.collectRootMoveScores = options.allRootScores;
        SearchResult result = searchBestMove(pos, limits);

        stats.positions++;
        if (!result.hasMove) stats.terminalPositions++;
        if (!result.completed) stats.interruptedSearches++;
        stats.nodes += result.nodes;
        stats.completedNodes += result.completedNodes;
        stats.elapsedMs += result.totalElapsedMs;
        for (int depth = 1; depth <= MAX_FUTILITY_DEPTH; depth++) {
            stats.futilityPrunes[depth] += result.stats.futilityPrunes[depth];
            stats.futilityPrunesInCheck[depth] += result.stats.futilityPrunesInCheck[depth];
        }
        writePosition(output, path, lineNumber, fen, options, result);

        if (options.reportEvery > 0 && stats.positions % options.reportEvery == 0) {
            std::cerr << "processed=" << stats.positions << " nodes=" << stats.nodes << "\n";
        }
    }
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
        std::cerr << "loaded NNUE weights from " << options.weightsPath << "\n";
    }

    std::ofstream outputFile;
    std::ostream* output = &std::cout;
    if (!options.outputPath.empty() && options.outputPath != "-") {
        std::filesystem::path outputPath = std::filesystem::absolute(options.outputPath).lexically_normal();
        for (const std::string& inputPath : options.inputPaths) {
            if (std::filesystem::absolute(inputPath).lexically_normal() == outputPath) {
                std::cerr << "fatal: output file must not also be an input file\n";
                return 1;
            }
        }
        std::error_code existsError;
        bool exists = std::filesystem::exists(outputPath, existsError);
        if (existsError) {
            std::cerr << "fatal: failed to inspect output path " << options.outputPath << "\n";
            return 1;
        }
        if (exists && !options.overwrite) {
            std::cerr << "fatal: output file already exists; pass --overwrite to replace it\n";
            return 1;
        }
        outputFile.open(outputPath, std::ios::out | std::ios::trunc);
        if (!outputFile) {
            std::cerr << "fatal: failed to open output file " << options.outputPath << "\n";
            return 1;
        }
        output = &outputFile;
    }

    RunStats stats;
    for (const std::string& path : options.inputPaths) {
        if (!processFile(path, options, stats, *output)) return 1;
    }
    writeSummary(*output, options, stats);
    if (!*output) {
        std::cerr << "fatal: failed while writing JSON Lines output\n";
        return 1;
    }
    if (stats.positions == 0) {
        std::cerr << "warning: no positions processed\n";
    }
    return 0;
}
