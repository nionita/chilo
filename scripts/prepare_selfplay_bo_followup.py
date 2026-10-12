#!/usr/bin/env python3
"""Prepare a fresh BO config from a stopped run; verify and retain every finished match."""
import argparse
from pathlib import Path
import sys
import tempfile

import run_selfplay_bo as bo


def prepare(source_config, source_run, output_config, output_run, seed,
            max_repeat_fraction=.25, max_consecutive_repeats=1, measurements=None,
            gp_ard=None, gp_length_scale_bounds=None, kappa=None):
    source_run, output_config, output_run = map(
        lambda p: Path(p).resolve(), (source_run, output_config, output_run))
    bo.require((source_run / "run.lock").is_file(), "source run has no lock file")
    bo.require(source_run != output_run, "follow-up needs a new run directory")
    bo.require(not output_run.exists() or not any(output_run.iterdir()), "follow-up run directory is not empty")
    with bo.run_lock(source_run / "run.lock"):
        config = bo.load_config(source_config)
        manifest = bo.read_json(source_run / "manifest.json")
        state = bo.read_json(source_run / "state.json")
        bo.require(state["schema"] == bo.SCHEMA and state["fingerprint"] == bo.digest(manifest),
                   "source state/manifest mismatch")
        bo.require(state["pending"] is None, "source still has a pending match; wait for graceful stop")
        # Prior drivers did not expand the optional repeat policy.
        comparable = dict(config)
        if "repeat_policy" not in manifest["config"]:
            comparable.pop("repeat_policy")
        bo.require(comparable == manifest["config"], "source config changed since run creation")
        contract = bo.match_contract(config)
        bo.require(contract == manifest["contract"], "source frozen match contract changed")
        bo.verify_checkpoint(state, bo.optimizer(config, state["optimizer"]))
        compact = {}
        if "bootstrap_summary" in config:
            compact = {o["id"]: o for o in bo.summary_observations(config["bootstrap_summary"], config, contract)}
        observations = [compact[o["id"]] if o["id"] in compact else
                        bo.import_match(o["path"], config, contract) for o in state["observations"]]
        bo.require(observations == state["observations"], "source measured evidence changed")
        imports = [{k: o[k] for k in ("id", "manifest_sha256", "journal")}
                   for o in observations[:len(manifest["imports"])]]
        bo.require(imports == manifest["imports"] and
                   state["completed"] == len(observations)-len(imports), "source import/count mismatch")
        bo.require(len({o["seed"] for o in observations}) == len(observations) and
                   len(state["used_seeds"]) == len(observations) and
                   set(state["used_seeds"]) == {o["seed"] for o in observations}, "source seed history mismatch")
        remaining = config["measurements"] - state["completed"]
        config.update(seed=seed, measurements=remaining if measurements is None else measurements,
                      bootstrap=[o["path"] for o in observations if o["id"] not in compact],
                      repeat_policy={"max_repeat_fraction": max_repeat_fraction,
                                     "max_consecutive_repeats": max_consecutive_repeats})
        if gp_ard is not None:
            bo.require(type(gp_ard) is bool, "gp_ard override must be boolean")
            config["model"]["gp_ard"] = gp_ard
        if gp_length_scale_bounds is not None:
            config["model"]["gp_length_scale_bounds"] = list(gp_length_scale_bounds)
        if kappa is not None:
            config["model"]["kappa"] = kappa
        # Use the full config parser before creating any permanent output.
        with tempfile.TemporaryDirectory() as temp:
            check = Path(temp) / "config.json"
            bo.atomic_json(check, config)
            config = bo.load_config(check)
        bo.optimizer(config)  # Validate the new numerical settings without restoring the old model.
        receipt = {"schema": "chilo.selfplay_bo_followup.v1", "source_run": str(source_run),
                   "source_manifest": bo.identity(source_run / "manifest.json"),
                   "source_state": bo.identity(source_run / "state.json"),
                   "imported_measurements": [o["id"] for o in observations],
                   "source_completed": state["completed"], "remaining_original_budget": remaining,
                   "output_run": str(output_run), "config_sha256": bo.digest(config),
                   "repeat_policy": config["repeat_policy"],
                   "source_model": manifest["config"]["model"], "model": config["model"],
                   "repeat_budget": bo.repeat_status(config, {"completed": 0, "observations": observations})["budget"],
                   "driver": bo.identity(Path(bo.__file__))}
        receipt_path = output_config.with_name(output_config.name + ".followup.json")
        for path, value in ((output_config, config), (receipt_path, receipt)):
            bo.require(not path.exists() or bo.read_json(path) == value, f"refusing to overwrite {path}")
        bo.atomic_json(output_config, config)
        bo.atomic_json(receipt_path, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-config", "source-run", "output-config", "output-run"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--measurements", type=int, help="default: original budget minus finished new matches")
    parser.add_argument("--max-repeat-fraction", type=float, default=.25)
    parser.add_argument("--max-consecutive-repeats", type=int, default=1)
    parser.add_argument("--gp-ard", action=argparse.BooleanOptionalAction, default=None,
                        help="override shared/ARD geometry for the fresh run only")
    parser.add_argument("--gp-length-scale-bounds", nargs=2, type=float, metavar=("LOW", "HIGH"),
                        help="override normalized length-scale bounds for the fresh run only")
    parser.add_argument("--kappa", type=float, help="future LCB exploration weight; measurements remain valid")
    args = parser.parse_args()
    try:
        receipt = prepare(**vars(args))
        print(f"follow-up prepared: imported={len(receipt['imported_measurements'])} "
              f"new_budget={bo.read_json(args.output_config)['measurements']} "
              f"repeat_budget={receipt['repeat_budget']}; no match started")
        return 0
    except (bo.BOError, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
