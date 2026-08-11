# rhapsody_flowgen/com_introspect.py
# hybrid_v3.2 - Diagnostic probe (run ON your machine, Rhapsody open).
#
# PURPOSE
#   The v3.1 log shows that (a) no ACTION body/text setter exists and (b) X/Y
#   never persist. This tool asks Rhapsody itself *what is actually available*
#   so we can pin the exact API instead of guessing. It writes everything to
#   com_introspect.txt next to this file.
#
#   It does NOT modify your project. It creates a scratch diagram in memory,
#   adds one Action + one Condition + their graphical nodes, then dumps every
#   attribute / method / type-library entry for each. Delete the scratch diagram
#   afterwards (it tries to) — nothing is saved.
#
# USAGE
#   python -m rhapsody_flowgen.com_introspect
#   (uses the same config.yaml as main.py to locate project/package/class)

import os
import sys
import logging
import win32com.client

from rhapsody_flowgen.config_loader import load_config  # existing loader
from rhapsody_flowgen.rhapsody_interface import RhapsodyInterface

OUT = os.path.join(os.path.dirname(__file__), "com_introspect.txt")


def _dump(obj, title, fh):
    fh.write("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78 + "\n")
    if obj is None:
        fh.write("  <None>\n")
        return
    # 1) dir()
    try:
        names = sorted(set(dir(obj)))
    except Exception as e:
        names = []
        fh.write(f"  dir() failed: {e}\n")
    fh.write("dir():\n")
    for n in names:
        fh.write(f"    {n}\n")

    # 2) win32com dispatch maps (the authoritative COM member list)
    for mapname in ("_prop_map_get_", "_prop_map_put_", "_dispid_to_func_"):
        m = getattr(obj, mapname, None)
        if m:
            fh.write(f"\n{mapname}:\n")
            try:
                for k in sorted(map(str, m.keys())):
                    fh.write(f"    {k}\n")
            except Exception as e:
                fh.write(f"    <error listing {mapname}: {e}>\n")

    # 3) Probe likely setters/props for text + geometry, report which EXIST.
    probe_attrs = [
        "name", "displayName", "description", "body", "actionCode", "action",
        "text", "specification", "primitiveAction", "label",
    ]
    probe_methods = [
        "setName", "setDisplayName", "setDescription", "setBody",
        "setActionCode", "setAction", "setActionText", "setSpecification",
        "getBody", "getActionCode",
        "setPosition", "getPosition", "setSize", "getSize",
        "setGraphicalProperty", "getGraphicalProperty",
        "setPropertyValue", "getPropertyValue", "getOverriddenProperties",
    ]
    fh.write("\nATTR EXISTS?\n")
    for a in probe_attrs:
        fh.write(f"    {a:20} -> {hasattr(obj, a)}\n")
    fh.write("\nMETHOD EXISTS?\n")
    for m in probe_methods:
        fh.write(f"    {m:22} -> {callable(getattr(obj, m, None))}\n")


def main():
    logging.basicConfig(level=logging.INFO)
    cfg = load_config(os.path.join(os.path.dirname(__file__), "config.yaml"))
    rh = RhapsodyInterface(cfg)
    rh.open_project()
    pkg = rh.find_package_by_path()
    clazz = rh.find_class(pkg, cfg["class_name"])
    op = rh.get_or_create_operation(clazz, cfg["operation_name"])

    op_as_classifier = win32com.client.CastTo(op, "IRPClassifier")
    diagram = op_as_classifier.addActivityDiagram()
    diagram.name = "AD__INTROSPECT_SCRATCH"
    fc = win32com.client.CastTo(diagram, "IRPFlowchart")

    act = diagram.addNewAggr("Action", "probe_action")
    cond = diagram.addNewAggr("Condition", "probe_condition")
    gact = fc.AddNewNodeForElement(win32com.client.CastTo(act, "IRPStateVertex"), 100, 100, 250, 75)
    gcond = fc.AddNewNodeForElement(win32com.client.CastTo(cond, "IRPStateVertex"), 100, 300, 250, 75)

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("Rhapsody COM introspection dump\n")
        try:
            fh.write(f"App: {rh.app.name}, version: {getattr(rh.app, 'version', '?')}\n")
        except Exception:
            pass
        _dump(act,  "MODEL ELEMENT: Action (probe_action)", fh)
        _dump(cond, "MODEL ELEMENT: Condition (probe_condition)", fh)
        _dump(gact, "GRAPHICAL NODE for Action", fh)
        _dump(gcond, "GRAPHICAL NODE for Condition", fh)

    # Clean up: delete the scratch diagram; do NOT save.
    try:
        diagram.deleteFromProject()
    except Exception as e:
        logging.warning("Could not delete scratch diagram automatically: %s "
                        "(delete 'AD__INTROSPECT_SCRATCH' manually; do not save).", e)

    print(f"\nWrote {OUT}. Send me that file and I'll pin the exact setters.")


if __name__ == "__main__":
    main()
