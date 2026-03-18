#include "chess.h"

uint64_t perftDivide(Position& pos, int d);

int main(int argc, char* argv[]) {
    if (argc < 3) { std::cerr << "Usage: " << argv[0] << " <fen> <depth> [divide]\n"; return 1; }
    Position pos = parseFEN(argv[1]);
    int maxD = std::stoi(argv[2]);
    bool divide = argc > 3 && std::string(argv[3]) == "divide";
    for (int d = 1; d <= maxD; d++) {
        if (divide && d > 1) break;
        uint64_t total = divide ? perftDivide(pos, d) : perft(pos, d);
        std::cout << "Depth " << d << ": " << total << "\n";
    }
    return 0;
}
