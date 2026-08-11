# Rhapsody FlowGen — DEVELOPER GUIDE (Opus v4)

Everything you need to **understand, maintain, and extend** the tool. Read this
before changing code. Pair it with `SBSX_SCHEMA_v109_PINNED.md` (the on‑disk
format) and `ROUTER_v3.2.3.md` / `FIX-G` / `FIX-H` (design notes).

---

## 1. Why hybrid (the core constraint)

On this Rhapsody build (v109.0.1), the **COM API cannot**:
- set an **Action’s body text** (an action rectangle renders its model *body*,
  not its name), and
- **persist node X/Y**.

It **can** create the model + all control‑flow edges. So:

```
COM  = model + structure   (works)
SBSX = text + geometry + connector anchors + guards   (raw-text edits)
```

The SBSX unit is **RPY‑ASCII**. Re‑serializing it with lxml/ElementTree
corrupts it (`<x></x>` → `<x/>`, declaration quote change) and Rhapsody rejects
the file. **Therefore the patcher never serializes XML — it edits the original
text in place** and preserves every other byte (LF endings, tabs, empty‑tag
style, the declaration). lxml is used **read‑only** to *locate* elements.

---

## 2. Pipeline & data flow

```
 .mmd ─┬─> mermaid_parser.parse_mermaid_file ──> (nodes, edges)
       │
       ├─> flow_utils.insert_merge_nodes  (decisions with >1 incoming get a merge)
       ├─> layout.compute_activity_layout ──> coords {id:(x,y)}   (deterministic)
       │
   COM │  rhapsody_interface.build_diagram_from_parsed_data(diagram, nodes, edges)
       │    - creates Action/Condition model elems (internal names action_N / condition_N)
       │    - creates ControlFlow edges
       │    - sbsx_tools.emit_sbsx_plan(...) ──> sbsx_plan.json     (names + ports + text)
       │    - project.save()
       ▼
 SBSX  sbsx_patch_v109 (raw-text, RPY-ASCII safe)
        locate  : find the .sbsx unit holding AD_<op>
        inspect : list scoped nodes (m_pRoot frame) + current body
        patch   : per node  -> set_action_body_raw + set_node_position_raw
                  per edge  -> route_edges (anchor spread) + set_edge_guard_raw
                  save once (+ .bak)
```

**Determinism matters:** `insert_merge_nodes` and `compute_activity_layout` are
pure/deterministic, so the plan `emit_sbsx_plan` writes matches the graphical
nodes COM created (same `action_N` numbering, same coordinates). The patcher
then matches plan↔graphics **by position** (COM leaves the visible name empty),
which is collision‑proof across a multi‑diagram unit.

---

## 3. Module map (single source of truth)

| File | Responsibility | Notes |
|---|---|---|
| `mermaid_parser.py` | parse `.mmd` → `Node`/`Edge` | FIX‑B: label *skeletonization* so `A[..] --> B[..]` edges aren’t dropped |
| `flow_utils.py` | start/end detection, levels, **merge insertion**, `validate_flow` | topology‑based (no label‑string hacks); cycle‑safe |
| `layout.py` | `compute_activity_layout` (deterministic), `find_main_flow_path`, `check_continuity` | main flow pinned to one X; branches fan out |
| `layout_plan.py` | orthogonal plan JSON (node boxes + right‑angle points) | preview/aux; not required by the SBSX patch |
| `rhapsody_interface.py` | **COM**: build model/edges, FIX‑G text attempts, FIX‑H port hints, `emit_sbsx_plan` hook, BMP export | needs `win32com`; only runs on Windows+Rhapsody |
| `sbsx_tools.py` | `emit_sbsx_plan(nodes, edges, coords)` → `sbsx_plan.json` | internal names + FIX‑H ports (bottom/right/left) |
| `sbsx_patch_v109.py` | **SBSX raw‑text patcher**: locate/inspect/patch; body, position, router, guards | RPY‑ASCII safe; dry‑run + `.bak` |
| `batch_config.py` | load multi‑diagram YAML → normalized jobs | back‑compatible with single keys |
| `batch_main.py` | COM build **many** diagrams; save per‑diagram plans to `plans/` | one Rhapsody session |
| `patch_all.py` | SBSX patch **many** diagrams; group by unit; one write/`.bak` per unit | reuses `sbsx_patch_v109` |
| `main.py` | single‑diagram COM entry point | unchanged classic path |
| `com_introspect.py` | optional probe of COM capabilities | run on your machine if pinning a new build |
| `test_flow_fixes.py` / `test_hybrid_updates.py` | pure‑Python regression tests | no Rhapsody needed |

---

## 4. The pinned SBSX schema (v109.0.1)

(Full detail in `SBSX_SCHEMA_v109_PINNED.md`.) Key facts the code relies on:

- **Diagram scoping**
  `IActivityDiagram/_name == AD_<op>` → its `_id`
  → `CGIStateChart` whose `m_pModelObject/_hid == that _id`
  → `CGIStateChart/m_pRoot` = **activity FRAME** id
  → **nodes** are `CGI*` with `m_pParent == frame` **and** an `m_transform`
    **and no** `m_pSource` (that would be an edge).
  Node kinds: **actions** are `CGIActionState` (model `IState`); **decisions**
  are `CGIConnector` (model `IBranch`).

- **Action text (FIX‑G)** → model `IState/_entryAction/IAction/_body`.
  Body is RPY‑encoded: XML‑escape, `CR → %0D`, keep `LF`.

- **Node position (FIX‑2)** → `CGIActionState/m_transform = "sx 0 0 sy tx ty"`;
  set the translate pair `tx,ty` (scale preserved).

- **Connector anchors (FIX‑H)** → per edge `CGITrans/m_SourcePort` &
  `m_TargetPort`, in **node‑local** coordinates (box `0..1095 × -17..1043`,
  center ~`548,513`; right=`1095`, left=`0`, bottom=`1043`, top=`-17`).

- **Guards** → mirror the file’s own working structure (hundreds of examples):
  `ITransition → AggregatesList → ILabel`, then
  `ILabel → AggregatesList → IGuard`, and `IGuard/_body = YES|NO|<label>`.
  We add one sibling `IGuard` and link it from the transition’s `ILabel`.

> **Real GUIDs are lowercase hex.** Guard linking matches `GUID [0-9a-f-]+`.
> Synthetic tests must use `uuid4()`; uppercase placeholders won’t match.

---

## 5. `sbsx_patch_v109.py` internals

- `class SbsxRaw`
  - `__init__` reads bytes, strips/records a BOM, keeps `self.raw` (exact text),
    and builds a **read‑only** lxml tree + indexes (`istate_id_to_elem`,
    `diagram_name_to_id`, `cgi_nodes`, `statecharts`).
  - **Locators** (read‑only): `statechart_for_diagram`, `root_frame`,
    `graph_nodes_for_frame`, `node_translate`, `node_id`, `node_model_hid`,
    `_istate_block_span`, `_cgitrans_block_span`, `_find_block`.
  - **Raw edits** (mutate `self.raw`): `set_action_body_raw`,
    `set_node_position_raw`, `set_edge_ports_raw`, module‑level
    `set_edge_guard_raw`.
  - `save(write)` → dry‑run returns a message; write makes `.bak` then writes
    `self._bom + self.raw` (no serialization).
- **Router** (`route_edges`, `_side_local`, `_spread_fracs`, `_infer_*`):
  picks each edge’s source/target **side** and **fans out** multiple edges that
  hit the same side so lines stop stacking. It sets anchors only; **no block
  moves, no polyline waypoints** → RPY‑ASCII safe.
- **Guards** (`_guard_text`, `transition_id_for_edge`, `set_edge_guard_raw`):
  only edges with a label get a guard; conditions (`IBranch`) never get a body.
- `do_patch(doc, diagram, plan, write, route=True)` orchestrates: match nodes by
  position → set body+position → route → guards → `save`. **It calls
  `doc.save(write)` at the end**, so:
  - single diagram: pass `write=True`.
  - **many diagrams in one unit** (see `patch_all`): call `do_patch(..., write=False)`
    for each diagram to accumulate edits in `doc.raw`, then call `doc.save(True)`
    **once**.

### Invariants every edit must keep (RPY‑ASCII)
1. Declaration stays exactly `<?xml version="1.0" encoding="UTF-8"?>\n`.
2. Empty tags stay `<x></x>` (never self‑close).
3. No BOM is added; LF endings and tabs preserved.
4. The file still parses (we assert `lxml.fromstring` in tests).

There is a self‑contained check used throughout tests:
```python
assert t.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
assert '<MagicNumber></MagicNumber>' in t
assert re.search(r'<[^>!?][^>]*/>', t) is None   # no self-closing tag
```

---

## 6. Multi‑diagram design

- `batch_config.load_jobs(path)` → `{project_path, rhapsody_path, jobs:[...]}`.
  Each job: `{class, operation, mermaid_file, package_path, diagram}`.
  Back‑compatible: if no `diagrams:` list, it synthesizes one job from the
  legacy top‑level keys.
- `batch_main.run` opens Rhapsody **once**, loops jobs, builds each AD, and
  copies the emitted `sbsx_plan.json` to `plans/<AD>.json`.
- `patch_all.run` resolves each `AD_<op>` to its unit via `locate_unit`,
  **groups by unit**, applies all diagrams to one in‑memory `SbsxRaw`, then
  writes each unit **once** (single `.bak`).

Why group by unit? Many diagrams live in the **same** `.sbsx`. Writing per
diagram would `.bak`/rewrite the whole (large) unit repeatedly. Grouping = one
write per file.

---

## 7. How to extend (recipes)

### 7.1 Set the decision text on the diamond (`_displayName`)
Reference diagrams show the real C condition on the diamond via
`IBranch/_displayName`. To do the same: in `sbsx_patch_v109`, add
`set_branch_displayname_raw(hid, text)` that finds the `IBranch` block (by
`_id == hid`) and sets/creates `<_displayName type="a">…</_displayName>` (Case A
replace / Case C inject before `</IBranch>`), using the same RPY‑encoding.
Call it in `do_patch` for `condition_*` nodes (their `node_model_hid` is an
`IBranch`). Keep it dry‑run/`.bak` and re‑assert the RPY invariants.

### 7.2 True right‑angle “elbow” routing (`--elbow`)
The line path lives in `CGITrans/m_position` as `N x0 y0 x1 y1 …`. Your files
currently store `1 0 0` (Rhapsody auto‑routes). To automate elbows safely you
need **one** real example: in Rhapsody drag a connector into an L‑shape and
save; read that unit to learn the exact `m_position` waypoint convention
(coordinate space, ordering, count). Then add `set_edge_waypoints_raw(src,tgt,
points)` that writes `m_position` for the matched `CGITrans`, guarded behind a
`--elbow` flag. Validate by re‑parsing and, ideally, opening in Rhapsody.

### 7.3 New node kinds (fork/join/object)
`graph_nodes_for_frame` already scopes “any `CGI*` with `m_transform`, no
`m_pSource`”. New kinds will be **positioned** automatically. Text/guards only
apply where a model `IState`/label exists; extend `do_patch` if a new kind needs
special text.

### 7.4 Support a different Rhapsody version
1. Run `com_introspect.py` (optional) and `inspect` on a real unit of that
   build. 2. Confirm the tag names in §4 still hold (`CGIActionState`,
   `CGIConnector`, `m_transform`, `m_pRoot`, `IState/_entryAction/_body`,
   `ITransition/ILabel/IGuard`). 3. Adjust the literals in `SbsxRaw`/router if
   they differ; keep the RPY‑ASCII invariants. 4. Re‑pin the node‑local box if
   `m_polygon` differs (search a node’s `m_polygon`).

---

## 8. Testing

- Pure‑Python (no Rhapsody):
  ```bat
  set PYTHONPATH=.
  python -m rhapsody_flowgen.test_flow_fixes       REM parser/layout/merge/continuity
  python -m rhapsody_flowgen.test_hybrid_updates   REM shape sizing + orthogonal plan
  ```
- SBSX patcher: build a small **RPY‑ASCII** unit (multi‑line elements, **real
  uuid4 GUIDs**), run `do_patch`, then assert the RPY invariants (§5) and check
  bodies/guards. See how the multi‑diagram test constructs `unitA.sbsx` with two
  diagrams and verifies a single write + bodies + `YES/NO` guards.
- The COM side (`rhapsody_interface`, `main`, `batch_main`) can only be run on
  Windows+Rhapsody; keep it **compile‑clean** and covered by the pure‑Python
  parts it depends on.

---

## 9. Pitfalls (learned the hard way)

- **Never** write the SBSX via an XML serializer (breaks RPY‑ASCII).
- **Match by position, not by name** — COM leaves the graphic’s visible name
  empty, and `action_N` repeats across diagrams (57× in the real file). Use the
  node’s **model GUID** for body edits (collision‑proof).
- **Diamonds are `CGIConnector`** (model `IBranch`), not `CGIActionState`; scope
  them in `graph_nodes_for_frame` (they have `m_transform`, no `m_pSource`).
- **Function order matters**: guard helpers must be defined **before**
  `_cli`/`__main__` (a load‑order bug once caused `NameError: _guard_text`).
- **Real GUIDs are lowercase hex** — respect `GUID [0-9a-f-]+` in guard linking.
- **Group multi‑diagram writes by unit** and save once.

---

## 10. File/versioning notes
- Schema pinned to **Rhapsody 109.0.1** (`BuildNo 202011191713`).
- Patcher header says `v3.2.2/RPY-ASCII safe` but includes v3.2.3 router +
  v3.2.4 guards + the ordering fix; the behavior is what this guide describes.
- Keep `docs/` in sync when you add features; add a short note to the relevant
  `FIX-*`/`ROUTER`/`SCHEMA` file and to the User Guide’s automation table.
