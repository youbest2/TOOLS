# Hybrid COM + SBSX — design & rollout (v3.2)

## Why hybrid (what the v3.1 run proved)
The 2026‑08‑10 17:33 log shows, for **every** node:
- `could not set an ACTION body via any known setter [body, actionCode, action, text]`
  → this Rhapsody build exposes **no** COM setter for an Action's on‑canvas text.
- `Geometry read‑back … {'X':'', 'Y':''}` → node **X/Y never persist** through COM
  (`Width`/`Height` do).

Conditions still show text because a diamond renders the model `displayName`
(which COM *can* set); an Action renders its **body**, which COM here cannot.
So COM is enough for **model + structure**, but **text, exact geometry, and edge
ports must be written directly into the saved diagram unit (SBSX).** This is the
root reason the tool stalled at ~70%.

## Architecture
```
main.py
 └─ RhapsodyInterface.build_diagram_from_parsed_data()   [COM]
      1. insert merge nodes, compute layout                (done)
      2. create Action/Condition model elements            (works)
      3. set displayName (Conditions show text)            (works)
      4. create control-flow edges                         (works, all 22)
      5. emit_sbsx_plan(...) -> sbsx_plan.json             (NEW hook)
      6. project.save() ; close project                    (so SBSX is on disk)
 └─ sbsx_tools.patch(project, diagram, sbsx_plan.json)     [SBSX post-process]
      7. locate diagram unit file
      8. set m_text (Action body), m_position (X/Y), m_size (per node)
      9. set distinct decision exit ports on edges
     10. .bak backup + write; reopen in Rhapsody
```

## What ships now (tested here)
- `sbsx_tools.py`
  - `inspect` — prints the exact XML sub‑tree + tag inventory around each node
    (so we pin your build's real tags). Handles namespaces and non‑XML fallback.
  - `patch` — sets text/position/size by **candidate‑priority** tag matching,
    **never overwriting the internal name**, dry‑run by default, always `.bak`.
  - `emit_sbsx_plan(nodes, edges, node_coords)` — writes `sbsx_plan.json` using
    the **same internal names the COM builder uses** (`action_1`, `condition_2`,
    …) and the FIX‑H decision ports (bottom/right/left).
- `com_introspect.py` — a safe, no‑save probe that dumps every available
  attribute/method/type‑library entry for an Action, a Condition, and their
  graphical nodes. This definitively answers "which setter exists" and may also
  reveal a real `setPosition` for geometry.

### Local test results (synthetic + real graph data)
```
inspect  : finds graphNode blocks, lists m_name/m_position/m_size/m_text
patch    : name preserved; m_text set; m_position/m_size set; namespaced XML ok
emit_plan: B->action_1 … H->condition_10 (matches COM numbering)
           H 3-way ports = bottom(R1) / right(R2) / left(R3)   ✔ (your target)
```

## Two‑step rollout (so we pin your schema, not guess it)
**Step 1 — discover (5 min on your machine):**
```
python -m rhapsody_flowgen.com_introspect          # -> com_introspect.txt
python -m rhapsody_flowgen.sbsx_tools inspect \
       --project "D:\...\FlashBootloader_SwDD.rpyx" \
       --diagram AD_AdcAbs_Get_VBATT_MON \
       --names action_1,condition_2,action_3         # -> stdout
```
Send me `com_introspect.txt` **and** the `inspect` output. From those two I will:
- pin the exact Action text setter (if any COM path exists after all), and
- set `SchemaProfile` to your real SBSX tag names (position/size/text/ports).

**Step 2 — apply:** I return a finalized `SchemaProfile` + the pipeline hook, then:
```
# COM run writes sbsx_plan.json and saves+closes the project, then:
python -m rhapsody_flowgen.sbsx_tools patch --project "...rpyx" \
       --diagram AD_AdcAbs_Get_VBATT_MON --plan sbsx_plan.json            # dry-run
python -m rhapsody_flowgen.sbsx_tools patch ... --plan sbsx_plan.json --write
```

## Pipeline hook (drop into rhapsody_interface, end of build)
```python
from rhapsody_flowgen.sbsx_tools import emit_sbsx_plan
emit_sbsx_plan(nodes, edges, node_coords,
               os.path.join(os.path.dirname(__file__), "sbsx_plan.json"))
```
(Place it right after layout is computed, before/after edges — nodes/edges here
are the post‑merge lists so names line up with the model elements.)

## Honesty / limits
- The SBSX **tag names are build‑specific**. `sbsx_tools` ships with sensible
  defaults and was tested on a synthetic Rhapsody‑style unit and on namespaced
  XML — but the final tags must be confirmed from your `inspect` output before a
  real write. `patch` is **dry‑run by default** and always makes a `.bak`.
- Edge‑port geometry in SBSX is the most schema‑specific piece; once `inspect`
  shows how connector anchors/waypoints are stored, I'll extend `patch` to write
  the bottom/right/left exit points (the plan already carries them).
- Do the SBSX edit **with the project closed** in Rhapsody, then reopen, to avoid
  overwrite on save.
```
