# Rhapsody FlowGen

Automated UML Activity Diagram Generator for IBM Rational Rhapsody using Mermaid `.mmd` files.

## Features
- Configurable YAML input
- COM automation via pywin32
- Diagram generation from flowcharts

## Run
```bash
python main.py
```

## Config Example
```yaml
project_path: "C:/Projects/ControlSystem.rpy"
package: "SensorModule"
class: "TempController"
operation: "initializeSensor"
mermaid_file: "examples/flowinitializesensor.mmd"
```

## Hybrid v2 updates
- Mermaid input resolves against the running `main.py` directory. If an absolute configured path points elsewhere but a same-named local file exists, the local file is used and logged.
- The resolved Mermaid path, byte size, modified timestamp, and SHA-256 are logged before parsing.
- Existing shape-based Mermaid parsing is retained.
- Action and condition symbols use Mermaid labels as visible Rhapsody names; generated names and Mermaid IDs are retained in descriptions.
- Node width and height are calculated from wrapped text rather than fixed at 250 x 75.
- Mermaid edge labels are written to Rhapsody control flows when the COM object supports name/displayName/description.
- `layout_plan.json` contains node rectangles and deterministic orthogonal edge points for the later graphical-only SBSX routing stage.
- This package does not directly edit SBSX connectors because the matching SBSX has not yet been supplied.
