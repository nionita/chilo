#include "chess.h"

int main(int argc, char* argv[]) {
    if (argc < 3) { std::cerr << "Usage: " << argv[0] << " <fen> <depth>\n"; return 1; }
    Position pos = parseFEN(argv[1]);
    int maxD = std::stoi(argv[2]);
    for (int d = 1; d <= maxD; d++) std::cout << "Depth " << d << ": " << perft(pos, d) << "\n";
    return 0;
}
