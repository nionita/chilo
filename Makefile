CXX := g++
CXXFLAGS := -std=c++17 -Wall -Wextra -pedantic

PERFT_SRC := perft.cpp
PERFT_DIAG_SRC := perft_diag.cpp
TEST_SRC := perft_tests.cpp

.PHONY: all clean release debug validate tests tests-debug tests-validate

all: release tests

release: perft perft_diag perft_tests

debug: perft_debug perft_diag_debug perft_tests_debug

validate: perft_validate perft_diag_validate perft_tests_validate

tests: perft_tests

tests-debug: perft_tests_debug

tests-validate: perft_tests_validate

perft: $(PERFT_SRC) chess.h
	$(CXX) $(CXXFLAGS) -O3 -DNDEBUG -o $@ $(PERFT_SRC)

perft_diag: $(PERFT_DIAG_SRC) chess.h
	$(CXX) $(CXXFLAGS) -O3 -DNDEBUG -o $@ $(PERFT_DIAG_SRC)

perft_tests: $(TEST_SRC) chess.h
	$(CXX) $(CXXFLAGS) -O3 -DNDEBUG -o $@ $(TEST_SRC)

perft_debug: $(PERFT_SRC) chess.h
	$(CXX) $(CXXFLAGS) -O0 -g -o $@ $(PERFT_SRC)

perft_diag_debug: $(PERFT_DIAG_SRC) chess.h
	$(CXX) $(CXXFLAGS) -O0 -g -o $@ $(PERFT_DIAG_SRC)

perft_tests_debug: $(TEST_SRC) chess.h
	$(CXX) $(CXXFLAGS) -O0 -g -o $@ $(TEST_SRC)

perft_validate: $(PERFT_SRC) chess.h
	$(CXX) $(CXXFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(PERFT_SRC)

perft_diag_validate: $(PERFT_DIAG_SRC) chess.h
	$(CXX) $(CXXFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(PERFT_DIAG_SRC)

perft_tests_validate: $(TEST_SRC) chess.h
	$(CXX) $(CXXFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(TEST_SRC)

clean:
	rm -f perft perft_diag perft_tests perft_debug perft_diag_debug perft_tests_debug perft_validate perft_diag_validate perft_tests_validate
