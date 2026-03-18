#include <iostream>
#include <string>
#include <vector>
using namespace std;

enum Piece { EMPTY, W_PAWN, W_KNIGHT, W_BISHOP, W_ROOK, W_QUEEN, W_KING,
             B_PAWN, B_KNIGHT, B_BISHOP, B_ROOK, B_QUEEN, B_KING };
enum Color { WHITE, BLACK };

int R(int s) { return s >> 3; }
int F(int s) { return s & 7; }

int main() {
    // White pawn at e4 should attack d5 and f5
    Piece board[64] = {EMPTY};
    board[4*8+4] = W_PAWN;  // e4
    
    // Check pawn attacks
    cout << "White pawn at e4 (square " << 4*8+4 << ")" << endl;
    cout << "Attacks d5? " << (board[(4-1)*8+(4-1)] == W_PAWN ? "yes" : "no") << endl;
    cout << "Attacks f5? " << (board[(4-1)*8+(4+1)] == W_PAWN ? "yes" : "no") << endl;
    
    return 0;
}
