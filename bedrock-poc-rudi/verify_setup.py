#!/usr/bin/env python3
"""
Setup Verification Script
Verifies that the Python project structure is correctly set up.
"""

import sys
import os
from pathlib import Path


def check_python_version():
    """Verify Python 3.10+ is installed (Requirement 7.1)"""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 10:
        print(f"✓ Python {version.major}.{version.minor}.{version.micro} detected (Requirement 7.1)")
        return True
    else:
        print(f"✗ Python {version.major}.{version.minor} detected. Python 3.10+ required.")
        return False


def check_dependencies():
    """Verify core dependencies are installed (Requirements 7.2, 7.3, 7.4)"""
    dependencies = {
        "boto3": ("boto3", "7.2"),
        "ddtrace": ("ddtrace", "7.3"),
        "pyyaml": ("yaml", "7.4"),
        "requests": ("requests", "7.4"),
        "mcp": ("mcp", "7.4"),
    }
    
    all_found = True
    for dep_name, (import_name, req) in dependencies.items():
        try:
            __import__(import_name)
            print(f"✓ {dep_name} installed (Requirement {req})")
        except ImportError:
            print(f"✗ {dep_name} not found (Requirement {req})")
            all_found = False
    
    return all_found


def check_directory_structure():
    """Verify required directories exist"""
    base_path = Path(__file__).parent
    required_dirs = ["src", "tests", "config", "alerts"]
    
    all_exist = True
    for dir_name in required_dirs:
        dir_path = base_path / dir_name
        if dir_path.exists() and dir_path.is_dir():
            print(f"✓ Directory '{dir_name}/' exists")
        else:
            print(f"✗ Directory '{dir_name}/' not found")
            all_exist = False
    
    return all_exist


def check_configuration_files():
    """Verify configuration files exist"""
    base_path = Path(__file__).parent
    required_files = {
        "pyproject.toml": "Project metadata",
        "requirements.txt": "Dependencies list",
        ".env.example": "Environment variables template",
        "config/agent.yaml": "Agent configuration",
        "alerts/example_alert.yaml": "Example alert scenario",
    }
    
    all_exist = True
    for file_path, description in required_files.items():
        full_path = base_path / file_path
        if full_path.exists() and full_path.is_file():
            print(f"✓ {description}: {file_path}")
        else:
            print(f"✗ {description} not found: {file_path}")
            all_exist = False
    
    return all_exist


def check_virtual_environment():
    """Check if running in a virtual environment"""
    in_venv = hasattr(sys, 'real_prefix') or (
        hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
    )
    
    if in_venv:
        print(f"✓ Running in virtual environment: {sys.prefix}")
        return True
    else:
        print("⚠ Not running in a virtual environment (recommended)")
        return True  # Not a failure, just a warning


def main():
    """Run all verification checks"""
    print("=" * 60)
    print("Python Project Setup Verification")
    print("Autonomous Incident Response Agent")
    print("=" * 60)
    print()
    
    checks = [
        ("Python Version", check_python_version),
        ("Virtual Environment", check_virtual_environment),
        ("Core Dependencies", check_dependencies),
        ("Directory Structure", check_directory_structure),
        ("Configuration Files", check_configuration_files),
    ]
    
    results = []
    for name, check_func in checks:
        print(f"\n{name}:")
        print("-" * 60)
        result = check_func()
        results.append(result)
    
    print("\n" + "=" * 60)
    if all(results):
        print("✓ All checks passed! Project setup is complete.")
        print("\nNext steps:")
        print("1. Copy .env.example to .env and configure your credentials")
        print("2. Review config/agent.yaml for agent settings")
        print("3. Start implementing modules following the design document")
        return 0
    else:
        print("✗ Some checks failed. Please review the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
