#!/usr/bin/env python3

import importlib.util
import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("run_fixed_depth_node_matrix.py")
SPEC = importlib.util.spec_from_file_location("run_fixed_depth_node_matrix", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def candidates(count):
    return [
        {"id": f"candidate-{index}", "engine": f"engine-{index}.exe", "weights": "weights.bin"}
        for index in range(count)
    ]


class CandidateConfigTests(unittest.TestCase):
    def test_arbitrary_candidate_list_preserves_order(self):
        expected = candidates(5)
        actual = MODULE.configured_candidates({"candidates": expected})
        self.assertEqual([item["id"] for item in actual], [item["id"] for item in expected])

    def test_legacy_groups_are_flattened_without_group_limits(self):
        configured = candidates(5)
        actual = MODULE.configured_candidates(
            {"candidates": configured, "groups": [["candidate-2", "candidate-0"], ["candidate-4", "candidate-1", "candidate-3"]]}
        )
        self.assertEqual(
            [item["id"] for item in actual],
            ["candidate-2", "candidate-0", "candidate-4", "candidate-1", "candidate-3"],
        )

    def test_groups_must_cover_candidates_exactly_once(self):
        with self.assertRaisesRegex(ValueError, "every candidate exactly once"):
            MODULE.configured_candidates({"candidates": candidates(3), "groups": [["candidate-0", "candidate-1"]]})

    def test_workers_are_restricted_to_two_through_four(self):
        for workers in (1, 5):
            with self.subTest(workers=workers), self.assertRaises(SystemExit):
                MODULE.main(["--config", "unused.json", "--depth", "8", "--workers", str(workers)])


class CandidateSchedulingTests(unittest.TestCase):
    def test_next_candidate_starts_without_a_group_barrier(self):
        configured = candidates(5)
        first_four_started = threading.Barrier(4)
        release_slow_candidates = threading.Event()
        fifth_started = threading.Event()
        lock = threading.Lock()
        active = 0
        maximum_active = 0

        def fake_run(candidate, root, fens, depth, resume):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            try:
                candidate_id = candidate["id"]
                if candidate_id in {"candidate-0", "candidate-1", "candidate-2", "candidate-3"}:
                    first_four_started.wait(timeout=3)
                if candidate_id == "candidate-0":
                    pass
                elif candidate_id in {"candidate-1", "candidate-2", "candidate-3"}:
                    if not release_slow_candidates.wait(timeout=3):
                        raise RuntimeError("queued candidate did not start while peers remained active")
                else:
                    fifth_started.set()
                    release_slow_candidates.set()
                return {"candidate": candidate_id}
            finally:
                with lock:
                    active -= 1

        with mock.patch.object(MODULE, "run_candidate", side_effect=fake_run):
            summaries, failures = MODULE.run_candidate_matrix(configured, Path("."), ["fen"], 8, False, 4)

        self.assertTrue(fifth_started.is_set())
        self.assertEqual(maximum_active, 4)
        self.assertEqual(failures, [])
        self.assertEqual([item["candidate"] for item in summaries], [item["id"] for item in configured])

    def test_failure_does_not_prevent_queued_candidates(self):
        configured = candidates(5)
        started = []
        lock = threading.Lock()

        def fake_run(candidate, root, fens, depth, resume):
            with lock:
                started.append(candidate["id"])
            if candidate["id"] == "candidate-1":
                raise RuntimeError("expected failure")
            return {"candidate": candidate["id"]}

        with mock.patch.object(MODULE, "run_candidate", side_effect=fake_run):
            summaries, failures = MODULE.run_candidate_matrix(configured, Path("."), ["fen"], 8, False, 2)

        self.assertCountEqual(started, [item["id"] for item in configured])
        self.assertEqual([item["candidate"] for item in summaries], ["candidate-0", "candidate-2", "candidate-3", "candidate-4"])
        self.assertEqual([item["candidate"] for item in failures], ["candidate-1"])


class ResumeTests(unittest.TestCase):
    def test_resume_continues_after_durable_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "engine.exe").touch()
            (root / "weights.bin").touch()
            run_dir = root / "run" / "candidate"
            run_dir.mkdir(parents=True)
            (run_dir / "records.jsonl").write_text(
                json.dumps(
                    {"index": 0, "nodes": 7, "engine_ms": 2, "nps": 3500, "cut_tt": 1, "bestmove": "a2a3"}
                )
                + "\n"
            )
            candidate = {"id": "candidate", "engine": "engine.exe", "weights": "weights.bin"}
            results = iter(
                [
                    {"nodes": 11, "engine_ms": 3, "nps": 3666, "cut_tt": 2, "bestmove": "b2b3"},
                    {"nodes": 13, "engine_ms": 4, "nps": 3250, "cut_tt": 3, "bestmove": "c2c3"},
                ]
            )

            with mock.patch.object(MODULE, "run_one", side_effect=lambda *args: next(results)) as run_one:
                summary = MODULE.run_candidate(candidate, root, ["fen-0", "fen-1", "fen-2"], 8, True)

            self.assertEqual(run_one.call_count, 2)
            self.assertEqual(summary["next_index"], 3)
            self.assertEqual(summary["totals"]["nodes"], 31)
            self.assertTrue(summary["complete"])


if __name__ == "__main__":
    unittest.main()
