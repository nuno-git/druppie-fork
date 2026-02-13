"""Testing MCP Server Module.

Provides testing-specific tools and utilities.
"""
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)


class TestingModule:
    """Testing operations module."""

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root)
        
        # Framework configuration from the plan
        self.FRAMEWORK_CONFIG = {
            "vitest": {
                "version_required": "^1.1.0",
                "doc_url": "https://vitest.dev/guide/",
                "config_files": ["vite.config.js", "vite.config.ts", "vitest.config.ts"],
                "package_key": "devDependencies.vitest",
                "test_command": "npm run test",
                "coverage_command": "npm run test -- --coverage --reporter=json",
                "coverage_file": "coverage/coverage-final.json",
                "output_parser": "parse_vitest_output",
            },
            "pytest": {
                "version_required": ">=7.4.0",
                "doc_url": "https://docs.pytest.org/en/7.4.x/",
                "config_files": ["pytest.ini", "pyproject.toml", "setup.cfg"],
                "requirements_key": "pytest",
                "test_command": "pytest",
                "coverage_command": "pytest --cov=. --cov-report=json",
                "coverage_file": "coverage.json",
                "output_parser": "parse_pytest_output",
            },
            "jest": {
                "version_required": "29.x",
                "doc_url": "https://jestjs.io/docs/getting-started",
                "config_files": ["jest.config.js", "jest.config.ts"],
                "package_key": "devDependencies.jest",
                "test_command": "npm test",
                "coverage_command": "npm test -- --coverage --coverageReporters=json",
                "coverage_file": "coverage/coverage-final.json",
                "output_parser": "parse_jest_output",
            },
            "playwright": {
                "version_required": "^1.40.0",
                "doc_url": "https://playwright.dev/docs/intro",
                "config_files": ["playwright.config.js", "playwright.config.ts"],
                "package_key": "devDependencies.@playwright/test",
                "test_command": "npx playwright test",
                "coverage_command": None,
                "coverage_file": None,
                "output_parser": "parse_playwright_output",
            },
            "gotest": {
                "version_required": "1.16+",
                "doc_url": "https://go.dev/testing/",
                "config_files": ["go.mod"],
                "test_command": "go test ./...",
                "coverage_command": "go test -coverprofile=coverage.out ./...",
                "coverage_file": "coverage.out",
                "output_parser": "parse_gotest_output",
            },
        }

    def _detect_test_framework(self, workspace_path: Path) -> Tuple[str, str, Dict[str, Any]]:
        """Detect test framework and return (framework, command, config_info).
        
        Enhanced version with detailed configuration information.
        
        Returns:
            Tuple of (framework, test_command, config_info) or ("unknown", "", {})
        """
        config_info = {}
        
        # Check for Vitest (Vite/React)
        vite_config = workspace_path / "vite.config.js"
        vite_ts_config = workspace_path / "vite.config.ts"
        package_json = workspace_path / "package.json"
        
        if vite_config.exists() or vite_ts_config.exists():
            if package_json.exists():
                try:
                    data = json.loads(package_json.read_text())
                    deps = data.get("devDependencies", {})
                    if "vitest" in deps:
                        config_info = {
                            "version": deps.get("vitest", "unknown"),
                            "config_file": str(vite_config) if vite_config.exists() else str(vite_ts_config),
                            "coverage_file": "coverage/coverage-final.json",
                            "doc_url": self.FRAMEWORK_CONFIG["vitest"]["doc_url"],
                        }
                        return "vitest", "npm run test", config_info
                except json.JSONDecodeError:
                    pass
        
        # Check for Pytest (Python)
        pytest_ini = workspace_path / "pytest.ini"
        pyproject = workspace_path / "pyproject.toml"
        requirements_txt = workspace_path / "requirements.txt"
        
        if pytest_ini.exists():
            config_info = {
                "version": "7.4.0+",
                "config_file": str(pytest_ini),
                "coverage_file": "coverage.json",
                "doc_url": self.FRAMEWORK_CONFIG["pytest"]["doc_url"],
            }
            return "pytest", "pytest", config_info
        
        if pyproject.exists():
            try:
                content = pyproject.read_text()
                if "pytest" in content or "[tool.pytest]" in content:
                    config_info = {
                        "version": "7.4.0+",
                        "config_file": str(pyproject),
                        "coverage_file": "coverage.json",
                        "doc_url": self.FRAMEWORK_CONFIG["pytest"]["doc_url"],
                    }
                    return "pytest", "pytest", config_info
            except Exception:
                pass
        
        # Check for Jest
        jest_config = workspace_path / "jest.config.js"
        if jest_config.exists():
            config_info = {
                "version": "29.x",
                "config_file": str(jest_config),
                "coverage_file": "coverage/coverage-final.json",
                "doc_url": self.FRAMEWORK_CONFIG["jest"]["doc_url"],
            }
            return "jest", "npm test", config_info
        
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                if "jest" in data.get("devDependencies", {}):
                    config_info = {
                        "version": "29.x",
                        "config_file": "package.json",
                        "coverage_file": "coverage/coverage-final.json",
                        "doc_url": self.FRAMEWORK_CONFIG["jest"]["doc_url"],
                    }
                    return "jest", "npm test", config_info
            except json.JSONDecodeError:
                pass
        
        # Check for Playwright
        playwright_config = workspace_path / "playwright.config.js"
        if playwright_config.exists():
            config_info = {
                "version": "1.40.0+",
                "config_file": str(playwright_config),
                "coverage_file": None,
                "doc_url": self.FRAMEWORK_CONFIG["playwright"]["doc_url"],
            }
            return "playwright", "npx playwright test", config_info
        
        # Check for Go
        go_mod = workspace_path / "go.mod"
        if go_mod.exists():
            config_info = {
                "version": "1.16+",
                "config_file": str(go_mod),
                "coverage_file": "coverage.out",
                "doc_url": self.FRAMEWORK_CONFIG["gotest"]["doc_url"],
            }
            return "gotest", "go test ./...", config_info
        
        # Check for test.sh (common fallback created by tester agent)
        test_sh = workspace_path / "test.sh"
        if test_sh.exists():
            config_info = {
                "version": "shell",
                "config_file": str(test_sh),
                "coverage_file": None,
                "doc_url": "",
            }
            return "shell", "bash test.sh", config_info

        # Fallback to basic detection from coding MCP
        framework, command = self._detect_test_framework_basic(workspace_path)
        if framework and command:
            return framework, command, {"version": "unknown", "config_file": None, "doc_url": ""}

        return "unknown", "", {}

    def _detect_test_framework_basic(self, workspace_path: Path) -> Tuple[Optional[str], Optional[str]]:
        """Basic test framework detection (copied from coding MCP)."""
        package_json = workspace_path / "package.json"
        if package_json.exists():
            try:
                pkg = json.loads(package_json.read_text())
                scripts = pkg.get("scripts", {})
                if "test" in scripts:
                    test_script = scripts["test"]
                    if "jest" in test_script:
                        return ("jest", "npm test")
                    elif "mocha" in test_script:
                        return ("mocha", "npm test")
                    elif "vitest" in test_script:
                        return ("vitest", "npm test")
                    elif "ava" in test_script:
                        return ("ava", "npm test")
                    else:
                        return ("npm", "npm test")
            except (json.JSONDecodeError, KeyError):
                pass
        
        pytest_ini = workspace_path / "pytest.ini"
        pyproject_toml = workspace_path / "pyproject.toml"
        has_pytest_files = list(workspace_path.glob("test_*.py")) or list(workspace_path.glob("**/test_*.py"))
        has_tests_dir = (workspace_path / "tests").exists()
        
        if pytest_ini.exists() or has_pytest_files or has_tests_dir:
            return ("pytest", "pytest -v")
        
        if pyproject_toml.exists():
            try:
                content = pyproject_toml.read_text()
                if "[tool.pytest" in content:
                    return ("pytest", "pytest -v")
            except Exception:
                pass
        
        go_test_files = list(workspace_path.glob("*_test.go")) or list(workspace_path.glob("**/*_test.go"))
        go_mod = workspace_path / "go.mod"
        if go_test_files or go_mod.exists():
            return ("go", "go test -v ./...")
        
        cargo_toml = workspace_path / "Cargo.toml"
        if cargo_toml.exists():
            return ("cargo", "cargo test")
        
        gemfile = workspace_path / "Gemfile"
        spec_dir = workspace_path / "spec"
        if spec_dir.exists():
            return ("rspec", "bundle exec rspec")
        elif gemfile.exists():
            try:
                content = gemfile.read_text()
                if "rspec" in content.lower():
                    return ("rspec", "bundle exec rspec")
                elif "minitest" in content.lower():
                    return ("minitest", "bundle exec rake test")
            except Exception:
                pass
        
        pom_xml = workspace_path / "pom.xml"
        if pom_xml.exists():
            return ("maven", "mvn test")
        
        build_gradle = workspace_path / "build.gradle"
        build_gradle_kts = workspace_path / "build.gradle.kts"
        if build_gradle.exists() or build_gradle_kts.exists():
            return ("gradle", "./gradlew test")
        
        return (None, None)

    def _parse_test_output(self, stdout: str, stderr: str, framework: str) -> Dict[str, Any]:
        """Parse test output to extract pass/fail counts (copied from coding MCP)."""
        result = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "failed_tests": [],
        }
        
        combined = stdout + "\n" + stderr
        
        if framework == "pytest":
            match = re.search(
                r"(\d+)\s+passed(?:,\s+(\d+)\s+failed)?(?:,\s+(\d+)\s+skipped)?",
                combined,
            )
            if match:
                result["passed"] = int(match.group(1))
                result["failed"] = int(match.group(2)) if match.group(2) else 0
                result["skipped"] = int(match.group(3)) if match.group(3) else 0
                result["total"] = result["passed"] + result["failed"] + result["skipped"]
            failed_matches = re.findall(r"FAILED\s+([\w:]+)", combined)
            result["failed_tests"] = failed_matches
        
        elif framework in ("jest", "vitest"):
            match = re.search(
                r"Tests:\s*(?:(\d+)\s+failed,\s*)?(?:(\d+)\s+skipped,\s*)?(?:(\d+)\s+passed,\s*)?(\d+)\s+total",
                combined,
            )
            if match:
                result["failed"] = int(match.group(1)) if match.group(1) else 0
                result["skipped"] = int(match.group(2)) if match.group(2) else 0
                result["passed"] = int(match.group(3)) if match.group(3) else 0
                result["total"] = int(match.group(4))
            failed_matches = re.findall(r"FAIL\s+(.+)", combined)
            result["failed_tests"] = failed_matches
        
        elif framework == "mocha":
            passing = re.search(r"(\d+)\s+passing", combined)
            failing = re.search(r"(\d+)\s+failing", combined)
            pending = re.search(r"(\d+)\s+pending", combined)
            if passing:
                result["passed"] = int(passing.group(1))
            if failing:
                result["failed"] = int(failing.group(1))
            if pending:
                result["skipped"] = int(pending.group(1))
            result["total"] = result["passed"] + result["failed"] + result["skipped"]
        
        elif framework == "go":
            ok_count = len(re.findall(r"^ok\s+", combined, re.MULTILINE))
            fail_count = len(re.findall(r"^FAIL\s+", combined, re.MULTILINE))
            skip_count = len(re.findall(r"^SKIP\s+", combined, re.MULTILINE))
            pass_match = re.search(r"PASS", combined)
            individual_fails = re.findall(r"--- FAIL:\s+(\w+)", combined)
            result["passed"] = ok_count if ok_count else (1 if pass_match else 0)
            result["failed"] = len(individual_fails) if individual_fails else fail_count
            result["skipped"] = skip_count
            result["total"] = result["passed"] + result["failed"] + result["skipped"]
            result["failed_tests"] = individual_fails
        
        elif framework == "cargo":
            match = re.search(
                r"(\d+)\s+passed;\s*(\d+)\s+failed;\s*(\d+)\s+ignored",
                combined,
            )
            if match:
                result["passed"] = int(match.group(1))
                result["failed"] = int(match.group(2))
                result["skipped"] = int(match.group(3))
                result["total"] = result["passed"] + result["failed"] + result["skipped"]
            failed_matches = re.findall(r"---- (\S+) stdout ----", combined)
            result["failed_tests"] = failed_matches
        
        elif framework == "rspec":
            match = re.search(
                r"(\d+)\s+examples?,\s*(\d+)\s+failures?(?:,\s*(\d+)\s+pending)?",
                combined,
            )
            if match:
                result["total"] = int(match.group(1))
                result["failed"] = int(match.group(2))
                result["skipped"] = int(match.group(3)) if match.group(3) else 0
                result["passed"] = result["total"] - result["failed"] - result["skipped"]
        
        elif framework in ("maven", "gradle"):
            match = re.search(
                r"Tests\s+run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)",
                combined,
            )
            if match:
                result["total"] = int(match.group(1))
                result["failed"] = int(match.group(2)) + int(match.group(3))
                result["skipped"] = int(match.group(4))
                result["passed"] = result["total"] - result["failed"] - result["skipped"]
        
        elif framework == "shell":
            # Shell scripts (test.sh) - try to parse common patterns
            # First try pytest/jest/vitest patterns in case test.sh wraps them
            pytest_match = re.search(
                r"(\d+)\s+passed(?:,\s+(\d+)\s+failed)?(?:,\s+(\d+)\s+skipped)?",
                combined,
            )
            jest_match = re.search(
                r"Tests:\s*(?:(\d+)\s+failed,\s*)?(?:(\d+)\s+skipped,\s*)?(?:(\d+)\s+passed,\s*)?(\d+)\s+total",
                combined,
            )
            if pytest_match:
                result["passed"] = int(pytest_match.group(1))
                result["failed"] = int(pytest_match.group(2)) if pytest_match.group(2) else 0
                result["skipped"] = int(pytest_match.group(3)) if pytest_match.group(3) else 0
                result["total"] = result["passed"] + result["failed"] + result["skipped"]
            elif jest_match:
                result["failed"] = int(jest_match.group(1)) if jest_match.group(1) else 0
                result["skipped"] = int(jest_match.group(2)) if jest_match.group(2) else 0
                result["passed"] = int(jest_match.group(3)) if jest_match.group(3) else 0
                result["total"] = int(jest_match.group(4))
            else:
                # Count PASS/FAIL lines as a last resort
                pass_count = len(re.findall(r"(?:PASS|OK|✓|pass)", combined, re.IGNORECASE))
                fail_count = len(re.findall(r"(?:FAIL|ERROR|✗|fail)", combined, re.IGNORECASE))
                result["passed"] = pass_count
                result["failed"] = fail_count
                result["total"] = pass_count + fail_count

        else:
            match = re.search(r"(\d+)\s+(?:passing|passed)", combined)
            if match:
                result["passed"] = int(match.group(1))
            match = re.search(r"(\d+)\s+(?:failing|failed)", combined)
            if match:
                result["failed"] = int(match.group(1))
            match = re.search(r"(\d+)\s+(?:pending|skipped)", combined)
            if match:
                result["skipped"] = int(match.group(1))
            result["total"] = result["passed"] + result["failed"] + result["skipped"]
        
        return result

    def parse_test_results(
        self,
        output: str,
        framework: str,
    ) -> Dict[str, Any]:
        """Parse test output to extract results.
        
        Args:
            output: Raw test output
            framework: Test framework (pytest, vitest, jest, playwright)
        
        Returns:
            Dict with parsed results
        """
        return self._parse_test_output(output, "", framework)

    def get_test_framework_info(self) -> Dict[str, Any]:
        """Get test framework information for workspace.
        
        Returns:
            Dict with framework details
        """
        framework, test_command, config_info = self._detect_test_framework(self.workspace_root)
        
        if framework == "unknown":
            return {
                "framework": "unknown",
                "message": "Could not auto-detect test framework.",
            }
        
        # Check if dependencies are installed
        requirements_check = self._check_framework_dependencies(framework)
        
        return {
            "framework": framework,
            "version": config_info.get("version", "unknown"),
            "test_command": test_command,
            "coverage_command": self.FRAMEWORK_CONFIG.get(framework, {}).get("coverage_command"),
            "coverage_file": config_info.get("coverage_file"),
            "config_file": config_info.get("config_file"),
            "doc_url": config_info.get("doc_url", ""),
            "requirements_check": requirements_check,
        }

    def _check_framework_dependencies(self, framework: str) -> Dict[str, Any]:
        """Check if required dependencies are installed for the framework.
        
        Returns:
            Dict with required packages and their installation status
        """
        if framework == "pytest":
            required = ["pytest", "pytest-cov", "pytest-asyncio"]
            installed = []
            
            for req in required:
                requirements_txt = self.workspace_root / "requirements.txt"
                pyproject = self.workspace_root / "pyproject.toml"
                
                if requirements_txt.exists():
                    if req in requirements_txt.read_text():
                        installed.append(req)
                if pyproject.exists():
                    if req in pyproject.read_text():
                        installed.append(req)
            
            return {
                "required": required,
                "installed": installed,
                "missing": [r for r in required if r not in installed],
            }
        
        elif framework == "vitest":
            required = ["vitest", "@vitest/coverage-v8"]
            installed = []
            
            package_json = self.workspace_root / "package.json"
            if package_json.exists():
                try:
                    data = json.loads(package_json.read_text())
                    deps = data.get("devDependencies", {})
                    for req in required:
                        if req in deps:
                            installed.append(f"{req}@{deps[req]}")
                except json.JSONDecodeError:
                    pass
            
            return {
                "required": required,
                "installed": installed,
                "missing": [r for r in required if r not in installed],
            }
        
        elif framework == "jest":
            required = ["jest"]
            installed = []
            
            package_json = self.workspace_root / "package.json"
            if package_json.exists():
                try:
                    data = json.loads(package_json.read_text())
                    deps = data.get("devDependencies", {})
                    for req in required:
                        if req in deps:
                            installed.append(f"{req}@{deps[req]}")
                except json.JSONDecodeError:
                    pass
            
            return {
                "required": required,
                "installed": installed,
                "missing": [r for r in required if r not in installed],
            }
        
        return {"required": [], "installed": [], "missing": []}

    def validate_tdd_workflow(
        self,
        test_results: Dict[str, Any],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate TDD workflow results.
        
        Args:
            test_results: Parsed test results
            config: TDD configuration
        
        Returns:
            Dict with validation result
        """
        passed = test_results.get("failed", 0) == 0
        coverage_ok = True
        
        coverage = test_results.get("coverage", {}).get("overall_percent", 0)
        threshold = config.get("coverage_threshold", 80.0)
        if coverage < threshold:
            coverage_ok = False
        
        return {
            "passed": passed and coverage_ok,
            "tests_passed": passed,
            "coverage_ok": coverage_ok,
            "coverage": coverage,
            "threshold": threshold,
        }

    def parse_coverage_json(self, framework: str) -> Optional[Dict[str, Any]]:
        """Parse coverage JSON file based on framework.
        
        Args:
            framework: Detected framework name
            
        Returns:
            Coverage dict or None if not available
        """
        coverage_files = {
            "vitest": "coverage/coverage-final.json",
            "jest": "coverage/coverage-final.json",
            "pytest": "coverage.json",
        }
        
        coverage_file_path = self.workspace_root / coverage_files.get(framework, "")
        if not coverage_file_path.exists():
            return None
        
        try:
            with open(coverage_file_path) as f:
                data = json.load(f)
            
            # Vitest/Jest format (v8 coverage provider)
            if framework in ["vitest", "jest"]:
                total_lines = sum(f.get("l", {}).get("total", 0) for f in data.values())
                covered_lines = sum(f.get("l", {}).get("covered", 0) for f in data.values())
                return {
                    "overall_percent": (covered_lines / total_lines * 100) if total_lines > 0 else 0,
                    "file_coverage": [
                        {
                            "file": file_path,
                            "statement_percent": stats.get("s", {}).get("pct", 0),
                            "branch_percent": stats.get("b", {}).get("pct", 0),
                            "function_percent": stats.get("f", {}).get("pct", 0),
                            "line_percent": stats.get("l", {}).get("pct", 0),
                            "lines_covered": stats.get("l", {}).get("covered", 0),
                            "lines_total": stats.get("l", {}).get("total", 0),
                        }
                        for file_path, stats in data.items()
                    ],
                    "format": "v8",
                }
            
            # Pytest format
            elif framework == "pytest":
                totals = data.get("totals", {})
                return {
                    "overall_percent": totals.get("percent_covered", 0),
                    "statement_percent": (
                        totals.get("num_statements_covered", 0) / 
                        max(totals.get("num_statements", 1), 1) * 100
                    ),
                    "branch_percent": (
                        totals.get("num_branches_covered", 0) / 
                        max(totals.get("num_branches", 1), 1) * 100
                    ),
                    "function_percent": (
                        totals.get("num_functions_covered", 0) / 
                        max(totals.get("num_functions", 1), 1) * 100
                    ),
                    "line_percent": (
                        totals.get("num_lines_covered", 0) / 
                        max(totals.get("num_lines", 1), 1) * 100
                    ),
                    "file_coverage": [
                        {
                            "file": file_data.get("filename", ""),
                            "summary": file_data.get("summary", {}),
                        }
                        for file_data in data.get("files", [])
                    ],
                    "format": "pytest",
                }
            
            return None
            
        except Exception as e:
            logger.error(f"coverage_parse_error: {e}")
            return None
