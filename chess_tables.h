#ifndef CHESS_TABLES_H
#define CHESS_TABLES_H

#include "chess_position.h"

struct AttackTables {
    uint64_t knight[64];
    uint64_t king[64];
    uint64_t pawnAttackers[2][64];
    int pawnPush[2][64];
    int pawnDoublePush[2][64];
    bool promotion[2][64];
    uint64_t rookMasks[64];
    uint64_t bishopMasks[64];
    uint64_t rookAttacks[64][ROOK_TABLE_SIZE];
    uint64_t bishopAttacks[64][BISHOP_TABLE_SIZE];
};

static const uint64_t rookMagics[64] = {
0x0a80106240008000ULL, 0x2040002000401000ULL, 0x2200081202824020ULL, 0x0c80040800821000ULL,
0x8a00080200102085ULL, 0x8900080400010002ULL, 0x0a00108824011200ULL, 0x0300084100008032ULL,
0x0203800280400020ULL, 0x8002004081020028ULL, 0x0000808020001000ULL, 0x0002001040220008ULL,
0xae03000801001044ULL, 0x2206000810420004ULL, 0x8420800200010080ULL, 0x2002001254018906ULL,
0x0000908008400020ULL, 0x029000c000402000ULL, 0x0030410020001100ULL, 0x9000808008001000ULL,
0x0401010010040802ULL, 0x1202880110402004ULL, 0xa108808001000200ULL, 0x0006020000804104ULL,
0x5800400080208000ULL, 0x0809028700224000ULL, 0x4420010300221040ULL, 0x1000081200220040ULL,
0x5001019100080005ULL, 0xc002000280800400ULL, 0x7003000300020004ULL, 0x1000942200004081ULL,
0x9000400082800120ULL, 0x2002402005401004ULL, 0x2020040010100201ULL, 0x5400082101001000ULL,
0x0408020041400400ULL, 0x0b08800400800200ULL, 0x1820487204005011ULL, 0x0001002041000082ULL,
0x0120401080218000ULL, 0x8000500020004000ULL, 0x2000220010820040ULL, 0x2050022100090010ULL,
0x0080040008008080ULL, 0x0281000804010002ULL, 0x0004083002540001ULL, 0x0018108408420005ULL,
0x0000800300402500ULL, 0x0840810020400900ULL, 0x4040802000100080ULL, 0x00c0800801d00280ULL,
0x0082040008028080ULL, 0x0012000280040080ULL, 0x0839000402000100ULL, 0x0009000200408100ULL,
0x0048800040110821ULL, 0x0102010040241286ULL, 0x200020d128820042ULL, 0x080a002008041042ULL,
0x0001001008000423ULL, 0x00c100080a040003ULL, 0x080041300200a804ULL, 0x0804102100840052ULL,
};
static const int rookShifts[64] = {
52, 53, 53, 53, 53, 53, 53, 52, 53, 54, 54, 54, 54, 54, 54, 53,
53, 54, 54, 54, 54, 54, 54, 53, 53, 54, 54, 54, 54, 54, 54, 53,
53, 54, 54, 54, 54, 54, 54, 53, 53, 54, 54, 54, 54, 54, 54, 53,
53, 54, 54, 54, 54, 54, 54, 53, 52, 53, 53, 53, 53, 53, 53, 52,
};
static const uint64_t bishopMagics[64] = {
0x0d40841102002103ULL, 0x0002100a22044005ULL, 0x0041010200808030ULL, 0x001a0a0208000401ULL,
0x4214050444200200ULL, 0x0402080209000808ULL, 0x0000440420084100ULL, 0x0142010400820802ULL,
0x0009404802408201ULL, 0x0100022401120600ULL, 0x0c0c08408c008100ULL, 0x2010042502010002ULL,
0x1210011040009200ULL, 0xb000020202225180ULL, 0x01400109d0102802ULL, 0x00609a0601440249ULL,
0x8004002008109100ULL, 0x0008000428008401ULL, 0x2f12020108020084ULL, 0x2208009092004040ULL,
0x8208100501400000ULL, 0x0000200200842000ULL, 0x8000844044100801ULL, 0x4000280146080440ULL,
0x2020101922040118ULL, 0x0211110020224204ULL, 0x0400480890008412ULL, 0x0440802108020020ULL,
0x1012001002005000ULL, 0x4056020010880924ULL, 0x4011012802080100ULL, 0x0028420029011100ULL,
0x501404230440020cULL, 0x0408020908824818ULL, 0x0040402088100108ULL, 0x2491020080080082ULL,
0x0408006c00044100ULL, 0x80d01001c0002400ULL, 0x00080208811400b0ULL, 0x0528050100004460ULL,
0x00241a2924004001ULL, 0x0102021024400201ULL, 0x0091008050000900ULL, 0xc12008e024208800ULL,
0x0140e000a4000082ULL, 0x000220080080010aULL, 0x6322021444000500ULL, 0x0388484500430420ULL,
0x0080923002204620ULL, 0x012202020125000aULL, 0x3100010080900801ULL, 0x0200000c20880022ULL,
0x0000024042820008ULL, 0x0000428408408008ULL, 0x4504100408108400ULL, 0x4104c40420420020ULL,
0x1001404210500200ULL, 0x00110600840108d0ULL, 0x8860320200420810ULL, 0x0011600003420a10ULL,
0x8400000008830400ULL, 0x0082808902080202ULL, 0x0420230202080100ULL, 0x0a3020022c09e820ULL,
};
static const int bishopShifts[64] = {
58, 59, 59, 59, 59, 59, 59, 58, 59, 59, 59, 59, 59, 59, 59, 59,
59, 59, 57, 57, 57, 57, 59, 59, 59, 59, 57, 55, 55, 57, 59, 59,
59, 59, 57, 55, 55, 57, 59, 59, 59, 59, 57, 57, 57, 57, 59, 59,
59, 59, 59, 59, 59, 59, 59, 59, 58, 59, 59, 59, 59, 59, 59, 58,
};

uint64_t bishopMask(int sq) {
    uint64_t mask = 0;
    int r = R(sq), f = F(sq);
    for (int nr = r + 1, nf = f + 1; nr <= 6 && nf <= 6; ++nr, ++nf) mask |= bitAt(nr * 8 + nf);
    for (int nr = r + 1, nf = f - 1; nr <= 6 && nf >= 1; ++nr, --nf) mask |= bitAt(nr * 8 + nf);
    for (int nr = r - 1, nf = f + 1; nr >= 1 && nf <= 6; --nr, ++nf) mask |= bitAt(nr * 8 + nf);
    for (int nr = r - 1, nf = f - 1; nr >= 1 && nf >= 1; --nr, --nf) mask |= bitAt(nr * 8 + nf);
    return mask;
}

uint64_t rookMask(int sq) {
    uint64_t mask = 0;
    int r = R(sq), f = F(sq);
    for (int nr = r + 1; nr <= 6; ++nr) mask |= bitAt(nr * 8 + f);
    for (int nr = r - 1; nr >= 1; --nr) mask |= bitAt(nr * 8 + f);
    for (int nf = f + 1; nf <= 6; ++nf) mask |= bitAt(r * 8 + nf);
    for (int nf = f - 1; nf >= 1; --nf) mask |= bitAt(r * 8 + nf);
    return mask;
}

uint64_t bishopAttacksOnTheFly(int sq, uint64_t occ) {
    uint64_t attacks = 0;
    int r = R(sq), f = F(sq);
    for (int nr = r + 1, nf = f + 1; nr <= 7 && nf <= 7; ++nr, ++nf) {
        int to = nr * 8 + nf;
        attacks |= bitAt(to);
        if (occ & bitAt(to)) break;
    }
    for (int nr = r + 1, nf = f - 1; nr <= 7 && nf >= 0; ++nr, --nf) {
        int to = nr * 8 + nf;
        attacks |= bitAt(to);
        if (occ & bitAt(to)) break;
    }
    for (int nr = r - 1, nf = f + 1; nr >= 0 && nf <= 7; --nr, ++nf) {
        int to = nr * 8 + nf;
        attacks |= bitAt(to);
        if (occ & bitAt(to)) break;
    }
    for (int nr = r - 1, nf = f - 1; nr >= 0 && nf >= 0; --nr, --nf) {
        int to = nr * 8 + nf;
        attacks |= bitAt(to);
        if (occ & bitAt(to)) break;
    }
    return attacks;
}

uint64_t rookAttacksOnTheFly(int sq, uint64_t occ) {
    uint64_t attacks = 0;
    int r = R(sq), f = F(sq);
    for (int nr = r + 1; nr <= 7; ++nr) {
        int to = nr * 8 + f;
        attacks |= bitAt(to);
        if (occ & bitAt(to)) break;
    }
    for (int nr = r - 1; nr >= 0; --nr) {
        int to = nr * 8 + f;
        attacks |= bitAt(to);
        if (occ & bitAt(to)) break;
    }
    for (int nf = f + 1; nf <= 7; ++nf) {
        int to = r * 8 + nf;
        attacks |= bitAt(to);
        if (occ & bitAt(to)) break;
    }
    for (int nf = f - 1; nf >= 0; --nf) {
        int to = r * 8 + nf;
        attacks |= bitAt(to);
        if (occ & bitAt(to)) break;
    }
    return attacks;
}

uint64_t setOccupancy(int index, int bits, uint64_t mask) {
    uint64_t occ = 0;
    for (int i = 0; i < bits; ++i) {
        int sq = __builtin_ctzll(mask);
        mask &= mask - 1;
        if (index & (1 << i)) occ |= bitAt(sq);
    }
    return occ;
}

AttackTables makeAttackTables() {
    AttackTables t = {};
    for (int color = 0; color < 2; color++) {
        for (int sq = 0; sq < 64; sq++) {
            t.pawnPush[color][sq] = -1;
            t.pawnDoublePush[color][sq] = -1;
            t.promotion[color][sq] = false;
        }
    }
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
        if (r < 7) t.pawnPush[WHITE][sq] = (r + 1) * 8 + f;
        if (r == 1) t.pawnDoublePush[WHITE][sq] = (r + 2) * 8 + f;
        if (r > 0) t.pawnPush[BLACK][sq] = (r - 1) * 8 + f;
        if (r == 6) t.pawnDoublePush[BLACK][sq] = (r - 2) * 8 + f;
        t.promotion[WHITE][sq] = r == 7;
        t.promotion[BLACK][sq] = r == 0;
        t.rookMasks[sq] = rookMask(sq);
        t.bishopMasks[sq] = bishopMask(sq);
        int rookBits = __builtin_popcountll(t.rookMasks[sq]);
        int bishopBits = __builtin_popcountll(t.bishopMasks[sq]);
        for (int i = 0; i < (1 << rookBits); ++i) {
            uint64_t occ = setOccupancy(i, rookBits, t.rookMasks[sq]);
            int idx = int(((occ & t.rookMasks[sq]) * rookMagics[sq]) >> rookShifts[sq]);
            t.rookAttacks[sq][idx] = rookAttacksOnTheFly(sq, occ);
        }
        for (int i = 0; i < (1 << bishopBits); ++i) {
            uint64_t occ = setOccupancy(i, bishopBits, t.bishopMasks[sq]);
            int idx = int(((occ & t.bishopMasks[sq]) * bishopMagics[sq]) >> bishopShifts[sq]);
            t.bishopAttacks[sq][idx] = bishopAttacksOnTheFly(sq, occ);
        }
    }
    return t;
}

const AttackTables& attackTables() {
    static const AttackTables tables = makeAttackTables();
    return tables;
}

uint64_t rookAttacks(int sq, uint64_t occ) {
    const AttackTables& tables = attackTables();
    uint64_t masked = occ & tables.rookMasks[sq];
    int idx = int((masked * rookMagics[sq]) >> rookShifts[sq]);
    return tables.rookAttacks[sq][idx];
}

uint64_t bishopAttacks(int sq, uint64_t occ) {
    const AttackTables& tables = attackTables();
    uint64_t masked = occ & tables.bishopMasks[sq];
    int idx = int((masked * bishopMagics[sq]) >> bishopShifts[sq]);
    return tables.bishopAttacks[sq][idx];
}

#endif
