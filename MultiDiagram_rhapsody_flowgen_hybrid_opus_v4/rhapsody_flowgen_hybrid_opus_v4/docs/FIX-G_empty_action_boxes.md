# FIX-G — Empty ACTION boxes (v3.1)

## Symptom (from the 2026-08-10 17:19 run + exported BMP)
- All **Condition diamonds show text** ("Pointers valid?", "OpStatus?", ...).
- All **Action rectangles are empty**.
- Log shows `Could not set visible text` for 16 of 17 nodes; only `Z` succeeded.
- Everything else is correct: 22/22 edges created (incl. `B->C`), Start at top,
  main spine at X=800, branches fanned, converge to return. (v3 structural fixes
  are working.)

## Root cause
In v3's node loop the three assignments were in **one** `try`:
```python
model_elem.description = ...
model_elem.displayName = node.label
model_elem.name        = node.label     # throws: names can't contain space/=/,/?
```
1. `.name = "Init retVal = E_NOT_OK"` raises (invalid identifier) and **aborts
   the whole block** -> the warning you saw.
2. More importantly, in a Rhapsody flowchart a **Condition** displays its
   name/displayName (so diamonds had text), but an **Action** displays its
   **body** — which the code never set. So even when `displayName` was applied,
   the rectangles stayed empty. (`Z` is an action whose `.name="Z"` happened to
   be valid, yet it is still blank because actions render the *body*, not name.)

## The fix (drop-in `rhapsody_interface.py`, v3.1)
`_set_node_visible_text()` replaces the single-try block and:
1. sets each field in **its own** try/except (one failure can't block the rest);
2. sets `.name` to a **sanitized identifier** (`Init_retVal_E_NOT_OK`) so it
   never throws;
3. keeps `.displayName = label` (verbatim) — this is what Conditions show;
4. sets the **Action body** via a cascade of known setters, stopping at the
   first that works:
   `setBody() -> setActionCode() -> setAction() -> setActionText()`,
   then attribute fallbacks `body -> actionCode -> action -> text`;
5. logs the **winning setter** per node so the correct one can be pinned.

## How to apply
Replace `rhapsody_flowgen/rhapsody_interface.py` in your local
`rhapsody_flowgen_hybrid_opus_v3` with this file, then re-run `main.py`.

## How to confirm it worked
In the new log, each action node should print:
`Visible text set for node.id=... : {... 'setBody()':'ok' ...}`
and the exported BMP will show text inside the rectangles.

## If rectangles are STILL empty
Your Rhapsody build uses a different body API. Search the new log for the line:
`could not set an ACTION body via any known setter [...]`
Send me that bracketed list (the attributes/methods that exist on the element)
and I will pin the exact one. Likely candidates to check in your COM type
library for the `Action` metaclass: `body`, `setBody`, `actionCode`,
`primitiveAction`, `specification`.

## Not changed
Everything else from v3 is intact (topology start detection, merge insertion,
verified geometry, safe BMP export, all edges). Only the node visible-text logic
was modified in this file.
