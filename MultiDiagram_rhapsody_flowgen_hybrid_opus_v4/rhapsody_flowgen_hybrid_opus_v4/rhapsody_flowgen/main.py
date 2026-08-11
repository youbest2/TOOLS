# rhapsody_flowgen/main.py
# Final Version - Corrected the function call to get_or_create_operation.

import logging
import sys
from pathlib import Path
import argparse
import hashlib

try:
    project_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(project_root.parent)) 
except NameError:
    project_root = Path.cwd()

from rhapsody_flowgen.config_loader import load_config, ConfigError
from rhapsody_flowgen.mermaid_parser import parse_mermaid_file, MermaidParseError, check_rhapsody_condition_compatibility
from rhapsody_flowgen.rhapsody_interface import RhapsodyInterface

def configure_logging():
    log_file = project_root / "rhapsody_flowgen.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - [%(levelname)s] - %(message)s',
        handlers=[logging.FileHandler(log_file, mode='w', encoding='utf-8'), logging.StreamHandler(sys.stdout)],
        force=True
    )
    logging.info("Logging configured. Log file at: %s", log_file)

def main():
    configure_logging()
    parser = argparse.ArgumentParser(description="Generate Rhapsody Activity Diagrams from Mermaid files.")
    parser.add_argument('--config', type=str, default=str(project_root / 'config.yaml'), help='Path to the configuration YAML file.')
    args = parser.parse_args()

    rhapsody_instance = None
    try:
        logging.info(f"Loading configuration from: {args.config}")
        config = load_config(args.config)
        
        configured_mermaid = Path(config.get('mermaid_file', 'flowinitializesensor.mmd'))
        if configured_mermaid.is_absolute():
            mermaid_path = configured_mermaid.resolve()
            if mermaid_path.parent != project_root:
                local_candidate = (project_root / configured_mermaid.name).resolve()
                if local_candidate.is_file():
                    logging.warning("Configured Mermaid is outside the running project; using local project copy: %s", local_candidate)
                    mermaid_path = local_candidate
        else:
            mermaid_path = (project_root / configured_mermaid).resolve()
        if not mermaid_path.is_file():
            raise FileNotFoundError(f"Mermaid input not found: {mermaid_path}")
        mermaid_bytes = mermaid_path.read_bytes()
        logging.info("Mermaid input resolved path: %s", mermaid_path)
        logging.info("Mermaid input size: %d bytes", len(mermaid_bytes))
        logging.info("Mermaid input SHA-256: %s", hashlib.sha256(mermaid_bytes).hexdigest())
        logging.info("Mermaid input modified timestamp: %s", mermaid_path.stat().st_mtime)
        nodes, edges = parse_mermaid_file(str(mermaid_path))
        check_rhapsody_condition_compatibility(nodes, edges)
        
        logging.info("Initializing Rhapsody connection...")
        rhapsody_instance = RhapsodyInterface(config)
        rhapsody_instance.open_project()

        package = rhapsody_instance.find_package_by_path()
        clazz = rhapsody_instance.find_class(package, config["class"])
        
        # --- CORRECTED FUNCTION CALL ---
        # Changed from find_operation to the correct get_or_create_operation
        operation = rhapsody_instance.get_or_create_operation(clazz, config["operation"])
        
        diagram = rhapsody_instance.recreate_activity_diagram(operation)

        logging.info("Starting diagram construction in Rhapsody...")
        rhapsody_instance.build_diagram_from_parsed_data(diagram, nodes, edges)

        logging.info("✔ Diagram generation process completed successfully!")

    except (FileNotFoundError, ConfigError, MermaidParseError) as e:
        logging.error(f"❌ SETUP_ERROR: {e}")
    except ConnectionError as e:
        logging.error(f"❌ RHAPSODY_CONNECTION_ERROR: {e}")
    except RuntimeError as e:
        logging.error(f"❌ MODEL_ERROR: {e}")
    except Exception as e:
        logging.error(f"❌ UNEXPECTED_ERROR: {e}", exc_info=True)
    finally:
        if rhapsody_instance and rhapsody_instance.project:
            try:
                rhapsody_instance.save_and_close_project()
            except Exception as e:
                logging.error(f"❌ Failed to save or close Rhapsody project: {e}")

if __name__ == "__main__":
    main()
