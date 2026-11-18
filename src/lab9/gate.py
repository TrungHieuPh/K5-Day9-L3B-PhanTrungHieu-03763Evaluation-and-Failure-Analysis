"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows = pr.get("rows") or []
    base_rows = base.get("rows") or []
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}

    # 1. metric values must be real numbers: nan < min and nan > max are both False, so a NaN
    #    sails past every threshold.
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (not a finite number)")

    # 2. evaluator failures: a crashed grader scores "missing", and missing drops out of the mean.
    for who, rep in (("PR", pr), ("baseline", base)):
        if rep.get("evaluator_failures"):
            problems.append(f"{who} has {len(rep['evaluator_failures'])} evaluator failure(s)")

    # 3. row count = items x seeds, as declared AND as in the baseline and the spec.
    want = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x "
                        f"{len(man.get('seeds') or [])} seeds = {want} (dropped or duplicated rows)")
    if len(rows) != len(base_rows):
        problems.append(f"{len(rows)} rows vs baseline {len(base_rows)}")
    for field in ("items", "seeds"):
        if field in bman and man.get(field) != bman.get(field):
            problems.append(f"manifest {field} {man.get(field)} != baseline {bman.get(field)}")
    if spec.get("seeds") and man.get("seeds") is not None and list(man["seeds"]) != list(spec["seeds"]):
        problems.append(f"manifest seeds {man['seeds']} != spec seeds {spec['seeds']}")

    # 4. the (item, seed) grid: no duplicates, and exactly the baseline's (no cherry-picking).
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dups:
        problems.append(f"duplicated (item, seed) rows: {dups[:5]}")
    pk, bk = set(keys), {(r.get("item_id"), r.get("seed")) for r in base_rows}
    if pk != bk:
        problems.append(f"(item, seed) set differs from baseline: {len(bk - pk)} missing, {len(pk - bk)} extra")

    # 5. every graded spec metric has a real value on every row.
    from lab9.graders import GRADERS
    graded = [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS
              and any(m["id"] in r for r in base_rows + rows)]
    for mid in graded:
        bad = [r for r in rows if not _is_score(r.get(mid))]
        if bad:
            problems.append(f"{len(bad)} row(s) with no valid value for graded metric {mid} "
                            f"(e.g. {bad[0].get('item_id')}@{bad[0].get('seed')}: {bad[0].get(mid)!r})")

    # 6. reported metrics must be what the rows say (a hand-edited headline number).
    if rows and not problems:
        problems += _metrics_match_rows(pr, graded, spec)

    # 7. slice tags come from labels and must not move between runs.
    btags = {(r.get("item_id"), r.get("seed")): sorted(r.get("slices") or []) for r in base_rows}
    moved = sorted({r.get("item_id") for r in rows
                    if (r.get("item_id"), r.get("seed")) in btags
                    and sorted(r.get("slices") or []) != btags[(r.get("item_id"), r.get("seed"))]}, key=str)
    if moved:
        problems.append(f"slice tags differ from baseline for {moved[:5]}")

    # 8. ratchet: on the same eval-set version thresholds may only get stricter.
    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems


def _is_score(v) -> bool:
    if isinstance(v, bool):
        return True
    return isinstance(v, (int, float)) and math.isfinite(v)


def _metrics_match_rows(pr: dict, graded: list[str], spec: dict) -> list[str]:
    from lab9.eval import aggregate
    rows = [dict(r, cost=r.get("cost", 0.0)) for r in pr["rows"]]
    has_cost = all("cost" in r for r in pr["rows"])
    try:
        again = aggregate(rows, graded, k_values=spec.get("pass_k") or [])
    except Exception as e:   # noqa: BLE001 - a report we cannot recompute is not trustworthy
        return [f"cannot recompute metrics from rows: {e!r}"]
    out = []
    for k, v in (pr.get("metrics") or {}).items():
        if k not in again or (k == "cost_per_success" and not has_cost):
            continue
        w = again[k]
        if (v is None) != (w is None) or (v is not None and abs(float(v) - float(w)) > 1e-3):
            out.append(f"metric {k} = {v} but rows give {w} (metrics edited by hand?)")
    return out


def _looser(th: dict, bth: dict) -> list[str]:
    out = []
    for key in ("max", "max_increase"):
        if key in bth and (key not in th or th[key] > bth[key]):
            out.append(f"{key} {bth[key]} -> {th.get(key, 'removed')}")
    if "min" in bth and ("min" not in th or th["min"] < bth["min"]):
        out.append(f"min {bth['min']} -> {th.get('min', 'removed')}")
    if bth.get("no_significant_drop") and not th.get("no_significant_drop"):
        out.append("no_significant_drop removed")
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []            # new eval-set version: thresholds may restart (with a new baseline)
    out = []
    for key in ("eval_set", "labels", "adversarial_pack"):
        if base_spec.get(key) != spec.get(key):
            out.append(f"RATCHET spec {key} changed on the same eval-set version")
    if list(spec.get("seeds") or []) != list(base_spec.get("seeds") or []):
        out.append(f"RATCHET seeds {base_spec.get('seeds')} -> {spec.get('seeds')}")
    bb, sb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if sb.get("confidence", 0.95) < bb.get("confidence", 0.95) or \
            sb.get("n_resamples", 1000) < bb.get("n_resamples", 1000):
        out.append("RATCHET bootstrap weakened")
    mine = {m["id"]: m for m in spec.get("metrics") or []}
    for bm in base_spec.get("metrics") or []:
        m = mine.get(bm["id"])
        if m is None:
            out.append(f"RATCHET metric {bm['id']} removed")
            continue
        if bm.get("blocking") and not m.get("blocking"):
            out.append(f"RATCHET metric {bm['id']} no longer blocking")
        if bm.get("kind") == "safety" and m.get("kind") != "safety":
            out.append(f"RATCHET metric {bm['id']} no longer a safety metric")
        out += [f"RATCHET metric {bm['id']} {x}" for x in _looser(m.get("threshold") or {}, bm.get("threshold") or {})]
    slices = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for bs in base_spec.get("slices") or []:
        sid = f"{bs['name']}/{bs['metric']}"
        s = slices.get((bs["name"], bs["metric"]))
        if s is None:
            out.append(f"RATCHET slice {sid} removed")
            continue
        if bs.get("blocking") and not s.get("blocking"):
            out.append(f"RATCHET slice {sid} no longer blocking")
        out += [f"RATCHET slice {sid} {x}" for x in _looser(s, bs)]
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a = per_item(pr, metric, slice_name=name)      # item -> mean over seeds, slice items only
        b = per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            # An empty slice cannot be judged; treat it as missing, never as a pass.
            verdict = "missing"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if "max" in s and val > s["max"]:
                verdict = "fail"
            if s.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027),
                                                       confidence=bs.get("confidence", 0.95))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
                else:
                    verdict, note = "missing", "no shared items with baseline"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "max", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<32} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
