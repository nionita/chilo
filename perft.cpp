#include "chess.h"

uint64_t perftDivide(Position& pos, int d);

int main(int argc, char* argv[]) {
    if (argc < 3) { std::cerr << "Usage: " << argv[0] << " <fen> <depth> [divide]\n"; return 1; }
    Position pos = parseFEN(argv[1]);
    int maxD = std::stoi(argv[2]);
    bool divide = argc > 3 && std::string(argv[3]) == "divide";
    if (divide) {
        uint64_t total = perftDivide(pos, maxD);
        std::cout << "Depth " << maxD << ": " << total << "\n";
    } else {
        for (int d = 1; d <= maxD; d++) {
            uint64_t total = perft(pos, d);
            std::cout << "Depth " << d << ": " << total << "\n";
        }
    }
    return 0;
}
