#include "engine.h"

#include <cctype>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace {

enum class ReportMode {
    Normal,
    Quiescence,
    Both,
};

struct Options {
    std::string fenFilePath;
    std::string weightsPath;
    ReportMode mode = ReportMode::Both;
    bool checks = true;
    bool helpRequested = false;
};

struct FenCase {
    int lineNumber = 0;
    std::string fen;
    std::string label;
};

std::string trim(const std::string& text) {
    std::size_t start = 0;
    while (start < text.size() && std::isspace(static_cast<unsigned char>(text[start]))) start++;
    std::size_t end = text.size();
    while (end > start && std::isspace(static_cast<unsigned char>(text[end - 1]))) end--;
    return text.substr(start, end - start);
}

void printUsage() {
    std::cout
        << "Usage: move_ordering_probe [options] <fen-file>\n"
        << "Options:\n"
        << "  -w, --weights <path>       Load external NNUE weights; failure is fatal\n"
        << "  -m, --mode <normal|qs|both> Report normal ordering, QS ordering, or both (default: both)\n"
        << "      --no-checks            Print ordering without invariant failures\n"
        << "  -h, --help                 Show this help\n";
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
        if (arg == "--weights" || arg == "-w") {
            const char* value = requireValue(arg.c_str());
            if (value == nullptr) return false;
            options.weightsPath = value;
        } else if (arg == "--mode" || arg == "-m") {
            const char* value = requireValue(arg.c_str());
            if (value == nullptr) return false;
            std::string mode = value;
            if (mode == "normal") options.mode = ReportMode::Normal;
            else if (mode == "qs") options.mode = ReportMode::Quiescence;
            else if (mode == "both") options.mode = ReportMode::Both;
            else {
                std::cerr << "Invalid mode: " << mode << "\n";
                return false;
            }
        } else if (arg == "--no-checks") {
            options.checks = false;
        } else if (!arg.empty() && arg[0] == '-') {
            std::cerr << "Unknown option: " << arg << "\n";
            return false;
        } else if (options.fenFilePath.empty()) {
            options.fenFilePath = arg;
        } else {
            std::cerr << "Unexpected extra argument: " << arg << "\n";
            return false;
        }
    }

    if (options.fenFilePath.empty() && !options.helpRequested) {
        std::cerr << "Missing FEN file path\n";
        return false;
    }
    return true;
}

std::vector<FenCase> readFenCases(const std::string& path) {
    std::ifstream input(path);
    std::vector<FenCase> cases;
    if (!input) {
        std::cerr << "Could not open FEN file: " << path << "\n";
        return cases;
    }

    std::string line;
    int lineNumber = 0;
    while (std::getline(input, line)) {
        lineNumber++;
        std::size_t comment = line.find('#');
        std::string fen = trim(comment == std::string::npos ? line : line.substr(0, comment));
        std::string label = comment == std::string::npos ? std::string() : trim(line.substr(comment + 1));
        if (fen.empty()) continue;
        cases.push_back({lineNumber, fen, label});
    }
    return cases;
}

char pieceChar(Piece piece) {
    switch (piece) {
        case W_PAWN: return 'P';
        case W_KNIGHT: return 'N';
        case W_BISHOP: return 'B';
        case W_ROOK: return 'R';
        case W_QUEEN: return 'Q';
        case W_KING: return 'K';
        case B_PAWN: return 'p';
        case B_KNIGHT: return 'n';
        case B_BISHOP: return 'b';
        case B_ROOK: return 'r';
        case B_QUEEN: return 'q';
        case B_KING: return 'k';
        default: return '.';
    }
}

bool isReportable(const MoveOrderingEntry& entry) {
    return entry.capture || entry.promotion || entry.filteredByQsSee;
}

int countHiddenQuietMoves(const std::vector<MoveOrderingEntry>& entries) {
    int hidden = 0;
    for (const MoveOrderingEntry& entry : entries) {
        if (!isReportable(entry)) hidden++;
    }
    return hidden;
}

void printEntry(const MoveOrderingEntry& entry) {
    std::cout << "    " << moveToUCI(entry.move)
              << " mover=" << pieceChar(entry.movingPiece)
              << " captured=" << pieceChar(entry.capturedPiece)
              << " see=" << entry.see
              << " mvv_lva=" << entry.mvvLvaScore
              << " order=" << entry.orderScore;
    if (entry.promotion) std::cout << " promotion=" << pieceChar(entry.move.promotion);
    if (entry.filteredByQsSee) std::cout << " QS_FILTERED";
    std::cout << "\n";
}

void printEntries(const std::string& title, const std::vector<MoveOrderingEntry>& entries, bool showQuietMoves) {
    std::cout << "  " << title << "\n";
    int hiddenQuietMoves = countHiddenQuietMoves(entries);
    for (const MoveOrderingEntry& entry : entries) {
        if ((showQuietMoves || isReportable(entry)) && !entry.filteredByQsSee) printEntry(entry);
    }
    if (!showQuietMoves && hiddenQuietMoves > 0) {
        std::cout << "    ... " << hiddenQuietMoves << " quiet moves hidden\n";
    }

    bool printedFilteredHeader = false;
    for (const MoveOrderingEntry& entry : entries) {
        if (!entry.filteredByQsSee) continue;
        if (!printedFilteredHeader) {
            std::cout << "  qs SEE<0 filtered captures\n";
            printedFilteredHeader = true;
        }
        printEntry(entry);
    }
}

bool checkCaptureBucketOrder(const std::vector<MoveOrderingEntry>& entries, bool includeFiltered, std::string& error) {
    bool seenNegative = false;
    for (const MoveOrderingEntry& entry : entries) {
        if (!entry.capture) continue;
        if (entry.filteredByQsSee && !includeFiltered) continue;
        if (entry.see < 0) {
            seenNegative = true;
        } else if (seenNegative) {
            error = "SEE >= 0 capture appears after a SEE < 0 capture";
            return false;
        }
    }
    return true;
}

bool checkMvvLvaOrder(const std::vector<MoveOrderingEntry>& entries, bool nonNegativeBucket, std::string& error) {
    bool havePrevious = false;
    int previousScore = 0;
    for (const MoveOrderingEntry& entry : entries) {
        if (!entry.capture || entry.filteredByQsSee) continue;
        if (nonNegativeBucket != (entry.see >= 0)) continue;
        if (havePrevious && entry.mvvLvaScore > previousScore) {
            error = "capture MVV/LVA score increases within the same SEE bucket";
            return false;
        }
        previousScore = entry.mvvLvaScore;
        havePrevious = true;
    }
    return true;
}

bool checkNormal(const std::vector<MoveOrderingEntry>& entries, std::vector<std::string>& errors) {
    std::string error;
    bool ok = true;
    if (!checkCaptureBucketOrder(entries, true, error)) {
        errors.push_back("normal: " + error);
        ok = false;
    }
    if (!checkMvvLvaOrder(entries, true, error)) {
        errors.push_back("normal SEE>=0: " + error);
        ok = false;
    }
    if (!checkMvvLvaOrder(entries, false, error)) {
        errors.push_back("normal SEE<0: " + error);
        ok = false;
    }
    return ok;
}

bool checkQuiescence(const Position& pos, const std::vector<MoveOrderingEntry>& entries, std::vector<std::string>& errors) {
    bool ok = true;
    if (!inCheck(pos, pos.sideToMove)) {
        for (const MoveOrderingEntry& entry : entries) {
            if (entry.capture && !entry.filteredByQsSee && entry.see < 0) {
                errors.push_back("qs: SEE < 0 capture was not filtered");
                ok = false;
                break;
            }
        }
        bool sawFiltered = false;
        for (const MoveOrderingEntry& entry : entries) {
            if (entry.filteredByQsSee) sawFiltered = true;
            else if (sawFiltered) {
                errors.push_back("qs: filtered entries should be reported after searched entries");
                ok = false;
                break;
            }
        }
    }

    std::string error;
    if (!checkMvvLvaOrder(entries, true, error)) {
        errors.push_back("qs SEE>=0: " + error);
        ok = false;
    }
    return ok;
}

bool runCase(const FenCase& fenCase, const Options& options) {
    Position pos = parseFEN(fenCase.fen);
    bool inCheckNow = inCheck(pos, pos.sideToMove);
    std::vector<std::string> errors;
    std::cout << "FEN line " << fenCase.lineNumber;
    if (!fenCase.label.empty()) std::cout << " (" << fenCase.label << ")";
    std::cout << ": " << fenCase.fen << "\n";
    if (inCheckNow) std::cout << "  in_check: yes, showing all legal evasions\n";

    if (options.mode == ReportMode::Normal || options.mode == ReportMode::Both) {
        std::vector<MoveOrderingEntry> normal =
            collectMoveOrderingDiagnostics(pos, MoveOrderingMode::Normal);
        printEntries(inCheckNow ? "normal ordered legal evasions" : "normal ordered tactical moves",
                     normal,
                     inCheckNow);
        if (options.checks) checkNormal(normal, errors);
    }

    if (options.mode == ReportMode::Quiescence || options.mode == ReportMode::Both) {
        std::vector<MoveOrderingEntry> qs =
            collectMoveOrderingDiagnostics(pos, MoveOrderingMode::Quiescence);
        printEntries(inCheckNow ? "qs ordered legal evasions" : "qs ordered tactical moves",
                     qs,
                     inCheckNow);
        if (options.checks) checkQuiescence(pos, qs, errors);
    }

    if (errors.empty()) {
        if (options.checks) std::cout << "  checks: ok\n";
    } else {
        for (const std::string& error : errors) std::cout << "  FAIL: " << error << "\n";
    }
    std::cout << "\n";
    return errors.empty();
}

}  // namespace

int main(int argc, char** argv) {
    Options options;
    if (!parseArgs(argc, argv, options)) return options.helpRequested ? 0 : 1;

    if (!options.weightsPath.empty()) {
        std::string error;
        if (!loadNnueWeightsFile(options.weightsPath, error)) {
            std::cerr << "Failed to load weights: " << error << "\n";
            return 1;
        }
    }

    std::vector<FenCase> cases = readFenCases(options.fenFilePath);
    if (cases.empty()) {
        std::cerr << "No FEN cases found in " << options.fenFilePath << "\n";
        return 1;
    }

    int failures = 0;
    for (const FenCase& fenCase : cases) {
        if (!runCase(fenCase, options)) failures++;
    }

    if (failures > 0) {
        std::cerr << failures << " move ordering case(s) failed\n";
        return 1;
    }
    return 0;
}
