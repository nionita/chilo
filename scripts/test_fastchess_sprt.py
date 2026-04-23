from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_fastchess_sprt


def write_config(temp_dir: Path) -> Path:
    config = {
        "fastchess": "fastchess",
        "work_root": "runs",
        "concurrency": 1,
        "rounds": 1000,
        "games": 2,
        "autosave_interval": 7,
        "rating_interval": 0,
        "opening": {
            "file": "book.epd",
            "format": "epd",
            "order": "random",
        },
        "each": {
            "tc": "10+0.1",
            "restart": "on",
            "proto": "uci",
            "option.Hash": 64,
        },
        "adjudication": {
            "resign": "movecount=3 score=600",
            "draw": "movenumber=34 movecount=8 score=20",
            "maxmoves": 200,
        },
        "sprt_profiles": {
            "quick": {
                "elo0": 0,
                "elo1": 5,
                "alpha": 0.05,
                "beta": 0.05,
                "model": "normalized",
            },
            "normal": {
                "elo0": 0,
                "elo1": 2,
                "alpha": 0.05,
                "beta": 0.05,
                "model": "normalized",
            },
        },
        "pgn": {
            "enabled": True,
            "notation": "san",
            "nodes": True,
            "append": True,
        },
        "log": {
            "enabled": True,
            "level": "warn",
            "engine": False,
            "append": True,
        },
    }
    path = temp_dir / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class FastchessSprtTest(unittest.TestCase):
    def test_builds_new_run_command_with_weights(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config_path = write_config(temp_dir)
            args = run_fastchess_sprt.parse_args(
                [
                    "--config",
                    str(config_path),
                    "--run-dir",
                    str(temp_dir / "match"),
                    "--engine-a",
                    str(temp_dir / "base" / "chilo"),
                    "--engine-b",
                    str(temp_dir / "candidate" / "chilo"),
                    "--net-a",
                    str(temp_dir / "base.bin"),
                    "--net-b",
                    str(temp_dir / "candidate.bin"),
                    "--name-a",
                    "base",
                    "--name-b",
                    "candidate",
                    "--sprt",
                    "quick",
                    "--elo1",
                    "3",
                ]
            )
            config = run_fastchess_sprt.load_config(config_path)
            run_dir = run_fastchess_sprt.resolve_run_dir(config, config_path.parent, args)
            profile_name, profile = run_fastchess_sprt.select_sprt_profile(config, args.sprt)
            self.assertEqual(profile_name, "quick")
            profile = run_fastchess_sprt.apply_sprt_overrides(profile, args)
            argv = run_fastchess_sprt.build_fastchess_argv(config, config_path, run_dir, "new", profile, args)

            self.assertEqual(argv[0], "fastchess")
            self.assertIn("-engine", argv)
            self.assertIn("cmd=" + str((temp_dir / "base" / "chilo").resolve()), argv)
            self.assertIn("name=base", argv)
            self.assertIn("args=--weights " + str((temp_dir / "base.bin").resolve()), argv)
            self.assertIn("args=--weights " + str((temp_dir / "candidate.bin").resolve()), argv)
            self.assertIn("file=" + str((temp_dir / "book.epd").resolve()), argv)
            self.assertIn("elo1=3", argv)
            self.assertIn(f"outname={run_fastchess_sprt.STATE_FILE_NAME}", argv)
            self.assertIn("7", argv)

    def test_run_mode_auto_resume_and_resume_requires_state(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            state = temp_dir / run_fastchess_sprt.STATE_FILE_NAME
            args = run_fastchess_sprt.parse_args(
                [
                    "--config",
                    str(temp_dir / "config.json"),
                    "--engine-a",
                    "a",
                    "--engine-b",
                    "b",
                ]
            )

            self.assertEqual(run_fastchess_sprt.choose_run_mode(args, state), "new")
            state.write_text("{}", encoding="utf-8")
            self.assertEqual(run_fastchess_sprt.choose_run_mode(args, state), "resume")

            resume_args = run_fastchess_sprt.parse_args(
                [
                    "--config",
                    str(temp_dir / "config.json"),
                    "--engine-a",
                    "a",
                    "--engine-b",
                    "b",
                    "--resume",
                ]
            )
            state.unlink()
            with self.assertRaises(SystemExit):
                run_fastchess_sprt.choose_run_mode(resume_args, state)

    def test_force_new_archives_known_run_files(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            for name in (
                run_fastchess_sprt.STATE_FILE_NAME,
                run_fastchess_sprt.PGN_FILE_NAME,
                run_fastchess_sprt.LOG_FILE_NAME,
                run_fastchess_sprt.COMMAND_FILE_NAME,
            ):
                (temp_dir / name).write_text(name, encoding="utf-8")

            archived = run_fastchess_sprt.archive_run_files(temp_dir)
            self.assertEqual(len(archived), 4)
            for original, backup in archived:
                self.assertFalse(Path(original).exists())
                self.assertTrue(Path(backup).exists())

    def test_dry_run_prints_command_without_creating_run_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config_path = write_config(temp_dir)
            run_dir = temp_dir / "dry-run-match"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = run_fastchess_sprt.main(
                    [
                        "--config",
                        str(config_path),
                        "--run-dir",
                        str(run_dir),
                        "--engine-a",
                        "chilo-a",
                        "--engine-b",
                        "chilo-b",
                        "--dry-run",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertFalse(run_dir.exists())
            self.assertIn("fastchess", stdout.getvalue())
            self.assertIn("-sprt", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
