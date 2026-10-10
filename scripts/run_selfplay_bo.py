#!/usr/bin/env python3
"""Sequential game-outcome BO. No proxy labels, cache, or automatic base promotion."""
import argparse
from contextlib import contextmanager, redirect_stdout
import fcntl
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import signal
import subprocess
import sys
import time
import warnings

SCHEMA = "chilo.selfplay_bo.v1"
MODEL = dict(kernel="matern52", gp_ard=False, gp_fit_mode="scaled",
             noise_mode="learned", acquisition="ucb", kappa=0.5, xi=0,
             ei_incumbent="posterior_mean", gp_length_scale_bounds=[0.005, 1000],
             gp_restart_strategy="coverage", gp_n_restarts=8, gp_max_iter=100,
             n_restarts=0, duplicate_policy="replicate", pool_observed_policy="allow")
SPRT = dict(model="normalized", elo0=0.0, elo1=2.0, alpha=0.05, beta=0.05)
ADJ = dict(resign=dict(movecount=3, score=600),
           draw=dict(movenumber=34, movecount=8, score=20), maxmoves=200)
TERMINAL = {"H0", "H1", "max_pairs", "openings_exhausted"}
REPEAT_POLICY = dict(max_repeat_fraction=1.0, max_consecutive_repeats=None)


class BOError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise BOError(message)


def read_json(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def cpp_digest(value):
    # Mirror nlohmann's numeric formatting without rewriting string contents.
    def dump(v):
        if isinstance(v, dict):
            return "{" + ",".join(canonical(k) + ":" + dump(v[k]) for k in sorted(v)) + "}"
        if isinstance(v, list):
            return "[" + ",".join(map(dump, v)) + "]"
        if type(v) is float:
            require(math.isfinite(v), "nonfinite C++ JSON value")
            if v == 0:
                return "-0.0" if math.copysign(1, v) < 0 else "0.0"
            text = repr(abs(v))
            mantissa, _, exponent = text.partition("e")
            digits = mantissa.replace(".", "").lstrip("0")
            power = int(exponent or 0) - (len(mantissa.split(".")[1]) if "." in mantissa else 0)
            while digits.endswith("0"):
                digits, power = digits[:-1], power+1
            n = len(digits) + power
            if len(digits) <= n <= 15:
                text = digits + "0"*(n-len(digits)) + ".0"
            elif 0 < n <= 15:
                text = digits[:n] + "." + digits[n:]
            elif -4 < n <= 0:
                text = "0." + "0"*(-n) + digits
            else:
                text = digits[0] + ("."+digits[1:] if len(digits) > 1 else "") + f"e{n-1:+03d}"
            return ("-" if v < 0 else "") + text
        return canonical(v)
    return hashlib.sha256(dump(value).encode()).hexdigest()


def identity(path):
    sha = hashlib.sha256()
    size = 0
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
            size += len(block)
    return dict(sha256=sha.hexdigest(), size=size)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def run_lock(path):
    with open(path, "a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BOError("run is locked") from exc
        yield


def integer(value, low, high, name):
    require(type(value) is int and low <= value <= high, f"invalid {name}")
    return value


def keys(value, allowed, name):
    require(isinstance(value, dict), f"{name} must be an object")
    require(not (set(value) - set(allowed)), f"unknown {name} keys: {set(value) - set(allowed)}")


def margins(value, strict=True):
    require(isinstance(value, list) and 1 <= len(value) <= 7, "expected 1–7 margins")
    for v in value:
        integer(v, 0, 1000000, "margin")
    require(not strict or all(a < b for a, b in zip(value, value[1:])),
            "candidate margins must be strictly increasing")
    return value


def encode(values):
    margins(list(values))
    return [int(values[0])] + [int(b - a) for a, b in zip(values, values[1:])]


def decode(values):
    require(all(math.isfinite(float(v)) and float(v).is_integer() for v in values),
            "noninteger difference coordinates")
    result, total = [], 0
    for v in values:
        total += int(v)
        result.append(total)
    return margins(result)


def in_region(values, bounds):
    return (len(values) == len(bounds) and
            all(lo <= v <= hi for v, (lo, hi) in zip(values, bounds)) and
            all(a < b for a, b in zip(values, values[1:])))


def check_bounds(bounds, model=False):
    require(isinstance(bounds, list) and 1 <= len(bounds) <= 7, "expected 1–7 margin bounds")
    prev = -1
    for pair in bounds:
        require(isinstance(pair, list) and len(pair) == 2, "invalid margin interval")
        lo, hi = [integer(v, 0, 1000000, "margin bound") for v in pair]
        require(lo < hi if model else lo <= hi, "empty margin interval")
        prev = max(lo, prev + 1)
        require(prev <= hi, "no strictly increasing tuple in region")
    return bounds


def delta_bounds(bounds):
    return [bounds[0]] + [[max(1, lo - prev_hi), hi - prev_lo]
                         for (prev_lo, prev_hi), (lo, hi) in zip(bounds, bounds[1:])]


def resolve(path, directory):
    return str((directory / Path(path).expanduser()).resolve())


def load_config(path):
    path = Path(path).resolve()
    raw = read_json(path)
    keys(raw, ["schema", "executable", "weights", "openings", "base", "nodes",
               "max_pairs", "measurements", "seed", "model_margin_bounds",
               "proposal_margin_bounds", "bootstrap", "tinibo_path", "model",
               "pool", "repeat_policy", "sprt", "adjudication"], "config")
    require(raw.get("schema") == SCHEMA, "unsupported BO config schema")
    c = dict(raw)
    for key in ("executable", "weights", "openings"):
        c[key] = resolve(raw[key], path.parent)
        require(Path(c[key]).is_file(), f"missing {key}: {c[key]}")
    require(os.access(c["executable"], os.X_OK), "executable is not executable")
    c["tinibo_path"] = resolve(raw.get("tinibo_path", "../../tinibo"), path.parent)
    keys(c["base"], ["name", "futility_margins"], "base")
    require(isinstance(c["base"]["name"], str) and c["base"]["name"], "invalid base name")
    base_values = c["base"]["futility_margins"]
    require(isinstance(base_values, list) and len(base_values) <= 7, "expected 0–7 base margins")
    for v in base_values:
        integer(v, 0, 1000000, "base margin")
    for key, default, upper in (("nodes", 120000, 2**63-1), ("max_pairs", 150, 2**31-1),
                                ("measurements", 30, 2**31-1), ("seed", 20261010, 2**64-1)):
        c[key] = integer(raw.get(key, default), 0 if key == "seed" else 1, upper, key)
    c["model_margin_bounds"] = check_bounds(c["model_margin_bounds"], model=True)
    c["proposal_margin_bounds"] = check_bounds(raw.get("proposal_margin_bounds", c["model_margin_bounds"]))
    require(len(c["proposal_margin_bounds"]) == len(c["model_margin_bounds"]) and
            all(ml <= pl <= ph <= mh for (ml, mh), (pl, ph) in
                zip(c["model_margin_bounds"], c["proposal_margin_bounds"])),
            "proposal region must be inside model domain")
    require(all(lo < hi for lo, hi in delta_bounds(c["model_margin_bounds"])),
            "model domain produces fixed/empty delta interval")
    c["model"] = {**MODEL, **raw.get("model", {})}
    keys(c["model"], MODEL, "model")
    require(c["model"]["duplicate_policy"] == "replicate" and
            c["model"]["pool_observed_policy"] == "allow", "repeat policies must be enabled")
    c["pool"] = {"size": 10000, "local_fraction": 0.8, "radius_fraction": 0.1, **raw.get("pool", {})}
    keys(c["pool"], ["size", "local_fraction", "radius_fraction"], "pool")
    integer(c["pool"]["size"], 1, 1000000, "pool size")
    for name in ("local_fraction", "radius_fraction"):
        require(type(c["pool"][name]) in (int, float) and math.isfinite(c["pool"][name]) and
                0 <= c["pool"][name] <= 1, f"invalid {name}")
    c["repeat_policy"] = {**REPEAT_POLICY, **raw.get("repeat_policy", {})}
    keys(c["repeat_policy"], REPEAT_POLICY, "repeat_policy")
    fraction = c["repeat_policy"]["max_repeat_fraction"]
    require(type(fraction) in (int, float) and math.isfinite(fraction) and 0 <= fraction <= 1,
            "invalid max_repeat_fraction")
    consecutive = c["repeat_policy"]["max_consecutive_repeats"]
    if consecutive is not None:
        integer(consecutive, 0, 2**31-1, "max_consecutive_repeats")
    keys(raw.get("sprt", {}), SPRT, "sprt")
    c["sprt"] = {**SPRT, **raw.get("sprt", {})}
    require(c["sprt"]["model"] == "normalized", "only normalized SPRT is supported")
    for key in ("elo0", "elo1", "alpha", "beta"):
        v = c["sprt"][key]
        require(type(v) in (int, float) and math.isfinite(v), f"invalid sprt {key}")
        c["sprt"][key] = float(v)
    s = c["sprt"]
    require(s["elo0"] < s["elo1"] and s["alpha"] > 0 and s["beta"] > 0 and
            s["alpha"] + s["beta"] < 1, "invalid SPRT settings")
    adj = raw.get("adjudication", {})
    keys(adj, ADJ, "adjudication")
    c["adjudication"] = {"maxmoves": adj.get("maxmoves", 200)}
    integer(c["adjudication"]["maxmoves"], 1, 1000000, "maxmoves")
    for group in ("resign", "draw"):
        keys(adj.get(group, {}), ADJ[group], group)
        c["adjudication"][group] = {**ADJ[group], **adj.get(group, {})}
        for key, value in c["adjudication"][group].items():
            low = 1 if group == "resign" and key == "score" else 0
            high = 1000 if key == "movecount" else (1000000 if key == "movenumber" else 28935)
            integer(value, low, high, f"{group} {key}")
    require(isinstance(raw.get("bootstrap", []), list), "bootstrap must be a list")
    c["bootstrap"] = [resolve(p, path.parent) for p in raw.get("bootstrap", [])]
    return c


def libraries(c):
    # Optional explicit source root also works in self-contained packages.
    if c["tinibo_path"] not in sys.path:
        sys.path.insert(0, c["tinibo_path"])
    import numpy as np
    import tinibo
    require(Path(tinibo.__file__).resolve().is_relative_to(Path(c["tinibo_path"])),
            "loaded tinibo is not from configured tinibo_path")
    return np, tinibo


def environment(c):
    np, tinibo = libraries(c)
    with warnings.catch_warnings(), redirect_stdout(io.StringIO()) as buffer:
        warnings.simplefilter("ignore", UserWarning)
        np.show_config()
    package = Path(tinibo.__file__).parent
    sources = {str(p.relative_to(package)): identity(p) for p in sorted(package.rglob("*.py"))}
    return {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__,
            "blas": buffer.getvalue(), "threads": {k: os.environ.get(k) for k in
                ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")},
            "tinibo": sources, "driver": identity(Path(__file__))}


def match_contract(c):
    return {k: identity(c[k]) for k in ("executable", "weights", "openings")} | {
        "base": c["base"]["futility_margins"], "budget": {"mode": "fixed_nodes_per_move", "nodes": c["nodes"]},
        "sprt": c["sprt"], "adjudication": c["adjudication"],
        "opening_order": "random", "fastchess_reference": "072859b"}


def match_config(c, values, seed, name):
    return {"schema": "chilo.selfplay_match.v1", "weights": c["weights"],
            "players": [{"name": name, "parameters": {"futility_margins": list(values)}},
                        {"name": c["base"]["name"], "parameters": {"futility_margins": c["base"]["futility_margins"]}}],
            "openings": {"file": c["openings"], "order": "random", "seed": seed},
            "budget": {"mode": "fixed_nodes_per_move", "nodes": c["nodes"]},
            "max_pairs": c["max_pairs"], "sprt": c["sprt"], "adjudication": c["adjudication"]}


def near(actual, expected, key):
    require(type(actual) in (int, float) and math.isfinite(actual) and
            math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12), f"summary mismatch: {key}")


def opening_fens(path):
    """Mirror the match reader's FEN/EPD counter normalization, without a chess dependency."""
    result = []
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        require(len(fields) >= 4, "invalid opening fields")
        ranks = []
        for rank in fields[0].split("/"):
            squares = "".join("."*int(ch) if ch in "12345678" else ch for ch in rank)
            require(len(squares) == 8, "invalid opening rank")
            ranks.append(re.sub(r"\.+", lambda m: str(len(m.group())), squares))
        require(len(ranks) == 8 and fields[1] in {"w", "b"}, "invalid opening board/side")
        castle = "".join(ch for ch in "KQkq" if ch in fields[2]) or "-"
        half, full = 0, 1
        if len(fields) > 4:
            if fields[4].isdigit():
                require(len(fields) >= 6 and fields[5].isdigit(), "invalid opening counters")
                half, full = int(fields[4]), max(1, int(fields[5]))
            else:
                for name, value in re.findall(r"\b(hmvc|fmvn)\s+(\d+)\s*;", " ".join(fields[4:])):
                    if name == "hmvc":
                        half = int(value)
                    else:
                        full = max(1, int(value))
        result.append(f"{'/'.join(ranks)} {fields[1]} {castle} {fields[3]} {half} {full}")
    require(result and len(result) == len(set(result)), "empty/duplicate opening book")
    return result


def import_match(path, c, contract=None):
    """Verify completed engine evidence, not merely a reported score."""
    path = Path(path).resolve()
    manifest = read_json(path / "manifest.json")
    require(manifest.get("schema") == "chilo.selfplay_match_manifest.v1", "unsupported match manifest")
    frozen = manifest["contract"]
    require(cpp_digest(frozen) == manifest["contract_sha256"], "match contract checksum mismatch")
    expected = contract or match_contract(c)
    settings = frozen["settings"]
    for key in ("executable", "weights", "openings", "fastchess_reference"):
        require(frozen[key] == expected[key], f"incompatible match {key}")
    for key in ("budget", "sprt", "adjudication"):
        require(settings[key] == expected[key], f"incompatible match {key}")
    require(settings["schema"] == "chilo.selfplay_match.v1" and
            settings["openings"]["order"] == "random", "incompatible opening policy")
    require(settings["players"][1]["parameters"]["futility_margins"] == expected["base"],
            "incompatible fixed base")
    values = margins(settings["players"][0]["parameters"]["futility_margins"])
    require(in_region(values, c["model_margin_bounds"]), "import tuple outside model domain")
    order = manifest["opening_order"]
    book = opening_fens(c["openings"])
    require(isinstance(order, list) and len(order) == len(book) and sorted(order) == list(range(len(order))) and
            cpp_digest(order) == manifest["opening_order_sha256"], "invalid opening order/checksum")
    result = read_json(path / "results.json")
    require(result == read_json(path / "status.json"), "terminal results/status disagree")
    require(result["schema"] == "chilo.selfplay_match_results.v1" and result["status"] in TERMINAL,
            "match is not complete")
    require(result["contract_sha256"] == manifest["contract_sha256"] and
            result["players"] == settings["players"], "result contract mismatch")
    bins, wdl, nodes, elapsed, wl, dd, count = [0]*5, [0]*3, 0, 0, 0, 0, 0
    first = None
    with (path / "games.jsonl").open("rb") as stream:
        for line in stream:
            require(line.endswith(b"\n"), "torn completed-game journal")
            record = json.loads(line)
            game = record["game"]
            require(cpp_digest(game) == record["sha256"], "game checksum mismatch")
            require(game["index"] == count and game["pair"] == count//2 and
                    game["white_player"] == count % 2, "journal game order mismatch")
            require(count//2 < len(order) and game["opening_index"] == order[count//2],
                    "journal opening mismatch")
            require(game["fen"] == book[order[count//2]], "journal FEN mismatch")
            score = integer(game["a_score"], 0, 2, "game score")
            wdl[score] += 1
            move_nodes = [0, 0]
            for i, move in enumerate(game["moves"]):
                player = game["white_player"] if game["fen"].split()[1] == "w" else 1-game["white_player"]
                require(move["player"] == (player if i % 2 == 0 else 1-player), "move player mismatch")
                n = integer(move["nodes"], 0, c["nodes"], "move nodes")
                integer(move["completed_nodes"], 0, n, "completed nodes")
                move_nodes[move["player"]] += n
            require(game["nodes"] == move_nodes, "journal node total mismatch")
            nodes += sum(move_nodes)
            elapsed += integer(game["elapsed_ms"], 0, 2**64-1, "game elapsed")
            if count % 2 == 0:
                first = game
            else:
                require(game["fen"] == first["fen"], "paired opening mismatch")
                total = score + first["a_score"]
                bins[total] += 1
                wl += total == 2 and score != first["a_score"]
                dd += score == first["a_score"] == 1
            count += 1
    require(count > 0 and count % 2 == 0, "no complete paired measurement")
    pairs = count // 2
    for key, expected_value in dict(games=count, completed_games=count, pairs=pairs,
                                    losses=wdl[0], draws=wdl[1], wins=wdl[2], pentanomial=bins,
                                    wl_pairs=wl, dd_pairs=dd, total_nodes=nodes, game_elapsed_ms=elapsed).items():
        require(result[key] == expected_value, f"summary mismatch: {key}")
    mean = sum(i*.25*n for i, n in enumerate(bins))/pairs
    variance = sum((i*.25-mean)**2*n for i, n in enumerate(bins))/pairs
    for key, value in dict(score=mean, pair_score_variance=variance,
                           score_mean_variance=variance/pairs, draw_rate=wdl[1]/count).items():
        near(result[key], value, key)
    elo = lambda p: -400*math.log10(1/p-1)
    error = 1.959963984540054*math.sqrt(variance/pairs)
    estimates = {"elo": elo(mean) if 0 < mean < 1 else None,
                 "elo_error95": (elo(mean+error)-elo(mean-error))/2
                 if variance > 0 and mean-error > 0 and mean+error < 1 else None,
                 "los": (1+math.erf((mean-.5)/math.sqrt(2*variance/pairs)))/2 if variance > 0 else None}
    scale = (800/math.log(10))/math.sqrt(2*variance) if variance else None
    estimates.update(normalized_elo=(mean-.5)*scale if variance else None,
                     normalized_elo_error95=error*scale if variance else None)
    for key, value in estimates.items():
        if value is None:
            require(result[key] is None, f"summary mismatch: {key}")
        else:
            near(result[key], value, key)
    lower = math.log(c["sprt"]["beta"]/(1-c["sprt"]["alpha"]))
    upper = math.log((1-c["sprt"]["beta"])/c["sprt"]["alpha"])
    near(result["lower_bound"], lower, "lower_bound")
    near(result["upper_bound"], upper, "upper_bound")
    llr = result["llr"]
    require(type(llr) in (int, float) and math.isfinite(llr), "invalid likelihood")
    decision = "H0" if llr <= lower else "H1" if llr >= upper else "continue"
    require(result["decision"] == decision, "inconsistent SPRT decision")
    status = result["status"]
    require(pairs <= min(settings["max_pairs"], len(order)), "match exceeds pair limit")
    require((status in {"H0", "H1"} and status == decision) or
            (status == "max_pairs" and pairs == settings["max_pairs"] and decision == "continue") or
            (status == "openings_exhausted" and pairs == len(order) and decision == "continue"),
            "terminal stopping reason mismatch")
    require(result["outcome"] == (status if status in {"H0", "H1"} else "inconclusive"),
            "terminal outcome mismatch")
    journal_identity = identity(path / "games.jsonl")
    return {"id": digest({"contract": manifest["contract_sha256"], "journal": journal_identity}),
            "path": str(path), "margins": values, "seed": settings["openings"]["seed"],
            "y": .5-mean, "noise_variance": variance/pairs, "degenerate": variance == 0,
            "result": result, "manifest_sha256": identity(path / "manifest.json")["sha256"],
            "journal": journal_identity, "source_revision": frozen["source_revision"]}


def proposal_pool(c, rng, observations, recommended=None):
    """Actual-margin feasibility first, difference encoding only at the model boundary."""
    bounds, settings = c["proposal_margin_bounds"], c["pool"]
    pool, seen = [], set()

    def add(point):
        point = tuple(point)
        if in_region(point, bounds) and point not in seen:
            seen.add(point)
            pool.append(list(point))

    if recommended is not None:
        add(recommended)
    for observation in observations:
        add(observation["margins"])
    centers = pool.copy()
    if not centers and in_region(c["base"]["futility_margins"], bounds):
        centers = [c["base"]["futility_margins"]]
    domain_upper_bound = math.prod(hi-lo+1 for lo, hi in bounds)
    target = max(min(settings["size"], domain_upper_bound), len(pool))  # Never drop measured repeats.
    local_target = len(pool) + round(max(0, target-len(pool))*settings["local_fraction"])
    radius = [max(1, round((hi-lo)*settings["radius_fraction"])) for lo, hi in bounds]
    # Bounded attempts also support regions with fewer feasible tuples than pool size.
    for local, goal in ((True, local_target), (False, target)):
        if local and not centers:
            continue
        attempts = 0
        while len(pool) < goal and attempts < max(100, target*30):
            attempts += 1
            if local:
                center = rng.choice(centers)
                point = [rng.randint(max(lo, v-r), min(hi, v+r))
                         for (lo, hi), v, r in zip(bounds, center, radius)]
            else:
                # Sequential feasible sampling avoids rejection collapse in narrow regions.
                point, previous = [], -1
                suffix = [hi for _, hi in bounds]
                for i in range(len(suffix)-2, -1, -1):
                    suffix[i] = min(suffix[i], suffix[i+1]-1)
                for (lo, _), hi in zip(bounds, suffix):
                    previous = rng.randint(max(lo, previous+1), hi)
                    point.append(previous)
            add(point)
    require(pool, "empty proposal pool")
    return pool


def tuple_tree(value):
    return tuple(tuple_tree(v) for v in value) if isinstance(value, list) else value


def repeat_status(c, state):
    """Bootstrap informs the model, but only new matches consume repeat quota."""
    completed, observations = state["completed"], state["observations"]
    integer(completed, 0, len(observations), "completed measurements")
    split = len(observations) - completed
    seen = {tuple(o["margins"]) for o in observations[:split]}
    repeats = streak = 0
    for o in observations[split:]:
        repeated = tuple(o["margins"]) in seen
        repeats += int(repeated)
        streak = streak + 1 if repeated else 0
        seen.add(tuple(o["margins"]))
    policy = c["repeat_policy"]
    quota = int(Fraction(str(policy["max_repeat_fraction"])) * c["measurements"])
    reasons = []
    if repeats >= quota:
        reasons.append("repeat_budget_exhausted")
    if policy["max_consecutive_repeats"] is not None and streak >= policy["max_consecutive_repeats"]:
        reasons.append("consecutive_repeat_limit")
    return {"policy": policy, "budget": quota, "completed_repeats": repeats,
            "consecutive_repeats": streak, "repeats_allowed": not reasons, "blocked_by": reasons}


def eligible_pool(c, state, pool):
    status = repeat_status(c, state)
    measured = {tuple(o["margins"]) for o in state["observations"]}
    eligible = pool if status["repeats_allowed"] else [p for p in pool if tuple(p) not in measured]
    status = status | {"excluded_measured_tuples": len(pool)-len(eligible)}
    require(eligible, "no eligible new tuples in proposal pool under repeat policy; "
            "expand the proposal region/pool in a new run")
    return eligible, status


def compact_fit(suggestion):
    if suggestion is None:
        return None
    fit = suggestion.diagnostics["fit"]
    return {k: fit[k] for k in ("length_scale", "ard", "parameters_at_bounds", "signal_standardized",
                                "residual_noise_variance", "negative_log_likelihood") if k in fit}


def optimizer(c, state=None):
    _, tinibo = libraries(c)
    if state is not None:
        require(state.get("schema") == "tinibo.optimizer.v4", "tinibo v4 checkpoint required")
        return tinibo.BayesianOptimizer.from_state(state)
    return tinibo.BayesianOptimizer(None, delta_bounds(c["model_margin_bounds"]),
                                    seed=c["seed"], **c["model"])


def save_state(root, state, opt, pool_rng, seed_rng):
    state.update(optimizer=opt.get_state(), pool_rng=pool_rng.getstate(), seed_rng=seed_rng.getstate())
    atomic_json(root / "state.json", state)


def verify_checkpoint(state, opt):
    actual = opt.get_state()["observations"]
    observations = state["observations"]
    require(actual["x"] == [encode(o["margins"]) for o in observations] and
            actual["y"] == [o["y"] for o in observations] and
            actual["noise_variance"] == [o["noise_variance"] for o in observations],
            "checkpoint/observation history mismatch")
    require(len({o["id"] for o in observations}) == len(observations), "duplicate measurement identity")


def report(root, state, opt, c):
    recommendation = None
    if state["observations"]:
        x, mean = opt.recommend_observed()
        recommendation = {"margins": decode(x), "fitted_score": .5-float(mean),
                          "scope": "model domain; not independently confirmed strength"}
    atomic_json(root / "report.json", {
        "schema": SCHEMA, "completed": state["completed"], "observations": len(state["observations"]),
        "repeat_status": repeat_status(c, state),
        "pending": state["pending"], "recommendation": recommendation,
        "measurements": [{k: o[k] for k in ("id", "path", "margins", "seed", "y", "noise_variance", "degenerate")}
                         | {"pairs": o["result"]["pairs"], "status": o["result"]["status"],
                            "elo": o["result"]["elo"], "elo_error95": o["result"]["elo_error95"]}
                         for o in state["observations"]]})


def execute(config_path, root, resume=False, dry_run=False, max_evaluations=None, clear_stop=False):
    c = load_config(config_path)
    opening_fens(c["openings"])
    opt = optimizer(c)  # Validate numerical settings before creating a run.
    contract = match_contract(c)
    imported, ids, seed_ids = [], set(), set()
    for path in c["bootstrap"]:
        o = import_match(path, c, contract)
        if o["id"] in ids:
            continue
        require(o["seed"] not in seed_ids, "bootstrap measurements share a seed; independence not established")
        imported.append(o)
        ids.add(o["id"])
        seed_ids.add(o["seed"])
    fingerprint = {"config": c, "contract": contract, "environment": environment(c),
                   "imports": [{k: o[k] for k in ("id", "manifest_sha256", "journal")} for o in imported]}
    if dry_run:
        print(json.dumps({"status": "ok", "bootstrap": len(imported), "fingerprint": digest(fingerprint),
                          "new_measurements": c["measurements"], "max_pairs": c["max_pairs"],
                          "repeat_status": repeat_status(c, {"completed": 0, "observations": imported}),
                          "delta_bounds": delta_bounds(c["model_margin_bounds"])}, indent=2))
        return
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with run_lock(root / "run.lock"):
        manifest_path = root / "manifest.json"
        if manifest_path.exists():
            require(resume, "existing optimizer run requires --resume")
            require(read_json(manifest_path) == fingerprint, "resume fingerprint mismatch")
        else:
            require(not any(p.name not in {"run.lock", "manifest.json.tmp", "STOP"} for p in root.iterdir()),
                    "new optimizer run directory is not empty")
            atomic_json(manifest_path, fingerprint)
        pool_rng, seed_rng = random.Random(c["seed"]), random.Random(c["seed"] ^ 0x53505254)
        if (root / "state.json").exists():
            state = read_json(root / "state.json")
            require(state["schema"] == SCHEMA and state["fingerprint"] == digest(fingerprint), "state fingerprint mismatch")
            opt = optimizer(c, state["optimizer"])
            verify_checkpoint(state, opt)
            require(state["observations"][:len(imported)] == imported and
                    state["completed"] == len(state["observations"])-len(imported), "state/import count mismatch")
            require(len(set(state["used_seeds"])) == len(state["used_seeds"]) and
                    set(state["used_seeds"]) == {o["seed"] for o in state["observations"]} |
                    ({state["pending"]["seed"]} if state["pending"] else set()), "state seed history mismatch")
            pool_rng.setstate(tuple_tree(state["pool_rng"]))
            seed_rng.setstate(tuple_tree(state["seed_rng"]))
        else:
            for o in imported:
                opt.tell(encode(o["margins"]), o["y"], noise_variance=o["noise_variance"])
            state = {"schema": SCHEMA, "fingerprint": digest(fingerprint), "observations": imported,
                     "completed": 0, "pending": None, "used_seeds": sorted(seed_ids)}
            save_state(root, state, opt, pool_rng, seed_rng)
        if clear_stop:
            (root / "STOP").unlink(missing_ok=True)
        interrupted, child = False, None

        def stop_signal(signum, frame):
            nonlocal interrupted
            interrupted = True
            if child is not None and child.poll() is None:
                child.send_signal(signal.SIGTERM)

        previous = {s: signal.signal(s, stop_signal) for s in (signal.SIGINT, signal.SIGTERM)}
        this_run = 0
        try:
            while state["completed"] < c["measurements"]:
                if interrupted or (root / "STOP").exists() or (max_evaluations is not None and this_run >= max_evaluations):
                    break
                if state["pending"] is None:
                    recommended = decode(opt.recommend_observed()[0]) if state["observations"] else None
                    pool = proposal_pool(c, pool_rng, state["observations"], recommended)
                    pool, policy_status = eligible_pool(c, state, pool)
                    suggestion = opt.ask(candidates=[encode(p) for p in pool], return_info=True) if state["observations"] else None
                    values = decode(suggestion.x) if suggestion else (
                        c["base"]["futility_margins"] if in_region(c["base"]["futility_margins"], c["proposal_margin_bounds"])
                        else pool_rng.choice(pool))
                    seed = seed_rng.getrandbits(64)
                    while seed in state["used_seeds"]:
                        seed = seed_rng.getrandbits(64)
                    name = f"gamebo-{state['completed']:04d}"
                    if name == c["base"]["name"]:
                        name += "-a"
                    state["used_seeds"].append(seed)
                    state["pending"] = {"name": name, "margins": values, "seed": seed,
                        "config": match_config(c, values, seed, name), "pool_sha256": digest(pool),
                        "pool_size": len(pool), "mean": float(suggestion.mean) if suggestion else None,
                        "std": float(suggestion.std) if suggestion else None,
                        "acquisition": float(suggestion.acquisition_value) if suggestion else None,
                        "repeat_status": policy_status, "fit": compact_fit(suggestion),
                        "repeat": any(o["margins"] == values for o in state["observations"])}
                    # Reserve tuple, seed and all post-ask RNG states before any child writes.
                    save_state(root, state, opt, pool_rng, seed_rng)
                pending = state["pending"]
                require(pending["config"] == match_config(c, pending["margins"], pending["seed"], pending["name"]) and
                        in_region(pending["margins"], c["proposal_margin_bounds"]), "invalid reserved proposal")
                repeated = any(o["margins"] == pending["margins"] for o in state["observations"])
                policy_status = repeat_status(c, state)
                require(pending["repeat"] == repeated and
                        {k: pending["repeat_status"][k] for k in policy_status} == policy_status and
                        (not repeated or policy_status["repeats_allowed"]), "invalid reserved repeat policy")
                require(all(identity(c[k]) == contract[k] for k in ("executable", "weights", "openings")),
                        "frozen artifact changed before match launch")
                directory = root / "measurements" / pending["name"]
                directory.mkdir(parents=True, exist_ok=True)
                proposal_path = directory / "proposal.json"
                if proposal_path.exists():
                    require(read_json(proposal_path) == pending, "reserved proposal evidence changed")
                else:
                    atomic_json(proposal_path, pending)
                cfg_path, match_root = directory / "match.json", directory / "match"
                if cfg_path.exists():
                    require(read_json(cfg_path) == pending["config"], "pending match config changed")
                else:
                    atomic_json(cfg_path, pending["config"])
                print(f"game BO {state['completed']+1}/{c['measurements']} {pending['name']} "
                      f"margins={','.join(map(str, pending['margins']))} seed={pending['seed']} repeat={pending['repeat']}", flush=True)
                print(f"repeat policy used={policy_status['completed_repeats']}/{policy_status['budget']} "
                      f"streak={policy_status['consecutive_repeats']} blocked={','.join(policy_status['blocked_by']) or 'none'} "
                      f"excluded={pending['repeat_status']['excluded_measured_tuples']} "
                      f"length_scale={(pending['fit'] or {}).get('length_scale')}", flush=True)
                # Always let the C++ journal recover/validate, including a completed match
                # whose result was written just before the driver crashed.
                cmd = [c["executable"], "--match-config", str(cfg_path), "--run-dir", str(match_root)]
                if (match_root / "manifest.json").exists():
                    cmd.append("--resume")
                elif match_root.exists():
                    # A kill during the first atomic manifest write can leave only
                    # its uncommitted temporary file. Never clean a live child.
                    with run_lock(match_root / "run.lock"):
                        require(not any(p.name not in {"run.lock", "manifest.json.tmp"} for p in match_root.iterdir()),
                                "unexpected files in uninitialized match")
                        (match_root / "manifest.json.tmp").unlink(missing_ok=True)
                with (directory / "engine.log").open("a", encoding="utf-8") as log:
                    log.write("command=" + canonical(cmd) + "\n")
                    log.flush()
                    if interrupted:
                        break
                    child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    if interrupted:
                        child.send_signal(signal.SIGTERM)
                    # flock in the engine prevents an orphan and a resumed driver from
                    # ever playing the same match simultaneously. A busy child fails safely.
                    while child.poll() is None:
                        time.sleep(0.1)
                    code = child.returncode
                    child = None
                require(code == 0, f"match failed ({code}); see {directory / 'engine.log'}; pending retained")
                if read_json(match_root / "status.json")["status"] == "stopped":
                    break
                o = import_match(match_root, c, contract)
                require(o["margins"] == pending["margins"] and o["seed"] == pending["seed"], "pending result mismatch")
                require(o["id"] not in {v["id"] for v in state["observations"]}, "measurement already imported")
                atomic_json(directory / "receipt.json", o)
                opt.tell(encode(o["margins"]), o["y"], noise_variance=o["noise_variance"])
                state["observations"].append(o)
                state["completed"] += 1
                state["pending"] = None
                save_state(root, state, opt, pool_rng, seed_rng)
                this_run += 1
                print(f"game BO measured score={o['result']['score']:.6f} variance={o['noise_variance']:.6g} "
                      f"pairs={o['result']['pairs']} status={o['result']['status']} degenerate={o['degenerate']}", flush=True)
            report(root, state, opt, c)
            print(f"game BO {'complete' if state['completed'] == c['measurements'] else 'stopped'} "
                  f"completed={state['completed']} pending={state['pending'] is not None}", flush=True)
        finally:
            for s, handler in previous.items():
                signal.signal(s, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "resume"):
        p = sub.add_parser(name)
        p.add_argument("--config", required=True)
        p.add_argument("--run-dir", required=True, type=Path)
        p.add_argument("--resume", action="store_true")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--max-evaluations", type=int)
    for name in ("status", "stop"):
        p = sub.add_parser(name)
        p.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "stop":
            require((args.run_dir / "manifest.json").exists(), "unknown optimizer run")
            atomic_json(args.run_dir / "STOP", {"request": "stop after current measurement"})
            print("stop requested; current measurement will finish")
        elif args.command == "status":
            state = read_json(args.run_dir / "state.json")
            c = read_json(args.run_dir / "manifest.json")["config"]
            c.setdefault("repeat_policy", REPEAT_POLICY)
            print(json.dumps({"completed": state["completed"], "observations": len(state["observations"]),
                              "repeat_status": repeat_status(c, state),
                              "pending": state["pending"], "stop_requested": (args.run_dir / "STOP").exists()}, indent=2))
        else:
            require(args.max_evaluations is None or args.max_evaluations > 0, "max-evaluations must be positive")
            if args.command == "resume":
                require((args.run_dir / "manifest.json").exists(), "unknown optimizer run")
            execute(args.config, args.run_dir, resume=args.resume or args.command == "resume",
                    dry_run=args.dry_run, max_evaluations=args.max_evaluations, clear_stop=args.command == "resume")
        return 0
    except (BOError, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
