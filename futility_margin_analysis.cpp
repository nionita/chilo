#include "engine.h"

#include <algorithm>
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
    std::string inputPath;
    std::string weightsPath;
    std::string resultsPath;
    std::string matesPath;
    std::string completedPath;
    int targetDepth = 0;
    std::vector<int> previousMargins;
    bool previousMarginsProvided = false;
    uint64_t reportEvery = 100;
};

struct MoveRecord {
    std::string move;
    char movingPiece = '?';
    int score = 0;
};

struct MateRecord : MoveRecord {
    int matePlies = 0;
    std::string outcome;
};

std::string trim(const std::string& text) {
    std::size_t first = 0;
    while (first < text.size() && std::isspace(static_cast<unsigned char>(text[first]))) first++;
    std::size_t last = text.size();
    while (last > first && std::isspace(static_cast<unsigned char>(text[last - 1]))) last--;
    return text.substr(first, last - first);
}

void usage() {
    std::cout
        << "Usage: futility_margin_analysis --input selected.fens --weights net.bin --target-depth N\\n"
        << "       --previous-margins M1[,M2,...]\\n"
        << "       --results positions.jsonl --mates mate-risks.jsonl --completed completed.indices [options]\\n"
        << "Options:\\n"
        << "  --report-every N    Progress interval in completed FENs (default: 100)\\n";
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

bool parseUint64(const std::string& text, uint64_t& value) {
    if (text.empty() || text[0] == '-') return false;
    try {
        std::size_t used = 0;
        value = std::stoull(text, &used);
        return used == text.size();
    } catch (...) {
        return false;
    }
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
            if (index + 1 >= argc) {
                std::cerr << "Missing value for " << name << "\\n";
                return nullptr;
            }
            return argv[++index];
        };
        if (argument == "--help" || argument == "-h") {
            usage();
            return false;
        } else if (argument == "--input") {
            const char* item = value("--input"); if (item == nullptr) return false; options.inputPath = item;
        } else if (argument == "--weights") {
            const char* item = value("--weights"); if (item == nullptr) return false; options.weightsPath = item;
        } else if (argument == "--target-depth") {
            const char* item = value("--target-depth");
            if (item == nullptr || !parseInt(item, options.targetDepth)) return false;
        } else if (argument == "--previous-margins") {
            const char* item = value("--previous-margins");
            if (item == nullptr || !parseMargins(item, options.previousMargins)) return false;
            options.previousMarginsProvided = true;
        } else if (argument == "--results") {
            const char* item = value("--results"); if (item == nullptr) return false; options.resultsPath = item;
        } else if (argument == "--mates") {
            const char* item = value("--mates"); if (item == nullptr) return false; options.matesPath = item;
        } else if (argument == "--completed") {
            const char* item = value("--completed"); if (item == nullptr) return false; options.completedPath = item;
        } else if (argument == "--report-every") {
            const char* item = value("--report-every");
            if (item == nullptr || !parseUint64(item, options.reportEvery) || options.reportEvery == 0) return false;
        } else {
            std::cerr << "Unknown argument: " << argument << "\\n";
            return false;
        }
    }
    if (options.inputPath.empty() || options.weightsPath.empty() || options.resultsPath.empty() || options.matesPath.empty() ||
        options.completedPath.empty() || options.targetDepth < 1 || options.targetDepth > MAX_FUTILITY_DEPTH ||
        !options.previousMarginsProvided) {
        std::cerr << "--input, --weights, --target-depth, --previous-margins, --results, --mates, and --completed are required\\n";
        return false;
    }
    if (options.previousMargins.size() != static_cast<std::size_t>(options.targetDepth - 1)) {
        std::cerr << "--previous-margins must contain exactly target-depth - 1 values\\n";
        return false;
    }
    return true;
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

char pieceSymbol(Piece piece) {
    switch (piece) {
        case W_PAWN: return 'P'; case W_KNIGHT: return 'N'; case W_BISHOP: return 'B';
        case W_ROOK: return 'R'; case W_QUEEN: return 'Q'; case W_KING: return 'K';
        case B_PAWN: return 'p'; case B_KNIGHT: return 'n'; case B_BISHOP: return 'b';
        case B_ROOK: return 'r'; case B_QUEEN: return 'q'; case B_KING: return 'k';
        default: return '?';
    }
}

bool quietMove(const Position& pos, const Move& move) {
    return move.promotion == EMPTY && !move.isCastle && !move.isEnPassant && pieceAt(pos, move.to) == EMPTY;
}

bool hasNonPawnMaterial(const Position& pos, Color side) {
    return pos.pieceBitboards[side][pieceTypeIndex(side == WHITE ? W_KNIGHT : B_KNIGHT)] != 0 ||
           pos.pieceBitboards[side][pieceTypeIndex(side == WHITE ? W_BISHOP : B_BISHOP)] != 0 ||
           pos.pieceBitboards[side][pieceTypeIndex(side == WHITE ? W_ROOK : B_ROOK)] != 0 ||
           pos.pieceBitboards[side][pieceTypeIndex(side == WHITE ? W_QUEEN : B_QUEEN)] != 0;
}

struct CompletedState {
    std::set<uint64_t> indices;
    uint64_t resultBytes = 0;
    uint64_t mateBytes = 0;
};

CompletedState loadCompleted(const std::string& path) {
    CompletedState result;
    std::ifstream input(path);
    if (!input) return result;
    std::string line;
    while (std::getline(input, line)) {
        std::istringstream fields(trim(line));
        std::string indexText, resultBytesText, mateBytesText, extra;
        fields >> indexText >> resultBytesText >> mateBytesText >> extra;
        uint64_t index = 0, positionBytes = 0, mateBytes = 0;
        if (!extra.empty() || !parseUint64(indexText, index) || !parseUint64(resultBytesText, positionBytes) ||
            !parseUint64(mateBytesText, mateBytes)) {
            throw std::runtime_error("invalid completed journal line: " + line);
        }
        if (!result.indices.insert(index).second) throw std::runtime_error("duplicate completed index: " + indexText);
        result.resultBytes += positionBytes;
        result.mateBytes += mateBytes;
    }
    return result;
}

std::string formatFiniteMoves(const std::string& fen, int staticEval, const std::vector<MoveRecord>& moves) {
    std::ostringstream output;
    for (const MoveRecord& move : moves) {
        output << "{\"fen\":\"" << jsonEscape(fen) << "\",\"static_eval\":" << staticEval
               << ",\"move\":\"" << move.move << "\",\"moving_piece\":\"" << move.movingPiece
               << "\",\"move_score\":" << move.score << "}\n";
    }
    return output.str();
}

std::string formatMates(const std::string& fen, int staticEval, const std::vector<MateRecord>& mates) {
    std::ostringstream output;
    for (const MateRecord& move : mates) {
        output << "{\"fen\":\"" << jsonEscape(fen) << "\",\"static_eval\":" << staticEval
               << ",\"move\":\"" << move.move << "\",\"moving_piece\":\"" << move.movingPiece
               << "\",\"move_score\":" << move.score << ",\"mate_plies\":" << move.matePlies
               << ",\"outcome\":\"" << move.outcome << "\"}\n";
    }
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
        const auto verifyAndTrim = [](const std::string& path, uint64_t expectedBytes) {
            const uint64_t actualBytes = std::filesystem::exists(path) ? std::filesystem::file_size(path) : 0;
            if (actualBytes < expectedBytes) throw std::runtime_error("output is shorter than the completed journal: " + path);
            if (actualBytes != expectedBytes) std::filesystem::resize_file(path, expectedBytes);
        };
        verifyAndTrim(options.resultsPath, completed.resultBytes);
        verifyAndTrim(options.matesPath, completed.mateBytes);
        std::ofstream results(options.resultsPath, std::ios::app);
        std::ofstream mates(options.matesPath, std::ios::app);
        std::ofstream completedOut(options.completedPath, std::ios::app);
        if (!results || !mates || !completedOut) throw std::runtime_error("failed to open run outputs for append");

        SearchParameters parameters{};
        parameters.futilityMargins.fill(0);
        parameters.futilityMaxDepth = options.targetDepth - 1;
        for (std::size_t i = 0; i < options.previousMargins.size(); i++) parameters.futilityMargins[i + 1] = options.previousMargins[i];

        uint64_t index = 0, done = 0, parentIneligible = 0, bestMoveIneligible = 0, finite = 0, mateCount = 0;
        std::string fen;
        while (std::getline(input, fen)) {
            fen = trim(fen);
            if (fen.empty()) continue;
            index++;
            if (completed.indices.count(index)) { done++; continue; }

            Position position = parseFEN(fen);
            resetDrawHistory(position);
            const int staticEval = evaluate(position);
            std::vector<MoveRecord> finiteMoves;
            std::vector<MateRecord> mateMoves;
            if (inCheck(position, position.sideToMove) || !hasNonPawnMaterial(position, position.sideToMove)) {
                parentIneligible++;
            } else {
                SearchLimits limits{};
                limits.depth = options.targetDepth;
                limits.parameters = parameters;
                limits.isolateTranspositionTable = true;
                const SearchResult result = searchBestMove(position, limits);
                if (!result.completed || !result.hasMove) {
                    throw std::runtime_error("normal search did not complete for input index " + std::to_string(index));
                }
                const Move& bestMove = result.bestMove;
                const Piece piece = pieceAt(position, bestMove.from);
                UndoState undoState;
                doMove(position, bestMove, undoState);
                const bool givesCheck = inCheck(position, position.sideToMove);
                undo(position, bestMove, undoState);
                if (!quietMove(position, bestMove) || givesCheck) {
                    bestMoveIneligible++;
                } else {
                    MoveRecord record{moveToUCI(bestMove), pieceSymbol(piece), result.score};
                    if (isMateScore(result.score)) {
                        mateMoves.push_back({record.move, record.movingPiece, record.score, mateDistancePlies(result.score),
                                             result.score > 0 ? "win" : "loss"});
                    } else {
                        finiteMoves.push_back(record);
                    }
                }
            }

            const std::string finiteOutput = formatFiniteMoves(fen, staticEval, finiteMoves);
            const std::string mateOutput = formatMates(fen, staticEval, mateMoves);
            results << finiteOutput;
            mates << mateOutput;
            results.flush(); mates.flush();
            completedOut << index << ' ' << finiteOutput.size() << ' ' << mateOutput.size() << '\n';
            completedOut.flush();
            done++; finite += finiteMoves.size(); mateCount += mateMoves.size();
            if (done % options.reportEvery == 0) {
                std::cout << "Futility-margin progress: completed " << done << ", quiet best moves " << finite
                          << ", quiet best mates " << mateCount << ", parent-ineligible " << parentIneligible
                          << ", best-move-ineligible " << bestMoveIneligible << "\n";
            }
        }
        std::cout << "Futility-margin complete: positions " << done << ", quiet best moves " << finite
                  << ", quiet best mates " << mateCount << ", parent-ineligible " << parentIneligible
                  << ", best-move-ineligible " << bestMoveIneligible << "\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "fatal: " << error.what() << '\n';
        return 1;
    }
}
