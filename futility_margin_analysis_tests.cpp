#include "engine.h"

#include <iostream>

namespace {
bool check(bool condition, const char* description) {
    if (condition) return true;
    std::cerr << "FAILED: " << description << '\n';
    return false;
}

SearchResult traceSearch(Position& position, FutilityMarginSiteResult& trace) {
    SearchLimits limits{};
    limits.depth = 1;
    limits.isolateTranspositionTable = true;
    limits.futilityMarginSiteResult = &trace;
    return searchBestMove(position, limits);
}
}  // namespace

int main() {
    bool ok = true;
    FutilityMarginSiteResult trace{};
    Position opening = parseFEN("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1");
    const SearchResult openingResult = traceSearch(opening, trace);
    ok &= check(openingResult.completed && trace.completed, "trace marks a completed ordinary PVS iteration");
    ok &= check(!trace.hasPrefix && !trace.hasUsefulQuiet, "a root with no capture or promotion has no rescue event");

    trace = FutilityMarginSiteResult{};
    Position capture = parseFEN("rnbqkbnr/pppp1ppp/8/4p3/3PP3/8/PPP2PPP/RNBQKBNR b KQkq - 0 2");
    const SearchResult captureResult = traceSearch(capture, trace);
    ok &= check(captureResult.completed && trace.completed, "capture-prefix PVS completes");
    ok &= check(trace.hasPrefix && trace.prefixMoveCount >= 1, "ordB trace retains its non-quiet prefix");
    ok &= check(moveToUCI(trace.prefixMove) == "e5d4", "the non-negative pawn capture is the prefix move");
    ok &= check(!trace.hasUsefulQuiet || trace.quietScore > trace.prefixScore,
                "any retained quiet event strictly improves the prefix alpha");

    if (!ok) return 1;
    std::cout << "futility_margin_analysis tests passed\n";
    return 0;
}
