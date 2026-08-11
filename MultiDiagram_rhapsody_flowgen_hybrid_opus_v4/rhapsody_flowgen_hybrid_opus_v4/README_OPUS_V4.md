# rhapsody_flowgen — Opus v4 (clean release)

Generates IBM Rhapsody 109 activity diagrams from Mermaid `.mmd` files, using a
**hybrid COM + SBSX** pipeline:

1. **COM** builds the model + all control-flow edges and saves the project.
2. **SBSX post-process** (`sbsx_patch_v109.py`) writes what COM cannot on this
   Rhapsody build: **Action body text**, **node positions**, **spread connector
   anchors** (no overlaps), and **[YES]/[NO] guards** on decision branches.
   All edits are RAW-TEXT / **RPY-ASCII safe** (dry-run by default, always `.bak`).

## What's in this package
```
run_sbsx_patch.bat                self-locating runner (locate→inspect→patch)
rhapsody_flowgen/
  __init__.py
  main.py                         entry point (COM build; writes sbsx_plan.json)
  config.yaml                     EDIT: project/package/class/operation/mmd
  config_loader.py
  mermaid_parser.py               FIX-B: no dropped edges
  flow_utils.py                   start/end detection, levels, merge insertion
  layout.py                       deterministic single-pass layout
  layout_plan.py                  orthogonal plan (JSON)
  rhapsody_interface.py           COM build + FIX-G text + FIX-H ports + emit hook
  sbsx_tools.py                   emit_sbsx_plan()
  sbsx_patch_v109.py              SBSX patcher: text+pos+route+guards (fixed order)
  com_introspect.py               optional COM capability probe
  test_flow_fixes.py              6 pure-Python regression tests
  test_hybrid_updates.py          layout/plan test
  flowinitializesensor.mmd        sample input (the 204F flow)
  sbsx_plan.json                  sample plan for the sample diagram
docs/                             analysis + pinned schema + fix notes
```

## Requirements
- Windows + IBM Rhapsody (for the COM step; `rhapsody_interface.py` uses win32com)
- Python 3.9+  with:  `pip install lxml pyyaml pywin32`
- (`matplotlib` is only needed if you run the optional test that imports it; the
  core pipeline does not require it.)

## Run (2 steps)
1) **COM build** (produces/updates `rhapsody_flowgen/sbsx_plan.json`):
```
python -m rhapsody_flowgen.main
```
2) **Close Rhapsody**, then patch the saved unit (self-locating bat):
```
run_sbsx_patch.bat
```
The bat runs: **locate** → **inspect** → **dry-run patch** → (confirm) → **write**.
Expect: actions `body=ok pos=ok`, diamonds `body=n/a pos=ok`, `guards set on N`,
then `WROTE … .bak`. Reopen the project: boxes filled, positioned, lines spread,
and `[YES]/[NO]` on decision branches.

Manual equivalent:
```
python -m rhapsody_flowgen.sbsx_patch_v109 locate  --root "<..._rpy>" --diagram AD_<Op>
python -m rhapsody_flowgen.sbsx_patch_v109 inspect --sbsx "<unit>.sbsx" --diagram AD_<Op>
python -m rhapsody_flowgen.sbsx_patch_v109 patch   --sbsx "<unit>.sbsx" --diagram AD_<Op> --plan rhapsody_flowgen\sbsx_plan.json
python -m rhapsody_flowgen.sbsx_patch_v109 patch   --sbsx "<unit>.sbsx" --diagram AD_<Op> --plan rhapsody_flowgen\sbsx_plan.json --write
```
`--no-route` reverts to legacy single-anchor edges.

## Verify the install (no Rhapsody needed)
```
set PYTHONPATH=.
python -m rhapsody_flowgen.test_flow_fixes      REM expect 6/6 PASS
python -m rhapsody_flowgen.test_hybrid_updates  REM expect PASS
```

## What changed vs v3.2.4
- **Fixed** `sbsx_patch_v109.py` load-order bug (guard functions now defined
  before `_cli`/`__main__`) — no more `NameError: _guard_text` on `patch`.
- **Removed** dead/duplicate code and files with hardcoded absolute paths:
  `Test.py`, `diagram_builder.py`, `test_layout.py`, `mermaid_to_graphviz.py`,
  the bundled **Graphviz/** tree (optional PNG preview only), old `1.bat`,
  `_backup_v2_originals/`, and generated artifacts (`*.log`, `layout_plan.json`,
  `*.bmp`, `mermaid_graphviz*`, `__pycache__`).
- **Kept** the entire working pipeline + tests + docs.

## Verified before shipping
- `py_compile` all modules: 0 failures.
- `python -m rhapsody_flowgen.sbsx_patch_v109 patch` on the real unit:
  **17/17 nodes, 22/22 routed, 11 guards**, RPY-ASCII safe (declaration +
  `<MagicNumber></MagicNumber>` preserved, no self-closing tags, no BOM,
  re-parses from disk).
- `test_flow_fixes` 6/6 PASS, `test_hybrid_updates` PASS — re-checked from the
  shipped zip.

## Safety
- Do the SBSX edit with the project **closed**, then reopen.
- `patch` is **dry-run by default** and always writes a `.bak`.
- Schema pinned to Rhapsody **109.0.1**. On a different build, run `inspect`
  and check the scoped-node count; the tag names may need re-pinning.

## Multi-diagram (Opus v4) & documentation
This release can build/patch MANY diagrams from ONE config.yaml.

- `rhapsody_flowgen/config.yaml` -> add a `diagrams:` list (class, operation,
  mermaid_file; optional per-entry `package_path`/`diagram`).
- `run_all.bat` -> COM-build all, then (project closed) patch all.
  Manual: `python -m rhapsody_flowgen.batch_main` then
          `python -m rhapsody_flowgen.patch_all --write`.
- New modules: batch_config.py, batch_main.py, patch_all.py.
- Docs: docs/USER_GUIDE.md (how to run) and docs/DEVELOPER_GUIDE.md
  (architecture + how to extend). Also SBSX_SCHEMA_v109_PINNED.md.
