from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_fastchess_sprt


def value_after(argv: List[str], flag: str) -> str:
    index = argv.index(flag)
    return argv[index + 1]


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
            self.assertEqual(value_after(argv, "-concurrency"), "1")
            self.assertIn("outname=" + str((temp_dir / "match" / run_fastchess_sprt.STATE_FILE_NAME).resolve()), argv)
            self.assertIn("7", argv)

    def test_concurrency_cli_override(self):
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
                    "a",
                    "--engine-b",
                    "b",
                    "--concurrency",
                    "4",
                ]
            )
            config = run_fastchess_sprt.load_config(config_path)
            _, profile = run_fastchess_sprt.select_sprt_profile(config, None)
            argv = run_fastchess_sprt.build_fastchess_argv(config, config_path, temp_dir / "match", "new", profile, args)

            self.assertEqual(value_after(argv, "-concurrency"), "4")

    def test_force_concurrency_precedence(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config_path = write_config(temp_dir)
            config = run_fastchess_sprt.load_config(config_path)
            config["force_concurrency"] = True

            no_force_args = run_fastchess_sprt.parse_args(
                [
                    "--config",
                    str(config_path),
                    "--run-dir",
                    str(temp_dir / "match"),
                    "--engine-a",
                    "a",
                    "--engine-b",
                    "b",
                    "--no-force-concurrency",
                ]
            )
            _, profile = run_fastchess_sprt.select_sprt_profile(config, None)
            argv = run_fastchess_sprt.build_fastchess_argv(config, config_path, temp_dir / "match", "new", profile, no_force_args)
            self.assertNotIn("-force-concurrency", argv)

            config.pop("force_concurrency")
            force_args = run_fastchess_sprt.parse_args(
                [
                    "--config",
                    str(config_path),
                    "--run-dir",
                    str(temp_dir / "match"),
                    "--engine-a",
                    "a",
                    "--engine-b",
                    "b",
                    "--force-concurrency",
                ]
            )
            argv = run_fastchess_sprt.build_fastchess_argv(config, config_path, temp_dir / "match", "new", profile, force_args)
            self.assertIn("-force-concurrency", argv)

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

    def test_resume_state_uses_metadata_without_regular_args(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            run_dir = Path(temp_dir_name)
            state_path = run_dir / run_fastchess_sprt.STATE_FILE_NAME
            state_path.write_text("{}", encoding="utf-8")
            (run_dir / run_fastchess_sprt.COMMAND_FILE_NAME).write_text(
                json.dumps(
                    {
                        "config": str(run_dir / "wrapper-config.json"),
                        "fastchess_argv": ["/usr/local/bin/fastchess", "-config", "outname=fastchess_state.json"],
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = run_fastchess_sprt.main(["--resume-state", str(state_path), "--dry-run"])

            self.assertEqual(exit_code, 0)
            printed = stdout.getvalue()
            self.assertIn("/usr/local/bin/fastchess", printed)
            self.assertIn("file=" + str(state_path.resolve()), printed)
            self.assertIn("outname=" + str(state_path.resolve()), printed)
            self.assertIn("stats=true", printed)

    def test_command_summary_contains_recovery_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            config_path = write_config(temp_dir)
            summary_path = temp_dir / run_fastchess_sprt.COMMAND_FILE_NAME
            args = run_fastchess_sprt.parse_args(
                [
                    "--config",
                    str(config_path),
                    "--run-dir",
                    str(temp_dir / "match"),
                    "--engine-a",
                    "base",
                    "--engine-b",
                    "candidate",
                    "--name-a",
                    "base",
                    "--name-b",
                    "candidate",
                ]
            )
            run_fastchess_sprt.write_command_summary(
                summary_path,
                config_path,
                temp_dir / "match",
                "new",
                "normal",
                {"elo0": 0, "elo1": 2, "alpha": 0.05, "beta": 0.05, "model": "normalized"},
                ["fastchess", "-config", "outname=state.json"],
                [],
                None,
                ["--config", str(config_path), "--engine-a", "base", "--engine-b", "candidate"],
                args,
            )

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["engine_a"]["name"], "base")
            self.assertEqual(summary["engine_b"]["name"], "candidate")
            self.assertEqual(summary["sprt_profile"], "normal")
            self.assertEqual(summary["state_file"], str((temp_dir / "match" / run_fastchess_sprt.STATE_FILE_NAME).resolve()))
            self.assertIn("--resume-state", summary["resume_command"])
            self.assertIn("wrapper_argv", summary)
            self.assertIn("fastchess_argv", summary)

    def test_keyboard_interrupt_returns_130_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            run_dir = Path(temp_dir_name)
            state_path = run_dir / run_fastchess_sprt.STATE_FILE_NAME

            def interrupting_runner(*_args, **_kwargs):
                raise KeyboardInterrupt

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = run_fastchess_sprt.run_fastchess_process(
                    ["fastchess", "-config", "outname=state.json"], run_dir, state_path, runner=interrupting_runner
                )

            self.assertEqual(exit_code, 130)
            self.assertIn("--resume-state", stdout.getvalue())
            self.assertIn(str(state_path.resolve()), stdout.getvalue())

    def test_fen_openings_are_normalized_to_epd(self):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source = temp_dir / "book.fen"
            source.write_text(
                "r1b1k1nr/ppp2ppp/2p2q2/b3P3/3p4/B1P2N2/P4PPP/RN1Q1RK1 b kq - 0 0\n"
                "8/8/8/8/8/8/4K3/4k2Q w - - 7 12\n",
                encoding="utf-8",
            )
            config = {
                "fastchess": "fastchess",
                "opening": {
                    "file": str(source),
                    "format": "fen",
                    "order": "sequential",
                },
                "sprt_profiles": {
                    "normal": {
                        "elo0": 0,
                        "elo1": 2,
                        "alpha": 0.05,
                        "beta": 0.05,
                    }
                },
            }
            config_path = temp_dir / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            run_dir = temp_dir / "match"

            opening_config, summary = run_fastchess_sprt.effective_opening_config(
                config, config_path, run_dir, materialize=True
            )

            self.assertEqual(opening_config["format"], "epd")
            self.assertEqual(opening_config["file"], str(run_dir / run_fastchess_sprt.NORMALIZED_OPENINGS_FILE_NAME))
            self.assertIsNotNone(summary)
            self.assertEqual(summary["positions"], 2)

            rows = (run_dir / run_fastchess_sprt.NORMALIZED_OPENINGS_FILE_NAME).read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                rows[0],
                "r1b1k1nr/ppp2ppp/2p2q2/b3P3/3p4/B1P2N2/P4PPP/RN1Q1RK1 b kq - hmvc 0; fmvn 1;",
            )
            self.assertEqual(rows[1], "8/8/8/8/8/8/4K3/4k2Q w - - hmvc 7; fmvn 12;")


if __name__ == "__main__":
    unittest.main()
