# v3.2.3 — Anchor-spreading connector router

## What it does
After text + positions are set, the patcher now chooses DISTINCT connector
anchor points per edge and FANS OUT lines that converge on the same node-side,
so control-flow lines stop overlapping. It does NOT move blocks and does NOT
write polyline waypoints -> stays RPY-ASCII safe.

## Rules (match your convention)
- Incoming edges enter from the side FACING the source (top when coming from
  above); a decision's outgoing edges leave LEFT / RIGHT (+ BOTTOM for 3-way).
- Multiple edges hitting one node-side are spread across that side (margins,
  never at corners), ordered by the opposite endpoint to minimise crossings.
- Side is chosen from the layout columns, so right-column lines stay right and
  left stays left => no criss-cross across the center spine for column layouts.
  (A genuine right-source -> left-target edge is the only case that must cross,
  by definition; none exist in the 204F flow.)

## Coordinates (pinned to your unit)
Anchors are NODE-LOCAL: box 0..1095 (x) by -17..1043 (y), center ~ (548,513).
  right=(1095,y) left=(0,y) bottom=(x,1043) top=(x,-17)

## Controls
- Router is ON by default in `patch`.
- `--no-route` reverts to the legacy single-anchor behaviour.

## Verified (this build)
- On your REAL patched unit (bak): 10/10 edges routed; the 5-incoming return
  node received 5 DISTINCT target anchors (no overlap).
- Wrote to disk with the REAL sbsx_plan.json, re-parsed from disk:
  declaration preserved, <MagicNumber></MagicNumber> intact, NO self-closing
  tags, no BOM, well-formed. Both route and --no-route paths verified.
- Package: 6/6 flow tests pass; end-to-end via the assembled package OK.

## Note
This improves anchor placement (what COM cannot do). True right-angle "elbow"
polylines would need a one-time reference: drag ONE connector into an L-shape in
Rhapsody and save; that reveals the exact m_position waypoint format for your
build, after which elbows can be automated safely (optional future --elbow).
