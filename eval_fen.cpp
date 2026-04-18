#include "engine.h"

#include <filesystem>
#include <iostream>
#include <string>

namespace {

std::filesystem::path sidecarWeightsPath(const char* argv0) {
    std::filesystem::path executablePath = std::filesystem::absolute(std::filesystem::path(argv0));
    return executablePath.parent_path() / (executablePath.stem().string() + ".bin");
}

bool loadStartupWeights(const std::string* explicitWeightsPath, const std::filesystem::path& sidecarPath) {
    std::string error;
    if (explicitWeightsPath != nullptr) {
        if (!loadNnueWeightsFile(*explicitWeightsPath, error)) {
            std::cerr << "fatal: failed to load NNUE weights from " << *explicitWeightsPath << ": " << error << "\n";
            return false;
        }
        return true;
    }

    std::error_code existsError;
    if (std::filesystem::exists(sidecarPath, existsError) && !existsError) {
        if (!loadNnueWeightsFile(sidecarPath.string(), error)) {
            std::cerr << "info: failed to load sidecar NNUE weights from " << sidecarPath
                      << ": " << error << "; using built-in weights\n";
        }
    }
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    std::string explicitWeightsPath;
    int fenStart = 1;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--weights") {
            if (i + 1 >= argc) {
                std::cerr << "Usage: eval_fen [--weights <path>] \"<fen>\" [more_fens...]\n";
                return 1;
            }
            explicitWeightsPath = argv[++i];
            fenStart = i + 1;
        } else {
            fenStart = i;
            break;
        }
    }

    if (fenStart >= argc) {
        std::cerr << "Usage: eval_fen [--weights <path>] \"<fen>\" [more_fens...]\n";
        return 1;
    }

    std::filesystem::path sidecarPath = sidecarWeightsPath(argv[0]);
    const std::string* explicitWeights = explicitWeightsPath.empty() ? nullptr : &explicitWeightsPath;
    if (!loadStartupWeights(explicitWeights, sidecarPath)) {
        return 1;
    }

    for (int i = fenStart; i < argc; ++i) {
        const std::string fen = argv[i];
        Position pos = parseFEN(fen);
        resetDrawHistory(pos);
        std::cout << evaluate(pos) << "\n";
    }
    return 0;
}
