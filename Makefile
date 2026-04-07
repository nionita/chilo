CXX := g++
CXXFLAGS := -std=c++17 -Wall -Wextra -pedantic
EXTRA_CPPFLAGS ?=
WIN64_CXX := x86_64-w64-mingw32-g++-posix
WIN64_CXXFLAGS := $(CXXFLAGS)
WIN64_LDFLAGS := -static -static-libgcc -static-libstdc++ -s

ENGINE_SRC := attack.cpp movegen.cpp make_unmake.cpp perft_lib.cpp eval.cpp search.cpp
ENGINE_OBJ := $(ENGINE_SRC:.cpp=.o)
ENGINE_DEBUG_OBJ := $(ENGINE_SRC:.cpp=.debug.o)
ENGINE_VALIDATE_OBJ := $(ENGINE_SRC:.cpp=.validate.o)
ENGINE_WIN64_OBJ := $(ENGINE_SRC:.cpp=.win64.o)
PERFT_SRC := perft.cpp
PERFT_DIAG_SRC := perft_diag.cpp
TEST_SRC := engine_tests.cpp
CHILO_SRC := chilo.cpp
SELFPLAY_SRC := selfplay_collect.cpp
EVAL_FEN_SRC := eval_fen.cpp
ENGINE_HEADERS := engine.h chess_position.h chess_tables.h generated_nnue_weights.h
VENV_PYTHON := .venv/bin/python

.PHONY: all clean release debug validate windows64 tests tests-debug tests-validate python-env nnue-python-tests nnue-verify

all: release tests

release: perft perft_diag engine_tests chilo selfplay_collect eval_fen

debug: perft_debug perft_diag_debug engine_tests_debug chilo_debug selfplay_collect_debug eval_fen_debug

validate: perft_validate perft_diag_validate engine_tests_validate chilo_validate selfplay_collect_validate eval_fen_validate

windows64: perft.exe perft_diag.exe engine_tests.exe chilo.exe selfplay_collect.exe eval_fen.exe

tests: engine_tests

tests-debug: engine_tests_debug

tests-validate: engine_tests_validate

python-env:
	bash ./scripts/setup_python_env.sh

nnue-python-tests:
	$(VENV_PYTHON) -m unittest discover -s scripts -p 'test_nnue_pipeline.py'

nnue-verify:
	$(VENV_PYTHON) scripts/verify_nnue_workflow.py

perft: $(PERFT_SRC) $(ENGINE_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -o $@ $(PERFT_SRC) $(ENGINE_OBJ)

perft_diag: $(PERFT_DIAG_SRC) $(ENGINE_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -o $@ $(PERFT_DIAG_SRC) $(ENGINE_OBJ)

engine_tests: $(TEST_SRC) $(ENGINE_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -o $@ $(TEST_SRC) $(ENGINE_OBJ)

chilo: $(CHILO_SRC) $(ENGINE_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -o $@ $(CHILO_SRC) $(ENGINE_OBJ)

selfplay_collect: $(SELFPLAY_SRC) $(ENGINE_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -o $@ $(SELFPLAY_SRC) $(ENGINE_OBJ)

eval_fen: $(EVAL_FEN_SRC) $(ENGINE_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -o $@ $(EVAL_FEN_SRC) $(ENGINE_OBJ)

perft_debug: $(PERFT_SRC) $(ENGINE_DEBUG_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -o $@ $(PERFT_SRC) $(ENGINE_DEBUG_OBJ)

perft_diag_debug: $(PERFT_DIAG_SRC) $(ENGINE_DEBUG_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -o $@ $(PERFT_DIAG_SRC) $(ENGINE_DEBUG_OBJ)

engine_tests_debug: $(TEST_SRC) $(ENGINE_DEBUG_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -o $@ $(TEST_SRC) $(ENGINE_DEBUG_OBJ)

chilo_debug: $(CHILO_SRC) $(ENGINE_DEBUG_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -o $@ $(CHILO_SRC) $(ENGINE_DEBUG_OBJ)

selfplay_collect_debug: $(SELFPLAY_SRC) $(ENGINE_DEBUG_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -o $@ $(SELFPLAY_SRC) $(ENGINE_DEBUG_OBJ)

eval_fen_debug: $(EVAL_FEN_SRC) $(ENGINE_DEBUG_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -o $@ $(EVAL_FEN_SRC) $(ENGINE_DEBUG_OBJ)

perft_validate: $(PERFT_SRC) $(ENGINE_VALIDATE_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(PERFT_SRC) $(ENGINE_VALIDATE_OBJ)

perft_diag_validate: $(PERFT_DIAG_SRC) $(ENGINE_VALIDATE_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(PERFT_DIAG_SRC) $(ENGINE_VALIDATE_OBJ)

engine_tests_validate: $(TEST_SRC) $(ENGINE_VALIDATE_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(TEST_SRC) $(ENGINE_VALIDATE_OBJ)

chilo_validate: $(CHILO_SRC) $(ENGINE_VALIDATE_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(CHILO_SRC) $(ENGINE_VALIDATE_OBJ)

selfplay_collect_validate: $(SELFPLAY_SRC) $(ENGINE_VALIDATE_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(SELFPLAY_SRC) $(ENGINE_VALIDATE_OBJ)

eval_fen_validate: $(EVAL_FEN_SRC) $(ENGINE_VALIDATE_OBJ)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(EVAL_FEN_SRC) $(ENGINE_VALIDATE_OBJ)

perft.exe: $(PERFT_SRC) $(ENGINE_WIN64_OBJ)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(PERFT_SRC) $(ENGINE_WIN64_OBJ)

perft_diag.exe: $(PERFT_DIAG_SRC) $(ENGINE_WIN64_OBJ)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(PERFT_DIAG_SRC) $(ENGINE_WIN64_OBJ)

engine_tests.exe: $(TEST_SRC) $(ENGINE_WIN64_OBJ)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(TEST_SRC) $(ENGINE_WIN64_OBJ)

chilo.exe: $(CHILO_SRC) $(ENGINE_WIN64_OBJ)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(CHILO_SRC) $(ENGINE_WIN64_OBJ)

selfplay_collect.exe: $(SELFPLAY_SRC) $(ENGINE_WIN64_OBJ)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(SELFPLAY_SRC) $(ENGINE_WIN64_OBJ)

eval_fen.exe: $(EVAL_FEN_SRC) $(ENGINE_WIN64_OBJ)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG $(WIN64_LDFLAGS) -o $@ $(EVAL_FEN_SRC) $(ENGINE_WIN64_OBJ)

%.o: %.cpp $(ENGINE_HEADERS)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -c -o $@ $<

%.debug.o: %.cpp $(ENGINE_HEADERS)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -c -o $@ $<

%.validate.o: %.cpp $(ENGINE_HEADERS)
	$(CXX) $(CXXFLAGS) $(EXTRA_CPPFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -c -o $@ $<

%.win64.o: %.cpp $(ENGINE_HEADERS)
	$(WIN64_CXX) $(WIN64_CXXFLAGS) $(EXTRA_CPPFLAGS) -O3 -DNDEBUG -c -o $@ $<

clean:
	rm -f perft perft_diag engine_tests chilo selfplay_collect eval_fen perft_tests perft_debug perft_diag_debug engine_tests_debug chilo_debug selfplay_collect_debug eval_fen_debug perft_tests_debug perft_validate perft_diag_validate engine_tests_validate chilo_validate selfplay_collect_validate eval_fen_validate perft_tests_validate perft.exe perft_diag.exe engine_tests.exe chilo.exe selfplay_collect.exe eval_fen.exe perft_tests.exe $(ENGINE_OBJ) $(ENGINE_DEBUG_OBJ) $(ENGINE_VALIDATE_OBJ) $(ENGINE_WIN64_OBJ)
