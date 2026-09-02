#include "engine.h"

#include <chrono>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef _WIN32
#include <process.h>
#else
#include <unistd.h>
#endif

namespace {

constexpr int DEFAULT_SEARCH_DEPTH = 7;
constexpr int DEFAULT_SITE_MAX_DEPTH = 5;
constexpr uint64_t DEFAULT_REPORT_EVERY = 100;

struct FileIdentity {
    std::filesystem::path path;
    std::string sha256;
    uint64_t size = 0;
};

struct Options {
    std::vector<std::string> inputPaths;
    std::string weightsPath;
    std::string outputPath;
    int depth = DEFAULT_SEARCH_DEPTH;
    int siteMaxDepth = DEFAULT_SITE_MAX_DEPTH;
    int minBeta = 0;
    uint64_t nodeLimit = 0;
    uint64_t maxRoots = 0;
    uint64_t maxSites = 0;
    uint64_t reportEvery = DEFAULT_REPORT_EVERY;
    uint64_t seed = 0;
    uint64_t rootSeed = 0;
    bool minBetaProvided = false;
    bool seedProvided = false;
    bool rootSeedProvided = false;
    bool helpRequested = false;
};

struct RunStats {
    uint64_t inputLines = 0;
    uint64_t skippedLines = 0;
    uint64_t parseErrors = 0;
    uint64_t validInputRoots = 0;
    uint64_t selectedRoots = 0;
    uint64_t acceptedRoots = 0;
    uint64_t completedRoots = 0;
    uint64_t interruptedRoots = 0;
    uint64_t eligibleSites = 0;
    uint64_t retainedSites = 0;
    uint64_t searchNodes = 0;
    uint64_t elapsedMs = 0;
};

std::string trim(const std::string& text) {
    std::size_t start = 0;
    while (start < text.size() && std::isspace(static_cast<unsigned char>(text[start]))) start++;
    std::size_t end = text.size();
    while (end > start && std::isspace(static_cast<unsigned char>(text[end - 1]))) end--;
    return text.substr(start, end - start);
}

void printUsage() {
    std::cout
        << "Usage: futility_site_collect --input <path> [--input <path> ...] --weights <path> --output <path>\n"
        << "                             --min-beta <cp> [options]\n"
        << "Options:\n"
        << "  -i, --input <path>          Root FEN/CSV input; repeatable\n"
        << "  -w, --weights <path>        Required external NNUE weights\n"
        << "  -o, --output <path>         New plain-FEN output path\n"
        << "  -d, --depth <N>             Fixed root search depth (default: 7)\n"
        << "      --node-limit <N>        Optional node cap per root (default: 0 = none)\n"
        << "      --site-max-depth <N>    Collect only residual depths 1..N (default: 5)\n"
        << "      --min-beta <cp>         Required strict beta floor for a non-losing site\n"
        << "      --max-roots <N>         Search at most N uniformly sampled input occurrences (default: 0 = all)\n"
        << "      --root-seed <N>         Required seed when --max-roots is positive\n"
        << "      --max-sites <N>         Keep at most N uniformly sampled occurrences (default: 0 = all)\n"
        << "      --report-every <N>      Report after N accepted roots (default: 100)\n"
        << "  -s, --seed <N>              Reservoir seed (default: time/process-derived)\n"
        << "  -h, --help                  Show this help\n";
}

bool parseInt(const std::string& text, int& value) {
    try {
        std::size_t consumed = 0;
        value = std::stoi(text, &consumed);
        return consumed == text.size();
    } catch (...) {
        return false;
    }
}

bool parsePositiveInt(const std::string& text, int& value) {
    return parseInt(text, value) && value > 0;
}

bool parseUInt64(const std::string& text, uint64_t& value) {
    if (text.empty() || text[0] == '-') return false;
    try {
        std::size_t consumed = 0;
        value = std::stoull(text, &consumed);
        return consumed == text.size();
    } catch (...) {
        return false;
    }
}

bool parseArgs(int argc, char** argv, Options& options) {
    for (int index = 1; index < argc; index++) {
        std::string argument = argv[index];
        auto requireValue = [&](const char* name) -> const char* {
            if (index + 1 >= argc) {
                std::cerr << "Missing value for " << name << "\n";
                return nullptr;
            }
            return argv[++index];
        };

        if (argument == "--help" || argument == "-h") {
            options.helpRequested = true;
            printUsage();
            return false;
        } else if (argument == "--input" || argument == "-i") {
            const char* value = requireValue("--input");
            if (value == nullptr) return false;
            options.inputPaths.emplace_back(value);
        } else if (argument == "--weights" || argument == "-w") {
            const char* value = requireValue("--weights");
            if (value == nullptr) return false;
            options.weightsPath = value;
        } else if (argument == "--output" || argument == "-o") {
            const char* value = requireValue("--output");
            if (value == nullptr) return false;
            options.outputPath = value;
        } else if (argument == "--depth" || argument == "-d") {
            const char* value = requireValue("--depth");
            if (value == nullptr || !parsePositiveInt(value, options.depth) || options.depth > MAX_SEARCH_DEPTH) return false;
        } else if (argument == "--node-limit") {
            const char* value = requireValue("--node-limit");
            if (value == nullptr || !parseUInt64(value, options.nodeLimit)) return false;
        } else if (argument == "--site-max-depth") {
            const char* value = requireValue("--site-max-depth");
            if (value == nullptr || !parsePositiveInt(value, options.siteMaxDepth) ||
                options.siteMaxDepth > MAX_FUTILITY_DEPTH) return false;
        } else if (argument == "--min-beta") {
            const char* value = requireValue("--min-beta");
            if (value == nullptr || !parseInt(value, options.minBeta)) return false;
            options.minBetaProvided = true;
        } else if (argument == "--max-roots") {
            const char* value = requireValue("--max-roots");
            if (value == nullptr || !parseUInt64(value, options.maxRoots)) return false;
        } else if (argument == "--root-seed") {
            const char* value = requireValue("--root-seed");
            if (value == nullptr || !parseUInt64(value, options.rootSeed)) return false;
            options.rootSeedProvided = true;
        } else if (argument == "--max-sites") {
            const char* value = requireValue("--max-sites");
            if (value == nullptr || !parseUInt64(value, options.maxSites)) return false;
        } else if (argument == "--report-every") {
            const char* value = requireValue("--report-every");
            if (value == nullptr || !parseUInt64(value, options.reportEvery) || options.reportEvery == 0) return false;
        } else if (argument == "--seed" || argument == "-s") {
            const char* value = requireValue("--seed");
            if (value == nullptr || !parseUInt64(value, options.seed)) return false;
            options.seedProvided = true;
        } else {
            std::cerr << "Unknown argument: " << argument << "\n";
            return false;
        }
    }

    if (options.inputPaths.empty() || options.weightsPath.empty() || options.outputPath.empty() || !options.minBetaProvided) {
        std::cerr << "--input, --weights, --output, and --min-beta are required\n";
        return false;
    }
    if (options.depth <= options.siteMaxDepth) {
        std::cerr << "--depth must exceed --site-max-depth so the requested residual depth is reachable\n";
        return false;
    }
    if (options.maxRoots > 0 && !options.rootSeedProvided) {
        std::cerr << "--root-seed is required when --max-roots is positive\n";
        return false;
    }
    if (options.maxRoots == 0 && options.rootSeedProvided) {
        std::cerr << "--root-seed requires a positive --max-roots\n";
        return false;
    }
    return true;
}

uint64_t splitmix64(uint64_t value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31);
}

uint64_t currentProcessId() {
#ifdef _WIN32
    return static_cast<uint64_t>(_getpid());
#else
    return static_cast<uint64_t>(getpid());
#endif
}

uint64_t generateDefaultSeed() {
    uint64_t steady = static_cast<uint64_t>(std::chrono::steady_clock::now().time_since_epoch().count());
    return splitmix64(steady ^ splitmix64(currentProcessId()));
}

std::string extractFenField(const std::string& line) {
    std::string text = trim(line);
    std::size_t comma = text.find(',');
    if (comma != std::string::npos) text = text.substr(0, comma);
    if (text.size() >= 2 && text.front() == '"' && text.back() == '"') text = text.substr(1, text.size() - 2);
    return trim(text);
}

bool isHeaderField(const std::string& field) {
    return field == "fen" || field == "eval_fen" || field == "root_fen";
}

bool looksLikeFen(const std::string& fen) {
    std::istringstream input(fen);
    std::string board;
    std::string side;
    std::string castling;
    std::string enPassant;
    if (!(input >> board >> side >> castling >> enPassant)) return false;
    if (side != "w" && side != "b") return false;
    if (enPassant != "-" && (enPassant.size() != 2 || enPassant[0] < 'a' || enPassant[0] > 'h' ||
                              enPassant[1] < '1' || enPassant[1] > '8')) return false;
    int ranks = 1;
    int files = 0;
    int whiteKings = 0;
    int blackKings = 0;
    for (char piece : board) {
        if (piece == '/') {
            if (files != 8) return false;
            ranks++;
            files = 0;
        } else if (piece >= '1' && piece <= '8') {
            files += piece - '0';
        } else {
            switch (piece) {
                case 'p': case 'n': case 'b': case 'r': case 'q': case 'k':
                case 'P': case 'N': case 'B': case 'R': case 'Q': case 'K':
                    files++;
                    if (piece == 'K') whiteKings++;
                    if (piece == 'k') blackKings++;
                    break;
                default:
                    return false;
            }
        }
        if (files > 8) return false;
    }
    return ranks == 8 && files == 8 && whiteKings == 1 && blackKings == 1;
}

std::string sha256File(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("failed to open for SHA-256: " + path.string());
    // Keep hashing in the same self-contained toolchain style as the existing
    // frontends: invoke the platform utility only for an immutable input file.
    std::string command = "sha256sum '";
    for (char character : path.string()) {
        if (character == '\'') command += "'\\''";
        else command += character;
    }
    command += "'";
    FILE* pipe = popen(command.c_str(), "r");
    if (pipe == nullptr) throw std::runtime_error("failed to start sha256sum");
    char buffer[256] = {};
    std::string line;
    if (fgets(buffer, sizeof(buffer), pipe) != nullptr) line = buffer;
    int status = pclose(pipe);
    if (status != 0 || line.size() < 64) throw std::runtime_error("sha256sum failed for " + path.string());
    return line.substr(0, 64);
}

FileIdentity identifyFile(const std::string& rawPath) {
    std::filesystem::path path = std::filesystem::absolute(rawPath);
    if (!std::filesystem::is_regular_file(path)) throw std::runtime_error("not a regular file: " + path.string());
    return {path, sha256File(path), static_cast<uint64_t>(std::filesystem::file_size(path))};
}

std::string jsonEscape(const std::string& text) {
    std::ostringstream output;
    for (unsigned char character : text) {
        switch (character) {
            case '"': output << "\\\""; break;
            case '\\': output << "\\\\"; break;
            case '\b': output << "\\b"; break;
            case '\f': output << "\\f"; break;
            case '\n': output << "\\n"; break;
            case '\r': output << "\\r"; break;
            case '\t': output << "\\t"; break;
            default:
                if (character < 0x20) {
                    output << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                           << static_cast<int>(character) << std::dec << std::setfill(' ');
                } else {
                    output << static_cast<char>(character);
                }
        }
    }
    return output.str();
}

std::string runGitCommand(const char* command) {
    FILE* pipe = popen(command, "r");
    if (pipe == nullptr) return "unknown";
    char buffer[256] = {};
    std::string output;
    if (fgets(buffer, sizeof(buffer), pipe) != nullptr) output = trim(buffer);
    int status = pclose(pipe);
    return status == 0 && !output.empty() ? output : "unknown";
}

std::filesystem::path manifestPathFor(const std::filesystem::path& output) {
    return std::filesystem::path(output.string() + ".manifest.json");
}

class RootReservoir {
public:
    RootReservoir(uint64_t capacity, uint64_t seed) : capacity_(capacity), rng_(seed) {}

    void add(const std::string& fen) {
        seen_++;
        if (roots_.size() < capacity_) {
            roots_.push_back(fen);
            return;
        }
        std::uniform_int_distribution<uint64_t> distribution(0, seen_ - 1);
        uint64_t replacement = distribution(rng_);
        if (replacement < capacity_) roots_[static_cast<std::size_t>(replacement)] = fen;
    }

    uint64_t seen() const { return seen_; }
    const std::vector<std::string>& roots() const { return roots_; }

private:
    uint64_t capacity_ = 0;
    uint64_t seen_ = 0;
    std::mt19937_64 rng_;
    std::vector<std::string> roots_;
};

class SiteReservoir {
public:
    SiteReservoir(uint64_t capacity, uint64_t seed, const std::filesystem::path& temporaryOutput)
        : capacity_(capacity), rng_(seed), temporaryOutput_(temporaryOutput) {
        if (capacity_ == 0) {
            stream_.open(temporaryOutput_);
            if (!stream_) throw std::runtime_error("failed to create temporary output " + temporaryOutput_.string());
        }
    }

    void add(const std::string& fen) {
        seen_++;
        if (capacity_ == 0) {
            stream_ << fen << '\n';
            if (!stream_) throw std::runtime_error("failed writing temporary output");
            return;
        }
        if (reservoir_.size() < capacity_) {
            reservoir_.push_back(fen);
            return;
        }
        std::uniform_int_distribution<uint64_t> distribution(0, seen_ - 1);
        uint64_t replacement = distribution(rng_);
        if (replacement < capacity_) reservoir_[static_cast<std::size_t>(replacement)] = fen;
    }

    uint64_t seen() const { return seen_; }
    uint64_t retained() const { return capacity_ == 0 ? seen_ : reservoir_.size(); }

    void finalize() {
        if (capacity_ == 0) {
            stream_.close();
            if (!stream_) throw std::runtime_error("failed closing temporary output");
            return;
        }
        std::ofstream output(temporaryOutput_);
        if (!output) throw std::runtime_error("failed to create temporary output " + temporaryOutput_.string());
        for (const std::string& fen : reservoir_) output << fen << '\n';
        if (!output) throw std::runtime_error("failed writing temporary output");
    }

private:
    uint64_t capacity_ = 0;
    uint64_t seen_ = 0;
    std::mt19937_64 rng_;
    std::filesystem::path temporaryOutput_;
    std::ofstream stream_;
    std::vector<std::string> reservoir_;
};

struct SiteCallbackData {
    SiteReservoir* reservoir = nullptr;
};

void collectFutilitySite(const std::string& fen, void* userData) {
    auto* data = static_cast<SiteCallbackData*>(userData);
    data->reservoir->add(fen);
}

bool extractInputFen(const std::string& line, RunStats& stats, std::string& fen) {
    stats.inputLines++;
    std::string text = trim(line);
    if (text.empty() || text[0] == '#') {
        stats.skippedLines++;
        return false;
    }
    fen = extractFenField(text);
    if (isHeaderField(fen)) {
        stats.skippedLines++;
        return false;
    }
    if (!looksLikeFen(fen)) {
        stats.parseErrors++;
        return false;
    }
    stats.validInputRoots++;
    return true;
}

void printProgress(const RunStats& stats, uint64_t totalRoots, std::chrono::steady_clock::time_point started) {
    uint64_t elapsedMs = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - started).count());
    double rootsPerSecond = elapsedMs == 0 ? 0.0 : static_cast<double>(stats.acceptedRoots) * 1000.0 / elapsedMs;
    std::cout << "Futility-site collection: roots " << stats.acceptedRoots << "/" << totalRoots
              << ", eligible " << stats.eligibleSites << ", retained " << stats.retainedSites
              << ", elapsed " << std::fixed << std::setprecision(1) << (elapsedMs / 1000.0) << "s";
    if (rootsPerSecond > 0.0 && totalRoots > stats.acceptedRoots) {
        std::cout << ", ETA " << std::setprecision(1) << ((totalRoots - stats.acceptedRoots) / rootsPerSecond) << "s";
    }
    std::cout << '\n';
}

void writeManifest(const std::filesystem::path& path, const std::vector<FileIdentity>& inputs,
                   const FileIdentity& weights, const FileIdentity& output, const Options& options,
                   const RunStats& stats) {
    std::filesystem::path temporary = std::filesystem::path(path.string() + ".tmp");
    std::ofstream stream(temporary);
    if (!stream) throw std::runtime_error("failed to create manifest " + temporary.string());

    stream << "{\n"
           << "  \"schema\": \"chilo.futility_site_corpus.v1\",\n"
           << "  \"source_commit\": \"" << jsonEscape(runGitCommand("git rev-parse HEAD 2>/dev/null")) << "\",\n"
           << "  \"source_dirty\": " << (runGitCommand("git status --porcelain 2>/dev/null") == "unknown" ? "false" : "true") << ",\n"
           << "  \"inputs\": [\n";
    for (std::size_t index = 0; index < inputs.size(); index++) {
        const FileIdentity& input = inputs[index];
        stream << "    {\"path\": \"" << jsonEscape(input.path.string()) << "\", \"sha256\": \""
               << input.sha256 << "\", \"size\": " << input.size << "}" << (index + 1 == inputs.size() ? "\n" : ",\n");
    }
    stream << "  ],\n"
           << "  \"weights\": {\"path\": \"" << jsonEscape(weights.path.string()) << "\", \"sha256\": \""
           << weights.sha256 << "\", \"size\": " << weights.size << "},\n"
           << "  \"search\": {\"root_depth\": " << options.depth << ", \"node_limit_per_root\": " << options.nodeLimit
           << ", \"futility_max_depth\": 0, \"isolate_transposition_table\": true},\n"
           << "  \"site_contract\": {\"non_root\": true, \"non_pv\": true, \"not_in_check\": true, \"has_nonpawn_material\": true, \"min_beta_exclusive\": " << options.minBeta
           << ", \"max_remaining_depth\": " << options.siteMaxDepth
           << ", \"later_quiet_nonchecking_move\": true, \"before_eval_alpha_margin_gate\": true},\n"
           << "  \"root_sampling\": {\"max_roots\": " << options.maxRoots << ", \"seed\": ";
    if (options.maxRoots == 0) stream << "null";
    else stream << options.rootSeed;
    stream << ", \"method\": \"" << (options.maxRoots == 0 ? "all_valid_input_occurrences" : "reservoir_occurrences") << "\"},\n"
           << "  \"site_sampling\": {\"seed\": " << options.seed << ", \"max_sites\": " << options.maxSites
           << ", \"method\": \"" << (options.maxSites == 0 ? "all_occurrences" : "reservoir_occurrences") << "\"},\n"
           << "  \"counts\": {\"input_lines\": " << stats.inputLines << ", \"skipped_lines\": " << stats.skippedLines
           << ", \"parse_errors\": " << stats.parseErrors << ", \"valid_input_roots\": " << stats.validInputRoots
           << ", \"selected_roots\": " << stats.selectedRoots << ", \"accepted_roots\": " << stats.acceptedRoots
           << ", \"completed_roots\": " << stats.completedRoots << ", \"interrupted_roots\": " << stats.interruptedRoots
           << ", \"eligible_sites\": " << stats.eligibleSites << ", \"retained_sites\": " << stats.retainedSites
           << ", \"search_nodes\": " << stats.searchNodes << ", \"elapsed_ms\": " << stats.elapsedMs << "},\n"
           << "  \"output\": {\"path\": \"" << jsonEscape(output.path.string()) << "\", \"sha256\": \""
           << output.sha256 << "\", \"size\": " << output.size << "}\n"
           << "}\n";
    if (!stream) throw std::runtime_error("failed writing manifest");
    stream.close();
    std::filesystem::rename(temporary, path);
}

}  // namespace

int main(int argc, char** argv) {
    try {
        Options options;
        if (!parseArgs(argc, argv, options)) return options.helpRequested ? 0 : 1;
        if (!options.seedProvided) options.seed = generateDefaultSeed();

        std::vector<FileIdentity> inputs;
        uint64_t totalRows = 0;
        for (const std::string& path : options.inputPaths) {
            inputs.push_back(identifyFile(path));
            std::ifstream input(path);
            std::string ignoredLine;
            while (std::getline(input, ignoredLine)) totalRows++;
        }
        FileIdentity weights = identifyFile(options.weightsPath);
        std::filesystem::path outputPath = std::filesystem::absolute(options.outputPath);
        std::filesystem::path manifestPath = manifestPathFor(outputPath);
        std::filesystem::path temporaryOutput = std::filesystem::path(outputPath.string() + ".tmp");
        if (std::filesystem::exists(outputPath) || std::filesystem::exists(manifestPath) || std::filesystem::exists(temporaryOutput)) {
            throw std::runtime_error("refusing to overwrite existing output, manifest, or temporary output");
        }

        std::string weightError;
        if (!loadNnueWeightsFile(weights.path.string(), weightError)) {
            throw std::runtime_error("failed to load NNUE weights: " + weightError);
        }
        std::cerr << "info string loaded NNUE weights from " << weights.path.string() << "\n";
        std::cout << "Using reservoir seed " << options.seed << "; futility is disabled for collection\n";

        SiteReservoir reservoir(options.maxSites, options.seed, temporaryOutput);
        SiteCallbackData callbackData{&reservoir};
        RunStats stats;
        auto started = std::chrono::steady_clock::now();

        std::vector<std::string> sampledRoots;
        if (options.maxRoots > 0) {
            RootReservoir rootReservoir(options.maxRoots, options.rootSeed);
            for (const FileIdentity& inputIdentity : inputs) {
                std::ifstream input(inputIdentity.path);
                if (!input) throw std::runtime_error("failed to open input " + inputIdentity.path.string());
                std::string line;
                while (std::getline(input, line)) {
                    std::string fen;
                    if (extractInputFen(line, stats, fen)) rootReservoir.add(fen);
                }
            }
            sampledRoots = rootReservoir.roots();
            stats.selectedRoots = static_cast<uint64_t>(sampledRoots.size());
            std::cout << "Root sampling: selected " << stats.selectedRoots << " of " << stats.validInputRoots
                      << " valid input occurrences with seed " << options.rootSeed << "\n";
        }

        const uint64_t totalRoots = options.maxRoots > 0 ? stats.selectedRoots : totalRows;
        SearchLimits limits{};
        limits.depth = options.depth;
        limits.nodeLimit = options.nodeLimit;
        limits.parameters.futilityMaxDepth = 0;
        limits.isolateTranspositionTable = true;
        limits.futilitySiteMaxDepth = options.siteMaxDepth;
        limits.futilitySiteMinBeta = options.minBeta;
        limits.futilitySiteCallback = collectFutilitySite;
        limits.futilitySiteUserData = &callbackData;
        auto searchRoot = [&](const std::string& fen) {
            Position position = parseFEN(fen);
            resetDrawHistory(position);
            stats.acceptedRoots++;
            SearchResult result = searchBestMove(position, limits);
            stats.searchNodes += result.nodes;
            if (result.completed) stats.completedRoots++;
            else stats.interruptedRoots++;
            stats.eligibleSites = reservoir.seen();
            stats.retainedSites = reservoir.retained();
            if (stats.acceptedRoots % options.reportEvery == 0) printProgress(stats, totalRoots, started);
        };

        if (options.maxRoots > 0) {
            for (const std::string& fen : sampledRoots) searchRoot(fen);
        } else {
            for (const FileIdentity& inputIdentity : inputs) {
                std::ifstream input(inputIdentity.path);
                if (!input) throw std::runtime_error("failed to open input " + inputIdentity.path.string());
                std::string line;
                while (std::getline(input, line)) {
                    std::string fen;
                    if (extractInputFen(line, stats, fen)) searchRoot(fen);
                }
            }
            stats.selectedRoots = stats.validInputRoots;
        }

        reservoir.finalize();
        std::filesystem::rename(temporaryOutput, outputPath);
        stats.eligibleSites = reservoir.seen();
        stats.retainedSites = reservoir.retained();
        stats.elapsedMs = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - started).count());
        FileIdentity output = identifyFile(outputPath.string());
        writeManifest(manifestPath, inputs, weights, output, options, stats);
        if (stats.acceptedRoots == 0 || stats.acceptedRoots % options.reportEvery != 0) {
            printProgress(stats, totalRoots, started);
        }
        std::cout << "Wrote " << stats.retainedSites << " futility-site FEN occurrences to " << outputPath << "\n"
                  << "Wrote manifest " << manifestPath << "\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "fatal: " << error.what() << "\n";
        return 1;
    }
}
