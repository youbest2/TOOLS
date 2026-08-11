# rhapsody_flowgen/batch_main.py
# Multi-diagram COM builder (Opus v4+).
#
# Builds MANY activity diagrams in one Rhapsody session from a single config.
# For each diagram job it: parses the .mmd, finds the class/operation, recreates
# the AD, builds it via COM, and saves the per-diagram plan to plans/<AD>.json
# (so patch_all.py can post-process each one).
#
# USAGE (Rhapsody must be running; it will open/save/close the project):
#   python -m rhapsody_flowgen.batch_main --config config.yaml
#
# After this, CLOSE the project in Rhapsody and run:
#   python -m rhapsody_flowgen.patch_all --config config.yaml --write

import os
import sys
import shutil
import logging
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from rhapsody_flowgen.batch_config import load_jobs, summarize, ConfigError
from rhapsody_flowgen.mermaid_parser import (
    parse_mermaid_file, MermaidParseError, check_rhapsody_condition_compatibility)
from rhapsody_flowgen.rhapsody_interface import RhapsodyInterface


def _configure_logging():
    log_file = HERE / "rhapsody_flowgen.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - [%(levelname)s] - %(message)s",
        handlers=[logging.FileHandler(log_file, mode="w", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
        force=True,
    )
    logging.info("Batch logging configured. Log: %s", log_file)


def _resolve_mmd(mmd: str) -> Path:
    p = Path(mmd)
    if p.is_absolute():
        if p.is_file():
            return p
        local = (HERE / p.name)
        if local.is_file():
            logging.warning("mmd '%s' not found; using local %s", p, local)
            return local
        raise FileNotFoundError("Mermaid not found: %s" % p)
    cand = (HERE / p)
    if cand.is_file():
        return cand
    raise FileNotFoundError("Mermaid not found: %s" % cand)


def run(config_path: str) -> int:
    _configure_logging()
    cfg = load_jobs(config_path)
    logging.info("\n%s", summarize(cfg))

    plans_dir = HERE / "plans"
    plans_dir.mkdir(exist_ok=True)
    emitted_plan = HERE / "sbsx_plan.json"   # build_diagram_from_parsed_data writes here

    iface = None
    built, failed = [], []
    try:
        # RhapsodyInterface expects a dict-like config; give it project/rhapsody.
        iface = RhapsodyInterface({
            "project_path": cfg["project_path"],
            "rhapsody_path": cfg.get("rhapsody_path"),
            "package_path": cfg.get("package_path") or [],
        })
        iface.open_project()

        for job in cfg["jobs"]:
            diagram = job["diagram"]
            try:
                logging.info("=== BUILD %s (class=%s, op=%s) ===",
                             diagram, job["class"], job["operation"])
                mmd = _resolve_mmd(job["mermaid_file"])
                nodes, edges = parse_mermaid_file(str(mmd))
                check_rhapsody_condition_compatibility(nodes, edges)

                # per-job package (allows different units/classes)
                iface.config["package_path"] = job["package_path"]
                package = iface.find_package_by_path()
                clazz = iface.find_class(package, job["class"])
                op = iface.get_or_create_operation(clazz, job["operation"])
                ad = iface.recreate_activity_diagram(op)
                iface.build_diagram_from_parsed_data(ad, nodes, edges)

                # capture the per-diagram plan
                if emitted_plan.exists():
                    shutil.copyfile(emitted_plan, plans_dir / (diagram + ".json"))
                    logging.info("Saved plan: %s", plans_dir / (diagram + ".json"))
                else:
                    logging.warning("No sbsx_plan.json emitted for %s", diagram)
                built.append(diagram)
            except Exception as e:
                logging.error("BUILD FAILED for %s: %s", diagram, e, exc_info=True)
                failed.append((diagram, str(e)))

    except Exception as e:
        logging.error("BATCH SETUP ERROR: %s", e, exc_info=True)
        return 2
    finally:
        if iface and iface.project:
            try:
                iface.save_and_close_project()
            except Exception as e:
                logging.error("save/close failed: %s", e)

    logging.info("BUILT: %s", ", ".join(built) or "(none)")
    if failed:
        logging.error("FAILED: %s", "; ".join("%s (%s)" % f for f in failed))
        return 1
    logging.info("All diagrams built. Now CLOSE the project in Rhapsody and run:")
    logging.info("  python -m rhapsody_flowgen.patch_all --config %s --write", config_path)
    return 0


def _cli(argv=None):
    ap = argparse.ArgumentParser(description="Build MANY Rhapsody diagrams from one config")
    ap.add_argument("--config", default=str(HERE / "config.yaml"))
    a = ap.parse_args(argv)
    try:
        return run(a.config)
    except (ConfigError, FileNotFoundError) as e:
        print("CONFIG ERROR: %s" % e); return 2


if __name__ == "__main__":
    sys.exit(_cli())
