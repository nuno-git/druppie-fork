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

# Compiled regex patterns for test output parsing
_RE_JEST = re.compile(
    r"Tests:\s*(?:(\d+)\s+failed,\s*)?(?:(\d+)\s+skipped,\s*)?(?:(\d+)\s+passed,\s*)?(\d+)\s+total"
)
_RE_VITEST = re.compile(
    r"Tests\s+(?:(\d+)\s+failed\s*\|?\s*)?(?:(\d+)\s+skipped\s*\|?\s*)?(?:(\d+)\s+passed\s*)?\((\d+)\)"
)
_RE_GENERIC_PASSED = re.compile(r"(\d+)\s+(?:passing|passed)")
_RE_GENERIC_FAILED = re.compile(r"(\d+)\s+(?:failing|failed)")
_RE_GENERIC_SKIPPED = re.compile(r"(\d+)\s+(?:pending|skipped)")
_RE_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text: str) -> str:
    return _RE_ANSI.sub("", text)


def _extract_counts(match):
    """Convert a 4-group regex match (failed, skipped, passed, total) to a dict."""
    return {
        "failed": int(match.group(1)) if match.group(1) else 0,
        "skipped": int(match.group(2)) if match.group(2) else 0,
        "passed": int(match.group(3)) if match.group(3) else 0,
        "total": int(match.group(4)),
    }


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
                "config_files": ["jest.config.js", "jest.config.cjs", "jest.config.mjs", "jest.config.ts"],
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
        
        # Check for Vitest (works with or without vite.config)
        vite_config = workspace_path / "vite.config.js"
        vite_ts_config = workspace_path / "vite.config.ts"
        vitest_config = workspace_path / "vitest.config.js"
        vitest_ts_config = workspace_path / "vitest.config.ts"
        package_json = workspace_path / "package.json"

        # Parse package.json once and reuse across vitest/jest detection
        pkg_data = None
        if package_json.exists():
            try:
                pkg_data = json.loads(package_json.read_text())
            except json.JSONDecodeError:
                pass

        if pkg_data is not None:
            deps = pkg_data.get("devDependencies", {})
            scripts = pkg_data.get("scripts", {})
            _test_val = scripts.get("test", "").strip()
            has_test_script = bool(_test_val) and "no test specified" not in _test_val

            if "vitest" in deps:
                config_file = None
                for cfg in [vitest_config, vitest_ts_config, vite_config, vite_ts_config]:
                    if cfg.exists():
                        config_file = str(cfg)
                        break
                config_info = {
                    "version": deps.get("vitest", "unknown"),
                    "config_file": config_file or "package.json",
                    "coverage_file": "coverage/coverage-final.json",
                    "doc_url": self.FRAMEWORK_CONFIG["vitest"]["doc_url"],
                }
                # Use npm test if a test script exists, otherwise call vitest directly
                test_cmd = "npm run test" if has_test_script else "npx vitest run"
                return "vitest", test_cmd, config_info

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

        # Check for Jest (supports .js, .cjs, .mjs, .ts)
        jest_config = None
        for jest_ext in ["jest.config.js", "jest.config.cjs", "jest.config.mjs", "jest.config.ts"]:
            candidate = workspace_path / jest_ext
            if candidate.exists():
                jest_config = candidate
                break

        if pkg_data is not None:
            has_jest_dep = "jest" in pkg_data.get("devDependencies", {})
        else:
            has_jest_dep = False

        if jest_config or has_jest_dep:
            config_info = {
                "version": "29.x",
                "config_file": str(jest_config) if jest_config else "package.json",
                "coverage_file": "coverage/coverage-final.json",
                "doc_url": self.FRAMEWORK_CONFIG["jest"]["doc_url"],
            }
            # Use npm test if a test script exists, otherwise call jest directly
            # has_test_script was computed above from the single pkg_data parse
            test_cmd = "npm test" if (pkg_data is not None and has_test_script) else "npx jest"
            return "jest", test_cmd, config_info
        
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
                    if "no test specified" in test_script:
                        pass  # Skip npm default — not a real test script
                    elif "jest" in test_script:
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
        """Parse test output to extract pass/fail counts."""
        result = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "failed_tests": [],
        }
        
        combined = _strip_ansi(stdout + "\n" + stderr)
        
        if framework == "pytest":
            # Pytest summary line has components in any order: "1 failed, 3 passed, 1 skipped in 2.34s"
            passed_m = re.search(r"(\d+)\s+passed", combined)
            failed_m = re.search(r"(\d+)\s+failed", combined)
            skipped_m = re.search(r"(\d+)\s+skipped", combined)
            error_m = re.search(r"(\d+)\s+error", combined)
            if passed_m or failed_m:
                result["passed"] = int(passed_m.group(1)) if passed_m else 0
                result["failed"] = int(failed_m.group(1)) if failed_m else 0
                if error_m:
                    result["failed"] += int(error_m.group(1))
                result["skipped"] = int(skipped_m.group(1)) if skipped_m else 0
                result["total"] = result["passed"] + result["failed"] + result["skipped"]
            failed_matches = re.findall(r"FAILED\s+(\S+?)(?:\s+-\s+|\s*$)", combined, re.MULTILINE)
            result["failed_tests"] = failed_matches

        elif framework in ("jest", "vitest"):
            jest_match = _RE_JEST.search(combined)
            vitest_match = _RE_VITEST.search(combined)
            if jest_match:
                result.update(_extract_counts(jest_match))
            elif vitest_match:
                result.update(_extract_counts(vitest_match))
            else:
                passed_m = _RE_GENERIC_PASSED.search(combined)
                failed_m = _RE_GENERIC_FAILED.search(combined)
                skipped_m = _RE_GENERIC_SKIPPED.search(combined)
                if passed_m or failed_m:
                    result["passed"] = int(passed_m.group(1)) if passed_m else 0
                    result["failed"] = int(failed_m.group(1)) if failed_m else 0
                    result["skipped"] = int(skipped_m.group(1)) if skipped_m else 0
                    result["total"] = result["passed"] + result["failed"] + result["skipped"]
            failed_matches = re.findall(r"(?:FAIL|×|✗)\s+(.+)", combined)
            result["failed_tests"] = [m.strip() for m in failed_matches]
        
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
        
        elif framework in ("go", "gotest"):
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
            jest_match = _RE_JEST.search(combined)
            vitest_match = _RE_VITEST.search(combined)
            if jest_match:
                result.update(_extract_counts(jest_match))
            elif vitest_match:
                result.update(_extract_counts(vitest_match))
            else:
                passed_m = _RE_GENERIC_PASSED.search(combined)
                failed_m = _RE_GENERIC_FAILED.search(combined)
                skipped_m = _RE_GENERIC_SKIPPED.search(combined)
                if passed_m or failed_m:
                    result["passed"] = int(passed_m.group(1)) if passed_m else 0
                    result["failed"] = int(failed_m.group(1)) if failed_m else 0
                    result["skipped"] = int(skipped_m.group(1)) if skipped_m else 0
                    result["total"] = result["passed"] + result["failed"] + result["skipped"]
                else:
                    # Count PASS/FAIL lines as a last resort
                    pass_count = len(re.findall(r"(?:PASS|OK|✓|pass)", combined, re.IGNORECASE))
                    fail_count = len(re.findall(r"(?:FAIL|ERROR|✗|fail)", combined, re.IGNORECASE))
                    result["passed"] = pass_count
                    result["failed"] = fail_count
                    result["total"] = pass_count + fail_count

        else:
            passed_m = _RE_GENERIC_PASSED.search(combined)
            failed_m = _RE_GENERIC_FAILED.search(combined)
            skipped_m = _RE_GENERIC_SKIPPED.search(combined)
            if passed_m:
                result["passed"] = int(passed_m.group(1))
            if failed_m:
                result["failed"] = int(failed_m.group(1))
            if skipped_m:
                result["skipped"] = int(skipped_m.group(1))
            result["total"] = result["passed"] + result["failed"] + result["skipped"]

        # Generic fallback: if framework-specific parsing returned nothing,
        # try common patterns regardless of framework
        if result["total"] == 0 and combined.strip():
            vitest_m = _RE_VITEST.search(combined)
            if vitest_m:
                result.update(_extract_counts(vitest_m))
            else:
                passed_m = _RE_GENERIC_PASSED.search(combined)
                failed_m = _RE_GENERIC_FAILED.search(combined)
                skipped_m = _RE_GENERIC_SKIPPED.search(combined)
                if passed_m or failed_m:
                    result["passed"] = int(passed_m.group(1)) if passed_m else 0
                    result["failed"] = int(failed_m.group(1)) if failed_m else 0
                    result["skipped"] = int(skipped_m.group(1)) if skipped_m else 0
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

            # Check actual installation via pip show, not just file listing.
            # String matching in requirements.txt doesn't mean the package
            # is actually installed in the environment.
            for req in required:
                try:
                    result = subprocess.run(
                        ["pip", "show", req],
                        cwd=str(self.workspace_root),
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        installed.append(req)
                except Exception:
                    pass

            return {
                "required": required,
                "installed": installed,
                "missing": [r for r in required if r not in installed],
            }
        
        elif framework == "vitest":
            required = ["vitest", "@vitest/coverage-v8"]
            installed = []
            installed_names = set()

            node_modules = self.workspace_root / "node_modules"
            has_node_modules = node_modules.exists()

            package_json = self.workspace_root / "package.json"
            if package_json.exists() and has_node_modules:
                try:
                    data = json.loads(package_json.read_text())
                    deps = data.get("devDependencies", {})
                    for req in required:
                        if req in deps:
                            # Verify the package is actually installed in node_modules
                            if (node_modules / req).exists():
                                installed.append(f"{req}@{deps[req]}")
                                installed_names.add(req)
                except json.JSONDecodeError:
                    pass

            return {
                "required": required,
                "installed": installed,
                "missing": [r for r in required if r not in installed_names],
            }

        elif framework == "jest":
            required = ["jest"]
            installed = []
            installed_names = set()

            node_modules = self.workspace_root / "node_modules"
            has_node_modules = node_modules.exists()

            package_json = self.workspace_root / "package.json"
            if package_json.exists() and has_node_modules:
                try:
                    data = json.loads(package_json.read_text())
                    deps = data.get("devDependencies", {})
                    for req in required:
                        if req in deps:
                            if (node_modules / req).exists():
                                installed.append(f"{req}@{deps[req]}")
                                installed_names.add(req)
                except json.JSONDecodeError:
                    pass

            return {
                "required": required,
                "installed": installed,
                "missing": [r for r in required if r not in installed_names],
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
            logger.info("coverage_file_not_found: %s (framework=%s)", coverage_file_path, framework)
            return None
        
        try:
            with open(coverage_file_path) as f:
                data = json.load(f)
            
            # Vitest/Jest istanbul coverage-final.json format
            # Each file entry has: statementMap, s (hit counts), branchMap, b, fnMap, f
            # "s": {"0": 1, "1": 3, "2": 0} — keys are indices, values are hit counts
            if framework in ["vitest", "jest"]:
                total_statements = 0
                covered_statements = 0
                file_coverage = []

                for file_path, stats in data.items():
                    s = stats.get("s", {})
                    f = stats.get("f", {})
                    b = stats.get("b", {})

                    file_total = len(s)
                    file_covered = sum(1 for v in s.values() if v > 0)
                    total_statements += file_total
                    covered_statements += file_covered

                    fn_total = len(f)
                    fn_covered = sum(1 for v in f.values() if v > 0)
                    br_total = sum(len(v) for v in b.values()) if b else 0
                    br_covered = sum(sum(1 for c in v if c > 0) for v in b.values()) if b else 0

                    file_coverage.append({
                        "file": file_path,
                        "statement_percent": (file_covered / file_total * 100) if file_total > 0 else 0,
                        "branch_percent": (br_covered / br_total * 100) if br_total > 0 else 0,
                        "function_percent": (fn_covered / fn_total * 100) if fn_total > 0 else 0,
                        "statements_covered": file_covered,
                        "statements_total": file_total,
                    })

                return {
                    "overall_percent": (covered_statements / total_statements * 100) if total_statements > 0 else 0,
                    "file_coverage": file_coverage,
                    "format": "istanbul",
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
