# FIX-H — Distinct decision exit ports (v3.2)

## What you asked
For a decision (Condition), the Yes/No (and 3-way) branches should **leave from
different points of the diamond** instead of all starting at the same
bottom-center point. Correct — that's what makes it look clean, and it matches
your reference image.

## What changed (drop-in `rhapsody_interface.py`)
Two small helpers + a reworked edge loop:

- `_source_port(...)` chooses the **exit** vertex on the source:
  - Action, or a decision with one out-edge  -> **bottom center** (unchanged).
  - Decision with >1 out-edge:
    - branch aligned below            -> **bottom** vertex
    - branch to the right             -> **right** vertex
    - branch to the left              -> **left** vertex
- `_target_port(...)` chooses a clean **entry** point on the target:
  - below/aligned -> enter **top**; to the right -> enter **left** side;
    to the left -> enter **right** side; above (loop) -> enter **bottom**.
- The edge loop now passes these ports to `AddNewEdgeForElement(...)` and logs
  `ports: exit=(x,y) enter=(x,y)` per edge.

`_ALIGN_TOL = 60` px decides "straight down" vs "side". Node box is 250x75, so a
right vertex is `(left+250, top+37)`, left vertex `(left, top+37)`, bottom
`(left+125, top+75)`.

## Proof on your 204F diagram (coords from the 17:19 run log)
```
C  -> X1  exit=RIGHT   -> D  exit=BOTTOM
D  -> X2  exit=RIGHT   -> E  exit=BOTTOM
E  -> Y1  exit=RIGHT   -> F  exit=BOTTOM
F  -> G1  exit=RIGHT   -> H  exit=BOTTOM
H  -> R2  exit=RIGHT   -> R1 exit=BOTTOM   -> R3 exit=LEFT
```
Every decision now emits its branches from separate vertices (the 3-way `H`
uses bottom + right + left).

## How to apply / verify
1. Replace `rhapsody_flowgen/rhapsody_interface.py` with this file (it already
   includes FIX-G visible-text). Re-run `main.py`.
2. In the new log, confirm lines like:
   `ports: exit=(1050,357) enter=(1060,477) [siblings=2, type=condition]`.

## Caveat (honest)
I can't run Rhapsody/win32com here, so this is **syntax-verified** and the port
math is unit-simulated on your real coordinates — but not COM-tested. Rhapsody
treats the given points as routing hints; on some builds you may still want
orthogonal cleanup from `layout_plan.json`. If the entry side looks off on your
build, tell me and I'll flip the target-port rule. `_ALIGN_TOL` (60) is the one
knob to tune if a near-vertical branch should still exit sideways.
