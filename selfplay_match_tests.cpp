// White-box tests exercise the match referee without asking the search to
// produce a particular sequence of moves or adjudication scores.
#include "selfplay_match.cpp"
#include <functional>

namespace {
constexpr const char* STARTPOS_FEN="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
void close(double actual,double expected,double tolerance=0.01) {
    require(std::isfinite(actual) && std::abs(actual-expected)<tolerance,"numeric mismatch: "+std::to_string(actual)+" vs "+std::to_string(expected));
}
void testStatistics() {
    matchplay::SprtSettings s;
    matchplay::PairStats stats;
    stats.bins={365,16618,36229,16974,390};
    close(matchplay::normalizedLLR(stats,s),2.25);
    stats.bins={127,4883,10712,5150,104}; s.elo0=-1.75; s.elo1=.25;
    close(matchplay::normalizedLLR(stats,s),3.01);
    stats.bins={0,0,0,0,5550}; s={0,5,.05,.05};
    close(matchplay::normalizedLLR(stats,s),111.82,.05); // upstream rounded fixture uses 1% tolerance
    stats={}; s={};
    require(matchplay::statistics(stats,s)["elo"].is_null(),"empty Elo");
    for(int a=0;a<3;++a) for(int b=0;b<3;++b) stats.addPair(a,b);
    require(stats.bins==std::array<uint64_t,5>{1,2,3,2,1},"pair bin mapping");
    require(stats.wl==2 && stats.dd==1 && stats.wins==6 && stats.draws==6 && stats.losses==6,"pair diagnostics");
    const auto report=matchplay::statistics(stats,s);
    close(report["score"],.5,1e-12); close(report["los"],.5,1e-12);
    close(report["pair_score_variance"],1.0/12,1e-12);
    stats={}; stats.addPair(1,1);
    require(matchplay::statistics(stats,s)["normalized_elo"].is_null(),"degenerate normalized Elo");
    require(matchplay::statistics(stats,s)["elo_error95"].is_null(),"degenerate error");
}
void compareSearch(const SearchResult& a,const SearchResult& b) {
    require(a.score==b.score && a.depth==b.depth && a.nodes==b.nodes && a.completedNodes==b.completedNodes && moveToUCI(a.bestMove)==moveToUCI(b.bestMove),"context search differs");
    require(a.pvLength==b.pvLength,"PV length differs");
    for(int i=0;i<a.pvLength;++i) require(moveToUCI(a.pv[i])==moveToUCI(b.pv[i]),"PV differs");
}
void testContexts() {
    SearchContext a,b,control;
    auto pos=parseFEN(STARTPOS_FEN);
    SearchLimits limits{MAX_SEARCH_DEPTH,0,nullptr,nullptr}; limits.nodeLimit=2000;
    auto result=searchBestMove(a,pos,limits); compareSearch(result,searchBestMove(control,pos,limits));
    for(const auto* uci:{"e2e4","e7e5","g1f3","b8c6"}) {
        Move move; require(parseUCIMove(pos,uci,move),"test move illegal");
        Position before=pos; UndoState undo; doMove(pos,move,undo);
        recordRealMoveForDrawHistory(a,before,move,pos);
        recordRealMoveForDrawHistory(control,before,move,pos);
        SearchLimits other=limits; other.parameters.futilityMaxDepth=7; other.parameters.futilityMargins.fill(0);
        auto unrelated=parseFEN("4k3/8/8/8/8/8/3Q4/4K3 w - - 0 1");
        searchBestMove(b,unrelated,other);
        const auto fen=positionToFEN(pos); const auto hash=pos.hashKey;
        compareSearch(searchBestMove(a,pos,limits),searchBestMove(control,pos,limits));
        require(positionToFEN(pos)==fen && pos.hashKey==hash,"search altered position");
    }
    a.clearForNewGame(); control.clearForNewGame();
    compareSearch(searchBestMove(a,pos,limits),searchBestMove(control,pos,limits));
    limits.isolateTranspositionTable=true;
    compareSearch(searchBestMove(a,pos,limits),searchBestMove(pos,limits));
    pos=parseFEN(STARTPOS_FEN); resetDrawHistory(a,pos);
    for(int i=0;i<704;++i) {
        const char* moves[]={"g1f3","g8f6","f3g1","f6g8"}; Move move;
        require(parseUCIMove(pos,moves[i%4],move),"long-history move");
        Position before=pos; UndoState undo; doMove(pos,move,undo);
        recordRealMoveForDrawHistory(a,before,move,pos);
    }
    require(searchBestMove(a,pos,limits).hasMove,"long history search");
}
bool finished(Referee& r,const Position& p,size_t plies=0) {
    Move legal[MAX_MOVES]; int n=genLegalMoves(p,legal); return r.finished(p,legal,n,plies);
}
void testReferee() {
    Settings s; s.drawCount=0;s.resignCount=0;
    auto p=parseFEN(STARTPOS_FEN); Referee r(s);
    require(!finished(r,p),"initial draw");
    size_t ply=0;
    for(int repeat=0;repeat<2;++repeat) for(const auto* uci:{"g1f3","g8f6","f3g1","f6g8"}) {
        Move move; require(parseUCIMove(p,uci,move),"repetition move"); UndoState undo; doMove(p,move,undo); ++ply;
        require(finished(r,p,ply)==(ply==8),"incorrect repetition count");
    }
    require(r.reason=="threefold_repetition","repetition reason");
    const std::pair<const char*,const char*> cases[]={
        {"7k/6Q1/5K2/8/8/8/8/8 b - - 100 1","checkmate"},
        {"7k/5Q2/5K2/8/8/8/8/8 b - - 100 1","stalemate"},
        {"7k/8/5K2/8/8/8/8/8 b - - 0 1","insufficient_material"},
        {"7k/8/5K2/8/8/8/P7/8 b - - 100 1","fifty_move"}};
    for(const auto& item:cases) { Referee terminal(s); require(finished(terminal,parseFEN(item.first)),"missing terminal"); require(terminal.reason==item.second,"terminal precedence"); }
    require(!insufficient(parseFEN("7k/8/5K2/8/8/8/NN6/8 w - - 0 1")),"two knights cannot auto-draw");
    s.resignCount=3; Referee resign(s); p=parseFEN(STARTPOS_FEN);
    for(int i=0;i<3;++i) { resign.played(WHITE,-600,p); resign.played(BLACK,600,p); }
    // fastchess only adjudicates when the last mover's score is negative.
    require(!finished(resign,p),"wrong resignation side"); resign.played(WHITE,-600,p);
    require(finished(resign,p) && resign.whiteResult==-1,"resignation missing");
    s.drawCount=8; Referee draw(s); p.fullMove=35; p.halfMove=16;
    for(int i=0;i<16;++i) draw.played(Color(i%2),0,p);
    require(finished(draw,p),"draw threshold");
    Referee reset(s); for(int i=0;i<15;++i) reset.played(Color(i%2),0,p);
    p.halfMove=0; reset.played(BLACK,0,p); require(reset.draw==1,"irreversible draw counter reset");
    p.halfMove=1; reset.played(WHITE,SEARCH_MATE_SCORE-3,p); require(reset.draw==0,"mate must not count as draw score");
    Referee cap(s); require(finished(cap,p,400) && cap.reason=="maxmoves","maxmoves count");
    const auto ep1=parseFEN("7k/8/8/4p3/8/8/8/K7 w - e6 0 1");
    const auto ep2=parseFEN("7k/8/8/4p3/8/8/8/K7 w - - 0 1");
    Move legal[MAX_MOVES]; int n=genLegalMoves(ep1,legal);
    require(repetitionKey(ep1,legal,n)==repetitionKey(ep2,legal,n),"uncapturable EP repetition key");
    require(normalizedFen("7k/8/5K2/8/8/8/P7/8 b - - hmvc 17; fmvn 35;")=="7k/8/5K2/8/8/8/P7/8 b - - 17 35","EPD counters");
}
}
int main() {
    try {
        testStatistics(); std::cout<<"statistics PASS\n";
        testContexts(); std::cout<<"contexts PASS\n";
        testReferee(); std::cout<<"referee PASS\n";
        return 0;
    } catch(const std::exception& e) { std::cerr<<e.what()<<"\n"; return 1; }
}
