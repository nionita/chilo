CXX := g++
CXXFLAGS := -std=c++17 -Wall -Wextra -pedantic

ENGINE_SRC := attack.cpp movegen.cpp make_unmake.cpp perft_lib.cpp
ENGINE_OBJ := $(ENGINE_SRC:.cpp=.o)
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

perft: $(PERFT_SRC) $(ENGINE_OBJ)
	$(CXX) $(CXXFLAGS) -O3 -DNDEBUG -o $@ $(PERFT_SRC) $(ENGINE_OBJ)

perft_diag: $(PERFT_DIAG_SRC) $(ENGINE_OBJ)
	$(CXX) $(CXXFLAGS) -O3 -DNDEBUG -o $@ $(PERFT_DIAG_SRC) $(ENGINE_OBJ)

perft_tests: $(TEST_SRC) $(ENGINE_OBJ)
	$(CXX) $(CXXFLAGS) -O3 -DNDEBUG -o $@ $(TEST_SRC) $(ENGINE_OBJ)

perft_debug: $(PERFT_SRC) attack.debug.o movegen.debug.o make_unmake.debug.o perft_lib.debug.o
	$(CXX) $(CXXFLAGS) -O0 -g -o $@ $(PERFT_SRC) attack.debug.o movegen.debug.o make_unmake.debug.o perft_lib.debug.o

perft_diag_debug: $(PERFT_DIAG_SRC) attack.debug.o movegen.debug.o make_unmake.debug.o perft_lib.debug.o
	$(CXX) $(CXXFLAGS) -O0 -g -o $@ $(PERFT_DIAG_SRC) attack.debug.o movegen.debug.o make_unmake.debug.o perft_lib.debug.o

perft_tests_debug: $(TEST_SRC) attack.debug.o movegen.debug.o make_unmake.debug.o perft_lib.debug.o
	$(CXX) $(CXXFLAGS) -O0 -g -o $@ $(TEST_SRC) attack.debug.o movegen.debug.o make_unmake.debug.o perft_lib.debug.o

perft_validate: $(PERFT_SRC) attack.validate.o movegen.validate.o make_unmake.validate.o perft_lib.validate.o
	$(CXX) $(CXXFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(PERFT_SRC) attack.validate.o movegen.validate.o make_unmake.validate.o perft_lib.validate.o

perft_diag_validate: $(PERFT_DIAG_SRC) attack.validate.o movegen.validate.o make_unmake.validate.o perft_lib.validate.o
	$(CXX) $(CXXFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(PERFT_DIAG_SRC) attack.validate.o movegen.validate.o make_unmake.validate.o perft_lib.validate.o

perft_tests_validate: $(TEST_SRC) attack.validate.o movegen.validate.o make_unmake.validate.o perft_lib.validate.o
	$(CXX) $(CXXFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -o $@ $(TEST_SRC) attack.validate.o movegen.validate.o make_unmake.validate.o perft_lib.validate.o

%.o: %.cpp engine.h chess_position.h chess_tables.h
	$(CXX) $(CXXFLAGS) -O3 -DNDEBUG -c -o $@ $<

%.debug.o: %.cpp engine.h chess_position.h chess_tables.h
	$(CXX) $(CXXFLAGS) -O0 -g -c -o $@ $<

%.validate.o: %.cpp engine.h chess_position.h chess_tables.h
	$(CXX) $(CXXFLAGS) -O0 -g -DCHESS_VALIDATE_STATE -c -o $@ $<

clean:
	rm -f perft perft_diag perft_tests perft_debug perft_diag_debug perft_tests_debug perft_validate perft_diag_validate perft_tests_validate $(ENGINE_OBJ) attack.debug.o movegen.debug.o make_unmake.debug.o perft_lib.debug.o attack.validate.o movegen.validate.o make_unmake.validate.o perft_lib.validate.o
