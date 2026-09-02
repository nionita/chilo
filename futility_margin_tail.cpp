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
    int passedPawnMinDestinationRank = 0;
    int topCount = 20;
};

struct Record {
    std::string fen;
    int staticEval = 0;
    std::string move;
    char movingPiece = '?';
    int moveScore = 0;
    int delta = 0;
    bool passedPawnAdvance = false;
    int relativeDestinationRank = 0;
};

struct Report {
    uint64_t records = 0;
    uint64_t positiveRecords = 0;
    uint64_t excludedRecords = 0;
    uint64_t excludedPositiveRecords = 0;
    std::vector<Record> top;
};

std::string trim(const std::string& text) {
    std::size_t first = 0;
    while (first < text.size() && std::isspace(static_cast<unsigned char>(text[first]))) first++;
    std::size_t last = text.size();
    while (last > first && std::isspace(static_cast<unsigned char>(text[last - 1]))) last--;
    return text.substr(first, last - first);
}

bool parseInt(const std::string& text, int& value) {
    try {
        std::size_t used = 0;
        value = std::stoi(text, &used);
        return used == text.size();
    } catch (...) {
        return false;
    }
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
    const std::size_t digitsStart = end;
    while (end < line.size() && std::isdigit(static_cast<unsigned char>(line[end]))) end++;
    return end > digitsStart && parseInt(line.substr(start + prefix.size(), end - (start + prefix.size())), value);
}

bool parseRecord(const std::string& line, Record& record) {
    std::string movingPiece;
    if (!parseJsonStringField(line, "fen", record.fen) ||
        !parseJsonIntField(line, "static_eval", record.staticEval) ||
        !parseJsonStringField(line, "move", record.move) ||
        !parseJsonStringField(line, "moving_piece", movingPiece) ||
        !parseJsonIntField(line, "move_score", record.moveScore) ||
        movingPiece.size() != 1 || record.move.size() != 4) {
        return false;
    }
    record.movingPiece = movingPiece[0];
    record.delta = record.moveScore - record.staticEval;
    return true;
}

bool parseUciSquare(char file, char rank, int& square) {
    if (file < 'a' || file > 'h' || rank < '1' || rank > '8') return false;
    square = (rank - '1') * 8 + (file - 'a');
    return true;
}

bool isPassedPawnAdvance(const Position& position, const Record& record, int& relativeDestinationRank) {
    int from = 0, to = 0;
    if (!parseUciSquare(record.move[0], record.move[1], from) || !parseUciSquare(record.move[2], record.move[3], to)) return false;
    const Piece pawn = pieceAt(position, from);
    if (pawn != W_PAWN && pawn != B_PAWN) return false;
    if (record.movingPiece != (pawn == W_PAWN ? 'P' : 'p')) return false;
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
    if (left.delta != right.delta) return left.delta > right.delta;
    if (left.fen != right.fen) return left.fen < right.fen;
    return left.move < right.move;
}

Report scan(std::istream& input, const Options& options) {
    Report report;
    std::string line;
    uint64_t lineNumber = 0;
    while (std::getline(input, line)) {
        lineNumber++;
        line = trim(line);
        if (line.empty()) continue;
        Record record;
        if (!parseRecord(line, record)) {
            throw std::runtime_error("invalid canonical finite JSONL record at line " + std::to_string(lineNumber));
        }
        Position position = parseFEN(record.fen);
        int relativeRank = 0;
        record.passedPawnAdvance = isPassedPawnAdvance(position, record, relativeRank);
        record.relativeDestinationRank = relativeRank;
        const bool excluded = options.passedPawnMinDestinationRank != 0 && record.passedPawnAdvance &&
                              relativeRank >= options.passedPawnMinDestinationRank;
        report.records++;
        if (record.delta > 0) report.positiveRecords++;
        if (excluded) {
            report.excludedRecords++;
            if (record.delta > 0) report.excludedPositiveRecords++;
            continue;
        }
        if (record.delta <= 0) continue;
        report.top.push_back(record);
        std::sort(report.top.begin(), report.top.end(), recordBefore);
        if (static_cast<int>(report.top.size()) > options.topCount) report.top.pop_back();
    }
    return report;
}

std::string jsonEscape(const std::string& text) {
    std::ostringstream output;
    for (unsigned char character : text) {
        if (character == '"') output << "\\\"";
        else if (character == '\\') output << "\\\\";
        else if (character == '\n') output << "\\n";
        else if (character == '\r') output << "\\r";
        else if (character == '\t') output << "\\t";
        else output << static_cast<char>(character);
    }
    return output.str();
}

void writeRecord(std::ostream& output, const Record& record) {
    output << "{\"fen\":\"" << jsonEscape(record.fen) << "\",\"static_eval\":" << record.staticEval
           << ",\"move\":\"" << record.move << "\",\"moving_piece\":\"" << record.movingPiece
           << "\",\"move_score\":" << record.moveScore << ",\"delta\":" << record.delta
           << ",\"passed_pawn_advance\":" << (record.passedPawnAdvance ? "true" : "false")
           << ",\"relative_destination_rank\":" << record.relativeDestinationRank << '}';
}

void writeReport(std::ostream& output, const Report& report, const Options& options) {
    output << "{\"records\":" << report.records << ",\"positive_records\":" << report.positiveRecords
           << ",\"passed_pawn_min_destination_rank\":" << options.passedPawnMinDestinationRank
           << ",\"excluded_records\":" << report.excludedRecords
           << ",\"excluded_positive_records\":" << report.excludedPositiveRecords
           << ",\"remaining_positive_records\":" << (report.positiveRecords - report.excludedPositiveRecords)
           << ",\"max_positive\":";
    if (report.top.empty()) output << "null";
    else writeRecord(output, report.top.front());
    output << ",\"top\":[";
    for (std::size_t index = 0; index < report.top.size(); index++) {
        if (index) output << ',';
        writeRecord(output, report.top[index]);
    }
    output << "]}\n";
}

bool parseArgs(int argc, char** argv, Options& options) {
    for (int index = 1; index < argc; index++) {
        const std::string argument = argv[index];
        auto value = [&](const char* name) -> const char* {
            if (index + 1 >= argc) {
                std::cerr << "Missing value for " << name << '\n';
                return nullptr;
            }
            return argv[++index];
        };
        if (argument == "--help" || argument == "-h") {
            std::cout << "Usage: futility_margin_tail --input positions.jsonl [options]\n"
                      << "Options:\n"
                      << "  --passed-pawn-min-destination-rank N  0 disables; otherwise relative rank 1..8 (default: 0)\n"
                      << "  --top N                                Positive records to retain (default: 20)\n";
            return false;
        } else if (argument == "--input") {
            const char* item = value("--input"); if (item == nullptr) return false; options.inputPath = item;
        } else if (argument == "--passed-pawn-min-destination-rank") {
            const char* item = value("--passed-pawn-min-destination-rank");
            if (item == nullptr || !parseInt(item, options.passedPawnMinDestinationRank)) return false;
        } else if (argument == "--top") {
            const char* item = value("--top");
            if (item == nullptr || !parseInt(item, options.topCount)) return false;
        } else {
            std::cerr << "Unknown argument: " << argument << '\n';
            return false;
        }
    }
    if (options.inputPath.empty() || options.passedPawnMinDestinationRank < 0 ||
        options.passedPawnMinDestinationRank > 8 || options.topCount < 1) {
        std::cerr << "--input is required; rank must be in 0..8; --top must be positive\n";
        return false;
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
        const futility_margin_tail::Report report = futility_margin_tail::scan(input, options);
        futility_margin_tail::writeReport(std::cout, report, options);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "fatal: " << error.what() << '\n';
        return 1;
    }
}
#endif
