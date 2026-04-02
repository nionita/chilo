#ifndef CHESS_POSITION_H
#define CHESS_POSITION_H

#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <string>
#include <vector>

enum Piece : uint8_t { EMPTY, W_PAWN, W_KNIGHT, W_BISHOP, W_ROOK, W_QUEEN, W_KING,
                       B_PAWN, B_KNIGHT, B_BISHOP, B_ROOK, B_QUEEN, B_KING };
enum Color : uint8_t { WHITE, BLACK };

constexpr int PIECE_TYPE_COUNT = 6;
constexpr int MAX_PIECES_PER_TYPE = 10;
constexpr int MAX_MOVES = 256;
constexpr int ROOK_TABLE_SIZE = 4096;
constexpr int BISHOP_TABLE_SIZE = 512;

struct Move {
    uint8_t from;
    uint8_t to;
    Piece promotion;
    uint8_t isEnPassant : 1;
    uint8_t isCastle : 1;
    uint8_t isDoublePush : 1;
    uint8_t reserved : 5;

    constexpr Move()
        : from(0), to(0), promotion(EMPTY), isEnPassant(0), isCastle(0), isDoublePush(0), reserved(0) {}

    constexpr Move(int fromSq, int toSq, Piece promo, bool enPassant, bool castle, bool doublePush)
        : from(static_cast<uint8_t>(fromSq)),
          to(static_cast<uint8_t>(toSq)),
          promotion(promo),
          isEnPassant(enPassant ? 1 : 0),
          isCastle(castle ? 1 : 0),
          isDoublePush(doublePush ? 1 : 0),
          reserved(0) {}
};
static_assert(sizeof(Move) == 4, "Move should stay compact");
struct UndoState {
    Piece captured;
    uint8_t castling;
    int enPassant;
    int halfMove;
    int fullMove;
    uint64_t hashKey;
};

struct Position {
    Piece pieceAtSquare[64];
    Color sideToMove;
    bool castling[4];
    int enPassant;
    int halfMove, fullMove;
    int kingSq[2];
    uint64_t pieceBitboards[2][PIECE_TYPE_COUNT];
    uint64_t occupancy[2];
    uint64_t occupancyAll;
    uint64_t hashKey;
};

inline int R(int s) { return s >> 3; }
inline int F(int s) { return s & 7; }
inline uint64_t bitAt(int sq) {
    assert(sq >= 0 && sq < 64);
    return 1ULL << sq;
}
inline uint64_t splitmix64(uint64_t& state) {
    uint64_t result = (state += 0x9e3779b97f4a7c15ULL);
    result = (result ^ (result >> 30)) * 0xbf58476d1ce4e5b9ULL;
    result = (result ^ (result >> 27)) * 0x94d049bb133111ebULL;
    return result ^ (result >> 31);
}
inline int pt(Piece p) {
    if (p == EMPTY) return 0;
    if (p == W_PAWN || p == B_PAWN) return 1;
    if (p == W_KNIGHT || p == B_KNIGHT) return 2;
    if (p == W_BISHOP || p == B_BISHOP) return 3;
    if (p == W_ROOK || p == B_ROOK) return 4;
    if (p == W_QUEEN || p == B_QUEEN) return 5;
    return 6;
}
inline bool wh(Piece p) { return p >= W_PAWN && p <= W_KING; }
inline bool bl(Piece p) { return p >= B_PAWN && p <= B_KING; }
inline bool sameCol(Piece a, Piece b) { return (wh(a) && wh(b)) || (bl(a) && bl(b)); }
inline Color pieceColor(Piece p) { assert(p != EMPTY); return wh(p) ? WHITE : BLACK; }
inline int pieceTypeIndex(Piece p) { assert(p != EMPTY); return pt(p) - 1; }
inline uint8_t packCastling(const Position& pos);
inline bool hashConsistent(const Position& pos);

struct ZobristTables {
    uint64_t piece[13][64];
    uint64_t castling[16];
    uint64_t enPassantFile[8];
    uint64_t sideToMove;
};

inline const ZobristTables& zobristTables() {
    static const ZobristTables tables = [] {
        ZobristTables t{};
        uint64_t seed = 0x1f2e3d4c5b6a7988ULL;
        for (int piece = 0; piece < 13; piece++) {
            for (int sq = 0; sq < 64; sq++) t.piece[piece][sq] = splitmix64(seed);
        }
        for (int rights = 0; rights < 16; rights++) t.castling[rights] = splitmix64(seed);
        for (int file = 0; file < 8; file++) t.enPassantFile[file] = splitmix64(seed);
        t.sideToMove = splitmix64(seed);
        return t;
    }();
    return tables;
}

inline uint64_t enPassantHash(int sq) {
    return sq == -1 ? 0 : zobristTables().enPassantFile[F(sq)];
}

inline uint64_t castlingHash(uint8_t rights) {
    return zobristTables().castling[rights];
}

inline uint64_t sideToMoveHash() {
    return zobristTables().sideToMove;
}

inline Piece pieceAt(const Position& pos, int sq) {
    assert(sq >= 0 && sq < 64);
    return pos.pieceAtSquare[sq];
}

inline bool hasPiece(const Position& pos, int sq, Piece pc) {
    return pieceAt(pos, sq) == pc;
}

inline void initPosition(Position& p) {
    for (int i = 0; i < 64; i++) p.pieceAtSquare[i] = EMPTY;
    for (int c = 0; c < 2; c++) {
        p.kingSq[c] = -1;
        p.occupancy[c] = 0;
        for (int t = 0; t < PIECE_TYPE_COUNT; t++) {
            p.pieceBitboards[c][t] = 0;
        }
    }
    p.occupancyAll = 0;
    p.hashKey = 0;
}

inline void addPiece(Position& pos, int sq, Piece pc) {
    assert(sq >= 0 && sq < 64);
    assert(pc != EMPTY);
    assert(pieceAt(pos, sq) == EMPTY);
    Color color = pieceColor(pc);
    int type = pieceTypeIndex(pc);
    pos.pieceAtSquare[sq] = pc;
    pos.pieceBitboards[color][type] |= bitAt(sq);
    pos.occupancy[color] |= bitAt(sq);
    pos.occupancyAll |= bitAt(sq);
    pos.hashKey ^= zobristTables().piece[pc][sq];
    if (type == 5) pos.kingSq[color] = sq;
}

inline void removePiece(Position& pos, int sq) {
    assert(sq >= 0 && sq < 64);
    Piece pc = pieceAt(pos, sq);
    assert(pc != EMPTY);
    Color color = pieceColor(pc);
    int type = pieceTypeIndex(pc);
    pos.pieceBitboards[color][type] &= ~bitAt(sq);
    pos.occupancy[color] &= ~bitAt(sq);
    pos.occupancyAll &= ~bitAt(sq);
    pos.pieceAtSquare[sq] = EMPTY;
    pos.hashKey ^= zobristTables().piece[pc][sq];
    if (type == 5) pos.kingSq[color] = -1;
}

inline void movePiece(Position& pos, int from, int to) {
    assert(from >= 0 && from < 64);
    assert(to >= 0 && to < 64);
    Piece pc = pieceAt(pos, from);
    assert(pc != EMPTY);
    assert(pieceAt(pos, to) == EMPTY);
    Color color = pieceColor(pc);
    int type = pieceTypeIndex(pc);
    uint64_t fromBit = bitAt(from);
    uint64_t toBit = bitAt(to);
    pos.pieceAtSquare[to] = pc;
    pos.pieceAtSquare[from] = EMPTY;
    pos.pieceBitboards[color][type] ^= fromBit | toBit;
    pos.occupancy[color] ^= fromBit | toBit;
    pos.occupancyAll ^= fromBit | toBit;
    pos.hashKey ^= zobristTables().piece[pc][from] ^ zobristTables().piece[pc][to];
    if (type == 5) pos.kingSq[color] = to;
}

inline bool bitboardsConsistent(const Position& pos) {
    uint64_t expectedPieces[2][PIECE_TYPE_COUNT] = {};
    uint64_t expectedOcc[2] = {};
    for (int sq = 0; sq < 64; sq++) {
        Piece pc = pos.pieceAtSquare[sq];
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

inline bool representationConsistent(const Position& pos) {
    if (!bitboardsConsistent(pos)) return false;
    if (!hashConsistent(pos)) return false;
    for (int color = 0; color < 2; color++) {
        int kingSq = pos.kingSq[color];
        if (kingSq < 0 || kingSq >= 64) return false;
        Piece king = color == WHITE ? W_KING : B_KING;
        if (pieceAt(pos, kingSq) != king) return false;
        if (pos.pieceBitboards[color][pieceTypeIndex(king)] != bitAt(kingSq)) return false;
    }
    return true;
}

inline bool positionsEqual(const Position& a, const Position& b) {
    for (int i = 0; i < 64; i++) if (a.pieceAtSquare[i] != b.pieceAtSquare[i]) return false;
    if (a.sideToMove != b.sideToMove) return false;
    for (int i = 0; i < 4; i++) if (a.castling[i] != b.castling[i]) return false;
    if (a.enPassant != b.enPassant) return false;
    if (a.halfMove != b.halfMove) return false;
    if (a.fullMove != b.fullMove) return false;
    if (a.hashKey != b.hashKey) return false;
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

inline uint8_t packCastling(const Position& pos) {
    return (pos.castling[0] ? 1 : 0) |
           (pos.castling[1] ? 2 : 0) |
           (pos.castling[2] ? 4 : 0) |
           (pos.castling[3] ? 8 : 0);
}

inline void restoreCastling(Position& pos, uint8_t rights) {
    pos.castling[0] = rights & 1;
    pos.castling[1] = rights & 2;
    pos.castling[2] = rights & 4;
    pos.castling[3] = rights & 8;
}

inline uint64_t computeHash(const Position& pos) {
    uint64_t hash = 0;
    const ZobristTables& zobrist = zobristTables();
    for (int sq = 0; sq < 64; sq++) {
        Piece piece = pos.pieceAtSquare[sq];
        if (piece != EMPTY) hash ^= zobrist.piece[piece][sq];
    }
    hash ^= castlingHash(packCastling(pos));
    hash ^= enPassantHash(pos.enPassant);
    if (pos.sideToMove == BLACK) hash ^= sideToMoveHash();
    return hash;
}

inline bool hashConsistent(const Position& pos) {
    return pos.hashKey == computeHash(pos);
}

inline void clearCastlingForSquare(Position& pos, int sq) {
    switch (sq) {
        case 0: pos.castling[1] = false; break;
        case 7: pos.castling[0] = false; break;
        case 56: pos.castling[3] = false; break;
        case 63: pos.castling[2] = false; break;
    }
}

inline Position parseFEN(const std::string& f) {
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
    p.halfMove = p2.size() >= 5 ? std::atoi(p2[4].c_str()) : 0;
    p.fullMove = p2.size() >= 6 ? std::atoi(p2[5].c_str()) : 1;
    p.hashKey = computeHash(p);
    assert(p.kingSq[WHITE] != -1 && p.kingSq[BLACK] != -1);
    return p;
}

inline std::string positionToFEN(const Position& pos) {
    std::string fen;
    for (int rank = 7; rank >= 0; rank--) {
        int emptyCount = 0;
        for (int file = 0; file < 8; file++) {
            Piece piece = pieceAt(pos, rank * 8 + file);
            if (piece == EMPTY) {
                emptyCount++;
                continue;
            }
            if (emptyCount > 0) {
                fen += char('0' + emptyCount);
                emptyCount = 0;
            }

            char pieceChar = '?';
            switch (piece) {
                case W_PAWN: pieceChar = 'P'; break;
                case W_KNIGHT: pieceChar = 'N'; break;
                case W_BISHOP: pieceChar = 'B'; break;
                case W_ROOK: pieceChar = 'R'; break;
                case W_QUEEN: pieceChar = 'Q'; break;
                case W_KING: pieceChar = 'K'; break;
                case B_PAWN: pieceChar = 'p'; break;
                case B_KNIGHT: pieceChar = 'n'; break;
                case B_BISHOP: pieceChar = 'b'; break;
                case B_ROOK: pieceChar = 'r'; break;
                case B_QUEEN: pieceChar = 'q'; break;
                case B_KING: pieceChar = 'k'; break;
                default: assert(false); break;
            }
            fen += pieceChar;
        }
        if (emptyCount > 0) fen += char('0' + emptyCount);
        if (rank > 0) fen += '/';
    }

    fen += pos.sideToMove == WHITE ? " w " : " b ";

    std::string castling;
    if (pos.castling[0]) castling += 'K';
    if (pos.castling[1]) castling += 'Q';
    if (pos.castling[2]) castling += 'k';
    if (pos.castling[3]) castling += 'q';
    fen += castling.empty() ? "-" : castling;
    fen += ' ';

    if (pos.enPassant == -1) {
        fen += '-';
    } else {
        fen += char('a' + F(pos.enPassant));
        fen += char('1' + R(pos.enPassant));
    }

    fen += ' ';
    fen += std::to_string(pos.halfMove);
    fen += ' ';
    fen += std::to_string(pos.fullMove);
    return fen;
}

inline std::string moveToUCI(const Move& mv) {
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

#endif
