"""Short real-process match tests; no production net or third-party Python needed."""
import copy
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BIN = Path(os.environ.get("CHILO_SELFPLAY_BIN", ROOT / "build/release/selfplay_collect"))
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def zero_net(path):
    manifest = json.loads((ROOT / "generated/generated_nnue_manifest.json").read_text())
    header = struct.pack("<8s10I64s64s", b"CHNNUEB5", 32, 8, 255, 32, 4, 8, 127, 2, 13, 64,
                         manifest["contract_id"].encode(), manifest["contract_sha256"].encode())
    path.write_bytes(header + bytes(13*64*32*2 + 32*2 + 8*64 + 8*4 + 8 + 4))


class Matches(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        zero_net(self.root / "net.bin")
        (self.root / "openings.fen").write_text(START + "\n" +
            "7k/8/5K2/8/8/8/P7/8 b - - 0 1\n")
        self.config = {
            "schema": "chilo.selfplay_match.v1", "weights": "net.bin",
            "players": [{"name": name, "parameters": {"futility_margins": [120, 240, 360]}}
                        for name in ("a", "b")],
            "openings": {"file": "openings.fen", "order": "sequential", "seed": 1},
            "budget": {"mode": "fixed_nodes_per_move", "nodes": 300}, "max_pairs": 2,
            "adjudication": {"maxmoves": 3, "resign": {"movecount": 0}, "draw": {"movecount": 0}}}
        self.save()

    def save(self):
        (self.root / "config.json").write_text(json.dumps(self.config))

    def command(self, name="run", resume=False):
        return [str(BIN), "--match-config", str(self.root / "config.json"), "--run-dir", str(self.root / name)] + (["--resume"] if resume else [])

    def run_match(self, name="run", resume=False, good=True):
        result = subprocess.run(self.command(name, resume), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode == 0, good, result.stdout + result.stderr)
        return result

    def games(self, name="run"):
        return [json.loads(line)["game"] for line in (self.root / name / "games.jsonl").read_text().splitlines()]

    def test_pairs_and_terminal_resume(self):
        self.run_match()
        games = self.games()
        self.assertEqual([g["white_player"] for g in games], [0, 1, 0, 1])
        self.assertEqual([g["pair"] for g in games], [0, 0, 1, 1])
        for a, b in zip(games[::2], games[1::2]):
            self.assertEqual(a["a_score"] + b["a_score"], 2)
            self.assertEqual([m["uci"] for m in a["moves"]], [m["uci"] for m in b["moves"]])
            self.assertTrue(all(m["nodes"] <= 300 for m in a["moves"]))
        before = (self.root / "run/games.jsonl").read_bytes()
        self.run_match(resume=True)
        self.assertEqual(before, (self.root / "run/games.jsonl").read_bytes())
        self.run_match(good=False)

    def test_between_games_and_torn_tail_resume(self):
        self.run_match()
        expected = self.games()
        path = self.root / "run/games.jsonl"
        first = path.read_bytes().splitlines(keepends=True)[0]
        path.write_bytes(first + b'{"game":')
        self.run_match(resume=True)
        actual = self.games()
        for records in (expected, actual):
            for g in records:
                g.pop("elapsed_ms")
                for m in g["moves"]: m.pop("elapsed_ms")
        self.assertEqual(expected, actual)

    def test_corrupt_committed_record_rejected(self):
        self.run_match()
        path = self.root / "run/games.jsonl"
        text = path.read_text().replace('"a_score":1', '"a_score":0', 1)
        path.write_text(text)
        self.assertIn("checksum mismatch", self.run_match(resume=True, good=False).stderr)

    def test_changed_contract_rejected(self):
        self.run_match()
        self.config["players"][0]["parameters"]["futility_margins"] = [0, 0, 50, 100]
        self.save()
        self.assertIn("contract mismatch", self.run_match(resume=True, good=False).stderr)

    def test_network_bytes_and_opening_bytes_are_frozen(self):
        self.run_match()
        net = self.root / "net.bin"
        before = net.read_bytes()
        net.write_bytes(before[:-1] + b'\x01')
        self.assertIn("contract mismatch", self.run_match(resume=True, good=False).stderr)
        net.write_bytes(before)
        with (self.root / "openings.fen").open("a") as f: f.write("\n")
        self.assertIn("contract mismatch", self.run_match(resume=True, good=False).stderr)

    def test_stop_file_resume_and_lock(self):
        run = self.root / "run"
        run.mkdir()
        # A fresh run refuses arbitrary files; initialize via a complete run.
        self.run_match()
        (run / "games.jsonl").write_text("")
        (run / "STOP").touch()
        self.run_match(resume=True)
        self.assertEqual(json.loads((run / "status.json").read_text())["status"], "stopped")
        (run / "STOP").unlink()
        self.run_match(resume=True)
        if os.name == "posix":
            import fcntl
            with (run / "run.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertIn("locked", self.run_match(resume=True, good=False).stderr)

    @unittest.skipUnless(os.name == "posix", "POSIX signals")
    def test_signal_finishes_pair(self):
        self.config["budget"]["nodes"] = 1000
        self.config["adjudication"]["maxmoves"] = 10
        self.save()
        process = subprocess.Popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertIn("game=1", process.stdout.readline())
            process.send_signal(signal.SIGTERM)
            out, err = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, out + err)
            self.assertEqual(len(self.games()), 2)
            self.assertEqual(json.loads((self.root / "run/status.json").read_text())["status"], "stopped")
            self.run_match(resume=True)
            self.assertEqual(len(self.games()), 4)
        finally:
            if process.poll() is None: process.kill(); process.wait()

    def test_invalid_config_and_missing_net(self):
        for field, value in [("budget", {"mode": "game_allowance", "nodes": 300}),
                             ("max_pairs", -1), ("typo", True), ("weights", "missing.bin")]:
            with self.subTest(field=field):
                original = copy.deepcopy(self.config)
                self.config[field] = value; self.save()
                self.run_match(name=field, good=False)
                self.config = original

    @unittest.skipUnless(os.name == "posix", "POSIX kill")
    def test_hard_kill_restarts_unfinished_game(self):
        self.config["budget"]["nodes"] = 10000
        self.config["adjudication"]["maxmoves"] = 8
        self.save()
        process = subprocess.Popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertIn("game=1", process.stdout.readline())
            process.kill(); process.communicate(timeout=10)
        finally:
            if process.poll() is None: process.kill(); process.wait()
        self.run_match(resume=True)
        self.run_match(name="uninterrupted")
        resumed, uninterrupted = self.games(), self.games("uninterrupted")
        for records in (resumed, uninterrupted):
            for g in records:
                g.pop("elapsed_ms")
                for m in g["moves"]: m.pop("elapsed_ms")
        self.assertEqual(resumed, uninterrupted)

    def test_bad_openings_rejected(self):
        for content in [START+"\n"+START+"\n", "8/8/8/8/8/8/8/8 w - - 0 1\n",
                        "7k/8/5K2/8/8/8/P7/8 w K - 0 1\n",
                        "7k/8/5K2/8/8/8/P7/8 w - - -1 1\n"]:
            (self.root / "openings.fen").write_text(content)
            self.run_match(good=False)

    def test_exhaustion_and_different_depths(self):
        self.config["max_pairs"] = 3
        self.config["players"][0]["parameters"]["futility_margins"] = []
        self.config["players"][1]["parameters"]["futility_margins"] = [0]*7
        self.save(); self.run_match()
        self.assertEqual(json.loads((self.root / "run/results.json").read_text())["status"], "openings_exhausted")

    def test_legacy_collector(self):
        result = subprocess.run([str(BIN), "--fen-file", str(self.root / "openings.fen"),
            "--output", str(self.root / "training.csv"), "--depth", "1", "--max-plies", "2", "--seed", "1"],
            text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "training.csv").read_text().startswith("eval_fen,score,result\n"))


if __name__ == "__main__": unittest.main()
