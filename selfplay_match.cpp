#include "engine.h"
#include "selfplay_match.h"
#include "match_statistics.h"
#include "third_party/picosha2.h"
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <numeric>
#include <random>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#include <sys/stat.h>
#else
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#endif

#ifndef CHILO_MATCH_SOURCE_REV
#define CHILO_MATCH_SOURCE_REV "unknown"
#endif

namespace {
using nlohmann::json;
namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
volatile std::sig_atomic_t stopping = 0;
void stopSignal(int) { stopping = 1; }
void require(bool ok, const std::string& message) { if (!ok) throw std::runtime_error(message); }
std::string digest(const std::string& text) { return picosha2::hash256_hex_string(text); }
std::string readText(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    require(bool(stream), "cannot read " + path.string());
    std::ostringstream text; text << stream.rdbuf();
    require(!stream.bad(), "read failed: " + path.string());
    return text.str();
}
json readJson(const fs::path& path) { return json::parse(readText(path)); }
json identity(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    require(bool(stream), "cannot hash " + path.string());
    picosha2::hash256_one_by_one hash;
    std::array<char,65536> buffer;
    uint64_t size=0;
    while (stream) { stream.read(buffer.data(),buffer.size()); const auto n=stream.gcount(); hash.process(buffer.begin(),buffer.begin()+n); size+=n; }
    require(stream.eof(), "hash read failed: " + path.string());
    hash.finish();
    return {{"sha256",picosha2::get_hash_hex_string(hash)}, {"size",size}};
}
void durableWrite(const fs::path& path, const std::string& text, bool append) {
#ifdef _WIN32
    int fd = _wopen(path.c_str(), _O_WRONLY|_O_CREAT|_O_BINARY|(append?_O_APPEND:_O_TRUNC), _S_IREAD|_S_IWRITE);
#else
    int fd = ::open(path.c_str(), O_WRONLY|O_CREAT|(append?O_APPEND:O_TRUNC), 0666);
#endif
    require(fd>=0,"cannot write " + path.string());
    size_t done=0;
    bool ok=true;
    while (done<text.size()) {
#ifdef _WIN32
        const auto n=_write(fd,text.data()+done,static_cast<unsigned>(std::min<size_t>(text.size()-done,1<<20)));
#else
        const auto n=::write(fd,text.data()+done,text.size()-done);
#endif
        if (n<0 && errno==EINTR) continue;
        if (n<=0) { ok=false; break; }
        done+=size_t(n);
    }
#ifdef _WIN32
    if (_commit(fd)!=0) ok=false;
    _close(fd);
#else
    if (::fsync(fd)!=0) ok=false;
    ::close(fd);
#endif
    require(ok,"write/flush failed: " + path.string());
}
void atomicJson(const fs::path& path, const json& value) {
    const fs::path temporary=path.string()+".tmp";
    durableWrite(temporary,value.dump(2)+"\n",false);
#ifdef _WIN32
    require(MoveFileExW(temporary.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH),"atomic replacement failed");
#else
    fs::rename(temporary,path);
    int fd=::open(path.parent_path().c_str(),O_RDONLY|O_DIRECTORY);
    require(fd>=0,"cannot open run directory for sync");
    const bool ok=::fsync(fd)==0; ::close(fd); require(ok,"directory sync failed");
#endif
}
struct RunLock {
#ifdef _WIN32
    HANDLE handle;
    explicit RunLock(const fs::path& path) : handle(CreateFileW(path.c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr)) {
        require(handle!=INVALID_HANDLE_VALUE,"run is locked or lock file inaccessible");
    }
    ~RunLock() { CloseHandle(handle); }
#else
    int fd;
    explicit RunLock(const fs::path& path) : fd(::open(path.c_str(),O_RDWR|O_CREAT,0666)) {
        require(fd>=0,"cannot open run lock");
        if (flock(fd,LOCK_EX|LOCK_NB)!=0) { ::close(fd); throw std::runtime_error("run is locked"); }
    }
    ~RunLock() { ::close(fd); }
#endif
};
fs::path executablePath() {
#ifdef _WIN32
    std::vector<wchar_t> path(32768);
    const auto n=GetModuleFileNameW(nullptr,path.data(),static_cast<DWORD>(path.size()));
    require(n>0 && n<path.size(),"cannot resolve executable"); return fs::path(std::wstring(path.data(),n));
#else
    return fs::read_symlink("/proc/self/exe");
#endif
}
void keys(const json& value, std::initializer_list<const char*> allowed) {
    require(value.is_object(),"expected config object");
    for (auto it=value.begin();it!=value.end();++it) {
        bool found=false; for (auto key:allowed) if(it.key()==key) found=true;
        require(found,"unknown config key: " + it.key());
    }
}
uint64_t integer(const json& value, uint64_t low, uint64_t high, const char* name) {
    require(value.is_number_integer(),std::string(name)+" must be an integer");
    require(!value.is_number_integer() || value.is_number_unsigned() || value.get<int64_t>()>=0,std::string(name)+" must be nonnegative");
    const uint64_t n=value.get<uint64_t>();
    require(n>=low && n<=high,std::string(name)+" out of range"); return n;
}
struct Player { std::string name; SearchParameters parameters; };
struct Settings {
    Player players[2];
    fs::path weights, openings;
    uint64_t nodes=120000, maxPairs=26000, seed=1;
    int resignCount=3, resignScore=600, drawNumber=34, drawCount=8, drawScore=20, maxMoves=200;
    bool shuffle=true;
    matchplay::SprtSettings sprt;
    json effective;
};
Settings settings(const fs::path& path) {
    const auto input=readJson(path);
    keys(input,{"schema","players","weights","openings","budget","sprt","max_pairs","adjudication"});
    require(input.at("schema")=="chilo.selfplay_match.v1","unsupported config schema");
    Settings s;
    const auto& players=input.at("players");
    require(players.is_array() && players.size()==2,"exactly two players required");
    json effectivePlayers=json::array();
    for(int i=0;i<2;++i) {
        keys(players[i],{"name","parameters"});
        s.players[i].name=players[i].at("name").get<std::string>();
        require(!s.players[i].name.empty(),"empty player name");
        const auto& parameters=players[i].at("parameters"); keys(parameters,{"futility_margins"});
        const auto& margins=parameters.at("futility_margins");
        require(margins.is_array() && margins.size()<=MAX_FUTILITY_DEPTH,"futility margins must be an array of at most seven entries");
        s.players[i].parameters.futilityMaxDepth=int(margins.size());
        s.players[i].parameters.futilityMargins.fill(0);
        for(size_t j=0;j<margins.size();++j) s.players[i].parameters.futilityMargins[j+1]=int(integer(margins[j],0,1000000,"futility margin"));
        effectivePlayers.push_back(players[i]);
    }
    require(s.players[0].name!=s.players[1].name,"player names must differ");
    s.weights=fs::weakly_canonical(path.parent_path()/input.at("weights").get<std::string>());
    const auto& opening=input.at("openings"); keys(opening,{"file","order","seed"});
    s.openings=fs::weakly_canonical(path.parent_path()/opening.at("file").get<std::string>());
    const std::string order=opening.value("order","random");
    require(order=="random" || order=="sequential","opening order must be random or sequential");
    s.shuffle=order=="random"; s.seed=integer(opening.value("seed",json(1)),0,UINT64_MAX,"seed");
    const auto budget=input.value("budget",json{{"mode","fixed_nodes_per_move"},{"nodes",120000}});
    keys(budget,{"mode","nodes"}); require(budget.at("mode")=="fixed_nodes_per_move","unsupported budget mode");
    s.nodes=integer(budget.at("nodes"),1,INT64_MAX,"nodes");
    s.maxPairs=integer(input.value("max_pairs",json(26000)),1,INT32_MAX,"max_pairs");
    const auto sprt=input.value("sprt",json::object()); keys(sprt,{"model","elo0","elo1","alpha","beta"});
    require(sprt.value("model","normalized")=="normalized","only normalized pentanomial SPRT is supported");
    s.sprt={sprt.value("elo0",0.0),sprt.value("elo1",2.0),sprt.value("alpha",.05),sprt.value("beta",.05)};
    require(std::isfinite(s.sprt.elo0) && std::isfinite(s.sprt.elo1) && s.sprt.elo0<s.sprt.elo1,"invalid SPRT hypotheses");
    require(s.sprt.alpha>0 && s.sprt.beta>0 && s.sprt.alpha+s.sprt.beta<1,"invalid SPRT alpha/beta");
    const auto adjud=input.value("adjudication",json::object()); keys(adjud,{"resign","draw","maxmoves"});
    const auto resign=adjud.value("resign",json::object()); keys(resign,{"movecount","score"});
    const auto draw=adjud.value("draw",json::object()); keys(draw,{"movenumber","movecount","score"});
    s.resignCount=int(integer(resign.value("movecount",json(3)),0,1000,"resign movecount"));
    s.resignScore=int(integer(resign.value("score",json(600)),1,SEARCH_MATE_THRESHOLD-1,"resign score"));
    s.drawNumber=int(integer(draw.value("movenumber",json(34)),0,1000000,"draw movenumber"));
    s.drawCount=int(integer(draw.value("movecount",json(8)),0,1000,"draw movecount"));
    s.drawScore=int(integer(draw.value("score",json(20)),0,SEARCH_MATE_THRESHOLD-1,"draw score"));
    s.maxMoves=int(integer(adjud.value("maxmoves",json(200)),1,1000000,"maxmoves"));
    s.effective={{"schema","chilo.selfplay_match.v1"},{"players",effectivePlayers},
        {"budget",{{"mode","fixed_nodes_per_move"},{"nodes",s.nodes}}},
        {"openings",{{"order",order},{"seed",s.seed}}},{"max_pairs",s.maxPairs},
        {"sprt",{{"model","normalized"},{"elo0",s.sprt.elo0},{"elo1",s.sprt.elo1},{"alpha",s.sprt.alpha},{"beta",s.sprt.beta}}},
        {"adjudication",{{"resign",{{"movecount",s.resignCount},{"score",s.resignScore}}},
          {"draw",{{"movenumber",s.drawNumber},{"movecount",s.drawCount},{"score",s.drawScore}}},{"maxmoves",s.maxMoves}}}};
    return s;
}

// Validate before calling the engine's deliberately lightweight FEN parser.
std::string normalizedFen(const std::string& line) {
    std::istringstream in(line);
    std::string board,side,castle,ep,half,full;
    require(bool(in>>board>>side>>castle>>ep),"opening needs four FEN/EPD fields");
    int squares=0,ranks=1,wk=0,bk=0;
    for(char c:board) {
        if(c=='/') { require(squares==8,"invalid FEN rank"); squares=0; ++ranks; }
        else if(c>='1' && c<='8') squares+=c-'0';
        else { require(std::string("pnbrqkPNBRQK").find(c)!=std::string::npos,"invalid FEN piece"); ++squares; wk+=c=='K'; bk+=c=='k'; }
        require(squares<=8,"invalid FEN rank width");
    }
    require(ranks==8 && squares==8 && wk==1 && bk==1,"invalid FEN board/kings");
    require(side=="w" || side=="b","invalid FEN side");
    require(castle=="-" || (!castle.empty() && castle.find_first_not_of("KQkq")==std::string::npos),"invalid FEN castling");
    require(ep=="-" || (ep.size()==2 && ep[0]>='a' && ep[0]<='h' && ep[1]==(side=="w"?'6':'3')),"invalid FEN en passant");
    int h=0,f=1;
    if(in>>half) {
        if(std::all_of(half.begin(),half.end(),[](char c){return c>='0' && c<='9';})) {
            require(bool(in>>full),"missing FEN fullmove");
            require(full.find_first_not_of("0123456789")==std::string::npos,"invalid FEN fullmove");
            h=std::stoi(half); f=std::max(1,std::stoi(full));
        } else {
            require(half[0]!='-' && half[0]!='+',"invalid FEN counter");
            // EPD's optional hmvc/fmvn operations set starting counters.
            std::string rest; std::getline(in,rest);
            std::istringstream operations(half+rest); std::string operation;
            while(std::getline(operations,operation,';')) {
                std::istringstream words(operation); std::string name,value; words>>name;
                if(name=="hmvc" || name=="fmvn") {
                    require(bool(words>>value) && value.find_first_not_of("0123456789")==std::string::npos,"invalid EPD counter");
                    if(name=="hmvc") h=std::stoi(value); else f=std::max(1,std::stoi(value));
                }
            }
        }
    }
    require(h<=1000000 && f<=1000000,"opening counters too large");
    const auto fen=board+" "+side+" "+castle+" "+ep+" "+std::to_string(h)+" "+std::to_string(f);
    const auto pos=parseFEN(fen);
    const int kingSquares[]={4,4,60,60}, rookSquares[]={7,0,63,56};
    for(int i=0;i<4;++i) if(pos.castling[i]) {
        require(pos.pieceAtSquare[kingSquares[i]]==(i<2?W_KING:B_KING) && pos.pieceAtSquare[rookSquares[i]]==(i<2?W_ROOK:B_ROOK),"invalid castling right");
    }
    if(pos.enPassant>=0) require(pos.pieceAtSquare[pos.enPassant]==EMPTY && pos.pieceAtSquare[pos.enPassant+(pos.sideToMove==WHITE?-8:8)]==(pos.sideToMove==WHITE?B_PAWN:W_PAWN),"invalid en passant pawn");
    require(!inCheck(pos,Color(pos.sideToMove^1)),"opening has the nonmoving king in check");
    for(int sq=0;sq<64;++sq) if(R(sq)==0 || R(sq)==7) require(pos.pieceAtSquare[sq]!=W_PAWN && pos.pieceAtSquare[sq]!=B_PAWN,"pawn on back rank");
    return positionToFEN(pos);
}
std::vector<std::string> loadOpenings(const Settings& s) {
    std::ifstream input(s.openings); require(bool(input),"cannot open opening file");
    std::vector<std::string> result; std::set<std::string> seen; std::string line;
    size_t number=0;
    while(std::getline(input,line)) {
        ++number;
        const auto first=line.find_first_not_of(" \t\r");
        if(first==std::string::npos || line[first]=='#') continue;
        try { auto fen=normalizedFen(line); require(seen.insert(fen).second,"duplicate opening"); result.push_back(fen); }
        catch(const std::exception& e) { throw std::runtime_error("opening line "+std::to_string(number)+": "+e.what()); }
    }
    require(!result.empty(),"no openings"); return result;
}
bool insufficient(const Position& p) {
    std::vector<int> pieces;
    for(int sq=0;sq<64;++sq) if(p.pieceAtSquare[sq]!=EMPTY) pieces.push_back(sq);
    if(pieces.size()==2) return true;
    auto minor=[](Piece piece){return piece==W_KNIGHT||piece==B_KNIGHT||piece==W_BISHOP||piece==B_BISHOP;};
    if(pieces.size()==3) for(int sq:pieces) if(minor(p.pieceAtSquare[sq])) return true;
    if(pieces.size()==4) {
        std::vector<int> bishops;
        for(int sq:pieces) if(p.pieceAtSquare[sq]==W_BISHOP || p.pieceAtSquare[sq]==B_BISHOP) bishops.push_back(sq);
        if(bishops.size()==2) return ((R(bishops[0])+F(bishops[0]))&1)==((R(bishops[1])+F(bishops[1]))&1);
    }
    return false;
}
std::string repetitionKey(const Position& p, const Move* moves, int count) {
    std::istringstream in(positionToFEN(p)); std::string board,side,castle,ep; in>>board>>side>>castle>>ep;
    bool legalEp=false; for(int i=0;i<count;++i) legalEp |= moves[i].isEnPassant;
    return board+" "+side+" "+castle+" "+(legalEp?ep:"-");
}

struct Referee {
    const Settings& settings;
    std::unordered_map<std::string,int> repetitions;
    int resign[2]={0,0}, draw=0, lastScore=0, lastColor=-1, whiteResult=0;
    std::string reason;
    explicit Referee(const Settings& s) : settings(s) {}
    bool finished(const Position& pos, const Move* legal, int count, size_t plies) {
        if(!count) { reason=inCheck(pos,pos.sideToMove)?"checkmate":"stalemate"; whiteResult=reason=="checkmate"?(pos.sideToMove==WHITE?-1:1):0; return true; }
        if(insufficient(pos)) { reason="insufficient_material"; return true; }
        if(pos.halfMove>=100) { reason="fifty_move"; return true; }
        if(++repetitions[repetitionKey(pos,legal,count)]>=3) { reason="threefold_repetition"; return true; }
        if(settings.resignCount && lastScore<0 && (resign[0]>=settings.resignCount || resign[1]>=settings.resignCount)) {
            reason="resign_adjudication"; whiteResult=lastColor==WHITE?-1:1; return true;
        }
        if(settings.drawCount && pos.fullMove-1>=settings.drawNumber && draw>=2*settings.drawCount) { reason="draw_adjudication"; return true; }
        if(plies>=size_t(2*settings.maxMoves)) { reason="maxmoves"; return true; }
        return false;
    }
    void played(Color color, int score, const Position& after) {
        lastScore=score; lastColor=color;
        if((!isMateScore(score) && score<=-settings.resignScore) || (isMateScore(score) && score<0)) ++resign[color]; else resign[color]=0;
        if(after.halfMove==0) draw=0;
        if(!isMateScore(score) && std::abs(score)<=settings.drawScore) ++draw; else draw=0;
    }
};

// Future game-allowance policies can own per-player balances here. Actual
// search work, including interrupted iterations, is always accounted for.
struct FixedNodeBudget {
    uint64_t cap, used=0;
    explicit FixedNodeBudget(uint64_t nodes) : cap(nodes) {}
    void startGame() { used=0; }
    SearchLimits nextLimits(const Position&, const SearchParameters& parameters) const {
        SearchLimits limits{MAX_SEARCH_DEPTH,0,nullptr,nullptr}; limits.nodeLimit=cap; limits.parameters=parameters; return limits;
    }
    void account(const SearchResult& result) { used+=result.nodes; }
};
json playGame(const Settings& s, const std::string& fen, uint64_t gameIndex, uint64_t openingIndex) {
    SearchContext contexts[2];
    Position pos=parseFEN(fen);
    for(auto& context:contexts) resetDrawHistory(context,pos);
    FixedNodeBudget budgets[2]={FixedNodeBudget(s.nodes),FixedNodeBudget(s.nodes)};
    for(auto& budget:budgets) budget.startGame();
    const int whitePlayer=int(gameIndex%2);
    Referee referee(s);
    json moves=json::array();
    const auto start=Clock::now();
    while(true) {
        Move legal[MAX_MOVES]; const int count=genLegalMoves(pos,legal);
        if(referee.finished(pos,legal,count,moves.size())) break;
        const int player=pos.sideToMove==WHITE?whitePlayer:1-whitePlayer;
        const auto result=searchBestMove(contexts[player],pos,budgets[player].nextLimits(pos,s.players[player].parameters));
        require(result.hasMove,"search returned no move in a nonterminal position");
        Move chosen;
        require(parseUCIMove(pos,moveToUCI(result.bestMove),chosen),"search returned an illegal move");
        budgets[player].account(result);
        moves.push_back({{"uci",moveToUCI(chosen)},{"player",player},{"score",result.score},{"mate",isMateScore(result.score)},
            {"depth",result.depth},{"nodes",result.nodes},{"completed_nodes",result.completedNodes},{"elapsed_ms",result.totalElapsedMs}});
        Position before=pos; UndoState undo; doMove(pos,chosen,undo);
        for(auto& context:contexts) recordRealMoveForDrawHistory(context,before,chosen,pos);
        referee.played(before.sideToMove,result.score,pos);
    }
    const int aScore=1+(whitePlayer==0?referee.whiteResult:-referee.whiteResult);
    return {{"index",gameIndex},{"pair",gameIndex/2},{"opening_index",openingIndex},{"fen",fen},
        {"white_player",whitePlayer},{"a_score",aScore},{"reason",referee.reason},{"moves",moves},
        {"nodes",{budgets[0].used,budgets[1].used}},{"elapsed_ms",std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now()-start).count()}};
}

struct Journal {
    uint64_t games=0, nodes=0, elapsed=0;
    int firstScore=0;
    matchplay::PairStats stats;
    void accept(const json& game, const std::vector<std::string>& openings, const std::vector<size_t>& order) {
        require(game.at("index")==games && game.at("pair")==games/2,"journal sequence mismatch");
        require(games/2<order.size(),"journal exceeds opening schedule");
        require(game.at("opening_index")==order[games/2] && game.at("fen")==openings[order[games/2]],"journal opening mismatch");
        require(game.at("white_player")==games%2,"journal colors mismatch");
        const int score=int(integer(game.at("a_score"),0,2,"game result"));
        if(games%2) stats.addPair(firstScore,score); else firstScore=score;
        for(const auto& n:game.at("nodes")) nodes+=n.get<uint64_t>();
        elapsed+=game.at("elapsed_ms").get<uint64_t>(); ++games;
    }
};
Journal loadJournal(const fs::path& path, const std::vector<std::string>& openings, const std::vector<size_t>& order) {
    Journal journal;
    if(!fs::exists(path)) return journal;
    std::ifstream input(path,std::ios::binary); require(bool(input),"cannot read journal");
    std::string line; uint64_t validBytes=0;
    while(std::getline(input,line)) {
        // A newline is the commit marker, even if the JSON itself is complete.
        if(input.eof()) { input.close(); fs::resize_file(path,validBytes); return journal; }
        const auto entry=json::parse(line);
        require(entry.at("sha256")==digest(entry.at("game").dump()),"journal checksum mismatch");
        journal.accept(entry.at("game"),openings,order); validBytes+=line.size()+1;
    }
    require(input.eof(),"journal read failed"); return journal;
}
}

int runSelfplayMatch(int argc, char** argv) {
    fs::path config,root;
    bool resume=false;
    try {
        for(int i=1;i<argc;++i) {
            const std::string arg=argv[i];
            if(arg=="--resume") resume=true;
            else if((arg=="--match-config" || arg=="--run-dir") && i+1<argc) {
                if(arg=="--match-config") config=fs::absolute(argv[++i]); else root=fs::absolute(argv[++i]);
            } else throw std::runtime_error("match usage: selfplay_collect --match-config CONFIG --run-dir DIR [--resume]");
        }
        require(!config.empty() && !root.empty(),"--match-config and --run-dir are required");
        const auto s=settings(config);
        const auto openings=loadOpenings(s);
        fs::create_directories(root); RunLock lock(root/"run.lock");
        json contract={{"settings",s.effective},{"weights",identity(s.weights)},{"openings",identity(s.openings)},
            {"executable",identity(executablePath())},{"source_revision",CHILO_MATCH_SOURCE_REV},{"fastchess_reference","072859b"}};
        std::vector<size_t> order(openings.size()); std::iota(order.begin(),order.end(),0);
        if(fs::exists(root/"manifest.json")) {
            require(resume,"run already exists; use --resume");
            const auto manifest=readJson(root/"manifest.json");
            require(manifest.at("schema")=="chilo.selfplay_match_manifest.v1","unsupported manifest schema");
            require(manifest.at("contract")==contract && manifest.at("contract_sha256")==digest(contract.dump()),"resume contract mismatch");
            order=manifest.at("opening_order").get<std::vector<size_t>>();
            require(manifest.at("opening_order_sha256")==digest(json(order).dump()),"opening schedule checksum mismatch");
            auto sorted=order; std::sort(sorted.begin(),sorted.end());
            require(sorted.size()==openings.size(),"invalid opening schedule");
            for(size_t i=0;i<sorted.size();++i) require(sorted[i]==i,"invalid opening schedule");
        } else {
            require(!resume,"cannot resume without manifest");
            for(const auto& entry:fs::directory_iterator(root)) require(entry.path().filename()=="run.lock","run directory is not empty");
            if(s.shuffle) { std::mt19937_64 rng(s.seed); std::shuffle(order.begin(),order.end(),rng); }
            atomicJson(root/"manifest.json",{{"schema","chilo.selfplay_match_manifest.v1"},{"contract",contract},{"contract_sha256",digest(contract.dump())},{"opening_order",order},{"opening_order_sha256",digest(json(order).dump())},
                {"weights_path",s.weights.string()},{"openings_path",s.openings.string()}});
        }
        auto journal=loadJournal(root/"games.jsonl",openings,order);
        require(journal.games<=2*s.maxPairs,"journal exceeds game limit");
        std::string error;
        const bool loaded=loadNnueWeightsFile(s.weights.string(),error);
        require(loaded,"cannot load weights: "+error);
        stopping=0; std::signal(SIGINT,stopSignal); std::signal(SIGTERM,stopSignal);
        auto publish=[&](const std::string& status) {
            auto value=matchplay::statistics(journal.stats,s.sprt);
            value["schema"]="chilo.selfplay_match_results.v1"; value["status"]=status;
            value["outcome"]=(status=="max_pairs" || status=="openings_exhausted") ? json("inconclusive") :
                ((status=="H0" || status=="H1") ? json(status) : json(nullptr));
            value["completed_games"]=journal.games; value["total_nodes"]=journal.nodes; value["game_elapsed_ms"]=journal.elapsed;
            value["contract_sha256"]=digest(contract.dump()); value["players"]=s.effective["players"];
            atomicJson(root/"status.json",value);
            if(status!="running" && status!="stopped") atomicJson(root/"results.json",value);
        };
        while(true) {
            const auto stats=matchplay::statistics(journal.stats,s.sprt);
            if(stats["decision"]!="continue") { publish(stats["decision"].get<std::string>()); break; }
            if(journal.games==2*s.maxPairs) { publish("max_pairs"); break; }
            if(journal.games==2*order.size()) { publish("openings_exhausted"); break; }
            if(journal.games%2==0 && (stopping || fs::exists(root/"STOP"))) { publish("stopped"); break; }
            publish("running");
            const size_t opening=order[journal.games/2];
            std::cout<<"match game="<<journal.games+1<<" pair="<<journal.games/2+1<<" start"<<std::endl;
            const auto game=playGame(s,openings[opening],journal.games,opening);
            durableWrite(root/"games.jsonl",json{{"game",game},{"sha256",digest(game.dump())}}.dump()+"\n",true);
            journal.accept(game,openings,order);
            if(journal.games%2==0) std::cout<<"match "<<matchplay::statistics(journal.stats,s.sprt).dump()<<std::endl;
        }
        std::cout<<"match finished: "<<(root/"status.json").string()<<std::endl;
        return 0;
    } catch(const std::exception& e) {
        std::cerr<<"fatal: "<<e.what()<<std::endl;
        return 1;
    }
}
