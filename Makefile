CXX := g++
CXXFLAGS := -std=c++17 -Wall -Wextra -pedantic
EXTRA_CPPFLAGS ?=
AVX2_CPPFLAGS := -DCHILO_AVX2 -mavx2
WIN64_CXX := x86_64-w64-mingw32-g++-posix
WIN64_CXXFLAGS := $(CXXFLAGS)
WIN64_LDFLAGS := -static -static-libgcc -static-libstdc++ -s
BUILD_DIR := build
RELEASE_DIR := $(BUILD_DIR)/release
RELEASE_AVX2_DIR := $(BUILD_DIR)/release-avx2
DEBUG_DIR := $(BUILD_DIR)/debug
VALIDATE_DIR := $(BUILD_DIR)/validate
WIN64_DIR := $(BUILD_DIR)/win64
WIN64_AVX2_DIR := $(BUILD_DIR)/win64-avx2
GENERATED_DIR := generated

ENGINE_SRC := attack.cpp movegen.cpp make_unmake.cpp perft_lib.cpp eval.cpp search.cpp
ENGINE_NAMES := $(basename $(ENGINE_SRC))
ENGINE_OBJ := $(addprefix $(RELEASE_DIR)/,$(addsuffix .o,$(ENGINE_NAMES)))
ENGINE_AVX2_OBJ := $(addprefix $(RELEASE_AVX2_DIR)/,$(addsuffix .avx2.o,$(ENGINE_NAMES)))
ENGINE_DEBUG_OBJ := $(addprefix $(DEBUG_DIR)/,$(addsuffix .debug.o,$(ENGINE_NAMES)))
ENGINE_VALIDATE_OBJ := $(addprefix $(VALIDATE_DIR)/,$(addsuffix .validate.o,$(ENGINE_NAMES)))
ENGINE_WIN64_OBJ := $(addprefix $(WIN64_DIR)/,$(addsuffix .win64.o,$(ENGINE_NAMES)))
ENGINE_WIN64_AVX2_OBJ := $(addprefix $(WIN64_AVX2_DIR)/,$(addsuffix .win64-avx2.o,$(ENGINE_NAMES)))
PERFT_SRC := perft.cpp
PERFT_DIAG_SRC := perft_diag.cpp
TEST_SRC := engine_tests.cpp
CHILO_SRC := chilo.cpp
SELFPLAY_SRC := selfplay_collect.cpp
EVAL_FEN_SRC := eval_fen.cpp
ENGINE_HEADERS := engine.h chess_position.h chess_tables.h $(GENERATED_DIR)/generated_nnue_weights.h
VENV_PYTHON := .venv/bin/python
RELEASE_BINS := $(RELEASE_DIR)/perft $(RELEASE_DIR)/perft_diag $(RELEASE_DIR)/engine_tests $(RELEASE_DIR)/chilo $(RELEASE_DIR)/selfplay_collect $(RELEASE_DIR)/eval_fen
RELEASE_AVX2_BINS := $(RELEASE_AVX2_DIR)/perft $(RELEASE_AVX2_DIR)/perft_diag $(RELEASE_AVX2_DIR)/engine_tests $(RELEASE_AVX2_DIR)/chilo $(RELEASE_AVX2_DIR)/selfplay_collect $(RELEASE_AVX2_DIR)/eval_fen
DEBUG_BINS := $(DEBUG_DIR)/perft_debug $(DEBUG_DIR)/perft_diag_debug $(DEBUG_DIR)/engine_tests_debug $(DEBUG_DIR)/chilo_debug $(DEBUG_DIR)/selfplay_collect_debug $(DEBUG_DIR)/eval_fen_debug
VALIDATE_BINS := $(VALIDATE_DIR)/perft_validate $(VALIDATE_DIR)/perft_diag_validate $(VALIDATE_DIR)/engine_tests_validate $(VALIDATE_DIR)/chilo_validate $(VALIDATE_DIR)/selfplay_collect_validate $(VALIDATE_DIR)/eval_fen_validate
WIN64_BINS := $(WIN64_DIR)/perft.exe $(WIN64_DIR)/perft_diag.exe $(WIN64_DIR)/engine_tests.exe $(WIN64_DIR)/chilo.exe $(WIN64_DIR)/selfplay_collect.exe $(WIN64_DIR)/eval_fen.exe
WIN64_AVX2_BINS := $(WIN64_AVX2_DIR)/perft.exe $(WIN64_AVX2_DIR)/perft_diag.exe $(WIN64_AVX2_DIR)/engine_tests.exe $(WIN64_AVX2_DIR)/chilo.exe $(WIN64_AVX2_DIR)/selfplay_collect.exe $(WIN64_AVX2_DIR)/eval_fen.exe

.PHONY: all clean release release-avx2 debug validate windows64 windows64-avx2 tests tests-debug tests-validate python-env nnue-python-tests nnue-verify \
	perft perft_diag engine_tests chilo selfplay_collect eval_fen \
	perft_debug perft_diag_debug engine_tests_debug chilo_debug selfplay_collect_debug eval_fen_debug \
	perft_validate perft_diag_validate engine_tests_validate chilo_validate selfplay_collect_validate eval_fen_validate \
	perft.exe perft_diag.exe engine_tests.exe chilo.exe selfplay_collect.exe eval_fen.exe

all: release tests

release: $(RELEASE_BINS)

release-avx2: $(RELEASE_AVX2_BINS)

debug: $(DEBUG_BINS)

validate: $(VALIDATE_BINS)

windows64: $(WIN64_BINS)

windows64-avx2: $(WIN64_AVX2_BINS)

tests: $(RELEASE_DIR)/engine_tests

tests-debug: $(DEBUG_DIR)/engine_tests_debug

tests-validate: $(VALIDATE_DIR)/engine_tests_validate

perft: $(RELEASE_DIR)/perft
perft_diag: $(RELEASE_DIR)/perft_diag
engine_tests: $(RELEASE_DIR)/engine_tests
chilo: $(RELEASE_DIR)/chilo
selfplay_collect: $(RELEASE_DIR)/selfplay_collect
eval_fen: $(RELEASE_DIR)/eval_fen

perft_debug: $(DEBUG_DIR)/perft_debug
perft_diag_debug: $(DEBUG_DIR)/perft_diag_debug
engine_tests_debug: $(DEBUG_DIR)/engine_tests_debug
chilo_debug: $(DEBUG_DIR)/chilo_debug
selfplay_collect_debug: $(DEBUG_DIR)/selfplay_collect_debug
eval_fen_debug: $(DEBUG_DIR)/eval_fen_debug

perft_validate: $(VALIDATE_DIR)/perft_validate
perft_diag_validate: $(VALIDATE_DIR)/perft_diag_validate
engine_tests_validate: $(VALIDATE_DIR)/engine_tests_validate
chilo_validate: $(VALIDATE_DIR)/chilo_validate
selfplay_collect_validate: $(VALIDATE_DIR)/selfplay_collect_validate
eval_fen_validate: $(VALIDATE_DIR)/eval_fen_validate

perft.exe: $(WIN64_DIR)/perft.exe
perft_diag.exe: $(WIN64_DIR)/perft_diag.exe
engine_tests.exe: $(WIN64_DIR)/engine_tests.exe
chilo.exe: $(WIN64_DIR)/chilo.exe
selfplay_collect.exe: $(WIN64_DIR)/selfplay_collect.exe
eval_fen.exe: $(WIN64_DIR)/eval_fen.exe

python-env:
	bash ./scripts/setup_python_env.sh

nnue-python-tests:
	$(VENV_PYTHON) -m unittest discover -s scripts -p 'test_*.py'

nnue-verify:
	$(VENV_PYTHON) scripts/verify_nnue_workflow.py

$(RELEASE_DIR) $(RELEASE_AVX2_DIR) $(DEBUG_DIR) $(VALIDATE_DIR) $(WIN64_DIR) $(WIN64_AVX2_DIR):
	mkdir -p $@

$(RELEASE_DIR)/perft: $(PERFT_SRC) $(ENGINE_OBJ) | $(RELEASE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -o $@ $(PERFT_SRC) $(ENGINE_OBJ)

$(RELEASE_DIR)/perft_diag: $(PERFT_DIAG_SRC) $(ENGINE_OBJ) | $(RELEASE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -o $@ $(PERFT_DIAG_SRC) $(ENGINE_OBJ)

$(RELEASE_DIR)/engine_tests: $(TEST_SRC) $(ENGINE_OBJ) | $(RELEASE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -o $@ $(TEST_SRC) $(ENGINE_OBJ)

$(RELEASE_DIR)/chilo: $(CHILO_SRC) $(ENGINE_OBJ) | $(RELEASE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -o $@ $(CHILO_SRC) $(ENGINE_OBJ)

$(RELEASE_DIR)/selfplay_collect: $(SELFPLAY_SRC) $(ENGINE_OBJ) | $(RELEASE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -o $@ $(SELFPLAY_SRC) $(ENGINE_OBJ)

$(RELEASE_DIR)/eval_fen: $(EVAL_FEN_SRC) $(ENGINE_OBJ) | $(RELEASE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -o $@ $(EVAL_FEN_SRC) $(ENGINE_OBJ)

$(RELEASE_AVX2_DIR)/perft: $(PERFT_SRC) $(ENGINE_AVX2_OBJ) | $(RELEASE_AVX2_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG -o $@ $(PERFT_SRC) $(ENGINE_AVX2_OBJ)

$(RELEASE_AVX2_DIR)/perft_diag: $(PERFT_DIAG_SRC) $(ENGINE_AVX2_OBJ) | $(RELEASE_AVX2_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG -o $@ $(PERFT_DIAG_SRC) $(ENGINE_AVX2_OBJ)

$(RELEASE_AVX2_DIR)/engine_tests: $(TEST_SRC) $(ENGINE_AVX2_OBJ) | $(RELEASE_AVX2_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG -o $@ $(TEST_SRC) $(ENGINE_AVX2_OBJ)

$(RELEASE_AVX2_DIR)/chilo: $(CHILO_SRC) $(ENGINE_AVX2_OBJ) | $(RELEASE_AVX2_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG -o $@ $(CHILO_SRC) $(ENGINE_AVX2_OBJ)

$(RELEASE_AVX2_DIR)/selfplay_collect: $(SELFPLAY_SRC) $(ENGINE_AVX2_OBJ) | $(RELEASE_AVX2_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG -o $@ $(SELFPLAY_SRC) $(ENGINE_AVX2_OBJ)

$(RELEASE_AVX2_DIR)/eval_fen: $(EVAL_FEN_SRC) $(ENGINE_AVX2_OBJ) | $(RELEASE_AVX2_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG -o $@ $(EVAL_FEN_SRC) $(ENGINE_AVX2_OBJ)

$(DEBUG_DIR)/perft_debug: $(PERFT_SRC) $(ENGINE_DEBUG_OBJ) | $(DEBUG_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -o $@ $(PERFT_SRC) $(ENGINE_DEBUG_OBJ)

$(DEBUG_DIR)/perft_diag_debug: $(PERFT_DIAG_SRC) $(ENGINE_DEBUG_OBJ) | $(DEBUG_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -o $@ $(PERFT_DIAG_SRC) $(ENGINE_DEBUG_OBJ)

$(DEBUG_DIR)/engine_tests_debug: $(TEST_SRC) $(ENGINE_DEBUG_OBJ) | $(DEBUG_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -o $@ $(TEST_SRC) $(ENGINE_DEBUG_OBJ)

$(DEBUG_DIR)/chilo_debug: $(CHILO_SRC) $(ENGINE_DEBUG_OBJ) | $(DEBUG_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -o $@ $(CHILO_SRC) $(ENGINE_DEBUG_OBJ)

$(DEBUG_DIR)/selfplay_collect_debug: $(SELFPLAY_SRC) $(ENGINE_DEBUG_OBJ) | $(DEBUG_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -o $@ $(SELFPLAY_SRC) $(ENGINE_DEBUG_OBJ)

$(DEBUG_DIR)/eval_fen_debug: $(EVAL_FEN_SRC) $(ENGINE_DEBUG_OBJ) | $(DEBUG_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -o $@ $(EVAL_FEN_SRC) $(ENGINE_DEBUG_OBJ)

$(VALIDATE_DIR)/perft_validate: $(PERFT_SRC) $(ENGINE_VALIDATE_OBJ) | $(VALIDATE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(PERFT_SRC) $(ENGINE_VALIDATE_OBJ)

$(VALIDATE_DIR)/perft_diag_validate: $(PERFT_DIAG_SRC) $(ENGINE_VALIDATE_OBJ) | $(VALIDATE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(PERFT_DIAG_SRC) $(ENGINE_VALIDATE_OBJ)

$(VALIDATE_DIR)/engine_tests_validate: $(TEST_SRC) $(ENGINE_VALIDATE_OBJ) | $(VALIDATE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(TEST_SRC) $(ENGINE_VALIDATE_OBJ)

$(VALIDATE_DIR)/chilo_validate: $(CHILO_SRC) $(ENGINE_VALIDATE_OBJ) | $(VALIDATE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(CHILO_SRC) $(ENGINE_VALIDATE_OBJ)

$(VALIDATE_DIR)/selfplay_collect_validate: $(SELFPLAY_SRC) $(ENGINE_VALIDATE_OBJ) | $(VALIDATE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(SELFPLAY_SRC) $(ENGINE_VALIDATE_OBJ)

$(VALIDATE_DIR)/eval_fen_validate: $(EVAL_FEN_SRC) $(ENGINE_VALIDATE_OBJ) | $(VALIDATE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(EVAL_FEN_SRC) $(ENGINE_VALIDATE_OBJ)

$(WIN64_DIR)/perft.exe: $(PERFT_SRC) $(ENGINE_WIN64_OBJ) | $(WIN64_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(PERFT_SRC) $(ENGINE_WIN64_OBJ)

$(WIN64_DIR)/perft_diag.exe: $(PERFT_DIAG_SRC) $(ENGINE_WIN64_OBJ) | $(WIN64_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(PERFT_DIAG_SRC) $(ENGINE_WIN64_OBJ)

$(WIN64_DIR)/engine_tests.exe: $(TEST_SRC) $(ENGINE_WIN64_OBJ) | $(WIN64_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(TEST_SRC) $(ENGINE_WIN64_OBJ)

$(WIN64_DIR)/chilo.exe: $(CHILO_SRC) $(ENGINE_WIN64_OBJ) | $(WIN64_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(CHILO_SRC) $(ENGINE_WIN64_OBJ)

$(WIN64_DIR)/selfplay_collect.exe: $(SELFPLAY_SRC) $(ENGINE_WIN64_OBJ) | $(WIN64_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(SELFPLAY_SRC) $(ENGINE_WIN64_OBJ)

$(WIN64_DIR)/eval_fen.exe: $(EVAL_FEN_SRC) $(ENGINE_WIN64_OBJ) | $(WIN64_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(EVAL_FEN_SRC) $(ENGINE_WIN64_OBJ)

$(WIN64_AVX2_DIR)/perft.exe: $(PERFT_SRC) $(ENGINE_WIN64_AVX2_OBJ) | $(WIN64_AVX2_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(PERFT_SRC) $(ENGINE_WIN64_AVX2_OBJ)

$(WIN64_AVX2_DIR)/perft_diag.exe: $(PERFT_DIAG_SRC) $(ENGINE_WIN64_AVX2_OBJ) | $(WIN64_AVX2_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(PERFT_DIAG_SRC) $(ENGINE_WIN64_AVX2_OBJ)

$(WIN64_AVX2_DIR)/engine_tests.exe: $(TEST_SRC) $(ENGINE_WIN64_AVX2_OBJ) | $(WIN64_AVX2_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(TEST_SRC) $(ENGINE_WIN64_AVX2_OBJ)

$(WIN64_AVX2_DIR)/chilo.exe: $(CHILO_SRC) $(ENGINE_WIN64_AVX2_OBJ) | $(WIN64_AVX2_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(CHILO_SRC) $(ENGINE_WIN64_AVX2_OBJ)

$(WIN64_AVX2_DIR)/selfplay_collect.exe: $(SELFPLAY_SRC) $(ENGINE_WIN64_AVX2_OBJ) | $(WIN64_AVX2_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(SELFPLAY_SRC) $(ENGINE_WIN64_AVX2_OBJ)

$(WIN64_AVX2_DIR)/eval_fen.exe: $(EVAL_FEN_SRC) $(ENGINE_WIN64_AVX2_OBJ) | $(WIN64_AVX2_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(EVAL_FEN_SRC) $(ENGINE_WIN64_AVX2_OBJ)

$(RELEASE_DIR)/%.o: %.cpp $(ENGINE_HEADERS) | $(RELEASE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -c -o $@ $<

$(RELEASE_AVX2_DIR)/%.avx2.o: %.cpp $(ENGINE_HEADERS) | $(RELEASE_AVX2_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG -c -o $@ $<

$(DEBUG_DIR)/%.debug.o: %.cpp $(ENGINE_HEADERS) | $(DEBUG_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -c -o $@ $<

$(VALIDATE_DIR)/%.validate.o: %.cpp $(ENGINE_HEADERS) | $(VALIDATE_DIR)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -c -o $@ $<

$(WIN64_DIR)/%.win64.o: %.cpp $(ENGINE_HEADERS) | $(WIN64_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -c -o $@ $<

$(WIN64_AVX2_DIR)/%.win64-avx2.o: %.cpp $(ENGINE_HEADERS) | $(WIN64_AVX2_DIR)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) $(AVX2_CPPFLAGS) -O3 -DNDEBUG -c -o $@ $<

clean:
	rm -rf $(BUILD_DIR)
	rm -f perft perft_diag engine_tests chilo selfplay_collect eval_fen perft_tests perft_debug perft_diag_debug engine_tests_debug chilo_debug selfplay_collect_debug eval_fen_debug perft_tests_debug perft_validate perft_diag_validate engine_tests_validate chilo_validate selfplay_collect_validate eval_fen_validate perft_tests_validate perft.exe perft_diag.exe engine_tests.exe chilo.exe selfplay_collect.exe eval_fen.exe perft_tests.exe attack.o movegen.o make_unmake.o perft_lib.o eval.o search.o attack.debug.o movegen.debug.o make_unmake.debug.o perft_lib.debug.o eval.debug.o search.debug.o attack.validate.o movegen.validate.o make_unmake.validate.o perft_lib.validate.o eval.validate.o search.validate.o attack.win64.o movegen.win64.o make_unmake.win64.o perft_lib.win64.o eval.win64.o search.win64.o
