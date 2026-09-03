#include "engine.h"

#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

struct Options {
    std::string inputPath, weightsPath, resultsPath, matesPath, completedPath;
    int targetDepth = 0;
    std::vector<int> previousMargins;
    bool previousMarginsProvided = false;
    uint64_t reportEvery = 100;
};

std::string trim(const std::string& text) {
    std::size_t first = 0;
    while (first < text.size() && std::isspace(static_cast<unsigned char>(text[first]))) first++;
    std::size_t last = text.size();
    while (last > first && std::isspace(static_cast<unsigned char>(text[last - 1]))) last--;
    return text.substr(first, last - first);
}

void usage() {
    std::cout << "Usage: futility_margin_analysis --input selected.fens --weights net.bin --target-depth N\n"
              << "       --previous-margins M1[,M2,...] --results positions.jsonl\n"
              << "       --mates mate-risks.jsonl --completed completed.indices [options]\n"
              << "Options:\n  --report-every N    Progress interval in completed FENs (default: 100)\n";
}

bool parseInt(const std::string& text, int& value) {
    try { std::size_t used = 0; value = std::stoi(text, &used); return used == text.size(); }
    catch (...) { return false; }
}

bool parseUint64(const std::string& text, uint64_t& value) {
    if (text.empty() || text[0] == '-') return false;
    try { std::size_t used = 0; value = std::stoull(text, &used); return used == text.size(); }
    catch (...) { return false; }
}

bool parseMargins(const std::string& text, std::vector<int>& margins) {
    margins.clear();
    if (text.empty() || text == "-") return true;
    std::stringstream stream(text);
    std::string item;
    while (std::getline(stream, item, ',')) {
        int margin = 0;
        if (!parseInt(item, margin) || margin < 0) return false;
        margins.push_back(margin);
    }
    return true;
}

bool parseArgs(int argc, char** argv, Options& options) {
    for (int index = 1; index < argc; index++) {
        const std::string argument = argv[index];
        auto value = [&](const char* name) -> const char* {
            if (index + 1 >= argc) { std::cerr << "Missing value for " << name << '\n'; return nullptr; }
            return argv[++index];
        };
        if (argument == "--help" || argument == "-h") { usage(); return false; }
        if (argument == "--input") { const char* v = value("--input"); if (!v) return false; options.inputPath = v; }
        else if (argument == "--weights") { const char* v = value("--weights"); if (!v) return false; options.weightsPath = v; }
        else if (argument == "--target-depth") { const char* v = value("--target-depth"); if (!v || !parseInt(v, options.targetDepth)) return false; }
        else if (argument == "--previous-margins") { const char* v = value("--previous-margins"); if (!v || !parseMargins(v, options.previousMargins)) return false; options.previousMarginsProvided = true; }
        else if (argument == "--results") { const char* v = value("--results"); if (!v) return false; options.resultsPath = v; }
        else if (argument == "--mates") { const char* v = value("--mates"); if (!v) return false; options.matesPath = v; }
        else if (argument == "--completed") { const char* v = value("--completed"); if (!v) return false; options.completedPath = v; }
        else if (argument == "--report-every") { const char* v = value("--report-every"); if (!v || !parseUint64(v, options.reportEvery) || !options.reportEvery) return false; }
        else { std::cerr << "Unknown argument: " << argument << '\n'; return false; }
    }
    if (options.inputPath.empty() || options.weightsPath.empty() || options.resultsPath.empty() || options.matesPath.empty() ||
        options.completedPath.empty() || options.targetDepth < 1 || options.targetDepth > MAX_FUTILITY_DEPTH || !options.previousMarginsProvided ||
        options.previousMargins.size() != static_cast<std::size_t>(options.targetDepth - 1)) {
        std::cerr << "--input, --weights, --target-depth, matching --previous-margins, --results, --mates, and --completed are required\n";
        return false;
    }
    return true;
}

std::string jsonEscape(const std::string& text) {
    std::ostringstream output;
    for (unsigned char c : text) {
        if (c == '"') output << "\\\"";
        else if (c == '\\') output << "\\\\";
        else if (c == '\n') output << "\\n";
        else if (c == '\r') output << "\\r";
        else if (c == '\t') output << "\\t";
        else output << static_cast<char>(c);
    }
    return output.str();
}

char pieceSymbol(Piece piece) {
    switch (piece) {
        case W_PAWN: return 'P'; case W_KNIGHT: return 'N'; case W_BISHOP: return 'B'; case W_ROOK: return 'R'; case W_QUEEN: return 'Q'; case W_KING: return 'K';
        case B_PAWN: return 'p'; case B_KNIGHT: return 'n'; case B_BISHOP: return 'b'; case B_ROOK: return 'r'; case B_QUEEN: return 'q'; case B_KING: return 'k'; default: return '?';
    }
}

bool hasNonPawnMaterial(const Position& pos, Color side) {
    return pos.pieceBitboards[side][pieceTypeIndex(side == WHITE ? W_KNIGHT : B_KNIGHT)] ||
           pos.pieceBitboards[side][pieceTypeIndex(side == WHITE ? W_BISHOP : B_BISHOP)] ||
           pos.pieceBitboards[side][pieceTypeIndex(side == WHITE ? W_ROOK : B_ROOK)] ||
           pos.pieceBitboards[side][pieceTypeIndex(side == WHITE ? W_QUEEN : B_QUEEN)];
}

struct CompletedState { std::set<uint64_t> indices; uint64_t resultBytes = 0, mateBytes = 0; };

CompletedState loadCompleted(const std::string& path) {
    CompletedState result;
    std::ifstream input(path);
    std::string line;
    while (std::getline(input, line)) {
        std::istringstream fields(trim(line));
        std::string indexText, resultText, mateText, extra;
        fields >> indexText >> resultText >> mateText >> extra;
        uint64_t index = 0, resultBytes = 0, mateBytes = 0;
        if (!extra.empty() || !parseUint64(indexText, index) || !parseUint64(resultText, resultBytes) || !parseUint64(mateText, mateBytes) ||
            !result.indices.insert(index).second) throw std::runtime_error("invalid completed journal line: " + line);
        result.resultBytes += resultBytes;
        result.mateBytes += mateBytes;
    }
    return result;
}

std::string commonJson(const std::string& fen, int staticEval, const Position& position, const FutilityMarginSiteResult& trace) {
    std::ostringstream output;
    output << "{\"schema\":\"chilo.futility_margin_rescue.v1\",\"fen\":\"" << jsonEscape(fen)
           << "\",\"static_eval\":" << staticEval
           << ",\"prefix_move\":\"" << moveToUCI(trace.prefixMove) << "\",\"prefix_piece\":\"" << pieceSymbol(pieceAt(position, trace.prefixMove.from))
           << "\",\"prefix_score\":" << trace.prefixScore << ",\"prefix_count\":" << trace.prefixMoveCount
           << ",\"quiet_move\":\"" << moveToUCI(trace.quietMove) << "\",\"quiet_piece\":\"" << pieceSymbol(pieceAt(position, trace.quietMove.from))
           << "\",\"quiet_score\":" << trace.quietScore
           << ",\"prefix_delta\":" << (trace.prefixScore - staticEval)
           << ",\"quiet_gain\":" << (trace.quietScore - trace.prefixScore);
    return output.str();
}

std::string finiteJson(const std::string& fen, int staticEval, const Position& position, const FutilityMarginSiteResult& trace) {
    return commonJson(fen, staticEval, position, trace) + "}\n";
}

std::string mateJson(const std::string& fen, int staticEval, const Position& position, const FutilityMarginSiteResult& trace) {
    std::ostringstream output;
    output << commonJson(fen, staticEval, position, trace) << ",\"mate_plies\":" << mateDistancePlies(trace.quietScore)
           << ",\"outcome\":\"" << (trace.quietScore > 0 ? "win" : "loss") << "\"}\n";
    return output.str();
}

}  // namespace

int main(int argc, char** argv) {
    try {
        Options options;
        if (!parseArgs(argc, argv, options)) return 1;
        std::string error;
        if (!loadNnueWeightsFile(options.weightsPath, error)) throw std::runtime_error("failed to load NNUE weights: " + error);
        std::ifstream input(options.inputPath);
        if (!input) throw std::runtime_error("failed to open input " + options.inputPath);
        const CompletedState completed = loadCompleted(options.completedPath);
        const auto verifyAndTrim = [](const std::string& path, uint64_t expected) {
            const uint64_t actual = std::filesystem::exists(path) ? std::filesystem::file_size(path) : 0;
            if (actual < expected) throw std::runtime_error("output is shorter than completed journal: " + path);
            if (actual != expected) std::filesystem::resize_file(path, expected);
        };
        verifyAndTrim(options.resultsPath, completed.resultBytes);
        verifyAndTrim(options.matesPath, completed.mateBytes);
        std::ofstream results(options.resultsPath, std::ios::app), mates(options.matesPath, std::ios::app), journal(options.completedPath, std::ios::app);
        if (!results || !mates || !journal) throw std::runtime_error("failed to open run outputs for append");

        SearchParameters parameters{};
        parameters.futilityMargins.fill(0);
        parameters.futilityMaxDepth = options.targetDepth - 1;
        for (std::size_t i = 0; i < options.previousMargins.size(); i++) parameters.futilityMargins[i + 1] = options.previousMargins[i];

        uint64_t index = 0, done = 0, parentIneligible = 0, noPrefix = 0, noUsefulQuiet = 0, finite = 0, mateCount = 0;
        std::string fen;
        while (std::getline(input, fen)) {
            fen = trim(fen);
            if (fen.empty()) continue;
            index++;
            if (completed.indices.count(index)) { done++; continue; }
            std::string finiteOutput, mateOutput;
            Position position = parseFEN(fen);
            resetDrawHistory(position);
            const int staticEval = evaluate(position);
            if (inCheck(position, position.sideToMove) || !hasNonPawnMaterial(position, position.sideToMove)) {
                parentIneligible++;
            } else {
                FutilityMarginSiteResult trace{};
                SearchLimits limits{};
                limits.depth = options.targetDepth;
                limits.parameters = parameters;
                limits.isolateTranspositionTable = true;
                limits.futilityMarginSiteResult = &trace;
                const SearchResult result = searchBestMove(position, limits);
                if (!result.completed || !trace.completed) throw std::runtime_error("root PVS did not complete for input index " + std::to_string(index));
                if (!trace.hasPrefix) noPrefix++;
                else if (!trace.hasUsefulQuiet) noUsefulQuiet++;
                else if (isMateScore(trace.quietScore)) { mateOutput = mateJson(fen, staticEval, position, trace); mateCount++; }
                else { finiteOutput = finiteJson(fen, staticEval, position, trace); finite++; }
            }
            results << finiteOutput; mates << mateOutput; results.flush(); mates.flush();
            journal << index << ' ' << finiteOutput.size() << ' ' << mateOutput.size() << '\n'; journal.flush();
            done++;
            if (done % options.reportEvery == 0) {
                std::cout << "Futility-margin progress: completed " << done << ", rescue events " << finite << ", quiet mates " << mateCount
                          << ", parent-ineligible " << parentIneligible << ", no-prefix " << noPrefix << ", no-useful-quiet " << noUsefulQuiet << "\n";
            }
        }
        std::cout << "Futility-margin complete: positions " << done << ", rescue events " << finite << ", quiet mates " << mateCount
                  << ", parent-ineligible " << parentIneligible << ", no-prefix " << noPrefix << ", no-useful-quiet " << noUsefulQuiet << "\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << "fatal: " << error.what() << '\n'; return 1; }
}
