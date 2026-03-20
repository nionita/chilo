#ifndef ENGINE_H
#define ENGINE_H

#include <cstdint>
#include <string>

#include "chess_position.h"
#include "chess_tables.h"

bool attacked(const Position& pos, int sq, Color att);
bool inCheck(const Position& pos, Color col);

int genMoves(const Position& pos, Move* moves);
int genLegalMoves(const Position& pos, Move* moves);
bool hasAnyLegalMove(const Position& pos);
bool isCheckmate(const Position& pos);
bool isStalemate(const Position& pos);

bool parseUCIMove(const Position& pos, const std::string& uci, Move& outMove);
bool applyUCIMove(Position& pos, const std::string& uci);

void doMove(Position& pos, const Move& mv, UndoState& undo);
void undo(Position& pos, const Move& mv, const UndoState& undo);

int evaluate(const Position& pos);

struct SearchLimits {
    int depth;
    int movetimeMs;
};

struct SearchResult {
    Move bestMove;
    int score;
    int depth;
    uint64_t nodes;
    bool completed;
    bool hasMove;
};

SearchResult searchBestMove(Position& pos, const SearchLimits& limits);
void requestSearchStop();

uint64_t perft(Position& pos, int d);
uint64_t perftDivide(Position& pos, int d);

#endif
