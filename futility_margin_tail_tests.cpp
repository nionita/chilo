#define FUTILITY_MARGIN_TAIL_TEST
#include "futility_margin_tail.cpp"

#include <iostream>
#include <sstream>

namespace {

using futility_margin_tail::Options;
using futility_margin_tail::Record;

bool check(bool condition, const char* description) {
    if (condition) return true;
    std::cerr << "FAILED: " << description << '\n';
    return false;
}

Record record(const std::string& fen, int staticEval, const std::string& move, char piece, int moveScore) {
    Record result;
    result.fen = fen;
    result.staticEval = staticEval;
    result.move = move;
    result.movingPiece = piece;
    result.moveScore = moveScore;
    result.delta = moveScore - staticEval;
    return result;
}

std::string json(const Record& item) {
    std::ostringstream output;
    output << "{\"fen\":\"" << item.fen << "\",\"static_eval\":" << item.staticEval
           << ",\"move\":\"" << item.move << "\",\"moving_piece\":\"" << item.movingPiece
           << "\",\"move_score\":" << item.moveScore << "}\n";
    return output.str();
}

}  // namespace

int main() {
    bool ok = true;
    const std::string whitePassed = "4k3/8/8/3P4/8/8/8/4K3 w - - 0 1";
    const std::string whiteDoublePassed = "4k3/8/8/8/8/8/3P4/4K3 w - - 0 1";
    const std::string whiteBlocked = "4k3/2p5/8/3P4/8/8/8/4K3 w - - 0 1";
    const std::string blackPassed = "4k3/8/8/8/3p4/8/8/4K3 b - - 0 1";
    const std::string blackBlocked = "4k3/8/8/8/3p4/4P3/8/4K3 b - - 0 1";
    const std::string rookMove = "4k3/8/8/8/8/8/8/4K2R w - - 0 1";

    int rank = 0;
    ok &= check(futility_margin_tail::isPassedPawnAdvance(parseFEN(whitePassed), record(whitePassed, 0, "d5d6", 'P', 1), rank) && rank == 6,
                "white passed pawn advance is recognized at its sixth rank");
    ok &= check(futility_margin_tail::isPassedPawnAdvance(parseFEN(whiteDoublePassed), record(whiteDoublePassed, 0, "d2d4", 'P', 1), rank) && rank == 4,
                "passed-pawn double advances are recognized");
    ok &= check(!futility_margin_tail::isPassedPawnAdvance(parseFEN(whiteBlocked), record(whiteBlocked, 0, "d5d6", 'P', 1), rank),
                "opposing pawn ahead on adjacent file blocks white passed status");
    ok &= check(futility_margin_tail::isPassedPawnAdvance(parseFEN(blackPassed), record(blackPassed, 0, "d4d3", 'p', 1), rank) && rank == 6,
                "black relative destination rank is measured from Black's side");
    ok &= check(!futility_margin_tail::isPassedPawnAdvance(parseFEN(blackBlocked), record(blackBlocked, 0, "d4d3", 'p', 1), rank),
                "opposing pawn ahead on adjacent file blocks black passed status");
    ok &= check(!futility_margin_tail::isPassedPawnAdvance(parseFEN(rookMove), record(rookMove, 0, "h1h2", 'R', 1), rank),
                "non-pawn moves never match");

    const std::string blackSeventh = "4k3/8/8/8/8/3p4/8/4K3 b - - 0 1";
    std::istringstream input(
        json(record(blackSeventh, 221, "d3d2", 'p', 749)) +
        json(record(whiteBlocked, 0, "d5d6", 'P', 600)) +
        json(record(blackPassed, 100, "d4d3", 'p', 500)) +
        json(record(rookMove, 0, "h1h2", 'R', 700)));
    Options options;
    options.passedPawnMinDestinationRank = 7;
    options.topCount = 20;
    const futility_margin_tail::Report report = futility_margin_tail::scan(input, options);
    ok &= check(report.records == 4 && report.positiveRecords == 4, "scanner counts all finite positive records");
    ok &= check(report.excludedRecords == 1 && report.excludedPositiveRecords == 1, "seventh-rank passed pawn is excluded");
    ok &= check(!report.top.empty() && report.top.front().move == "h1h2" && report.top.front().delta == 700,
                "top result is descending after exclusion");

    std::istringstream staticEvalInput(
        json(record(rookMove, -401, "h1h2", 'R', 99)) +
        json(record(whitePassed, -400, "d5d6", 'P', 10)) +
        json(record(blackPassed, 400, "d4d3", 'p', 500)) +
        json(record(blackBlocked, 401, "d4d3", 'p', 30)));
    Options staticEvalOptions;
    staticEvalOptions.staticEvalLimitProvided = true;
    staticEvalOptions.staticEvalLimit = 400;
    const futility_margin_tail::Report staticEvalReport = futility_margin_tail::scan(staticEvalInput, staticEvalOptions);
    ok &= check(staticEvalReport.staticEvalTooLowRecords == 2 && staticEvalReport.staticEvalTooHighRecords == 1 &&
                    staticEvalReport.excludedRecords == 3,
                "static evaluation limit excludes both out-of-range tails");
    ok &= check(!staticEvalReport.top.empty() && staticEvalReport.top.front().staticEval == 400,
                "the static-evaluation interval is -limit exclusive and +limit inclusive");

    if (!ok) return 1;
    std::cout << "futility_margin_tail tests passed\n";
    return 0;
}
