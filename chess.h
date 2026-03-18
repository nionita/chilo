#ifndef CHESS_H
#define CHESS_H

#include <iostream>
#include <string>
#include <vector>
#include <cstdint>
#include <cassert>
#include <cctype>

enum Piece { EMPTY, W_PAWN, W_KNIGHT, W_BISHOP, W_ROOK, W_QUEEN, W_KING,
             B_PAWN, B_KNIGHT, B_BISHOP, B_ROOK, B_QUEEN, B_KING };
enum Color { WHITE, BLACK };

struct Move { int from, to; Piece promotion; bool isEnPassant, isCastle, isDoublePush; };

struct Position {
    Piece board[64];
    Color sideToMove;
    bool castling[4];
    int enPassant;
    int halfMove, fullMove;
};

int R(int s) { return s >> 3; }
int F(int s) { return s & 7; }
int pt(Piece p) { return p == W_PAWN || p == B_PAWN ? 1 : p == W_KNIGHT || p == B_KNIGHT ? 2 : p == W_BISHOP || p == B_BISHOP ? 3 : p == W_ROOK || p == B_ROOK ? 4 : p == W_QUEEN || p == B_QUEEN ? 5 : 6; }
bool wh(Piece p) { return p >= W_PAWN && p <= W_KING; }
bool bl(Piece p) { return p >= B_PAWN && p <= B_KING; }
bool sameCol(Piece a, Piece b) { return (wh(a) && wh(b)) || (bl(a) && bl(b)); }

Position parseFEN(const std::string& f) {
    Position p;
    for (int i = 0; i < 64; i++) p.board[i] = EMPTY;
    std::vector<std::string> p2; std::string cur;
    for (char ch : f) { if (ch == ' ') { p2.push_back(cur); cur.clear(); } else cur.push_back(ch); }
    p2.push_back(cur);
    int rank = 7, file = 0;
    for (char ch : p2[0]) {
        if (ch == '/') { rank--; file = 0; continue; }
        if (ch >= '1' && ch <= '8') { file += ch - '0'; continue; }
        int s = rank * 8 + file;
        if (ch == 'p') p.board[s] = B_PAWN;
        else if (ch == 'n') p.board[s] = B_KNIGHT;
        else if (ch == 'b') p.board[s] = B_BISHOP;
        else if (ch == 'r') p.board[s] = B_ROOK;
        else if (ch == 'q') p.board[s] = B_QUEEN;
        else if (ch == 'k') p.board[s] = B_KING;
        else if (ch == 'P') p.board[s] = W_PAWN;
        else if (ch == 'N') p.board[s] = W_KNIGHT;
        else if (ch == 'B') p.board[s] = W_BISHOP;
        else if (ch == 'R') p.board[s] = W_ROOK;
        else if (ch == 'Q') p.board[s] = W_QUEEN;
        else if (ch == 'K') p.board[s] = W_KING;
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
    p.halfMove = 0; p.fullMove = 1;
    return p;
}

int findKing(const Position& pos, Color col) {
    Piece k = col == WHITE ? W_KING : B_KING;
    for (int i = 0; i < 64; i++) if (pos.board[i] == k) return i;
    assert(false && "King not found on board");
    return -1;
}

bool attacked(const Position& pos, int sq, Color att) {
    int Rr = R(sq), Fc = F(sq);
    if (att == WHITE) {
        if (Rr > 0 && Fc > 0 && pos.board[(Rr-1)*8 + (Fc-1)] == W_PAWN) return true;
        if (Rr > 0 && Fc < 7 && pos.board[(Rr-1)*8 + (Fc+1)] == W_PAWN) return true;
    } else {
        if (Rr < 7 && Fc > 0 && pos.board[(Rr+1)*8 + (Fc-1)] == B_PAWN) return true;
        if (Rr < 7 && Fc < 7 && pos.board[(Rr+1)*8 + (Fc+1)] == B_PAWN) return true;
    }
    int nm[] = {-17,-15,-10,-6,6,10,15,17};
    for (int d : nm) { 
        int t = sq + d; 
        if (t < 0 || t >= 64) continue; 
        if (abs(R(t)-Rr) + abs(F(t)-Fc) != 3) continue; 
        Piece pc = pos.board[t]; 
        if (att == WHITE && pc == W_KNIGHT) return true; 
        if (att == BLACK && pc == B_KNIGHT) return true; 
    }
    int bd[] = {-9,-7,7,9};
    for (int d : bd) { 
        int t = sq + d; 
        while (t >= 0 && t < 64) { 
            if (abs(R(t)-Rr) != abs(F(t)-Fc)) break;
            Piece pc = pos.board[t];
            if (pc != EMPTY) { 
                if (att == WHITE && (pc == W_BISHOP || pc == W_QUEEN)) return true; 
                if (att == BLACK && (pc == B_BISHOP || pc == B_QUEEN)) return true; 
                break; 
            }
            t += d; 
        } 
    }
    int rd[] = {-8,-1,1,8};
    for (int d : rd) { 
        int t = sq + d; 
        while (t >= 0 && t < 64) {
            bool sameRow = R(t) == Rr, sameCol = F(t) == Fc;
            if (!sameRow && !sameCol) break;
            Piece pc = pos.board[t];
            if (pc != EMPTY) { 
                if (att == WHITE && (pc == W_ROOK || pc == W_QUEEN)) return true; 
                if (att == BLACK && (pc == B_ROOK || pc == B_QUEEN)) return true; 
                break; 
            }
            t += d; 
        } 
    }
    int kd[] = {-9,-8,-7,-1,1,7,8,9};
    for (int d : kd) { 
        int t = sq + d; 
        if (t < 0 || t >= 64) continue; 
        if (abs(R(t)-Rr) > 1 || abs(F(t)-Fc) > 1) continue; 
        Piece pc = pos.board[t]; 
        if (att == WHITE && pc == W_KING) return true; 
        if (att == BLACK && pc == B_KING) return true; 
    }
    return false;
}

bool inCheck(const Position& pos, Color col) {
    int k = findKing(pos, col);
    return k >= 0 && attacked(pos, k, col == WHITE ? BLACK : WHITE);
}

std::vector<Move> genMoves(const Position& pos) {
    std::vector<Move> m;
    Color us = pos.sideToMove, them = us == WHITE ? BLACK : WHITE;
    for (int f = 0; f < 64; f++) {
        Piece pc = pos.board[f];
        if (pc == EMPTY) continue;
        if (us == WHITE && !wh(pc)) continue;
        if (us == BLACK && !bl(pc)) continue;
        
        int fr = R(f), fc = F(f), typ = pt(pc);
        if (typ == 1) {
            int dir = us == WHITE ? 1 : -1, start = us == WHITE ? 1 : 6, promo = us == WHITE ? 7 : 0;
            int to = (fr + dir) * 8 + fc;
            if (fr + dir >= 0 && fr + dir < 8 && pos.board[to] == EMPTY) {
                if (fr + dir == promo) {
                    Piece promos[] = {us == WHITE ? W_QUEEN : B_QUEEN, us == WHITE ? W_ROOK : B_ROOK, us == WHITE ? W_BISHOP : B_BISHOP, us == WHITE ? W_KNIGHT : B_KNIGHT};
                    for (Piece pr : promos) m.push_back({f, to, pr, false, false, false});
                }
                else { m.push_back({f, to, EMPTY, false, false, false}); if (fr == start) { int t2 = (fr + 2*dir)*8 + fc; if (pos.board[t2] == EMPTY) m.push_back({f, t2, EMPTY, false, false, true}); } }
            }
            for (int dc : {-1, 1}) { 
                int nc = fc + dc; 
                if (nc < 0 || nc > 7) continue; 
                int cap = (fr + dir)*8 + nc; 
                if (fr + dir < 0 || fr + dir >= 8) continue; 
                Piece tp = pos.board[cap]; 
                if (tp != EMPTY && !sameCol(pc, tp) && pt(tp) != 6) { 
                    if (fr + dir == promo) {
                        Piece promos[] = {us == WHITE ? W_QUEEN : B_QUEEN, us == WHITE ? W_ROOK : B_ROOK, us == WHITE ? W_BISHOP : B_BISHOP, us == WHITE ? W_KNIGHT : B_KNIGHT};
                        for (Piece pr : promos) m.push_back({f, cap, pr, false, false, false});
                    }
                    else m.push_back({f, cap, EMPTY, false, false, false}); 
                } 
                if (pos.enPassant != -1 && cap == pos.enPassant) m.push_back({f, cap, EMPTY, true, false, false}); 
            }
        }
        if (typ == 2) { 
            int nm[] = {-17,-15,-10,-6,6,10,15,17}; 
            for (int d : nm) { 
                int to = f + d; 
                if (to < 0 || to >= 64) continue; 
                if (abs(R(to)-fr) + abs(F(to)-fc) != 3) continue; 
                Piece tp = pos.board[to]; 
                if (tp == EMPTY || (!sameCol(pc, tp) && pt(tp) != 6)) m.push_back({f, to, EMPTY, false, false, false}); 
            } 
        }
        if (typ == 3 || typ == 5) { 
            int bd[] = {-9,-7,7,9}; 
            for (int d : bd) { 
                for (int to = f + d; ; to += d) { 
                    if (to < 0 || to >= 64) break; 
                    if (abs(R(to)-R(f)) != abs(F(to)-F(f))) break;
                    Piece tp = pos.board[to]; 
                    if (tp == EMPTY) m.push_back({f, to, EMPTY, false, false, false}); 
                    else { if (!sameCol(pc, tp) && pt(tp) != 6) m.push_back({f, to, EMPTY, false, false, false}); break; } 
                } 
            } 
        }
        if (typ == 4 || typ == 5) { 
            int rd[] = {-8,-1,1,8}; 
            for (int d : rd) { 
                for (int to = f + d; ; to += d) { 
                    if (to < 0 || to >= 64) break;
                    if (d == -1 && F(to) >= F(f)) break;
                    if (d == 1 && F(to) <= F(f)) break;
                    if (d == -8 && R(to) >= R(f)) break;
                    if (d == 8 && R(to) <= R(f)) break;
                    Piece tp = pos.board[to]; 
                    if (tp == EMPTY) m.push_back({f, to, EMPTY, false, false, false}); 
                    else { if (!sameCol(pc, tp) && pt(tp) != 6) m.push_back({f, to, EMPTY, false, false, false}); break; } 
                } 
            } 
        }
        if (typ == 6) { 
            int kd[] = {-9,-8,-7,-1,1,7,8,9}; 
            for (int d : kd) { 
                int to = f + d; 
                if (to < 0 || to >= 64) continue; 
                if (abs(R(to)-fr) > 1 || abs(F(to)-fc) > 1) continue; 
                Piece tp = pos.board[to]; 
                if (tp == EMPTY || (!sameCol(pc, tp) && pt(tp) != 6)) m.push_back({f, to, EMPTY, false, false, false}); 
            } 
            int kr = us == WHITE ? 0 : 7, ki = us == WHITE ? 0 : 2, qi = us == WHITE ? 1 : 3;
            Piece ourRook = us == WHITE ? W_ROOK : B_ROOK;
            if (fr == kr && fc == 4 && pos.castling[ki] && pos.board[kr*8+7] == ourRook) if (pos.board[kr*8+5] == EMPTY && pos.board[kr*8+6] == EMPTY) if (!attacked(pos, kr*8+4, them) && !attacked(pos, kr*8+5, them) && !attacked(pos, kr*8+6, them)) m.push_back({f, kr*8+6, EMPTY, false, true, false});
            if (fr == kr && fc == 4 && pos.castling[qi] && pos.board[kr*8+0] == ourRook) if (pos.board[kr*8+2] == EMPTY && pos.board[kr*8+3] == EMPTY) if (!attacked(pos, kr*8+4, them) && !attacked(pos, kr*8+3, them) && !attacked(pos, kr*8+2, them)) m.push_back({f, kr*8+2, EMPTY, false, true, false});
        }
    }
    return m;
}

void doMove(Position& pos, const Move& mv) {
    Piece pc = pos.board[mv.from], cap = pos.board[mv.to];
    pos.board[mv.to] = pc; pos.board[mv.from] = EMPTY;
    if (mv.promotion != EMPTY) pos.board[mv.to] = mv.promotion;
    if (mv.isEnPassant) { 
        int epR = R(mv.to); 
        int capR = pos.sideToMove == WHITE ? epR - 1 : epR + 1; 
        Piece capturedPawn = pos.board[capR*8 + F(mv.to)];
        assert(capturedPawn == W_PAWN || capturedPawn == B_PAWN);
        pos.board[capR*8 + F(mv.to)] = EMPTY; 
    }
    if (mv.isCastle) { 
        int rr = R(mv.to); 
        Piece expectedRook = (rr == 0) ? W_ROOK : B_ROOK;
        if (F(mv.to) == 6) { 
            assert(pos.board[rr*8+7] == expectedRook);
            pos.board[rr*8+5] = pos.board[rr*8+7]; 
            pos.board[rr*8+7] = EMPTY; 
        } else if (F(mv.to) == 2) { 
            assert(pos.board[rr*8+0] == expectedRook);
            pos.board[rr*8+3] = pos.board[rr*8+0]; 
            pos.board[rr*8+0] = EMPTY; 
        } 
    }
    pos.enPassant = -1;
    if (mv.isDoublePush) { int epR = pos.sideToMove == WHITE ? R(mv.from) + 1 : R(mv.from) - 1; pos.enPassant = epR * 8 + F(mv.from); }
    if (pt(pc) == 1 || cap != EMPTY) pos.halfMove = 0; else pos.halfMove++;
    pos.sideToMove = pos.sideToMove == WHITE ? BLACK : WHITE;
    if (pos.sideToMove == WHITE) pos.fullMove++;
}

void undo(Position& pos, const Move& mv, Piece cap) {
    pos.sideToMove = pos.sideToMove == WHITE ? BLACK : WHITE;
    if (pos.sideToMove == WHITE) pos.fullMove--;
    Piece pc = pos.board[mv.to];
    if (mv.promotion != EMPTY) pc = pos.sideToMove == WHITE ? W_PAWN : B_PAWN;
    pos.board[mv.from] = pc; pos.board[mv.to] = cap;
    if (mv.isEnPassant) { 
        int epR = R(mv.to); 
        int capR = pos.sideToMove == WHITE ? epR - 1 : epR + 1; 
        Piece restoredPawn = pos.sideToMove == WHITE ? B_PAWN : W_PAWN;
        assert(pos.board[capR*8 + F(mv.to)] == EMPTY);
        pos.board[capR*8 + F(mv.to)] = restoredPawn; 
    }
    if (mv.isCastle) { 
        int rr = R(mv.to); 
        if (F(mv.to) == 6) { 
            assert(pos.board[rr*8+5] == W_ROOK || pos.board[rr*8+5] == B_ROOK);
            pos.board[rr*8+7] = pos.board[rr*8+5]; 
            pos.board[rr*8+5] = EMPTY; 
        } else if (F(mv.to) == 2) { 
            assert(pos.board[rr*8+3] == W_ROOK || pos.board[rr*8+3] == B_ROOK);
            pos.board[rr*8+0] = pos.board[rr*8+3]; 
            pos.board[rr*8+3] = EMPTY; 
        } 
    }
    if (pt(pc) == 1 && cap == EMPTY) pos.enPassant = mv.isDoublePush ? mv.to : -1;
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
    auto moves = genMoves(pos);
    uint64_t total = 0;
    Color us = pos.sideToMove;
    for (const Move& mv : moves) {
        Piece cap = pos.board[mv.to];
        doMove(pos, mv);
        if (!inCheck(pos, us)) {
            uint64_t count = perft(pos, d - 1);
            std::cout << moveToUCI(mv) << ": " << count << "\n";
            total += count;
        }
        undo(pos, mv, cap);
    }
    return total;
}

uint64_t perft(Position& pos, int d) {
    if (d == 0) return 1;
    auto moves = genMoves(pos);
    uint64_t n = 0;
    Color us = pos.sideToMove;
    for (const Move& mv : moves) {
        Piece cap = pos.board[mv.to];
        doMove(pos, mv);
        if (!inCheck(pos, us)) n += perft(pos, d - 1);
        undo(pos, mv, cap);
    }
    return n;
}

#endif
