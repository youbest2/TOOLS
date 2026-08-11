# rhapsody_flowgen/config_loader.py
# Final Version - Validates all required keys.

import yaml
import logging
import os
from typing import Dict, Any

class ConfigError(Exception):
    """Custom exception for configuration-related errors."""
    pass

def load_config(path: str) -> Dict[str, Any]:
    """Loads and validates a YAML configuration file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Configuration file not found at path: {path}")
    try:
        with open(path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
            if not config_data:
                raise ConfigError("Configuration file is empty or invalid.")
            
            required_keys = ['project_path', 'class', 'operation', 'mermaid_file']
            if 'package_path' not in config_data:
                 raise ConfigError("Config must contain the 'package_path' key.")
            missing_keys = [key for key in required_keys if key not in config_data]
            if missing_keys:
                raise ConfigError(f"Missing required keys: {', '.join(missing_keys)}")

            logging.info(f"✔ Configuration loaded and validated.")
            return config_data
    except yaml.YAMLError as e:
        raise ConfigError(f"Error parsing YAML file '{path}': {e}")
