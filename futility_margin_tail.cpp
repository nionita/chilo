#include "chess_position.h"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace futility_margin_tail {

struct Options {
    std::string inputPath;
    bool marginProvided = false;
    int margin = 0;
    int rescueLimit = 0;
    int passedPawnMinDestinationRank = 0;
    bool staticEvalLimitProvided = false;
    int staticEvalLimit = 0;
    int topCount = 20;
};

struct Record {
    std::string fen, prefixMove, quietMove;
    char quietPiece = '?';
    int staticEval = 0, prefixScore = 0, quietScore = 0, quietGain = 0;
    bool passedPawnAdvance = false;
    int relativeDestinationRank = 0;
};

struct Report {
    uint64_t records = 0;
    uint64_t passedPawnExcluded = 0, staticEvalLowExcluded = 0, staticEvalHighExcluded = 0, excluded = 0;
    uint64_t remaining = 0, wouldPrune = 0, rescued = 0, unrescued = 0;
    std::vector<Record> top;
};

std::string trim(const std::string& text) {
    std::size_t first = 0; while (first < text.size() && std::isspace(static_cast<unsigned char>(text[first]))) first++;
    std::size_t last = text.size(); while (last > first && std::isspace(static_cast<unsigned char>(text[last - 1]))) last--;
    return text.substr(first, last - first);
}

bool parseInt(const std::string& text, int& value) {
    try { std::size_t used = 0; value = std::stoi(text, &used); return used == text.size(); }
    catch (...) { return false; }
}

bool parseJsonStringField(const std::string& line, const char* name, std::string& value) {
    const std::string prefix = std::string("\"") + name + "\":\"";
    const std::size_t start = line.find(prefix);
    if (start == std::string::npos) return false;
    const std::size_t valueStart = start + prefix.size();
    const std::size_t valueEnd = line.find('"', valueStart);
    if (valueEnd == std::string::npos) return false;
    value = line.substr(valueStart, valueEnd - valueStart);
    return true;
}

bool parseJsonIntField(const std::string& line, const char* name, int& value) {
    const std::string prefix = std::string("\"") + name + "\":";
    const std::size_t start = line.find(prefix);
    if (start == std::string::npos) return false;
    std::size_t end = start + prefix.size();
    if (end < line.size() && line[end] == '-') end++;
    const std::size_t digits = end;
    while (end < line.size() && std::isdigit(static_cast<unsigned char>(line[end]))) end++;
    return end > digits && parseInt(line.substr(start + prefix.size(), end - (start + prefix.size())), value);
}

bool parseRecord(const std::string& line, Record& record) {
    std::string schema, quietPiece;
    if (!parseJsonStringField(line, "schema", schema) || schema != "chilo.futility_margin_rescue.v1" ||
        !parseJsonStringField(line, "fen", record.fen) || !parseJsonIntField(line, "static_eval", record.staticEval) ||
        !parseJsonStringField(line, "prefix_move", record.prefixMove) || !parseJsonIntField(line, "prefix_score", record.prefixScore) ||
        !parseJsonStringField(line, "quiet_move", record.quietMove) || !parseJsonStringField(line, "quiet_piece", quietPiece) ||
        !parseJsonIntField(line, "quiet_score", record.quietScore) || !parseJsonIntField(line, "quiet_gain", record.quietGain) ||
        quietPiece.size() != 1 || record.quietMove.size() != 4 ||
        (record.prefixMove.size() != 4 && record.prefixMove.size() != 5) ||
        record.quietGain != record.quietScore - record.prefixScore || record.quietGain <= 0) return false;
    record.quietPiece = quietPiece[0];
    return true;
}

bool parseUciSquare(char file, char rank, int& square) {
    if (file < 'a' || file > 'h' || rank < '1' || rank > '8') return false;
    square = (rank - '1') * 8 + (file - 'a'); return true;
}

bool isPassedPawnAdvance(const Position& position, const Record& record, int& relativeDestinationRank) {
    int from = 0, to = 0;
    if (!parseUciSquare(record.quietMove[0], record.quietMove[1], from) || !parseUciSquare(record.quietMove[2], record.quietMove[3], to)) return false;
    const Piece pawn = pieceAt(position, from);
    if (pawn != W_PAWN && pawn != B_PAWN) return false;
    if (record.quietPiece != (pawn == W_PAWN ? 'P' : 'p')) return false;
    const int direction = pawn == W_PAWN ? 1 : -1;
    const int advance = R(to) - R(from);
    if (F(from) != F(to) || (advance != direction && advance != 2 * direction)) return false;
    const Piece opponentPawn = pawn == W_PAWN ? B_PAWN : W_PAWN;
    for (int file = std::max(0, F(from) - 1); file <= std::min(7, F(from) + 1); file++) {
        for (int rank = R(from) + direction; rank >= 0 && rank < 8; rank += direction) {
            if (pieceAt(position, rank * 8 + file) == opponentPawn) return false;
        }
    }
    relativeDestinationRank = pawn == W_PAWN ? R(to) + 1 : 8 - R(to);
    return true;
}

bool recordBefore(const Record& left, const Record& right) {
    if (left.quietGain != right.quietGain) return left.quietGain > right.quietGain;
    if (left.fen != right.fen) return left.fen < right.fen;
    return left.quietMove < right.quietMove;
}

Report scan(std::istream& input, const Options& options) {
    Report report;
    std::string line;
    uint64_t lineNumber = 0;
    while (std::getline(input, line)) {
        lineNumber++;
        line = trim(line); if (line.empty()) continue;
        Record record;
        if (!parseRecord(line, record)) throw std::runtime_error("invalid rescue JSONL record at line " + std::to_string(lineNumber));
        Position position = parseFEN(record.fen);
        int relativeRank = 0;
        record.passedPawnAdvance = isPassedPawnAdvance(position, record, relativeRank);
        record.relativeDestinationRank = relativeRank;
        const bool passedPawn = options.passedPawnMinDestinationRank && record.passedPawnAdvance && relativeRank >= options.passedPawnMinDestinationRank;
        const bool staticLow = options.staticEvalLimitProvided && record.staticEval <= -options.staticEvalLimit;
        const bool staticHigh = options.staticEvalLimitProvided && record.staticEval > options.staticEvalLimit;
        report.records++;
        if (passedPawn) report.passedPawnExcluded++;
        if (staticLow) report.staticEvalLowExcluded++;
        if (staticHigh) report.staticEvalHighExcluded++;
        if (passedPawn || staticLow || staticHigh) { report.excluded++; continue; }
        report.remaining++;
        if (record.staticEval + options.margin > record.prefixScore) continue;
        report.wouldPrune++;
        if (record.quietGain <= options.rescueLimit) { report.rescued++; continue; }
        report.unrescued++;
        report.top.push_back(record);
        std::sort(report.top.begin(), report.top.end(), recordBefore);
        if (static_cast<int>(report.top.size()) > options.topCount) report.top.pop_back();
    }
    return report;
}

std::string jsonEscape(const std::string& text) {
    std::ostringstream output;
    for (unsigned char c : text) {
        if (c == '"') output << "\\\""; else if (c == '\\') output << "\\\\";
        else if (c == '\n') output << "\\n"; else if (c == '\r') output << "\\r"; else if (c == '\t') output << "\\t";
        else output << static_cast<char>(c);
    }
    return output.str();
}

void writeRecord(std::ostream& output, const Record& r) {
    output << "{\"fen\":\"" << jsonEscape(r.fen) << "\",\"static_eval\":" << r.staticEval
           << ",\"prefix_move\":\"" << r.prefixMove << "\",\"prefix_score\":" << r.prefixScore
           << ",\"quiet_move\":\"" << r.quietMove << "\",\"quiet_piece\":\"" << r.quietPiece
           << "\",\"quiet_score\":" << r.quietScore << ",\"quiet_gain\":" << r.quietGain
           << ",\"passed_pawn_advance\":" << (r.passedPawnAdvance ? "true" : "false")
           << ",\"relative_destination_rank\":" << r.relativeDestinationRank << '}';
}

void writeReport(std::ostream& output, const Report& report, const Options& options) {
    output << "{\"records\":" << report.records << ",\"margin\":" << options.margin << ",\"rescue_limit\":" << options.rescueLimit
           << ",\"passed_pawn_min_destination_rank\":" << options.passedPawnMinDestinationRank << ",\"static_eval_limit\":";
    if (options.staticEvalLimitProvided) output << options.staticEvalLimit; else output << "null";
    output << ",\"passed_pawn_excluded\":" << report.passedPawnExcluded << ",\"static_eval_low_excluded\":" << report.staticEvalLowExcluded
           << ",\"static_eval_high_excluded\":" << report.staticEvalHighExcluded << ",\"excluded\":" << report.excluded
           << ",\"remaining\":" << report.remaining << ",\"would_prune\":" << report.wouldPrune
           << ",\"rescued\":" << report.rescued << ",\"unrescued\":" << report.unrescued << ",\"max_unrescued\":";
    if (report.top.empty()) output << "null"; else writeRecord(output, report.top.front());
    output << ",\"top\":[";
    for (std::size_t i = 0; i < report.top.size(); i++) { if (i) output << ','; writeRecord(output, report.top[i]); }
    output << "]}\n";
}

bool parseArgs(int argc, char** argv, Options& options) {
    for (int index = 1; index < argc; index++) {
        const std::string argument = argv[index];
        auto value = [&](const char* name) -> const char* { if (index + 1 >= argc) { std::cerr << "Missing value for " << name << '\n'; return nullptr; } return argv[++index]; };
        if (argument == "--help" || argument == "-h") {
            std::cout << "Usage: futility_margin_tail --input positions.jsonl --margin CP [options]\nOptions:\n"
                      << "  --rescue-limit CP                      Accepted local loss (default: 0)\n"
                      << "  --passed-pawn-min-destination-rank N  0 disables (default: 0)\n"
                      << "  --static-eval-limit CP                 Retain -CP < static score <= CP\n  --top N                                Unrescued records to retain (default: 20)\n";
            return false;
        } else if (argument == "--input") { const char* v = value("--input"); if (!v) return false; options.inputPath = v; }
        else if (argument == "--margin") { const char* v = value("--margin"); if (!v || !parseInt(v, options.margin)) return false; options.marginProvided = true; }
        else if (argument == "--rescue-limit") { const char* v = value("--rescue-limit"); if (!v || !parseInt(v, options.rescueLimit)) return false; }
        else if (argument == "--passed-pawn-min-destination-rank") { const char* v = value("--passed-pawn-min-destination-rank"); if (!v || !parseInt(v, options.passedPawnMinDestinationRank)) return false; }
        else if (argument == "--static-eval-limit") { const char* v = value("--static-eval-limit"); if (!v || !parseInt(v, options.staticEvalLimit)) return false; options.staticEvalLimitProvided = true; }
        else if (argument == "--top") { const char* v = value("--top"); if (!v || !parseInt(v, options.topCount)) return false; }
        else { std::cerr << "Unknown argument: " << argument << '\n'; return false; }
    }
    if (options.inputPath.empty() || !options.marginProvided || options.margin < 0 || options.rescueLimit < 0 || options.passedPawnMinDestinationRank < 0 ||
        options.passedPawnMinDestinationRank > 8 || options.staticEvalLimit < 0 || options.topCount < 1) {
        std::cerr << "--input and non-negative --margin are required; all limits must be non-negative and --top positive\n"; return false;
    }
    return true;
}

}  // namespace futility_margin_tail

#ifndef FUTILITY_MARGIN_TAIL_TEST
int main(int argc, char** argv) {
    try {
        futility_margin_tail::Options options;
        if (!futility_margin_tail::parseArgs(argc, argv, options)) return 1;
        std::ifstream input(options.inputPath);
        if (!input) throw std::runtime_error("failed to open input " + options.inputPath);
        futility_margin_tail::writeReport(std::cout, futility_margin_tail::scan(input, options), options);
        return 0;
    } catch (const std::exception& error) { std::cerr << "fatal: " << error.what() << '\n'; return 1; }
}
#endif
