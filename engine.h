#ifndef ENGINE_H
#define ENGINE_H

#include <cstdint>

#include "chess_position.h"
#include "chess_tables.h"

bool attacked(const Position& pos, int sq, Color att);
bool inCheck(const Position& pos, Color col);

int genMoves(const Position& pos, Move* moves);

void doMove(Position& pos, const Move& mv, UndoState& undo);
void undo(Position& pos, const Move& mv, const UndoState& undo);

uint64_t perft(Position& pos, int d);
uint64_t perftDivide(Position& pos, int d);

#endif
