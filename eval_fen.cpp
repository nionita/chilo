#include "engine.h"

#include <iostream>
#include <string>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: ./eval_fen \"<fen>\" [more_fens...]\n";
        return 1;
    }

    for (int i = 1; i < argc; ++i) {
        const std::string fen = argv[i];
        Position pos = parseFEN(fen);
        resetDrawHistory(pos);
        std::cout << evaluate(pos) << "\n";
    }
    return 0;
}
