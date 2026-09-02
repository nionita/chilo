#include "engine.h"

#include <iostream>
#include <string>
#include <vector>

namespace {

struct CollectedSites {
    std::vector<std::string> fens;
};

void collect(const std::string& fen, void* userData) {
    static_cast<CollectedSites*>(userData)->fens.push_back(fen);
}

bool runSearch(const std::string& fen, int maxDepth, int minBeta, CollectedSites& sites) {
    Position position = parseFEN(fen);
    resetDrawHistory(position);
    SearchLimits limits{};
    limits.depth = 4;
    limits.parameters.futilityMaxDepth = 0;
    limits.isolateTranspositionTable = true;
    limits.futilitySiteMaxDepth = maxDepth;
    limits.futilitySiteMinBeta = minBeta;
    limits.futilitySiteCallback = collect;
    limits.futilitySiteUserData = &sites;
    SearchResult result = searchBestMove(position, limits);
    return result.completed;
}

bool check(bool condition, const char* description) {
    if (condition) return true;
    std::cerr << "FAILED: " << description << '\n';
    return false;
}

}  // namespace

int main() {
    const std::string startFen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
    bool ok = true;

    CollectedSites ordinary;
    ok &= check(runSearch(startFen, 3, -30000, ordinary), "ordinary search completes");
    ok &= check(!ordinary.fens.empty(), "eligible non-root, non-PV quiet sites are reported");
    for (const std::string& fen : ordinary.fens) {
        ok &= check(fen.find(" w ") != std::string::npos || fen.find(" b ") != std::string::npos,
                    "reported site is a FEN");
    }

    CollectedSites disabled;
    ok &= check(runSearch(startFen, 0, -30000, disabled), "disabled-depth search completes");
    ok &= check(disabled.fens.empty(), "zero collection depth reports no sites");

    CollectedSites betaRejected;
    ok &= check(runSearch(startFen, 3, 30000, betaRejected), "high-beta-floor search completes");
    ok &= check(betaRejected.fens.empty(), "strict beta floor rejects every site at the search infinity");

    CollectedSites pawnOnly;
    ok &= check(runSearch("4k3/8/8/8/8/8/4K3/8 w - - 0 1", 3, -30000, pawnOnly),
                "king-only search completes");
    ok &= check(pawnOnly.fens.empty(), "side without non-pawn material reports no sites");

    if (!ok) return 1;
    std::cout << "futility_site_collect tests passed\n";
    return 0;
}
