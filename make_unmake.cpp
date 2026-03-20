#include "engine.h"

#include <cassert>

void doMove(Position& pos, const Move& mv, UndoState& undo) {
    assert(mv.from >= 0 && mv.from < 64);
    assert(mv.to >= 0 && mv.to < 64);
    assert(pieceAt(pos, mv.from) != EMPTY);

    Piece pc = pieceAt(pos, mv.from);
    undo.captured = pieceAt(pos, mv.to);
    undo.halfMove = pos.halfMove;
    undo.fullMove = pos.fullMove;
    undo.enPassant = pos.enPassant;
    undo.castling = packCastling(pos);

    if (undo.captured != EMPTY) {
        clearCastlingForSquare(pos, mv.to);
        removePiece(pos, mv.to);
    }
    if (mv.isEnPassant) {
        int epR = R(mv.to);
        int capR = pos.sideToMove == WHITE ? epR - 1 : epR + 1;
        int capSq = capR * 8 + F(mv.to);
        assert(hasPiece(pos, capSq, W_PAWN) || hasPiece(pos, capSq, B_PAWN));
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
            assert(hasPiece(pos, rr * 8 + 7, rr == 0 ? W_ROOK : B_ROOK));
            movePiece(pos, rr * 8 + 7, rr * 8 + 5);
        } else if (F(mv.to) == 2) {
            assert(hasPiece(pos, rr * 8 + 0, rr == 0 ? W_ROOK : B_ROOK));
            movePiece(pos, rr * 8 + 0, rr * 8 + 3);
        }
    }

    pos.enPassant = -1;
    if (mv.isDoublePush) {
        int epR = pos.sideToMove == WHITE ? R(mv.from) + 1 : R(mv.from) - 1;
        pos.enPassant = epR * 8 + F(mv.from);
    }
    if (pt(pc) == 1 || undo.captured != EMPTY || mv.isEnPassant) pos.halfMove = 0;
    else pos.halfMove++;
    pos.sideToMove = pos.sideToMove == WHITE ? BLACK : WHITE;
    if (pos.sideToMove == WHITE) pos.fullMove++;
#ifdef CHESS_VALIDATE_STATE
    assert(representationConsistent(pos));
#endif
}

void undo(Position& pos, const Move& mv, const UndoState& undoState) {
    assert(mv.from >= 0 && mv.from < 64);
    assert(mv.to >= 0 && mv.to < 64);

    pos.sideToMove = pos.sideToMove == WHITE ? BLACK : WHITE;
    pos.halfMove = undoState.halfMove;
    pos.fullMove = undoState.fullMove;
    pos.enPassant = undoState.enPassant;
    restoreCastling(pos, undoState.castling);

    if (mv.isCastle) {
        int rr = R(mv.to);
        if (F(mv.to) == 6) {
            assert(hasPiece(pos, rr * 8 + 5, W_ROOK) || hasPiece(pos, rr * 8 + 5, B_ROOK));
            movePiece(pos, rr * 8 + 5, rr * 8 + 7);
        } else if (F(mv.to) == 2) {
            assert(hasPiece(pos, rr * 8 + 3, W_ROOK) || hasPiece(pos, rr * 8 + 3, B_ROOK));
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
        assert(pieceAt(pos, capSq) == EMPTY);
        addPiece(pos, capSq, restoredPawn);
    } else if (undoState.captured != EMPTY) {
        assert(pieceAt(pos, mv.to) == EMPTY);
        addPiece(pos, mv.to, undoState.captured);
    }
#ifdef CHESS_VALIDATE_STATE
    assert(representationConsistent(pos));
#endif
}
