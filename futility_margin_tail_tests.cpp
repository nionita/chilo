#define FUTILITY_MARGIN_TAIL_TEST
#include "futility_margin_tail.cpp"

#include <iostream>
#include <sstream>

namespace {
using futility_margin_tail::Options;
using futility_margin_tail::Record;

bool check(bool value, const char* what) {
    if (value) return true;
    std::cerr << "FAILED: " << what << '\n'; return false;
}

Record record(const std::string& fen, int staticEval, const std::string& prefix, int prefixScore,
              const std::string& quiet, char piece, int quietScore) {
    Record r; r.fen = fen; r.staticEval = staticEval; r.prefixMove = prefix; r.prefixScore = prefixScore;
    r.quietMove = quiet; r.quietPiece = piece; r.quietScore = quietScore; r.quietGain = quietScore - prefixScore; return r;
}

std::string json(const Record& r) {
    std::ostringstream out;
    out << "{\"schema\":\"chilo.futility_margin_rescue.v1\",\"fen\":\"" << r.fen
        << "\",\"static_eval\":" << r.staticEval << ",\"prefix_move\":\"" << r.prefixMove
        << "\",\"prefix_score\":" << r.prefixScore << ",\"quiet_move\":\"" << r.quietMove
        << "\",\"quiet_piece\":\"" << r.quietPiece << "\",\"quiet_score\":" << r.quietScore
        << ",\"quiet_gain\":" << r.quietGain << "}\n";
    return out.str();
}
}  // namespace

int main() {
    bool ok = true;
    const std::string whitePassed = "4k3/8/8/3P4/8/8/8/4K3 w - - 0 1";
    const std::string blackPassed = "4k3/8/8/8/3p4/8/8/4K3 b - - 0 1";
    const std::string blocked = "4k3/2p5/8/3P4/8/8/8/4K3 w - - 0 1";
    const std::string rookMove = "4k3/8/8/8/8/8/8/4K2R w - - 0 1";

    int rank = 0;
    ok &= check(futility_margin_tail::isPassedPawnAdvance(parseFEN(whitePassed), record(whitePassed, 0, "e1e2", 0, "d5d6", 'P', 1), rank) && rank == 6,
                "white passed-pawn quiet advance is recognized");
    ok &= check(futility_margin_tail::isPassedPawnAdvance(parseFEN(blackPassed), record(blackPassed, 0, "e8e7", 0, "d4d3", 'p', 1), rank) && rank == 6,
                "black passed-pawn destination is relative");
    ok &= check(!futility_margin_tail::isPassedPawnAdvance(parseFEN(blocked), record(blocked, 0, "e1e2", 0, "d5d6", 'P', 1), rank),
                "opposing pawn blocks passed status");

    std::istringstream input(
        json(record(whitePassed, 100, "e1e2", 150, "d5d6", 'P', 175)) +   // prune at M=50; exclude as passed to sixth
        json(record(rookMove, -399, "e1e2", -349, "h1h2", 'R', -339)) +   // equality prunes; gain 10 rescue at 10
        json(record(rookMove, 400, "e1e2", 450, "h1h2", 'R', 490)) +       // equality prunes; unrescued 40
        json(record(rookMove, -400, "e1e2", -350, "h1h2", 'R', -340)) +    // static lower boundary is excluded
        json(record(blocked, 401, "e1e2", 500, "d5d6", 'P', 540)));        // static high exclusion
    Options options;
    options.marginProvided = true; options.margin = 50; options.rescueLimit = 10;
    options.passedPawnMinDestinationRank = 6; options.staticEvalLimitProvided = true; options.staticEvalLimit = 400;
    const auto report = futility_margin_tail::scan(input, options);
    ok &= check(report.records == 5 && report.passedPawnExcluded == 1 && report.staticEvalLowExcluded == 1 && report.staticEvalHighExcluded == 1 && report.excluded == 3,
                "predicate filters are counted before margin analysis");
    ok &= check(report.remaining == 2 && report.wouldPrune == 2, "margin equality is a prune event");
    ok &= check(report.rescued == 1 && report.unrescued == 1, "rescue equality is accepted and larger loss remains");
    ok &= check(report.top.size() == 1 && report.top.front().quietMove == "h1h2" && report.top.front().quietGain == 40,
                "top ranks remaining local quiet loss");
    Record promotionPrefix = record(rookMove, 0, "a7a8q", 20, "h1h2", 'R', 30);
    std::istringstream promotionInput(json(promotionPrefix));
    const auto promotionReport = futility_margin_tail::scan(promotionInput, options);
    ok &= check(promotionReport.records == 1, "promotion prefixes use five-character UCI notation");
    if (!ok) return 1;
    std::cout << "futility_margin_tail tests passed\n";
    return 0;
}
