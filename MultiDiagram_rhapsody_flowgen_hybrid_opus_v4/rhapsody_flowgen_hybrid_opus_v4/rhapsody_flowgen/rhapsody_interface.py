# rhapsody_flowgen/rhapsody_interface.py
# hybrid_v3.1 - drop-in replacement.
#
# Builds on v3 (topology start, merge insertion, verified geometry, safe BMP)
# and adds the fix for the empty ACTION boxes seen in the 17:19 run:
#
#   [FIX-G] Visible node text:
#     * Each visible-text field is set in ITS OWN try/except, so one failure no
#       longer aborts the rest (v3 put description/displayName/name in a single
#       try; the invalid `.name` assignment threw and blocked everything).
#     * `.name` is sanitized to a valid identifier (spaces / '=' / ',' / '?' are
#       not allowed in Rhapsody names) so it never throws.
#     * The ACTION *body* is set via a cascade of known Rhapsody setters
#       (setBody/body/setActionCode/...). In a flowchart a Condition displays its
#       name/displayName (that already worked), but an Action displays its BODY,
#       which v3 never set -> rectangles rendered empty.
#     * Every attempt is logged with the winning setter for easy field tuning.
#
# Method names / signatures unchanged from v2/v3.

import re
import win32com.client
import logging
import os
import pywintypes
import time
from typing import Dict, Any, List, Optional

from rhapsody_flowgen.mermaid_parser import Node, Edge
from rhapsody_flowgen.layout import compute_activity_layout
from rhapsody_flowgen.layout_plan import build_plan, write_plan
from rhapsody_flowgen.flow_utils import insert_merge_nodes
from rhapsody_flowgen.sbsx_tools import emit_sbsx_plan  # [FIX-hybrid] SBSX plan


def retry_operation(operation, retries=3, delay=2):
    """Retries a COM operation if the Rhapsody RPC server is busy."""
    for attempt in range(retries):
        try:
            return operation()
        except pywintypes.com_error as e:
            if e.hresult == -2147418111:
                logging.warning(f"Rhapsody RPC server busy. Retrying... (Attempt {attempt + 1}/{retries})")
                time.sleep(delay)
            else:
                raise
    raise RuntimeError("Operation failed after multiple retries.")


def _prop_value(prop):
    """Normalize an IRPGraphicalProperty (or plain value) into a string/None."""
    if prop is None:
        return None
    for attr in ("value", "Value"):
        if hasattr(prop, attr):
            return getattr(prop, attr)
    return prop


class RhapsodyInterface:
    """Manages all interactions with the IBM Rhapsody COM API."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.project = None
        self.app = None
        rhapsody_path = self.config.get("rhapsody_path")
        if rhapsody_path and os.path.isdir(rhapsody_path):
            os.environ['PATH'] = rhapsody_path + os.pathsep + os.environ['PATH']
        logging.info("Attempting to connect to Rhapsody COM server...")
        try:
            self.app = win32com.client.Dispatch("Rhapsody2.Application")
            logging.info("✔ Successfully connected to Rhapsody2.Application.")
        except pywintypes.com_error as e:
            raise ConnectionError("Could not connect to Rhapsody. Is it running?") from e

    def open_project(self):
        project_path = self.config["project_path"]
        if not os.path.exists(project_path):
            raise FileNotFoundError(f"Rhapsody project file not found: {project_path}")
        logging.info(f"Opening Rhapsody project: {project_path}")
        self.project = retry_operation(lambda: self.app.openProject(project_path))
        logging.info("✔ Project opened successfully.")

    def find_package_by_path(self):
        """Finds a package by navigating a path using recursive search."""
        path_parts = self.config.get("package_path", [])
        current_element = self.project
        for pkg_name in path_parts:
            next_package = current_element.findNestedElementRecursive(pkg_name, "Package")
            if not next_package:
                raise RuntimeError(f"Package '{pkg_name}' not found within '{current_element.name}'.")
            current_element = next_package
            logging.info(f"✔ Located package: '{current_element.name}'")
        return current_element

    def find_class(self, package, class_name):
        """Finds a class within a given package."""
        logging.info(f"Locating class: '{class_name}'")
        clazz = package.findNestedElementRecursive(class_name, "Class")
        if not clazz:
            raise RuntimeError(f"Class '{class_name}' not found in package '{package.name}'.")
        logging.info(f"✔ Located class: '{class_name}'")
        return clazz

    def get_or_create_operation(self, class_element, op_name):
        """Finds an existing operation or creates it if not found."""
        logging.info(f"Checking for operation: '{op_name}'")
        for op in class_element.getNestedElementsByMetaClass("Operation", 0):
            if op.name == op_name:
                logging.info(f"✔ Found operation: '{op_name}'")
                return op
        logging.warning(f"Operation '{op_name}' not found. Creating it...")
        operation_element = retry_operation(lambda: class_element.addNewAggr("Operation", op_name))
        if not operation_element:
            raise RuntimeError(f"Failed to create operation '{op_name}'.")
        logging.info(f"✔ Created new operation: {operation_element.name}")
        return operation_element

    def recreate_activity_diagram(self, operation):
        """Delete any existing same-named diagram, then create a fresh one."""
        op_as_classifier = win32com.client.CastTo(operation, "IRPClassifier")
        diagram_name = f"AD_{operation.name}"

        for ad in op_as_classifier.getNestedElementsByMetaClass("ActivityDiagram", 0):
            if ad.name == diagram_name:
                logging.warning(f"Found and deleting existing diagram '{diagram_name}' to ensure a clean state.")
                retry_operation(lambda: ad.deleteFromProject())
                retry_operation(lambda: self.project.save())
                break

        logging.info(f"Creating new, clean activity diagram: '{diagram_name}'")
        diagram = retry_operation(lambda: op_as_classifier.addActivityDiagram())
        diagram.name = diagram_name
        return diagram

    # ------------------------------------------------------------------ #
    # [FIX-G] Visible text helpers                                       #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _sanitize_identifier(text: str, fallback: str) -> str:
        """Rhapsody element names must be valid identifiers (no spaces/=,?).
        Collapse everything else to '_'."""
        ident = re.sub(r"\W+", "_", text or "").strip("_")
        if not ident:
            ident = fallback
        if ident[0].isdigit():
            ident = f"n_{ident}"
        return ident[:120]

    def _set_node_visible_text(self, model_elem, node, safe_name: str) -> dict:
        """
        Make the on-canvas text appear for BOTH shapes.

        Conditions display name/displayName (worked in v3). Actions display their
        BODY, so we set that too. Each field is attempted independently; the
        winning setters are logged so the correct one can be pinned per build.
        """
        label = node.label
        results = {}

        # 1) description - traceability only (never rendered, always safe first).
        try:
            model_elem.description = f"Mermaid id={node.id}; generated_name={safe_name}; label={label}"
            results["description"] = "ok"
        except Exception as e:
            results["description"] = f"ERR {e}"

        # 2) name - MUST be a valid identifier or Rhapsody throws (v3 root cause).
        try:
            model_elem.name = self._sanitize_identifier(label, safe_name)
            results["name"] = "ok"
        except Exception as e:
            results["name"] = f"ERR {e}"

        # 3) displayName - what a CONDITION diamond shows (keep verbatim label).
        try:
            model_elem.displayName = label
            results["displayName"] = "ok"
        except Exception as e:
            results["displayName"] = f"ERR {e}"

        # 4) ACTION BODY - what an ACTION rectangle shows. Try method setters
        #    first, then attribute assignment. Stop at the first that works.
        body_set = False
        for setter in ("setBody", "setActionCode", "setAction", "setActionText"):
            fn = getattr(model_elem, setter, None)
            if callable(fn):
                try:
                    fn(label)
                    results[setter + "()"] = "ok"
                    body_set = True
                    break
                except Exception as e:
                    results[setter + "()"] = f"ERR {e}"
        if not body_set:
            for attr in ("body", "actionCode", "action", "text"):
                try:
                    setattr(model_elem, attr, label)
                    results[attr] = "ok"
                    body_set = True
                    break
                except Exception as e:
                    results[attr] = f"ERR {e}"

        if body_set:
            logging.info("Visible text set for node.id=%s (%s): %s", node.id, safe_name, results)
        else:
            logging.warning(
                "Node.id=%s: could not set an ACTION body via any known setter %s. "
                "The rectangle may render empty on this build; please report which "
                "of these setters exists so it can be pinned (see ANALYSIS_REPORT.md, FIX-G).",
                node.id, list(results.keys()),
            )
        return results

    # ------------------------------------------------------------------ #
    # [FIX-2] Robust geometry helper (unchanged from v3)                 #
    # ------------------------------------------------------------------ #
    def _apply_and_verify_geometry(self, graph_node, node_id, x, y, w, h):
        for prop, val in (("X", x), ("Y", y), ("Width", w), ("Height", h)):
            for name in (prop, prop.lower(), f"m_{prop.lower()}"):
                try:
                    graph_node.setGraphicalProperty(name, str(val))
                    break
                except Exception:
                    continue
        try:
            self.project.save()
        except Exception as e:
            logging.warning("project.save() during geometry set failed for %s: %s", node_id, e)
        time.sleep(0.05)

        read = {}
        for prop in ("X", "Y", "Width", "Height"):
            try:
                read[prop] = _prop_value(graph_node.getGraphicalProperty(prop))
            except Exception:
                read[prop] = None
        logging.info("Geometry read-back for %s: %s", node_id, read)

        if read.get("X") in (None, "", "0") and read.get("Y") in (None, "", "0"):
            logging.error(
                "Node %s reported no X/Y via graphical properties. "
                "Position is governed by AddNewNodeForElement(x=%s, y=%s). "
                "If the on-canvas position is wrong, the Rhapsody build needs "
                "IRPGraphElement.setPosition/graphical-connector post-processing "
                "on a saved SBSX (see ANALYSIS_REPORT.md, FIX-2).",
                node_id, x, y,
            )
        return read

    # ------------------------------------------------------------------ #
    # [FIX-H] Edge port selection (distinct decision exits)              #
    # ------------------------------------------------------------------ #
    # Node graphical box is created as (x, y, W, H) = (left, top, 250, 75).
    NODE_W = 250
    NODE_H = 75
    # If |target_center_x - source_center_x| is below this, the branch is
    # treated as "straight down" and uses the BOTTOM vertex.
    _ALIGN_TOL = 60

    def _source_port(self, src_node, s_left, s_top, t_left, t_top, sibling_count):
        """
        Choose the exit point on the SOURCE node.

          * Action, or a decision with a single out-edge  -> bottom center.
          * Decision with >1 out-edge:
              - branch aligned below            -> bottom vertex
              - branch to the right             -> right vertex
              - branch to the left              -> left vertex
        This spreads Yes/No so they no longer overlap at the start.
        """
        W, H = self.NODE_W, self.NODE_H
        s_cx = s_left + W / 2
        t_cx = t_left + W / 2
        dx = t_cx - s_cx

        is_condition = getattr(src_node, "node_type", "action") == "condition"
        if (not is_condition) or sibling_count <= 1 or abs(dx) <= self._ALIGN_TOL:
            return int(s_cx), int(s_top + H)          # bottom-center
        if dx > 0:
            return int(s_left + W), int(s_top + H / 2)  # right vertex
        return int(s_left), int(s_top + H / 2)          # left vertex

    def _target_port(self, s_left, s_top, t_left, t_top):
        """
        Choose the entry point on the TARGET node so the arrowhead lands
        cleanly opposite the source direction:
          * target below/aligned -> enter TOP center
          * target to the right  -> enter LEFT middle
          * target to the left   -> enter RIGHT middle
          * target above (loop)  -> enter BOTTOM center
        """
        W, H = self.NODE_W, self.NODE_H
        s_cx, s_cy = s_left + W / 2, s_top + H / 2
        t_cx, t_cy = t_left + W / 2, t_top + H / 2
        dx, dy = t_cx - s_cx, t_cy - s_cy

        # Mostly vertical relationship.
        if abs(dx) <= self._ALIGN_TOL:
            if dy >= 0:
                return int(t_cx), int(t_top)           # enter top
            return int(t_cx), int(t_top + H)           # enter bottom (loop-back)

        # Horizontal-ish relationship (side branch).
        if dx > 0:
            return int(t_left), int(t_cy)              # enter left side
        return int(t_left + W), int(t_cy)              # enter right side

    def build_diagram_from_parsed_data(self, diagram, nodes, edges):
        """Populate the activity diagram (model elements added to the diagram)."""
        # [FIX-1] Insert explicit merge nodes before multi-incoming decisions.
        nodes, edges = insert_merge_nodes(nodes, edges)

        model_elements = {}
        graphical_nodes = {}
        diagram_as_flowchart = win32com.client.CastTo(diagram, "IRPFlowchart")

        node_coords = compute_activity_layout(nodes, edges)
        layout_plan = build_plan(nodes, edges, node_coords)
        layout_plan_path = os.path.join(os.path.dirname(__file__), "layout_plan.json")
        write_plan(layout_plan, layout_plan_path)
        logging.info("Wrote node and orthogonal edge plan: %s", layout_plan_path)

        # [FIX-hybrid] Emit the SBSX post-processing plan (node text/geometry +
        # distinct decision ports). After COM saves & closes the project, run:
        #   python -m rhapsody_flowgen.sbsx_patch_v109 patch --sbsx <unit> \
        #          --diagram AD_<op> --plan sbsx_plan.json --write
        try:
            sbsx_plan_path = os.path.join(os.path.dirname(__file__), "sbsx_plan.json")
            emit_sbsx_plan(nodes, edges, node_coords, sbsx_plan_path)
            logging.info("Wrote SBSX post-process plan: %s", sbsx_plan_path)
        except Exception as e:
            logging.warning("Could not emit sbsx_plan.json: %s", e)

        for idx, node in enumerate(nodes):
            meta_type = "Condition" if node.node_type == "condition" else "Action"
            safe_name = f"{meta_type.lower()}_{idx + 1}"
            existing = None
            for elem in diagram.getNestedElementsByMetaClass(meta_type, 0):
                if elem.name == safe_name:
                    existing = elem
                    break
            if existing:
                model_elem = existing
                logging.info(f"Element '{safe_name}' ({meta_type}) exists; reusing. Label: {node.label}")
            else:
                try:
                    model_elem = diagram.addNewAggr(meta_type, safe_name)
                    logging.info(f"Created element '{safe_name}' of type '{meta_type}'. Label: {node.label}")
                except Exception as e:
                    logging.error(f"❌ Failed to add element '{safe_name}' ({meta_type}): {e}")
                    raise

            # [FIX-G] robust, independent visible-text setting (incl. action body)
            self._set_node_visible_text(model_elem, node, safe_name)

            model_elements[node.id] = win32com.client.CastTo(model_elem, "IRPStateVertex")
            logging.info(f"Model element for node.id={node.id}, label='{node.label}', "
                         f"meta_type={meta_type}, safe_name={safe_name}")

        # Place graphical nodes using computed layout
        for node in nodes:
            model_elem = model_elements.get(node.id)
            if model_elem:
                x, y = node_coords[node.id]
                graph_node = diagram_as_flowchart.AddNewNodeForElement(model_elem, x, y, 250, 75)
                logging.info(f"Graphical node created for node.id={node.id}, "
                             f"label='{node.label}', at ({x},{y})")
                self._apply_and_verify_geometry(graph_node, node.id, x, y, 250, 75)
                graphical_nodes[node.id] = graph_node

        node_ids_with_outgoing = set(edge.source_id for edge in edges)
        nodes_with_no_outgoing = [n for n in nodes if n.id not in node_ids_with_outgoing]
        logging.info("Nodes with no outgoing control flow (possible ends):")
        for n in nodes_with_no_outgoing:
            logging.info(f"  Node id={n.id}, label='{n.label}', type={n.node_type}")

        # [FIX-H] Distinct decision exit ports.
        # A decision (Condition) with >1 outgoing edge must not have all edges
        # leave from the same bottom-center point (they overlap and look messy).
        # We give the vertically-aligned branch the BOTTOM vertex and route side
        # branches out of the RIGHT / LEFT vertex of the diamond, based on where
        # the target sits. Actions (single out-edge) keep the bottom port.
        out_by_src = {}
        for e in edges:
            out_by_src.setdefault(e.source_id, []).append(e)
        node_by_id = {n.id: n for n in nodes}

        logging.info("Control flow edges to be created:")
        for edge in edges:
            logging.info(f"  Edge: {edge.source_id} -> {edge.target_id}")
            src = model_elements.get(edge.source_id)
            tgt = model_elements.get(edge.target_id)
            src_graph = graphical_nodes.get(edge.source_id)
            tgt_graph = graphical_nodes.get(edge.target_id)
            if not all([src, tgt, src_graph, tgt_graph]):
                logging.warning(
                    f"Skipping edge {edge.source_id} -> {edge.target_id} due to missing elements: "
                    f"src={src}, tgt={tgt}, src_graph={src_graph}, tgt_graph={tgt_graph}")
                continue

            s_left, s_top = node_coords[edge.source_id]
            t_left, t_top = node_coords[edge.target_id]
            src_node = node_by_id.get(edge.source_id)
            sibling_count = len(out_by_src.get(edge.source_id, []))

            src_x, src_y = self._source_port(src_node, s_left, s_top, t_left, t_top, sibling_count)
            tgt_x, tgt_y = self._target_port(s_left, s_top, t_left, t_top)
            logging.info(f"    ports: exit=({src_x},{src_y}) enter=({tgt_x},{tgt_y}) "
                         f"[siblings={sibling_count}, type={getattr(src_node,'node_type','action')}]")

            try:
                flow = src.addFlow("ControlFlow", tgt)
                if not all([flow, src_graph, tgt_graph]):
                    logging.error(f"Invalid args for AddNewEdgeForElement: "
                                  f"flow={flow}, src_graph={src_graph}, tgt_graph={tgt_graph}")
                    continue
                diagram_as_flowchart.AddNewEdgeForElement(
                    flow, src_graph, src_x, src_y, tgt_graph, tgt_x, tgt_y)
                label = getattr(edge, "label", None)
                if label:
                    for attr in ("name", "displayName", "description"):
                        try:
                            setattr(flow, attr, label)
                        except Exception:
                            pass
            except pywintypes.com_error as e:
                logging.error(f"COM error in AddNewEdgeForElement for "
                              f"{edge.source_id}->{edge.target_id}: {e}", exc_info=True)
                continue
            except Exception as e:
                logging.error(f"Unexpected error in AddNewEdgeForElement for "
                              f"{edge.source_id}->{edge.target_id}: {e}", exc_info=True)
                continue

        self.project.save()
        logging.info("✔ Diagram build complete and project saved.")
        self._export_bmp(diagram)

    # ------------------------------------------------------------------ #
    # [FIX-3] BMP export (no tuple.count() crash)                        #
    # ------------------------------------------------------------------ #
    def _export_bmp(self, diagram):
        try:
            diagram_file = os.path.join(os.path.dirname(__file__), f"{diagram.name}.bmp")
            logging.info(f"Exporting diagram to BMP: {diagram_file}")
            if hasattr(self.app, 'createNewCollection') and callable(self.app.createNewCollection):
                diagrammap = self.app.createNewCollection()
            elif hasattr(diagram, 'createNewCollection') and callable(diagram.createNewCollection):
                diagrammap = diagram.createNewCollection()
            else:
                raise AttributeError("createNewCollection method not found on app or diagram.")

            files = diagram.getPictureAs(diagram_file, "BMP", 0, diagrammap)

            try:
                if files is None:
                    logging.info(f"✔ Diagram exported as BMP: {diagram_file}")
                elif isinstance(files, (list, tuple)):
                    for f in files:
                        logging.info(f"✔ Diagram exported as BMP: {f}")
                elif hasattr(files, "getCount") and hasattr(files, "getItem"):
                    n = files.getCount()
                    for i in range(1, int(n) + 1):
                        logging.info(f"✔ Diagram exported as BMP: {files.getItem(i)}")
                elif hasattr(files, "Count"):
                    n = files.Count() if callable(files.Count) else files.Count
                    for i in range(1, int(n) + 1):
                        logging.info(f"✔ Diagram exported as BMP: {files.getItem(i)}")
                else:
                    logging.info(f"✔ Diagram exported as BMP: {diagram_file}")
            except Exception as log_error:
                logging.warning(f"⚠️ Exported, but could not enumerate BMP file list: {log_error}")
        except AttributeError as e:
            logging.error(f"❌ Failed to invoke createNewCollection: {e}")
        except Exception as e:
            logging.error(f"❌ Failed to export diagram as BMP: {e}")
            try:
                emf_file = os.path.join(os.path.dirname(__file__), f"{diagram.name}.emf")
                logging.info(f"Attempting to export diagram as EMF: {emf_file}")
                diagram.getPicture(emf_file)
                logging.info(f"✔ Diagram exported as EMF: {emf_file}")
            except Exception as emf_error:
                logging.error(f"❌ Failed to export diagram as EMF: {emf_error}")

    def save_and_close_project(self):
        if self.project:
            logging.info("Closing Rhapsody project...")
            retry_operation(lambda: self.project.close())
            self.project = None
