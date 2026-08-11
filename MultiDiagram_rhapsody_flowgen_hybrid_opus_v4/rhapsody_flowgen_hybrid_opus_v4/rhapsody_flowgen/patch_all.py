# rhapsody_flowgen/patch_all.py
# Multi-diagram SBSX post-processor (Opus v4+).
#
# Reads the multi-diagram config, finds the unit file that holds each diagram,
# GROUPS diagrams by unit, applies all edits for a unit IN MEMORY, then writes
# each unit ONCE (single .bak per unit). RPY-ASCII safe (reuses sbsx_patch_v109).
#
# USAGE (run with Rhapsody CLOSED):
#   python -m rhapsody_flowgen.patch_all --config config.yaml            # dry-run
#   python -m rhapsody_flowgen.patch_all --config config.yaml --write    # apply
#
# Plan file per diagram (produced by batch_main.py):
#   <package>/plans/<AD-name>.json
# Fallback if a per-diagram plan is missing:
#   <package>/sbsx_plan.json   (the single-diagram plan)

import os
import sys
import json
import glob
import argparse
import logging
from collections import defaultdict

from rhapsody_flowgen import sbsx_patch_v109 as P
from rhapsody_flowgen.batch_config import load_jobs, summarize, ConfigError

HERE = os.path.dirname(os.path.abspath(__file__))


def project_rpy_root(project_path: str) -> str:
    """Return the folder that contains the unit .sbsx files for a .rpyx."""
    return P.find_project_dir(project_path)


def locate_unit(root: str, diagram: str):
    """Return (unit_path, node_count) for the unit whose statechart for
    `diagram` has the most graphical nodes; else (None, 0)."""
    best = (None, -1)
    for f in glob.glob(os.path.join(root, "**", "*.sbsx"), recursive=True):
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                head = fh.read()
            if diagram not in head:
                continue
            doc = P.SbsxRaw(f)
            sc = doc.statechart_for_diagram(diagram)
            n = len(doc.graph_nodes_for_frame(sc)) if sc is not None else 0
            if n > best[1]:
                best = (f, n)
        except Exception as ex:
            logging.warning("locate skip %s: %s", os.path.basename(f), ex)
    return best if best[0] else (None, 0)


def plan_path_for(diagram: str) -> str:
    per = os.path.join(HERE, "plans", diagram + ".json")
    if os.path.exists(per):
        return per
    return os.path.join(HERE, "sbsx_plan.json")  # single-diagram fallback


def run(config_path: str, write: bool, route: bool = True) -> int:
    cfg = load_jobs(config_path)
    print(summarize(cfg))
    root = project_rpy_root(cfg["project_path"])
    print("scanning units under: %s" % root)

    # 1) resolve each diagram to a unit
    per_unit = defaultdict(list)   # unit_path -> [(diagram, plan_path, nodes)]
    missing = []
    for j in cfg["jobs"]:
        diagram = j["diagram"]
        unit, n = locate_unit(root, diagram)
        if not unit:
            missing.append(diagram)
            print("  [MISS] %s: not found in any .sbsx under project root" % diagram)
            continue
        plan = plan_path_for(diagram)
        if not os.path.exists(plan):
            print("  [MISS] %s: no plan file (%s). Run batch_main first." % (diagram, plan))
            missing.append(diagram)
            continue
        per_unit[unit].append((diagram, plan, n))
        print("  [OK]   %s -> %s  (nodes=%d, plan=%s)"
              % (diagram, os.path.basename(unit), n, os.path.basename(plan)))

    if not per_unit:
        print("Nothing to patch."); return 2

    # 2) patch each unit: accumulate all diagrams in memory, then save ONCE
    rc = 0
    for unit, items in per_unit.items():
        print("\n=== UNIT: %s  (%d diagram(s)) ===" % (unit, len(items)))
        doc = P.SbsxRaw(unit)
        for diagram, plan, _n in items:
            plan_obj = json.load(open(plan, encoding="utf-8"))
            rep = P.do_patch(doc, diagram, plan_obj, write=False, route=route)
            for line in rep:
                if line.startswith(("-- matched", "-- routed", "-- guards")):
                    print("  [%s] %s" % (diagram, line))
                elif line.startswith("ABORT"):
                    print("  [%s] %s" % (diagram, line)); rc = 3
        if write:
            print("  " + doc.save(True))   # one .bak + one write for the whole unit
        else:
            print("  DRY-RUN (no file written for this unit)")

    if missing:
        print("\nNOT PATCHED (missing unit or plan): %s" % ", ".join(missing))
    return rc


def _cli(argv=None):
    ap = argparse.ArgumentParser(description="Patch MANY Rhapsody diagrams from one config")
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--write", action="store_true", help="apply (writes one .bak per unit)")
    ap.add_argument("--no-route", dest="route", action="store_false")
    ap.set_defaults(route=True)
    a = ap.parse_args(argv)
    try:
        return run(a.config, write=a.write, route=a.route)
    except (ConfigError, FileNotFoundError) as e:
        print("CONFIG ERROR: %s" % e); return 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(_cli())
