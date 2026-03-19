#ifndef CHESS_H
#define CHESS_H

#include <iostream>
#include <string>
#include <vector>
#include <cstdint>
#include <cassert>
#include <cctype>
#include <cstdlib>

enum Piece { EMPTY, W_PAWN, W_KNIGHT, W_BISHOP, W_ROOK, W_QUEEN, W_KING,
             B_PAWN, B_KNIGHT, B_BISHOP, B_ROOK, B_QUEEN, B_KING };
enum Color { WHITE, BLACK };

constexpr int PIECE_TYPE_COUNT = 6;
constexpr int MAX_PIECES_PER_TYPE = 10;
constexpr int MAX_MOVES = 256;

struct Move { int from, to; Piece promotion; bool isEnPassant, isCastle, isDoublePush; };

struct Position {
    Piece board[64];
    Color sideToMove;
    bool castling[4];
    int enPassant;
    int halfMove, fullMove;
    int kingSq[2];
    uint64_t pieceBitboards[2][PIECE_TYPE_COUNT];
    uint64_t occupancy[2];
    uint64_t occupancyAll;
};

int R(int s) { return s >> 3; }
int F(int s) { return s & 7; }
uint64_t bitAt(int sq) {
    assert(sq >= 0 && sq < 64);
    return 1ULL << sq;
}
int pt(Piece p) {
    if (p == EMPTY) return 0;
    if (p == W_PAWN || p == B_PAWN) return 1;
    if (p == W_KNIGHT || p == B_KNIGHT) return 2;
    if (p == W_BISHOP || p == B_BISHOP) return 3;
    if (p == W_ROOK || p == B_ROOK) return 4;
    if (p == W_QUEEN || p == B_QUEEN) return 5;
    return 6;
}
bool wh(Piece p) { return p >= W_PAWN && p <= W_KING; }
bool bl(Piece p) { return p >= B_PAWN && p <= B_KING; }
bool sameCol(Piece a, Piece b) { return (wh(a) && wh(b)) || (bl(a) && bl(b)); }
Color pieceColor(Piece p) { assert(p != EMPTY); return wh(p) ? WHITE : BLACK; }
int pieceTypeIndex(Piece p) { assert(p != EMPTY); return pt(p) - 1; }

struct AttackTables {
    uint64_t knight[64];
    uint64_t king[64];
    uint64_t pawnAttackers[2][64];
};

AttackTables makeAttackTables() {
    AttackTables t = {};
    int knightDr[] = {-2, -2, -1, -1, 1, 1, 2, 2};
    int knightDf[] = {-1, 1, -2, 2, -2, 2, -1, 1};
    int kingDr[] = {-1, -1, -1, 0, 0, 1, 1, 1};
    int kingDf[] = {-1, 0, 1, -1, 1, -1, 0, 1};
    for (int sq = 0; sq < 64; sq++) {
        int r = R(sq), f = F(sq);
        for (int i = 0; i < 8; i++) {
            int nr = r + knightDr[i], nf = f + knightDf[i];
            if (nr >= 0 && nr < 8 && nf >= 0 && nf < 8) t.knight[sq] |= bitAt(nr * 8 + nf);
        }
        for (int i = 0; i < 8; i++) {
            int nr = r + kingDr[i], nf = f + kingDf[i];
            if (nr >= 0 && nr < 8 && nf >= 0 && nf < 8) t.king[sq] |= bitAt(nr * 8 + nf);
        }
        if (r > 0 && f > 0) t.pawnAttackers[WHITE][sq] |= bitAt((r - 1) * 8 + (f - 1));
        if (r > 0 && f < 7) t.pawnAttackers[WHITE][sq] |= bitAt((r - 1) * 8 + (f + 1));
        if (r < 7 && f > 0) t.pawnAttackers[BLACK][sq] |= bitAt((r + 1) * 8 + (f - 1));
        if (r < 7 && f < 7) t.pawnAttackers[BLACK][sq] |= bitAt((r + 1) * 8 + (f + 1));
    }
    return t;
}

const AttackTables& attackTables() {
    static const AttackTables tables = makeAttackTables();
    return tables;
}

void initPosition(Position& p) {
    for (int i = 0; i < 64; i++) p.board[i] = EMPTY;
    for (int c = 0; c < 2; c++) {
        p.kingSq[c] = -1;
        p.occupancy[c] = 0;
        for (int t = 0; t < PIECE_TYPE_COUNT; t++) {
            p.pieceBitboards[c][t] = 0;
        }
    }
    p.occupancyAll = 0;
}

void addPiece(Position& pos, int sq, Piece pc) {
    assert(sq >= 0 && sq < 64);
    assert(pc != EMPTY);
    assert(pos.board[sq] == EMPTY);
    Color color = pieceColor(pc);
    int type = pieceTypeIndex(pc);
    pos.board[sq] = pc;
    pos.pieceBitboards[color][type] |= bitAt(sq);
    pos.occupancy[color] |= bitAt(sq);
    pos.occupancyAll |= bitAt(sq);
    if (type == 5) pos.kingSq[color] = sq;
}

void removePiece(Position& pos, int sq) {
    assert(sq >= 0 && sq < 64);
    Piece pc = pos.board[sq];
    assert(pc != EMPTY);
    Color color = pieceColor(pc);
    int type = pieceTypeIndex(pc);
    pos.pieceBitboards[color][type] &= ~bitAt(sq);
    pos.occupancy[color] &= ~bitAt(sq);
    pos.occupancyAll &= ~bitAt(sq);
    pos.board[sq] = EMPTY;
    if (type == 5) pos.kingSq[color] = -1;
}

void movePiece(Position& pos, int from, int to) {
    assert(from >= 0 && from < 64);
    assert(to >= 0 && to < 64);
    Piece pc = pos.board[from];
    assert(pc != EMPTY);
    assert(pos.board[to] == EMPTY);
    Color color = pieceColor(pc);
    int type = pieceTypeIndex(pc);
    uint64_t fromBit = bitAt(from);
    uint64_t toBit = bitAt(to);
    pos.board[to] = pc;
    pos.board[from] = EMPTY;
    pos.pieceBitboards[color][type] ^= fromBit | toBit;
    pos.occupancy[color] ^= fromBit | toBit;
    pos.occupancyAll ^= fromBit | toBit;
    if (type == 5) pos.kingSq[color] = to;
}

bool bitboardsConsistent(const Position& pos) {
    uint64_t expectedPieces[2][PIECE_TYPE_COUNT] = {};
    uint64_t expectedOcc[2] = {};
    for (int sq = 0; sq < 64; sq++) {
        Piece pc = pos.board[sq];
        if (pc == EMPTY) continue;
        Color color = pieceColor(pc);
        int type = pieceTypeIndex(pc);
        uint64_t bit = bitAt(sq);
        expectedPieces[color][type] |= bit;
        expectedOcc[color] |= bit;
    }
    for (int color = 0; color < 2; color++) {
        uint64_t combined = 0;
        for (int type = 0; type < PIECE_TYPE_COUNT; type++) {
            if (pos.pieceBitboards[color][type] != expectedPieces[color][type]) return false;
            combined |= pos.pieceBitboards[color][type];
        }
        if (pos.occupancy[color] != expectedOcc[color]) return false;
        if (combined != pos.occupancy[color]) return false;
    }
    return pos.occupancyAll == (pos.occupancy[WHITE] | pos.occupancy[BLACK]);
}

bool representationConsistent(const Position& pos) {
    if (!bitboardsConsistent(pos)) return false;
    for (int color = 0; color < 2; color++) {
        int kingSq = pos.kingSq[color];
        if (kingSq < 0 || kingSq >= 64) return false;
        Piece king = color == WHITE ? W_KING : B_KING;
        if (pos.board[kingSq] != king) return false;
        if (pos.pieceBitboards[color][pieceTypeIndex(king)] != bitAt(kingSq)) return false;
    }
    return true;
}

bool positionsEqual(const Position& a, const Position& b) {
    for (int i = 0; i < 64; i++) if (a.board[i] != b.board[i]) return false;
    if (a.sideToMove != b.sideToMove) return false;
    for (int i = 0; i < 4; i++) if (a.castling[i] != b.castling[i]) return false;
    if (a.enPassant != b.enPassant) return false;
    if (a.halfMove != b.halfMove) return false;
    if (a.fullMove != b.fullMove) return false;
    if (a.kingSq[WHITE] != b.kingSq[WHITE] || a.kingSq[BLACK] != b.kingSq[BLACK]) return false;
    for (int color = 0; color < 2; color++) {
        if (a.occupancy[color] != b.occupancy[color]) return false;
        for (int type = 0; type < PIECE_TYPE_COUNT; type++) {
            if (a.pieceBitboards[color][type] != b.pieceBitboards[color][type]) return false;
        }
    }
    if (a.occupancyAll != b.occupancyAll) return false;
    return representationConsistent(a) && representationConsistent(b);
}

uint8_t packCastling(const Position& pos) {
    return (pos.castling[0] ? 1 : 0) |
           (pos.castling[1] ? 2 : 0) |
           (pos.castling[2] ? 4 : 0) |
           (pos.castling[3] ? 8 : 0);
}

void restoreCastling(Position& pos, uint8_t rights) {
    pos.castling[0] = rights & 1;
    pos.castling[1] = rights & 2;
    pos.castling[2] = rights & 4;
    pos.castling[3] = rights & 8;
}

void clearCastlingForSquare(Position& pos, int sq) {
    switch (sq) {
        case 0: pos.castling[1] = false; break;
        case 7: pos.castling[0] = false; break;
        case 56: pos.castling[3] = false; break;
        case 63: pos.castling[2] = false; break;
    }
}

Position parseFEN(const std::string& f) {
    Position p;
    initPosition(p);
    std::vector<std::string> p2;
    std::string cur;
    for (char ch : f) {
        if (ch == ' ') {
            p2.push_back(cur);
            cur.clear();
        } else {
            cur.push_back(ch);
        }
    }
    p2.push_back(cur);
    assert(p2.size() >= 4);
    int rank = 7, file = 0;
    for (char ch : p2[0]) {
        if (ch == '/') { rank--; file = 0; continue; }
        if (ch >= '1' && ch <= '8') { file += ch - '0'; continue; }
        int s = rank * 8 + file;
        if (ch == 'p') addPiece(p, s, B_PAWN);
        else if (ch == 'n') addPiece(p, s, B_KNIGHT);
        else if (ch == 'b') addPiece(p, s, B_BISHOP);
        else if (ch == 'r') addPiece(p, s, B_ROOK);
        else if (ch == 'q') addPiece(p, s, B_QUEEN);
        else if (ch == 'k') addPiece(p, s, B_KING);
        else if (ch == 'P') addPiece(p, s, W_PAWN);
        else if (ch == 'N') addPiece(p, s, W_KNIGHT);
        else if (ch == 'B') addPiece(p, s, W_BISHOP);
        else if (ch == 'R') addPiece(p, s, W_ROOK);
        else if (ch == 'Q') addPiece(p, s, W_QUEEN);
        else if (ch == 'K') addPiece(p, s, W_KING);
        file++;
    }
    p.sideToMove = p2[1] == "w" ? WHITE : BLACK;
    p.castling[0] = p.castling[1] = p.castling[2] = p.castling[3] = false;
    if (p2[2] != "-") for (char ch : p2[2]) {
        if (ch == 'K') p.castling[0] = true;
        if (ch == 'Q') p.castling[1] = true;
        if (ch == 'k') p.castling[2] = true;
        if (ch == 'q') p.castling[3] = true;
    }
    p.enPassant = -1;
    if (p2[3] != "-") p.enPassant = (p2[3][1] - '1') * 8 + (p2[3][0] - 'a');
    p.halfMove = 0;
    p.fullMove = 1;
    assert(p.kingSq[WHITE] != -1 && p.kingSq[BLACK] != -1);
    return p;
}

bool rayAttacked(const Position& pos, int sq, Color att, int dr, int df, Piece sliderA, Piece sliderB) {
    int r = R(sq) + dr, f = F(sq) + df;
    Piece attSliderA = att == WHITE ? sliderA : static_cast<Piece>(sliderA + 6);
    Piece attSliderB = att == WHITE ? sliderB : static_cast<Piece>(sliderB + 6);
    while (r >= 0 && r < 8 && f >= 0 && f < 8) {
        int target = r * 8 + f;
        if (pos.occupancyAll & bitAt(target)) {
            Piece pc = pos.board[target];
            return pc == attSliderA || pc == attSliderB;
        }
        r += dr;
        f += df;
    }
    return false;
}

bool attacked(const Position& pos, int sq, Color att) {
    assert(sq >= 0 && sq < 64);
    const AttackTables& tables = attackTables();
    bool result = false;

    int pawnType = pieceTypeIndex(att == WHITE ? W_PAWN : B_PAWN);
    if (pos.pieceBitboards[att][pawnType] & tables.pawnAttackers[att][sq]) result = true;

    if (!result) {
        int knightType = pieceTypeIndex(att == WHITE ? W_KNIGHT : B_KNIGHT);
        if (pos.pieceBitboards[att][knightType] & tables.knight[sq]) result = true;
    }

    if (!result) {
        int kingType = pieceTypeIndex(att == WHITE ? W_KING : B_KING);
        if (pos.pieceBitboards[att][kingType] & tables.king[sq]) result = true;
    }

    if (!result) {
        result = rayAttacked(pos, sq, att, -1, -1, W_BISHOP, W_QUEEN) ||
                 rayAttacked(pos, sq, att, -1, 1, W_BISHOP, W_QUEEN) ||
                 rayAttacked(pos, sq, att, 1, -1, W_BISHOP, W_QUEEN) ||
                 rayAttacked(pos, sq, att, 1, 1, W_BISHOP, W_QUEEN) ||
                 rayAttacked(pos, sq, att, -1, 0, W_ROOK, W_QUEEN) ||
                 rayAttacked(pos, sq, att, 1, 0, W_ROOK, W_QUEEN) ||
                 rayAttacked(pos, sq, att, 0, -1, W_ROOK, W_QUEEN) ||
                 rayAttacked(pos, sq, att, 0, 1, W_ROOK, W_QUEEN);
    }

    return result;
}

bool inCheck(const Position& pos, Color col) {
    int k = pos.kingSq[col];
    assert(k >= 0 && k < 64);
    return attacked(pos, k, col == WHITE ? BLACK : WHITE);
}

void pushMove(Move* moves, int& count, int from, int to, Piece promotion, bool isEnPassant, bool isCastle, bool isDoublePush) {
    assert(count < MAX_MOVES);
    moves[count++] = {from, to, promotion, isEnPassant, isCastle, isDoublePush};
}

int popLsb(uint64_t& bits) {
    assert(bits != 0);
    int sq = __builtin_ctzll(bits);
    bits &= bits - 1;
    return sq;
}

void genPawnMoves(const Position& pos, Color us, Move* moves, int& count) {
    uint64_t pawns = pos.pieceBitboards[us][pieceTypeIndex(us == WHITE ? W_PAWN : B_PAWN)];
    int dir = us == WHITE ? 1 : -1;
    int start = us == WHITE ? 1 : 6;
    int promo = us == WHITE ? 7 : 0;
    while (pawns) {
        int from = popLsb(pawns);
        int fr = R(from), fc = F(from);
        int nextRank = fr + dir;
        if (nextRank >= 0 && nextRank < 8) {
            int to = nextRank * 8 + fc;
            if (pos.board[to] == EMPTY) {
                if (nextRank == promo) {
                    Piece promos[] = {
                        us == WHITE ? W_QUEEN : B_QUEEN,
                        us == WHITE ? W_ROOK : B_ROOK,
                        us == WHITE ? W_BISHOP : B_BISHOP,
                        us == WHITE ? W_KNIGHT : B_KNIGHT
                    };
                    for (Piece pr : promos) pushMove(moves, count, from, to, pr, false, false, false);
                } else {
                    pushMove(moves, count, from, to, EMPTY, false, false, false);
                    if (fr == start) {
                        int t2 = (fr + 2 * dir) * 8 + fc;
                        if (pos.board[t2] == EMPTY) pushMove(moves, count, from, t2, EMPTY, false, false, true);
                    }
                }
            }
        }
        uint64_t attacks = attackTables().pawnAttackers[us == WHITE ? BLACK : WHITE][from];
        while (attacks) {
            int cap = popLsb(attacks);
            Piece tp = pos.board[cap];
            if (tp != EMPTY && !sameCol(pos.board[from], tp) && pt(tp) != 6) {
                if (R(cap) == promo) {
                    Piece promos[] = {
                        us == WHITE ? W_QUEEN : B_QUEEN,
                        us == WHITE ? W_ROOK : B_ROOK,
                        us == WHITE ? W_BISHOP : B_BISHOP,
                        us == WHITE ? W_KNIGHT : B_KNIGHT
                    };
                    for (Piece pr : promos) pushMove(moves, count, from, cap, pr, false, false, false);
                } else {
                    pushMove(moves, count, from, cap, EMPTY, false, false, false);
                }
            }
            if (pos.enPassant != -1 && cap == pos.enPassant) pushMove(moves, count, from, cap, EMPTY, true, false, false);
        }
    }
}

void genKnightMoves(const Position& pos, Color us, Move* moves, int& count) {
    uint64_t pieces = pos.pieceBitboards[us][pieceTypeIndex(us == WHITE ? W_KNIGHT : B_KNIGHT)];
    uint64_t ownOcc = pos.occupancy[us];
    while (pieces) {
        int from = popLsb(pieces);
        uint64_t targets = attackTables().knight[from] & ~ownOcc;
        while (targets) {
            int to = popLsb(targets);
            Piece tp = pos.board[to];
            if (tp == EMPTY || pt(tp) != 6) pushMove(moves, count, from, to, EMPTY, false, false, false);
        }
    }
}

void genSlidingMoves(const Position& pos, uint64_t pieces, const int* dirs, int dirCount, Move* moves, int& count) {
    while (pieces) {
        int from = popLsb(pieces);
        int fr = R(from), fc = F(from);
        for (int i = 0; i < dirCount; i++) {
            int d = dirs[i];
            for (int to = from + d; ; to += d) {
                if (to < 0 || to >= 64) break;
                if ((d == -9 || d == 9 || d == -7 || d == 7) && std::abs(R(to) - fr) != std::abs(F(to) - fc)) break;
                if (d == -1 && F(to) >= F(from)) break;
                if (d == 1 && F(to) <= F(from)) break;
                if (d == -8 && R(to) >= R(from)) break;
                if (d == 8 && R(to) <= R(from)) break;
                Piece tp = pos.board[to];
                if (tp == EMPTY) pushMove(moves, count, from, to, EMPTY, false, false, false);
                else {
                    if (!sameCol(pos.board[from], tp) && pt(tp) != 6) pushMove(moves, count, from, to, EMPTY, false, false, false);
                    break;
                }
            }
        }
    }
}

void genKingMoves(const Position& pos, Color us, Move* moves, int& count) {
    int from = pos.kingSq[us];
    uint64_t targets = attackTables().king[from] & ~pos.occupancy[us];
    while (targets) {
        int to = popLsb(targets);
        Piece tp = pos.board[to];
        if (tp == EMPTY || pt(tp) != 6) pushMove(moves, count, from, to, EMPTY, false, false, false);
    }
    int fr = R(from), fc = F(from);
    Color them = us == WHITE ? BLACK : WHITE;
    int kr = us == WHITE ? 0 : 7, ki = us == WHITE ? 0 : 2, qi = us == WHITE ? 1 : 3;
    Piece ourRook = us == WHITE ? W_ROOK : B_ROOK;
    if (fr == kr && fc == 4 && pos.castling[ki] && pos.board[kr * 8 + 7] == ourRook) {
        if (pos.board[kr * 8 + 5] == EMPTY && pos.board[kr * 8 + 6] == EMPTY) {
            if (!attacked(pos, kr * 8 + 4, them) && !attacked(pos, kr * 8 + 5, them) && !attacked(pos, kr * 8 + 6, them)) {
                pushMove(moves, count, from, kr * 8 + 6, EMPTY, false, true, false);
            }
        }
    }
    if (fr == kr && fc == 4 && pos.castling[qi] && pos.board[kr * 8 + 0] == ourRook) {
        if (pos.board[kr * 8 + 1] == EMPTY && pos.board[kr * 8 + 2] == EMPTY && pos.board[kr * 8 + 3] == EMPTY) {
            if (!attacked(pos, kr * 8 + 4, them) && !attacked(pos, kr * 8 + 3, them) && !attacked(pos, kr * 8 + 2, them)) {
                pushMove(moves, count, from, kr * 8 + 2, EMPTY, false, true, false);
            }
        }
    }
}

int genMoves(const Position& pos, Move* moves) {
    int count = 0;
    Color us = pos.sideToMove;

    genPawnMoves(pos, us, moves, count);
    genKnightMoves(pos, us, moves, count);

    int bishopDirs[] = {-9, -7, 7, 9};
    int rookDirs[] = {-8, -1, 1, 8};
    uint64_t bishops = pos.pieceBitboards[us][pieceTypeIndex(us == WHITE ? W_BISHOP : B_BISHOP)];
    uint64_t rooks = pos.pieceBitboards[us][pieceTypeIndex(us == WHITE ? W_ROOK : B_ROOK)];
    uint64_t queens = pos.pieceBitboards[us][pieceTypeIndex(us == WHITE ? W_QUEEN : B_QUEEN)];

    genSlidingMoves(pos, bishops, bishopDirs, 4, moves, count);
    genSlidingMoves(pos, rooks, rookDirs, 4, moves, count);
    genSlidingMoves(pos, queens, bishopDirs, 4, moves, count);
    genSlidingMoves(pos, queens, rookDirs, 4, moves, count);

    genKingMoves(pos, us, moves, count);

    return count;
}

void doMove(Position& pos, const Move& mv) {
    assert(mv.from >= 0 && mv.from < 64);
    assert(mv.to >= 0 && mv.to < 64);
    assert(pos.board[mv.from] != EMPTY);

    Piece pc = pos.board[mv.from];
    Piece cap = pos.board[mv.to];

    if (cap != EMPTY) {
        clearCastlingForSquare(pos, mv.to);
        removePiece(pos, mv.to);
    }
    if (mv.isEnPassant) {
        int epR = R(mv.to);
        int capR = pos.sideToMove == WHITE ? epR - 1 : epR + 1;
        int capSq = capR * 8 + F(mv.to);
        assert(pos.board[capSq] == W_PAWN || pos.board[capSq] == B_PAWN);
        removePiece(pos, capSq);
    }

    if (pc == W_KING) {
        pos.castling[0] = false;
        pos.castling[1] = false;
    } else if (pc == B_KING) {
        pos.castling[2] = false;
        pos.castling[3] = false;
    } else if (pc == W_ROOK || pc == B_ROOK) {
        clearCastlingForSquare(pos, mv.from);
    }

    movePiece(pos, mv.from, mv.to);

    if (mv.promotion != EMPTY) {
        assert((mv.promotion >= W_PAWN && mv.promotion <= W_KING) ||
               (mv.promotion >= B_PAWN && mv.promotion <= B_KING));
        removePiece(pos, mv.to);
        addPiece(pos, mv.to, mv.promotion);
    }

    if (mv.isCastle) {
        int rr = R(mv.to);
        if (F(mv.to) == 6) {
            assert(pos.board[rr * 8 + 7] == (rr == 0 ? W_ROOK : B_ROOK));
            movePiece(pos, rr * 8 + 7, rr * 8 + 5);
        } else if (F(mv.to) == 2) {
            assert(pos.board[rr * 8 + 0] == (rr == 0 ? W_ROOK : B_ROOK));
            movePiece(pos, rr * 8 + 0, rr * 8 + 3);
        }
    }

    pos.enPassant = -1;
    if (mv.isDoublePush) {
        int epR = pos.sideToMove == WHITE ? R(mv.from) + 1 : R(mv.from) - 1;
        pos.enPassant = epR * 8 + F(mv.from);
    }
    if (pt(pc) == 1 || cap != EMPTY || mv.isEnPassant) pos.halfMove = 0;
    else pos.halfMove++;
    pos.sideToMove = pos.sideToMove == WHITE ? BLACK : WHITE;
    if (pos.sideToMove == WHITE) pos.fullMove++;
#ifdef CHESS_VALIDATE_STATE
    assert(representationConsistent(pos));
#endif
}

void undo(Position& pos, const Move& mv, Piece cap, int oldHalfMove = 0, int oldFullMove = 1,
          int oldEnPassant = -1, uint8_t oldCastling = 0) {
    assert(mv.from >= 0 && mv.from < 64);
    assert(mv.to >= 0 && mv.to < 64);

    pos.sideToMove = pos.sideToMove == WHITE ? BLACK : WHITE;
    pos.halfMove = oldHalfMove;
    pos.fullMove = oldFullMove;
    pos.enPassant = oldEnPassant;
    restoreCastling(pos, oldCastling);

    if (mv.isCastle) {
        int rr = R(mv.to);
        if (F(mv.to) == 6) {
            assert(pos.board[rr * 8 + 5] == W_ROOK || pos.board[rr * 8 + 5] == B_ROOK);
            movePiece(pos, rr * 8 + 5, rr * 8 + 7);
        } else if (F(mv.to) == 2) {
            assert(pos.board[rr * 8 + 3] == W_ROOK || pos.board[rr * 8 + 3] == B_ROOK);
            movePiece(pos, rr * 8 + 3, rr * 8 + 0);
        }
    }

    if (mv.promotion != EMPTY) {
        removePiece(pos, mv.to);
        addPiece(pos, mv.to, pos.sideToMove == WHITE ? W_PAWN : B_PAWN);
    }

    movePiece(pos, mv.to, mv.from);

    if (mv.isEnPassant) {
        int epR = R(mv.to);
        int capR = pos.sideToMove == WHITE ? epR - 1 : epR + 1;
        int capSq = capR * 8 + F(mv.to);
        Piece restoredPawn = pos.sideToMove == WHITE ? B_PAWN : W_PAWN;
        assert(pos.board[capSq] == EMPTY);
        addPiece(pos, capSq, restoredPawn);
    } else if (cap != EMPTY) {
        assert(pos.board[mv.to] == EMPTY);
        addPiece(pos, mv.to, cap);
    }
#ifdef CHESS_VALIDATE_STATE
    assert(representationConsistent(pos));
#endif
}

uint64_t perft(Position& pos, int d);

std::string moveToUCI(const Move& mv) {
    std::string s;
    s += char('a' + F(mv.from));
    s += char('1' + R(mv.from));
    s += char('a' + F(mv.to));
    s += char('1' + R(mv.to));
    if (mv.promotion != EMPTY) {
        char p = mv.promotion == W_QUEEN || mv.promotion == B_QUEEN ? 'q' :
                 mv.promotion == W_ROOK || mv.promotion == B_ROOK ? 'r' :
                 mv.promotion == W_BISHOP || mv.promotion == B_BISHOP ? 'b' : 'n';
        s += p;
    }
    return s;
}

uint64_t perftDivide(Position& pos, int d) {
    Move moves[MAX_MOVES];
    int moveCount = genMoves(pos, moves);
    uint64_t total = 0;
    Color us = pos.sideToMove;
#ifdef CHESS_VALIDATE_STATE
    Position startPos = pos;
#endif
    for (int i = 0; i < moveCount; i++) {
        const Move& mv = moves[i];
        Piece cap = pos.board[mv.to];
        int oldHalfMove = pos.halfMove;
        int oldFullMove = pos.fullMove;
        int oldEnPassant = pos.enPassant;
        uint8_t oldCastling = packCastling(pos);
        doMove(pos, mv);
        if (!inCheck(pos, us)) {
            uint64_t count = perft(pos, d - 1);
            std::cout << moveToUCI(mv) << ": " << count << "\n";
            total += count;
        }
        undo(pos, mv, cap, oldHalfMove, oldFullMove, oldEnPassant, oldCastling);
#ifdef CHESS_VALIDATE_STATE
        assert(positionsEqual(startPos, pos));
#endif
    }
    return total;
}

uint64_t perft(Position& pos, int d) {
    if (d == 0) return 1;
    Move moves[MAX_MOVES];
    int moveCount = genMoves(pos, moves);
    uint64_t n = 0;
    Color us = pos.sideToMove;
#ifdef CHESS_VALIDATE_STATE
    Position startPos = pos;
#endif
    for (int i = 0; i < moveCount; i++) {
        const Move& mv = moves[i];
        Piece cap = pos.board[mv.to];
        int oldHalfMove = pos.halfMove;
        int oldFullMove = pos.fullMove;
        int oldEnPassant = pos.enPassant;
        uint8_t oldCastling = packCastling(pos);
        doMove(pos, mv);
        if (!inCheck(pos, us)) n += perft(pos, d - 1);
        undo(pos, mv, cap, oldHalfMove, oldFullMove, oldEnPassant, oldCastling);
#ifdef CHESS_VALIDATE_STATE
        assert(positionsEqual(startPos, pos));
#endif
    }
    return n;
}

#endif
