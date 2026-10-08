#pragma once
#include <array>
#include <cstdint>
#include "third_party/json.hpp"

namespace matchplay {
struct SprtSettings {
    double elo0 = 0, elo1 = 2, alpha = 0.05, beta = 0.05;
};
struct PairStats {
    // Candidate A's pair score: 0, 0.5, 1, 1.5, 2.
    std::array<uint64_t, 5> bins{};
    uint64_t wins = 0, draws = 0, losses = 0, wl = 0, dd = 0;
    void addPair(int first, int second); // game scores doubled: 0, 1, 2
    uint64_t pairs() const;
};
double normalizedLLR(const PairStats&, const SprtSettings&);
nlohmann::json statistics(const PairStats&, const SprtSettings&);
}
