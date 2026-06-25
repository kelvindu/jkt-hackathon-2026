"""
Configuration management module for alert scenarios.

This module handles loading and validating alert configurations from JSON or YAML files.
Supports multiple alert scenarios within a single configuration file.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
"""

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)


@dataclass
class AlertScenario:
    """
    Represents an alert scenario for investigation.
    
    Attributes:
        name: Human-readable name of the alert scenario
        description: Brief description of the alert
        initial_context: Context information about the alert (dict or string)
        metadata: Additional metadata (severity, team, runbook, etc.)
    """
    name: str
    description: str
    initial_context: Any
    metadata: dict[str, Any]
    
    def __post_init__(self):
        """Validate that metadata is a dictionary."""
        if not isinstance(self.metadata, dict):
            raise ValueError(f"metadata must be a dictionary, got {type(self.metadata)}")


class ConfigLoader:
    """
    Loads and validates alert scenario configurations from JSON or YAML files.
    
    Supports:
    - JSON format (.json)
    - YAML format (.yaml, .yml)
    - Multiple scenarios per file
    - Schema validation for required fields
    """
    
    REQUIRED_FIELDS = {"name", "description", "initial_context", "metadata"}
    
    @classmethod
    def load_scenarios(cls, file_path: str) -> list[AlertScenario]:
        """
        Load alert scenarios from a configuration file.
        
        Args:
            file_path: Path to JSON or YAML configuration file
            
        Returns:
            List of AlertScenario objects loaded from the file
            
        Raises:
            SystemExit: If file is missing, invalid format, or schema validation fails
        """
        path = Path(file_path)
        
        # Check if file exists (Requirement 4.4)
        if not path.exists():
            logger.error(f"Configuration file not found: {file_path}")
            sys.exit(1)
        
        # Load file based on extension
        try:
            with open(path, 'r', encoding='utf-8') as f:
                if path.suffix.lower() == '.json':
                    config_data = json.load(f)
                elif path.suffix.lower() in {'.yaml', '.yml'}:
                    config_data = yaml.safe_load(f)
                else:
                    logger.error(f"Unsupported file format: {path.suffix}. Use .json, .yaml, or .yml")
                    sys.exit(1)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in configuration file: {e}")
            sys.exit(1)
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Error reading configuration file: {e}")
            sys.exit(1)
        
        # Validate and parse scenarios (Requirements 4.1, 4.5)
        if not isinstance(config_data, dict):
            logger.error("Configuration file must contain a JSON/YAML object")
            sys.exit(1)
        
        scenarios_data = config_data.get("scenarios", [])
        if not isinstance(scenarios_data, list):
            logger.error("Configuration 'scenarios' field must be a list")
            sys.exit(1)
        
        if not scenarios_data:
            logger.error("Configuration file contains no scenarios")
            sys.exit(1)
        
        scenarios = []
        for idx, scenario_data in enumerate(scenarios_data):
            try:
                cls.validate_schema(scenario_data)
                scenario = AlertScenario(
                    name=scenario_data["name"],
                    description=scenario_data["description"],
                    initial_context=scenario_data["initial_context"],
                    metadata=scenario_data.get("metadata", {})
                )
                scenarios.append(scenario)
            except (ValueError, KeyError) as e:
                logger.error(f"Invalid scenario at index {idx}: {e}")
                sys.exit(1)
        
        logger.info(f"Loaded {len(scenarios)} scenario(s) from {file_path}")
        return scenarios
    
    @classmethod
    def validate_schema(cls, config_data: dict) -> bool:
        """
        Validate that a scenario configuration has all required fields.
        
        Args:
            config_data: Dictionary containing scenario data
            
        Returns:
            True if validation passes
            
        Raises:
            ValueError: If required fields are missing
        """
        if not isinstance(config_data, dict):
            raise ValueError(f"Scenario data must be a dictionary, got {type(config_data)}")
        
        # Check for required fields (Requirement 4.4)
        missing_fields = cls.REQUIRED_FIELDS - set(config_data.keys())
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(sorted(missing_fields))}")
        
        # Validate field types
        if not isinstance(config_data["name"], str) or not config_data["name"].strip():
            raise ValueError("Field 'name' must be a non-empty string")
        
        if not isinstance(config_data["description"], str) or not config_data["description"].strip():
            raise ValueError("Field 'description' must be a non-empty string")
        
        if not isinstance(config_data["metadata"], dict):
            raise ValueError("Field 'metadata' must be a dictionary")
        
        # initial_context can be string or dict, just check it exists
        if config_data["initial_context"] is None:
            raise ValueError("Field 'initial_context' cannot be None")
        
        return True
