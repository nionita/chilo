#include "engine.h"

#include <cctype>
#include <chrono>
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
    std::string baselineOutputPath;
    uint64_t nodeLimit = 0;
    uint64_t baselineNodeLimit = 0;
    uint64_t referenceNodesPerRoot = 0;
    uint64_t reportEvery = 100;
    int referenceDepthGap = 0;
    SearchParameters parameters{};
    bool hasNodeLimit = false;
    bool hasBaselineNodeLimit = false;
    bool hasReferenceNodesPerRoot = false;
    bool hasReferenceDepthGap = false;
    bool hasMargins = false;
    bool allRootScores = false;
    bool perRootReference = false;
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

struct ReferenceRunStats {
    uint64_t positions = 0;
    uint64_t terminalPositions = 0;
    uint64_t completedPositions = 0;
    uint64_t rejectedPositions = 0;
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
        << "  --per-root-reference         Run baseline then a full-window reference for every root move\n"
        << "  --baseline-nodes <N>         Baseline PVS nodes per position (per-root mode)\n"
        << "  --reference-nodes-per-root <N>  Full-window cap for each legal root move\n"
        << "  --reference-depth-gap <N>    Required reference depth over baseline (per-root mode)\n"
        << "  --baseline-output <path>     Baseline JSONL output (per-root mode)\n"
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
        } else if (arg == "--baseline-nodes") {
            const char* value = requireValue("--baseline-nodes");
            if (value == nullptr || !parseUInt64(value, options.baselineNodeLimit) || options.baselineNodeLimit == 0) {
                std::cerr << "--baseline-nodes must be a positive integer\n";
                return false;
            }
            options.hasBaselineNodeLimit = true;
        } else if (arg == "--reference-nodes-per-root") {
            const char* value = requireValue("--reference-nodes-per-root");
            if (value == nullptr || !parseUInt64(value, options.referenceNodesPerRoot) ||
                options.referenceNodesPerRoot == 0) {
                std::cerr << "--reference-nodes-per-root must be a positive integer\n";
                return false;
            }
            options.hasReferenceNodesPerRoot = true;
        } else if (arg == "--reference-depth-gap") {
            const char* value = requireValue("--reference-depth-gap");
            if (value == nullptr || !parseNonNegativeInt(value, options.referenceDepthGap) ||
                options.referenceDepthGap <= 0) {
                std::cerr << "--reference-depth-gap must be a positive integer\n";
                return false;
            }
            options.hasReferenceDepthGap = true;
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
        } else if (arg == "--per-root-reference") {
            options.perRootReference = true;
        } else if (arg == "--baseline-output") {
            const char* value = requireValue("--baseline-output");
            if (value == nullptr) return false;
            options.baselineOutputPath = value;
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

    if (options.perRootReference) {
        if (options.hasNodeLimit || options.allRootScores) {
            std::cerr << "--per-root-reference cannot be combined with --nodes or --all-root-scores\n";
            return false;
        }
        if (!options.hasBaselineNodeLimit || !options.hasReferenceNodesPerRoot || !options.hasReferenceDepthGap ||
            options.baselineOutputPath.empty() || options.outputPath.empty()) {
            std::cerr << "--per-root-reference requires --baseline-nodes, --reference-nodes-per-root, "
                         "--reference-depth-gap, --baseline-output, and --output\n";
            return false;
        }
    } else if (!options.hasNodeLimit) {
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

void writeReferencePosition(std::ostream& output, const std::string& source, uint64_t lineNumber,
                            const std::string& fen, const Options& options, const SearchResult& baseline,
                            const std::vector<RootMoveResult>& rootScores, uint64_t rootNodes,
                            uint64_t rootCompletedNodes, uint64_t rootElapsedMs, int targetDepth,
                            int legalRootMoves, const char* status, const char* rejectionReason = nullptr,
                            const SearchResult* failedRoot = nullptr, int completedRootMoves = 0) {
    const bool complete = std::string(status) == "complete";
    const bool terminal = !baseline.hasMove;
    Move bestMove{};
    int bestScore = baseline.score;
    if (complete && !rootScores.empty()) {
        bestMove = rootScores.front().move;
        bestScore = rootScores.front().score;
        for (const RootMoveResult& root : rootScores) {
            if (root.score > bestScore) {
                bestScore = root.score;
                bestMove = root.move;
            }
        }
    } else if (baseline.hasMove) {
        bestMove = baseline.bestMove;
    }

    output << "{\"type\":\"position\",\"reference_mode\":\"per_root_v1\",\"reference_status\":";
    writeJsonString(output, status);
    output << ",\"source\":";
    writeJsonString(output, source);
    output << ",\"line\":" << lineNumber << ",\"fen\":";
    writeJsonString(output, fen);
    output << ",\"futility_margins\":";
    writeMargins(output, options.parameters);
    output << ",\"weights\":";
    writeJsonString(output, options.weightsPath.empty() ? "built-in" : options.weightsPath);
    output << ",\"futility_max_depth\":" << options.parameters.futilityMaxDepth
           << ",\"all_root_scores\":true"
           << ",\"node_limit\":" << options.referenceNodesPerRoot
           << ",\"node_limit_per_root\":" << options.referenceNodesPerRoot
           << ",\"baseline_node_limit\":" << options.baselineNodeLimit
           << ",\"baseline_completed_depth\":" << baseline.depth
           << ",\"target_depth\":" << targetDepth
           << ",\"legal_root_moves\":" << legalRootMoves
           << ",\"completed_root_moves\":" << completedRootMoves
           << ",\"nodes\":" << rootNodes
           << ",\"completed_nodes\":" << rootCompletedNodes
           << ",\"baseline_nodes\":" << baseline.nodes
           << ",\"total_nodes\":" << (baseline.nodes + rootNodes)
           << ",\"completed_depth\":" << (complete ? targetDepth : 0)
           << ",\"elapsed_ms\":" << rootElapsedMs
           << ",\"iteration_interrupted\":" << (complete || terminal ? "false" : "true")
           << ",\"terminal\":" << (terminal ? "true" : "false")
           << ",\"has_move\":" << (baseline.hasMove ? "true" : "false")
           << ",\"bestmove\":";
    writeJsonString(output, baseline.hasMove ? moveToUCI(bestMove) : "0000");
    output << ",\"score\":" << bestScore << ",\"pv\":[]";
    if (complete) {
        output << ",\"root_scores\":{";
        for (std::size_t i = 0; i < rootScores.size(); i++) {
            if (i > 0) output << ',';
            writeJsonString(output, moveToUCI(rootScores[i].move));
            output << ':' << rootScores[i].score;
        }
        output << '}';
    }
    if (rejectionReason != nullptr) {
        output << ",\"rejection_reason\":";
        writeJsonString(output, rejectionReason);
    }
    if (failedRoot != nullptr) {
        output << ",\"failed_root_move\":";
        writeJsonString(output, failedRoot->hasMove ? moveToUCI(failedRoot->bestMove) : "0000");
        output << ",\"failed_root_completed_depth\":" << failedRoot->depth
               << ",\"failed_root_nodes\":" << failedRoot->nodes
               << ",\"failed_root_completed_nodes\":" << failedRoot->completedNodes;
    }
    output << ",\"futility_prunes\":[0,0,0,0,0,0,0]"
           << ",\"futility_prunes_in_check\":[0,0,0,0,0,0,0]}\n";
}

void writeReferenceSummary(std::ostream& output, const Options& options, const ReferenceRunStats& stats) {
    output << "{\"type\":\"summary\",\"reference_mode\":\"per_root_v1\",\"futility_margins\":";
    writeMargins(output, options.parameters);
    output << ",\"weights\":";
    writeJsonString(output, options.weightsPath.empty() ? "built-in" : options.weightsPath);
    output << ",\"futility_max_depth\":" << options.parameters.futilityMaxDepth
           << ",\"all_root_scores\":true"
           << ",\"node_limit\":" << options.referenceNodesPerRoot
           << ",\"node_limit_per_root\":" << options.referenceNodesPerRoot
           << ",\"baseline_node_limit\":" << options.baselineNodeLimit
           << ",\"reference_depth_gap\":" << options.referenceDepthGap
           << ",\"positions\":" << stats.positions
           << ",\"terminal_positions\":" << stats.terminalPositions
           << ",\"completed_reference_positions\":" << stats.completedPositions
           << ",\"rejected_reference_positions\":" << stats.rejectedPositions
           << ",\"nodes\":" << stats.nodes
           << ",\"completed_nodes\":" << stats.completedNodes
           << ",\"elapsed_ms\":" << stats.elapsedMs
           << ",\"futility_prunes\":[0,0,0,0,0,0,0]"
           << ",\"futility_prunes_in_check\":[0,0,0,0,0,0,0]}\n";
}

uint64_t countInputPositions(const std::vector<std::string>& paths) {
    uint64_t count = 0;
    for (const std::string& path : paths) {
        std::ifstream input(path);
        std::string line;
        while (std::getline(input, line)) {
            std::string text = trim(line);
            if (text.empty() || text[0] == '#') continue;
            std::string field;
            std::string error;
            if (extractFirstField(text, field, error) && !isHeaderField(field)) count++;
        }
    }
    return count;
}

void reportReferenceProgress(const ReferenceRunStats& stats, uint64_t total,
                             std::chrono::steady_clock::time_point started) {
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - started).count();
    const double rate = elapsed > 0 ? (1000.0 * static_cast<double>(stats.positions) / elapsed) : 0.0;
    const double etaSeconds = rate > 0.0 && total >= stats.positions ? (total - stats.positions) / rate : 0.0;
    std::cerr << "reference progress: " << stats.positions << '/' << total
              << " complete=" << stats.completedPositions
              << " rejected=" << stats.rejectedPositions
              << " terminal=" << stats.terminalPositions
              << " nodes=" << stats.nodes
              << " elapsed_s=" << elapsed / 1000
              << " positions_per_s=" << rate
              << " eta_s=" << static_cast<uint64_t>(etaSeconds) << "\n";
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

bool processReferenceFile(const std::string& path, const Options& options, RunStats& baselineStats,
                          ReferenceRunStats& referenceStats, std::ostream& baselineOutput,
                          std::ostream& referenceOutput, uint64_t totalPositions,
                          std::chrono::steady_clock::time_point started) {
    std::ifstream input(path);
    if (!input) {
        std::cerr << "fatal: failed to open input file " << path << "\n";
        return false;
    }

    Options baselineOptions = options;
    baselineOptions.nodeLimit = options.baselineNodeLimit;
    baselineOptions.allRootScores = false;
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
        SearchLimits baselineLimits{};
        baselineLimits.nodeLimit = options.baselineNodeLimit;
        baselineLimits.parameters = options.parameters;
        baselineLimits.isolateTranspositionTable = true;
        SearchResult baseline = searchBestMove(pos, baselineLimits);
        baselineStats.positions++;
        if (!baseline.hasMove) baselineStats.terminalPositions++;
        if (!baseline.completed) baselineStats.interruptedSearches++;
        baselineStats.nodes += baseline.nodes;
        baselineStats.completedNodes += baseline.completedNodes;
        baselineStats.elapsedMs += baseline.totalElapsedMs;
        for (int depth = 1; depth <= MAX_FUTILITY_DEPTH; depth++) {
            baselineStats.futilityPrunes[depth] += baseline.stats.futilityPrunes[depth];
            baselineStats.futilityPrunesInCheck[depth] += baseline.stats.futilityPrunesInCheck[depth];
        }
        writePosition(baselineOutput, path, lineNumber, fen, baselineOptions, baseline);

        referenceStats.positions++;
        if (!baseline.hasMove) {
            referenceStats.terminalPositions++;
            writeReferencePosition(referenceOutput, path, lineNumber, fen, options, baseline, {}, 0, 0, 0, 0, 0,
                                   "terminal");
        } else if (baseline.depth == 0) {
            referenceStats.rejectedPositions++;
            writeReferencePosition(referenceOutput, path, lineNumber, fen, options, baseline, {}, 0, 0, 0, 0, 0,
                                   "rejected", "baseline_depth_zero");
        } else {
            const int targetDepth = baseline.depth + options.referenceDepthGap;
            Move rootMoves[MAX_MOVES];
            const int rootCount = genLegalMoves(pos, rootMoves);
            if (targetDepth > MAX_SEARCH_DEPTH) {
                referenceStats.rejectedPositions++;
                writeReferencePosition(referenceOutput, path, lineNumber, fen, options, baseline, {}, 0, 0, 0,
                                       targetDepth, rootCount, "rejected", "target_depth_exceeds_max");
            } else {
                std::vector<RootMoveResult> rootScores;
                rootScores.reserve(rootCount);
                uint64_t rootNodes = 0;
                uint64_t rootCompletedNodes = 0;
                uint64_t rootElapsedMs = 0;
                bool rejected = false;
                SearchResult failedRoot{};
                for (int i = 0; i < rootCount; i++) {
                    resetDrawHistory(pos);
                    SearchLimits rootLimits{};
                    rootLimits.depth = targetDepth;
                    rootLimits.nodeLimit = options.referenceNodesPerRoot;
                    rootLimits.parameters = options.parameters;
                    rootLimits.isolateTranspositionTable = true;
                    rootLimits.restrictRootMove = true;
                    rootLimits.rootMove = rootMoves[i];
                    SearchResult root = searchBestMove(pos, rootLimits);
                    rootNodes += root.nodes;
                    rootCompletedNodes += root.completedNodes;
                    rootElapsedMs += root.totalElapsedMs;
                    for (int depth = 1; depth <= MAX_FUTILITY_DEPTH; depth++) {
                        referenceStats.futilityPrunes[depth] += root.stats.futilityPrunes[depth];
                        referenceStats.futilityPrunesInCheck[depth] += root.stats.futilityPrunesInCheck[depth];
                    }
                    if (!root.completed || root.depth != targetDepth || !root.hasMove) {
                        rejected = true;
                        failedRoot = root;
                        break;
                    }
                    RootMoveResult rootScore{};
                    rootScore.move = rootMoves[i];
                    rootScore.score = root.score;
                    rootScores.push_back(std::move(rootScore));
                }
                referenceStats.nodes += rootNodes;
                referenceStats.completedNodes += rootCompletedNodes;
                referenceStats.elapsedMs += rootElapsedMs;
                if (rejected) {
                    referenceStats.rejectedPositions++;
                    writeReferencePosition(referenceOutput, path, lineNumber, fen, options, baseline, rootScores,
                                           rootNodes, rootCompletedNodes, rootElapsedMs, targetDepth, rootCount,
                                           "rejected", "root_node_limit", &failedRoot,
                                           static_cast<int>(rootScores.size()));
                } else {
                    referenceStats.completedPositions++;
                    writeReferencePosition(referenceOutput, path, lineNumber, fen, options, baseline, rootScores,
                                           rootNodes, rootCompletedNodes, rootElapsedMs, targetDepth, rootCount,
                                           "complete", nullptr, nullptr, rootCount);
                }
            }
        }

        if (options.reportEvery > 0 && referenceStats.positions % options.reportEvery == 0) {
            reportReferenceProgress(referenceStats, totalPositions, started);
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

    auto checkOutputPath = [&](const std::string& text, const char* label,
                               std::filesystem::path& outputPath) -> bool {
        outputPath = std::filesystem::absolute(text).lexically_normal();
        for (const std::string& inputPath : options.inputPaths) {
            if (std::filesystem::absolute(inputPath).lexically_normal() == outputPath) {
                std::cerr << "fatal: " << label << " must not also be an input file\n";
                return false;
            }
        }
        std::error_code existsError;
        bool exists = std::filesystem::exists(outputPath, existsError);
        if (existsError) {
            std::cerr << "fatal: failed to inspect " << label << " " << text << "\n";
            return false;
        }
        if (exists && !options.overwrite) {
            std::cerr << "fatal: " << label << " already exists; pass --overwrite to replace it\n";
            return false;
        }
        return true;
    };

    if (options.perRootReference) {
        std::filesystem::path referencePath;
        std::filesystem::path baselinePath;
        if (!checkOutputPath(options.outputPath, "reference output", referencePath) ||
            !checkOutputPath(options.baselineOutputPath, "baseline output", baselinePath)) {
            return 1;
        }
        if (referencePath == baselinePath) {
            std::cerr << "fatal: reference output and baseline output must differ\n";
            return 1;
        }
        std::ofstream referenceFile(referencePath, std::ios::out | std::ios::trunc);
        std::ofstream baselineFile(baselinePath, std::ios::out | std::ios::trunc);
        if (!referenceFile || !baselineFile) {
            std::cerr << "fatal: failed to open per-root reference outputs\n";
            return 1;
        }
        const uint64_t totalPositions = countInputPositions(options.inputPaths);
        const auto started = std::chrono::steady_clock::now();
        RunStats baselineStats;
        ReferenceRunStats referenceStats;
        for (const std::string& path : options.inputPaths) {
            if (!processReferenceFile(path, options, baselineStats, referenceStats, baselineFile, referenceFile,
                                      totalPositions, started)) {
                return 1;
            }
        }
        Options baselineOptions = options;
        baselineOptions.nodeLimit = options.baselineNodeLimit;
        baselineOptions.allRootScores = false;
        writeSummary(baselineFile, baselineOptions, baselineStats);
        writeReferenceSummary(referenceFile, options, referenceStats);
        if (!referenceFile || !baselineFile) {
            std::cerr << "fatal: failed while writing per-root reference JSON Lines output\n";
            return 1;
        }
        if (referenceStats.positions == 0) std::cerr << "warning: no positions processed\n";
        reportReferenceProgress(referenceStats, totalPositions, started);
        return 0;
    }

    std::ofstream outputFile;
    std::ostream* output = &std::cout;
    if (!options.outputPath.empty() && options.outputPath != "-") {
        std::filesystem::path outputPath;
        if (!checkOutputPath(options.outputPath, "output file", outputPath)) return 1;
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
    if (stats.positions == 0) std::cerr << "warning: no positions processed\n";
    return 0;
}
