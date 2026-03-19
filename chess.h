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
    int pieceCount[2][PIECE_TYPE_COUNT];
    int pieceSquares[2][PIECE_TYPE_COUNT][MAX_PIECES_PER_TYPE];
    int squareToListIndex[64];
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
int maxPiecesForType(int type) {
    static constexpr int limits[PIECE_TYPE_COUNT] = {8, 10, 10, 10, 9, 1};
    assert(type >= 0 && type < PIECE_TYPE_COUNT);
    return limits[type];
}

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
    for (int i = 0; i < 64; i++) {
        p.board[i] = EMPTY;
        p.squareToListIndex[i] = -1;
    }
    for (int c = 0; c < 2; c++) {
        p.kingSq[c] = -1;
        p.occupancy[c] = 0;
        for (int t = 0; t < PIECE_TYPE_COUNT; t++) {
            p.pieceCount[c][t] = 0;
            p.pieceBitboards[c][t] = 0;
            for (int i = 0; i < MAX_PIECES_PER_TYPE; i++) p.pieceSquares[c][t][i] = -1;
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
    int& count = pos.pieceCount[color][type];
    assert(count < maxPiecesForType(type));
    pos.board[sq] = pc;
    pos.pieceSquares[color][type][count] = sq;
    pos.squareToListIndex[sq] = count;
    pos.pieceBitboards[color][type] |= bitAt(sq);
    pos.occupancy[color] |= bitAt(sq);
    pos.occupancyAll |= bitAt(sq);
    if (type == 5) pos.kingSq[color] = sq;
    count++;
}

void removePiece(Position& pos, int sq) {
    assert(sq >= 0 && sq < 64);
    Piece pc = pos.board[sq];
    assert(pc != EMPTY);
    Color color = pieceColor(pc);
    int type = pieceTypeIndex(pc);
    int idx = pos.squareToListIndex[sq];
    int& count = pos.pieceCount[color][type];
    assert(idx >= 0 && idx < count);
    int lastSq = pos.pieceSquares[color][type][count - 1];
    pos.pieceSquares[color][type][idx] = lastSq;
    if (lastSq != sq) pos.squareToListIndex[lastSq] = idx;
    pos.pieceSquares[color][type][count - 1] = -1;
    pos.squareToListIndex[sq] = -1;
    pos.pieceBitboards[color][type] &= ~bitAt(sq);
    pos.occupancy[color] &= ~bitAt(sq);
    pos.occupancyAll &= ~bitAt(sq);
    pos.board[sq] = EMPTY;
    count--;
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
    int idx = pos.squareToListIndex[from];
    assert(idx >= 0 && idx < pos.pieceCount[color][type]);
    uint64_t fromBit = bitAt(from);
    uint64_t toBit = bitAt(to);
    pos.board[to] = pc;
    pos.board[from] = EMPTY;
    pos.pieceSquares[color][type][idx] = to;
    pos.squareToListIndex[to] = idx;
    pos.squareToListIndex[from] = -1;
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

bool pieceListsConsistent(const Position& pos) {
    for (int sq = 0; sq < 64; sq++) {
        Piece pc = pos.board[sq];
        if (pc == EMPTY) {
            if (pos.squareToListIndex[sq] != -1) return false;
            continue;
        }
        Color color = pieceColor(pc);
        int type = pieceTypeIndex(pc);
        int idx = pos.squareToListIndex[sq];
        if (idx < 0 || idx >= pos.pieceCount[color][type]) return false;
        if (pos.pieceSquares[color][type][idx] != sq) return false;
        if (type == 5 && pos.kingSq[color] != sq) return false;
    }
    for (int color = 0; color < 2; color++) {
        if (pos.kingSq[color] < 0 || pos.kingSq[color] >= 64) return false;
        if (pos.board[pos.kingSq[color]] != (color == WHITE ? W_KING : B_KING)) return false;
        for (int type = 0; type < PIECE_TYPE_COUNT; type++) {
            bool seen[64] = {};
            for (int i = 0; i < pos.pieceCount[color][type]; i++) {
                int sq = pos.pieceSquares[color][type][i];
                if (sq < 0 || sq >= 64 || seen[sq]) return false;
                seen[sq] = true;
                Piece expected = pos.board[sq];
                if (expected == EMPTY || pieceColor(expected) != color || pieceTypeIndex(expected) != type) return false;
            }
            for (int i = pos.pieceCount[color][type]; i < maxPiecesForType(type); i++) {
                if (pos.pieceSquares[color][type][i] != -1) return false;
            }
        }
    }
    return bitboardsConsistent(pos);
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
            if (a.pieceCount[color][type] != b.pieceCount[color][type]) return false;
            if (a.pieceBitboards[color][type] != b.pieceBitboards[color][type]) return false;
            bool seenA[64] = {};
            bool seenB[64] = {};
            for (int i = 0; i < a.pieceCount[color][type]; i++) seenA[a.pieceSquares[color][type][i]] = true;
            for (int i = 0; i < b.pieceCount[color][type]; i++) seenB[b.pieceSquares[color][type][i]] = true;
            for (int sq = 0; sq < 64; sq++) if (seenA[sq] != seenB[sq]) return false;
        }
    }
    if (a.occupancyAll != b.occupancyAll) return false;
    return pieceListsConsistent(a) && pieceListsConsistent(b);
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

#ifdef CHESS_VALIDATE_STATE
bool attackedSlow(const Position& pos, int sq, Color att) {
    assert(sq >= 0 && sq < 64);
    int Rr = R(sq), Fc = F(sq);
    if (att == WHITE) {
        if (Rr > 0 && Fc > 0 && pos.board[(Rr - 1) * 8 + (Fc - 1)] == W_PAWN) return true;
        if (Rr > 0 && Fc < 7 && pos.board[(Rr - 1) * 8 + (Fc + 1)] == W_PAWN) return true;
    } else {
        if (Rr < 7 && Fc > 0 && pos.board[(Rr + 1) * 8 + (Fc - 1)] == B_PAWN) return true;
        if (Rr < 7 && Fc < 7 && pos.board[(Rr + 1) * 8 + (Fc + 1)] == B_PAWN) return true;
    }
    int nm[] = {-17, -15, -10, -6, 6, 10, 15, 17};
    for (int d : nm) {
        int t = sq + d;
        if (t < 0 || t >= 64) continue;
        if (std::abs(R(t) - Rr) + std::abs(F(t) - Fc) != 3) continue;
        Piece pc = pos.board[t];
        if (att == WHITE && pc == W_KNIGHT) return true;
        if (att == BLACK && pc == B_KNIGHT) return true;
    }
    int bd[] = {-9, -7, 7, 9};
    for (int d : bd) {
        int t = sq + d;
        while (t >= 0 && t < 64) {
            if (std::abs(R(t) - Rr) != std::abs(F(t) - Fc)) break;
            Piece pc = pos.board[t];
            if (pc != EMPTY) {
                if (att == WHITE && (pc == W_BISHOP || pc == W_QUEEN)) return true;
                if (att == BLACK && (pc == B_BISHOP || pc == B_QUEEN)) return true;
                break;
            }
            t += d;
        }
    }
    int rd[] = {-8, -1, 1, 8};
    for (int d : rd) {
        int t = sq + d;
        while (t >= 0 && t < 64) {
            bool sameRow = R(t) == Rr, sameFile = F(t) == Fc;
            if (!sameRow && !sameFile) break;
            Piece pc = pos.board[t];
            if (pc != EMPTY) {
                if (att == WHITE && (pc == W_ROOK || pc == W_QUEEN)) return true;
                if (att == BLACK && (pc == B_ROOK || pc == B_QUEEN)) return true;
                break;
            }
            t += d;
        }
    }
    int kd[] = {-9, -8, -7, -1, 1, 7, 8, 9};
    for (int d : kd) {
        int t = sq + d;
        if (t < 0 || t >= 64) continue;
        if (std::abs(R(t) - Rr) > 1 || std::abs(F(t) - Fc) > 1) continue;
        Piece pc = pos.board[t];
        if (att == WHITE && pc == W_KING) return true;
        if (att == BLACK && pc == B_KING) return true;
    }
    return false;
}
#endif

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

#ifdef CHESS_VALIDATE_STATE
    assert(result == attackedSlow(pos, sq, att));
#endif
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

void genPawnMoves(const Position& pos, Color us, int from, Move* moves, int& count) {
    int fr = R(from), fc = F(from);
    int dir = us == WHITE ? 1 : -1;
    int start = us == WHITE ? 1 : 6;
    int promo = us == WHITE ? 7 : 0;
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
    for (int dc : {-1, 1}) {
        int nc = fc + dc;
        if (nc < 0 || nc > 7 || nextRank < 0 || nextRank >= 8) continue;
        int cap = nextRank * 8 + nc;
        Piece tp = pos.board[cap];
        if (tp != EMPTY && !sameCol(pos.board[from], tp) && pt(tp) != 6) {
            if (nextRank == promo) {
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

void genKnightMoves(const Position& pos, int from, Move* moves, int& count) {
    int fr = R(from), fc = F(from);
    int nm[] = {-17, -15, -10, -6, 6, 10, 15, 17};
    for (int d : nm) {
        int to = from + d;
        if (to < 0 || to >= 64) continue;
        if (std::abs(R(to) - fr) + std::abs(F(to) - fc) != 3) continue;
        Piece tp = pos.board[to];
        if (tp == EMPTY || (!sameCol(pos.board[from], tp) && pt(tp) != 6)) pushMove(moves, count, from, to, EMPTY, false, false, false);
    }
}

void genBishopMoves(const Position& pos, int from, Move* moves, int& count) {
    int bd[] = {-9, -7, 7, 9};
    for (int d : bd) {
        for (int to = from + d; ; to += d) {
            if (to < 0 || to >= 64) break;
            if (std::abs(R(to) - R(from)) != std::abs(F(to) - F(from))) break;
            Piece tp = pos.board[to];
            if (tp == EMPTY) pushMove(moves, count, from, to, EMPTY, false, false, false);
            else {
                if (!sameCol(pos.board[from], tp) && pt(tp) != 6) pushMove(moves, count, from, to, EMPTY, false, false, false);
                break;
            }
        }
    }
}

void genRookMoves(const Position& pos, int from, Move* moves, int& count) {
    int rd[] = {-8, -1, 1, 8};
    for (int d : rd) {
        for (int to = from + d; ; to += d) {
            if (to < 0 || to >= 64) break;
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

void genKingMoves(const Position& pos, Color us, Move* moves, int& count) {
    int from = pos.kingSq[us];
    int fr = R(from), fc = F(from);
    int kd[] = {-9, -8, -7, -1, 1, 7, 8, 9};
    for (int d : kd) {
        int to = from + d;
        if (to < 0 || to >= 64) continue;
        if (std::abs(R(to) - fr) > 1 || std::abs(F(to) - fc) > 1) continue;
        Piece tp = pos.board[to];
        if (tp == EMPTY || (!sameCol(pos.board[from], tp) && pt(tp) != 6)) pushMove(moves, count, from, to, EMPTY, false, false, false);
    }
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

    int pawnType = pieceTypeIndex(us == WHITE ? W_PAWN : B_PAWN);
    for (int i = 0; i < pos.pieceCount[us][pawnType]; i++) genPawnMoves(pos, us, pos.pieceSquares[us][pawnType][i], moves, count);

    int knightType = pieceTypeIndex(us == WHITE ? W_KNIGHT : B_KNIGHT);
    for (int i = 0; i < pos.pieceCount[us][knightType]; i++) genKnightMoves(pos, pos.pieceSquares[us][knightType][i], moves, count);

    int bishopType = pieceTypeIndex(us == WHITE ? W_BISHOP : B_BISHOP);
    for (int i = 0; i < pos.pieceCount[us][bishopType]; i++) genBishopMoves(pos, pos.pieceSquares[us][bishopType][i], moves, count);

    int rookType = pieceTypeIndex(us == WHITE ? W_ROOK : B_ROOK);
    for (int i = 0; i < pos.pieceCount[us][rookType]; i++) genRookMoves(pos, pos.pieceSquares[us][rookType][i], moves, count);

    int queenType = pieceTypeIndex(us == WHITE ? W_QUEEN : B_QUEEN);
    for (int i = 0; i < pos.pieceCount[us][queenType]; i++) {
        int sq = pos.pieceSquares[us][queenType][i];
        genBishopMoves(pos, sq, moves, count);
        genRookMoves(pos, sq, moves, count);
    }

    genKingMoves(pos, us, moves, count);
    return count;
}

void doMove(Position& pos, const Move& mv) {
    assert(mv.from >= 0 && mv.from < 64);
    assert(mv.to >= 0 && mv.to < 64);
    assert(pos.board[mv.from] != EMPTY);

    Piece pc = pos.board[mv.from];
    Piece cap = pos.board[mv.to];

    if (cap != EMPTY) removePiece(pos, mv.to);
    if (mv.isEnPassant) {
        int epR = R(mv.to);
        int capR = pos.sideToMove == WHITE ? epR - 1 : epR + 1;
        int capSq = capR * 8 + F(mv.to);
        assert(pos.board[capSq] == W_PAWN || pos.board[capSq] == B_PAWN);
        removePiece(pos, capSq);
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
}

void undo(Position& pos, const Move& mv, Piece cap, int oldHalfMove = 0, int oldFullMove = 1, int oldEnPassant = -1) {
    assert(mv.from >= 0 && mv.from < 64);
    assert(mv.to >= 0 && mv.to < 64);

    pos.sideToMove = pos.sideToMove == WHITE ? BLACK : WHITE;
    pos.halfMove = oldHalfMove;
    pos.fullMove = oldFullMove;
    pos.enPassant = oldEnPassant;

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
        doMove(pos, mv);
        if (!inCheck(pos, us)) {
            uint64_t count = perft(pos, d - 1);
            std::cout << moveToUCI(mv) << ": " << count << "\n";
            total += count;
        }
        undo(pos, mv, cap, oldHalfMove, oldFullMove, oldEnPassant);
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
        doMove(pos, mv);
        if (!inCheck(pos, us)) n += perft(pos, d - 1);
        undo(pos, mv, cap, oldHalfMove, oldFullMove, oldEnPassant);
#ifdef CHESS_VALIDATE_STATE
        assert(positionsEqual(startPos, pos));
#endif
    }
    return n;
}

#endif
