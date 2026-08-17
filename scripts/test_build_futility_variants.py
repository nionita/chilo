from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_futility_variants as builder


def manifest_data() -> dict[str, object]:
    return {
        "schema": builder.SCHEMA,
        "base_version": "0.7.5",
        "engine_directory": "engines",
        "build_root": "builds",
        "baseline": {"margins": [120, 320, 550]},
        "variants": [
            {"code": "f01", "margins": [120, 240, 360], "note": "control"},
            {"code": "f02", "margins": [120, 240, 360, 480, 600]},
        ],
    }


def write_manifest(directory: Path, data: dict[str, object]) -> Path:
    path = directory / "variants.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class ManifestTest(unittest.TestCase):
    def test_loads_relative_paths_and_variants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = builder.load_manifest(write_manifest(root, manifest_data()))
            self.assertEqual(manifest["engine_directory"], root / "engines")
            self.assertEqual(manifest["build_root"], root / "builds")
            self.assertEqual(manifest["variants"][1]["margins"], [120, 240, 360, 480, 600])

    def test_rejects_duplicate_codes_and_invalid_margins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = manifest_data()
            duplicate["variants"] = [{"code": "f01", "margins": [100]}, {"code": "f01", "margins": [200]}]
            with self.assertRaisesRegex(builder.VariantBuildError, "duplicate variant code"):
                builder.load_manifest(write_manifest(root, duplicate))

            invalid = manifest_data()
            invalid["variants"] = [{"code": "f01", "margins": [200, 100]}]
            with self.assertRaisesRegex(builder.VariantBuildError, "nondecreasing"):
                builder.load_manifest(write_manifest(root, invalid))


class BuildCommandTest(unittest.TestCase):
    def test_generates_isolated_avx2_build_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = builder.load_manifest(write_manifest(root, manifest_data()))
            command = builder.build_command(manifest["variants"][0], manifest)
            build_dir = root / "builds" / "0.7.5-f01-d3-120-240-360"
            self.assertEqual(command[0], "make")
            self.assertIn(f"BUILD_DIR={build_dir}", command)
            cppflags = next(item for item in command if item.startswith("EXTRA_CPPFLAGS="))
            self.assertIn("-DCHILO_VERSION_OVERRIDE=0.7.5-f01", cppflags)
            self.assertIn("-DCHILO_FUTILITY_MAX_DEPTH=3", cppflags)
            self.assertIn("-DCHILO_FUTILITY_MARGINS=0,120,240,360,0,0,0,0", cppflags)
            self.assertEqual(command[-1], str(build_dir / "release-avx2" / "chilo"))

    @mock.patch("build_futility_variants.subprocess.run")
    @mock.patch("build_futility_variants.shutil.copy2")
    @mock.patch("build_futility_variants.verify_version")
    @mock.patch("build_futility_variants.sha256_file", return_value="abc")
    def test_builds_and_records_one_variant(
        self,
        sha_mock: mock.Mock,
        verify_mock: mock.Mock,
        copy_mock: mock.Mock,
        run_mock: mock.Mock,
    ) -> None:
        run_mock.return_value.returncode = 0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = manifest_data()
            data["variants"] = [data["variants"][0]]
            manifest = builder.load_manifest(write_manifest(root, data))
            built = root / "builds" / "0.7.5-f01-d3-120-240-360" / "release-avx2" / "chilo"
            built.parent.mkdir(parents=True)
            built.touch()
            entries = builder.build_variants(manifest, overwrite=False, dry_run=False)
            self.assertEqual(entries[0]["sha256"], "abc")
            self.assertTrue(copy_mock.called)
            verify_mock.assert_called_once_with(root / "engines" / "chilo-0.7.5-f01-avx2", "0.7.5-f01 avx2")

    def test_refuses_existing_output_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = manifest_data()
            data["variants"] = [data["variants"][0]]
            manifest = builder.load_manifest(write_manifest(root, data))
            output = root / "engines" / "chilo-0.7.5-f01-avx2"
            output.parent.mkdir()
            output.touch()
            with self.assertRaisesRegex(builder.VariantBuildError, "already exists"):
                builder.build_variants(manifest, overwrite=False, dry_run=True)
