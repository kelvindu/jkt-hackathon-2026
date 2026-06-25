"""
Unit tests for configuration loading module.

Tests configuration loading with valid/invalid files, JSON/YAML formats,
schema validation, and error handling.
"""

import json
import pytest
import tempfile
from pathlib import Path

from src.config import AlertScenario, ConfigLoader


class TestAlertScenario:
    """Tests for AlertScenario dataclass."""
    
    def test_alert_scenario_creation(self):
        """Test creating a valid AlertScenario."""
        scenario = AlertScenario(
            name="Test Alert",
            description="Test description",
            initial_context={"key": "value"},
            metadata={"severity": "high"}
        )
        
        assert scenario.name == "Test Alert"
        assert scenario.description == "Test description"
        assert scenario.initial_context == {"key": "value"}
        assert scenario.metadata == {"severity": "high"}
    
    def test_alert_scenario_with_string_context(self):
        """Test AlertScenario with string initial_context."""
        scenario = AlertScenario(
            name="Test Alert",
            description="Test description",
            initial_context="Error rate increased",
            metadata={}
        )
        
        assert scenario.initial_context == "Error rate increased"
    
    def test_alert_scenario_invalid_metadata(self):
        """Test AlertScenario rejects non-dict metadata."""
        with pytest.raises(ValueError, match="metadata must be a dictionary"):
            AlertScenario(
                name="Test",
                description="Test",
                initial_context={},
                metadata="not a dict"
            )


class TestConfigLoaderValidation:
    """Tests for ConfigLoader schema validation."""
    
    def test_validate_schema_valid(self):
        """Test validation passes for valid scenario data."""
        valid_data = {
            "name": "Test Alert",
            "description": "Test description",
            "initial_context": {"alert": "data"},
            "metadata": {"team": "ops"}
        }
        
        assert ConfigLoader.validate_schema(valid_data) is True
    
    def test_validate_schema_missing_fields(self):
        """Test validation fails when required fields are missing."""
        incomplete_data = {
            "name": "Test Alert",
            "description": "Test description"
            # Missing initial_context and metadata
        }
        
        with pytest.raises(ValueError, match="Missing required fields"):
            ConfigLoader.validate_schema(incomplete_data)
    
    def test_validate_schema_empty_name(self):
        """Test validation fails for empty name."""
        invalid_data = {
            "name": "",
            "description": "Test description",
            "initial_context": {},
            "metadata": {}
        }
        
        with pytest.raises(ValueError, match="name.*non-empty string"):
            ConfigLoader.validate_schema(invalid_data)
    
    def test_validate_schema_empty_description(self):
        """Test validation fails for empty description."""
        invalid_data = {
            "name": "Test",
            "description": "   ",
            "initial_context": {},
            "metadata": {}
        }
        
        with pytest.raises(ValueError, match="description.*non-empty string"):
            ConfigLoader.validate_schema(invalid_data)
    
    def test_validate_schema_invalid_metadata_type(self):
        """Test validation fails when metadata is not a dict."""
        invalid_data = {
            "name": "Test",
            "description": "Test",
            "initial_context": {},
            "metadata": ["not", "a", "dict"]
        }
        
        with pytest.raises(ValueError, match="metadata.*dictionary"):
            ConfigLoader.validate_schema(invalid_data)
    
    def test_validate_schema_none_initial_context(self):
        """Test validation fails when initial_context is None."""
        invalid_data = {
            "name": "Test",
            "description": "Test",
            "initial_context": None,
            "metadata": {}
        }
        
        with pytest.raises(ValueError, match="initial_context.*cannot be None"):
            ConfigLoader.validate_schema(invalid_data)
    
    def test_validate_schema_not_dict(self):
        """Test validation fails when input is not a dictionary."""
        with pytest.raises(ValueError, match="must be a dictionary"):
            ConfigLoader.validate_schema("not a dict")


class TestConfigLoaderJSON:
    """Tests for loading JSON configuration files."""
    
    def test_load_valid_json_single_scenario(self):
        """Test loading a valid JSON file with single scenario."""
        config = {
            "version": "1.0",
            "scenarios": [
                {
                    "name": "High Error Rate",
                    "description": "Error spike detected",
                    "initial_context": {"error_rate": "15%"},
                    "metadata": {"severity": "high"}
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config, f)
            temp_path = f.name
        
        try:
            scenarios = ConfigLoader.load_scenarios(temp_path)
            
            assert len(scenarios) == 1
            assert scenarios[0].name == "High Error Rate"
            assert scenarios[0].description == "Error spike detected"
            assert scenarios[0].initial_context == {"error_rate": "15%"}
            assert scenarios[0].metadata == {"severity": "high"}
        finally:
            Path(temp_path).unlink()
    
    def test_load_valid_json_multiple_scenarios(self):
        """Test loading a JSON file with multiple scenarios."""
        config = {
            "scenarios": [
                {
                    "name": "Alert 1",
                    "description": "Description 1",
                    "initial_context": "Context 1",
                    "metadata": {}
                },
                {
                    "name": "Alert 2",
                    "description": "Description 2",
                    "initial_context": "Context 2",
                    "metadata": {"team": "backend"}
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config, f)
            temp_path = f.name
        
        try:
            scenarios = ConfigLoader.load_scenarios(temp_path)
            assert len(scenarios) == 2
            assert scenarios[0].name == "Alert 1"
            assert scenarios[1].name == "Alert 2"
        finally:
            Path(temp_path).unlink()
    
    def test_load_invalid_json(self):
        """Test loading a file with invalid JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{invalid json content")
            temp_path = f.name
        
        try:
            with pytest.raises(SystemExit) as exc_info:
                ConfigLoader.load_scenarios(temp_path)
            assert exc_info.value.code == 1
        finally:
            Path(temp_path).unlink()


class TestConfigLoaderYAML:
    """Tests for loading YAML configuration files."""
    
    def test_load_valid_yaml_single_scenario(self):
        """Test loading a valid YAML file with single scenario."""
        yaml_content = """
version: "1.0"
scenarios:
  - name: "Database Slowdown"
    description: "Query latency increased"
    initial_context:
      alert_time: "2024-01-15T16:45:00Z"
      database: "orders-db"
    metadata:
      severity: "critical"
      team: "database"
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            scenarios = ConfigLoader.load_scenarios(temp_path)
            
            assert len(scenarios) == 1
            assert scenarios[0].name == "Database Slowdown"
            assert scenarios[0].description == "Query latency increased"
            assert "alert_time" in scenarios[0].initial_context
            assert scenarios[0].metadata["severity"] == "critical"
        finally:
            Path(temp_path).unlink()
    
    def test_load_valid_yml_extension(self):
        """Test loading a YAML file with .yml extension."""
        yaml_content = """
scenarios:
  - name: "Test"
    description: "Test"
    initial_context: "test"
    metadata: {}
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            scenarios = ConfigLoader.load_scenarios(temp_path)
            assert len(scenarios) == 1
            assert scenarios[0].name == "Test"
        finally:
            Path(temp_path).unlink()
    
    def test_load_invalid_yaml(self):
        """Test loading a file with invalid YAML."""
        yaml_content = """
scenarios:
  - name: "Test"
    description: invalid yaml structure
      bad_indent: value
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            with pytest.raises(SystemExit) as exc_info:
                ConfigLoader.load_scenarios(temp_path)
            assert exc_info.value.code == 1
        finally:
            Path(temp_path).unlink()


class TestConfigLoaderErrorHandling:
    """Tests for error handling and edge cases."""
    
    def test_load_missing_file(self):
        """Test loading a non-existent file exits with error."""
        with pytest.raises(SystemExit) as exc_info:
            ConfigLoader.load_scenarios("/nonexistent/path/config.json")
        
        assert exc_info.value.code == 1
    
    def test_load_unsupported_format(self):
        """Test loading a file with unsupported extension."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("some content")
            temp_path = f.name
        
        try:
            with pytest.raises(SystemExit) as exc_info:
                ConfigLoader.load_scenarios(temp_path)
            assert exc_info.value.code == 1
        finally:
            Path(temp_path).unlink()
    
    def test_load_empty_scenarios_list(self):
        """Test loading a file with empty scenarios list."""
        config = {"scenarios": []}
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config, f)
            temp_path = f.name
        
        try:
            with pytest.raises(SystemExit) as exc_info:
                ConfigLoader.load_scenarios(temp_path)
            assert exc_info.value.code == 1
        finally:
            Path(temp_path).unlink()
    
    def test_load_scenarios_not_list(self):
        """Test loading a file where scenarios is not a list."""
        config = {"scenarios": "not a list"}
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config, f)
            temp_path = f.name
        
        try:
            with pytest.raises(SystemExit) as exc_info:
                ConfigLoader.load_scenarios(temp_path)
            assert exc_info.value.code == 1
        finally:
            Path(temp_path).unlink()
    
    def test_load_invalid_scenario_in_list(self):
        """Test loading a file with an invalid scenario (missing fields)."""
        config = {
            "scenarios": [
                {
                    "name": "Valid Scenario",
                    "description": "This is valid",
                    "initial_context": {},
                    "metadata": {}
                },
                {
                    "name": "Invalid Scenario",
                    "description": "Missing initial_context and metadata"
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config, f)
            temp_path = f.name
        
        try:
            with pytest.raises(SystemExit) as exc_info:
                ConfigLoader.load_scenarios(temp_path)
            assert exc_info.value.code == 1
        finally:
            Path(temp_path).unlink()
    
    def test_load_not_dict_root(self):
        """Test loading a file where root is not a dictionary."""
        config = ["not", "a", "dict"]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config, f)
            temp_path = f.name
        
        try:
            with pytest.raises(SystemExit) as exc_info:
                ConfigLoader.load_scenarios(temp_path)
            assert exc_info.value.code == 1
        finally:
            Path(temp_path).unlink()
