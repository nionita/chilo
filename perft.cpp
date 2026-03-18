#include "chess.h"
#include <chrono>

uint64_t perftDivide(Position& pos, int d);

uint64_t computeNps(uint64_t nodes, double seconds) {
    return seconds > 0.0 ? static_cast<uint64_t>(nodes / seconds) : 0;
}

int main(int argc, char* argv[]) {
    if (argc < 3) { std::cerr << "Usage: " << argv[0] << " <fen> <depth> [divide]\n"; return 1; }
    Position pos = parseFEN(argv[1]);
    int maxD = std::stoi(argv[2]);
    bool divide = argc > 3 && std::string(argv[3]) == "divide";
    if (divide) {
        auto start = std::chrono::steady_clock::now();
        uint64_t total = perftDivide(pos, maxD);
        auto end = std::chrono::steady_clock::now();
        double seconds = std::chrono::duration<double>(end - start).count();
        uint64_t nps = computeNps(total, seconds);
        std::cout << "Depth " << maxD << ": " << total
                  << " (" << seconds << " s, " << nps << " nps)\n";
    } else {
        for (int d = 1; d <= maxD; d++) {
            auto start = std::chrono::steady_clock::now();
            uint64_t total = perft(pos, d);
            auto end = std::chrono::steady_clock::now();
            double seconds = std::chrono::duration<double>(end - start).count();
            uint64_t nps = computeNps(total, seconds);
            std::cout << "Depth " << d << ": " << total
                      << " (" << seconds << " s, " << nps << " nps)\n";
        }
    }
    return 0;
}
