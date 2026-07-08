"""Tests for file-path access validation (shared path_validation module)."""

import pytest

from druppie.execution.path_validation import (
    FILE_WRITE_TOOLS,
    extract_file_paths,
    normalize_path,
    path_matches_pattern,
    validate_file_path_access,
)


class TestNormalizePath:
    def test_strips_leading_slash(self):
        assert normalize_path("/src/app.py") == "src/app.py"

    def test_resolves_parent_traversal(self):
        assert normalize_path("src/components/../server/app.py") == "src/server/app.py"

    def test_resolves_dot_segments(self):
        assert normalize_path("./src/app.py") == "src/app.py"

    def test_normalizes_backslashes(self):
        assert normalize_path("src\\components\\app.tsx") == "src/components/app.tsx"

    def test_collapses_double_slashes(self):
        assert normalize_path("src//app.py") == "src/app.py"

    def test_plain_filename(self):
        assert normalize_path("app.py") == "app.py"


class TestPathMatchesPattern:
    """Tests for path_matches_pattern with pre-normalized paths."""

    # --- Directory prefix patterns (ending with /) ---

    def test_dir_pattern_matches_file_under_dir(self):
        assert path_matches_pattern("src/components/App.tsx", "src/components/")

    def test_dir_pattern_matches_nested_file(self):
        assert path_matches_pattern("src/components/sub/deep/File.tsx", "src/components/")

    def test_dir_pattern_does_not_match_sibling(self):
        assert not path_matches_pattern("src/componentsFoo/bar.tsx", "src/components/")

    def test_dir_pattern_does_not_match_prefix_substring(self):
        assert not path_matches_pattern("api-docs/readme.md", "api/")

    def test_dir_pattern_matches_exact_dir_name(self):
        assert path_matches_pattern("src/components", "src/components/")

    def test_dir_pattern_no_match_unrelated(self):
        assert not path_matches_pattern("server/app.py", "src/components/")

    def test_single_segment_dir(self):
        assert path_matches_pattern("frontend/src/App.tsx", "frontend/")

    def test_single_segment_dir_no_false_positive(self):
        assert not path_matches_pattern("frontend2/src/App.tsx", "frontend/")

    # --- Extension glob patterns (*.ext) ---

    def test_ext_glob_matches_at_root(self):
        assert path_matches_pattern("app.py", "*.py")

    def test_ext_glob_matches_nested(self):
        assert path_matches_pattern("src/deep/app.py", "*.py")

    def test_ext_glob_no_match_wrong_ext(self):
        assert not path_matches_pattern("app.tsx", "*.py")

    # --- Multi-segment glob patterns (contain /) ---

    def test_multi_segment_glob_matches(self):
        assert path_matches_pattern("src/App.tsx", "src/App.*")

    def test_multi_segment_glob_matches_different_ext(self):
        assert path_matches_pattern("src/App.js", "src/App.*")

    def test_multi_segment_glob_no_match_wrong_dir(self):
        assert not path_matches_pattern("lib/App.tsx", "src/App.*")

    def test_multi_segment_glob_no_match_wrong_name(self):
        assert not path_matches_pattern("src/Main.tsx", "src/App.*")

    def test_config_glob(self):
        assert path_matches_pattern("tailwind.config.js", "tailwind.config.*")

    def test_config_glob_ts(self):
        assert path_matches_pattern("tailwind.config.ts", "tailwind.config.*")

    def test_docker_compose_glob(self):
        assert path_matches_pattern("docker-compose.yml", "docker-compose.*")

    # --- Exact filename patterns ---

    def test_exact_matches_at_root(self):
        assert path_matches_pattern("package.json", "package.json")

    def test_exact_matches_nested(self):
        assert path_matches_pattern("frontend/package.json", "package.json")

    def test_exact_no_match_different_name(self):
        assert not path_matches_pattern("cargo.toml", "package.json")

    def test_exact_dockerfile(self):
        assert path_matches_pattern("Dockerfile", "Dockerfile")

    def test_exact_dockerfile_nested(self):
        assert path_matches_pattern("services/api/Dockerfile", "Dockerfile")

    # --- Wildcard filename patterns ---

    def test_test_file_pattern(self):
        assert path_matches_pattern("tests/test_user.py", "test_*.py")

    def test_test_file_pattern_nested(self):
        assert path_matches_pattern("src/tests/test_user.py", "test_*.py")

    def test_test_file_no_match(self):
        assert not path_matches_pattern("src/user.py", "test_*.py")

    def test_spec_pattern(self):
        assert path_matches_pattern("App.spec.ts", "*.spec.*")

    def test_test_tsx_pattern(self):
        assert path_matches_pattern("App.test.tsx", "*.test.tsx")


class TestExtractFilePaths:
    def test_read_file_path(self):
        assert extract_file_paths("read_file", {"path": "src/app.py"}) == ["src/app.py"]

    def test_edit_file_file_path(self):
        assert extract_file_paths("edit_file", {"file_path": "src/app.py"}) == ["src/app.py"]

    def test_batch_write_files(self):
        args = {"files": [{"path": "a.py"}, {"path": "b.py"}]}
        assert extract_file_paths("batch_write_files", args) == ["a.py", "b.py"]

    def test_batch_write_files_skips_invalid(self):
        args = {"files": ["not_a_dict", {"path": "a.py"}]}
        assert extract_file_paths("batch_write_files", args) == ["a.py"]

    def test_empty_args(self):
        assert extract_file_paths("read_file", {}) == []

    def test_no_args(self):
        assert extract_file_paths("bash", {"command": "echo hi"}) == []


class TestPathTraversalPrevention:
    """Verify that ../ traversal is caught by normalization."""

    def test_traversal_out_of_allowed_dir(self):
        path = normalize_path("src/components/../server/app.py")
        assert path == "src/server/app.py"
        assert not path_matches_pattern(path, "src/components/")
        assert path_matches_pattern(path, "src/server/")

    def test_traversal_into_forbidden_dir(self):
        path = normalize_path("allowed/../forbidden/secret.py")
        assert path == "forbidden/secret.py"
        assert path_matches_pattern(path, "forbidden/")

    def test_double_traversal(self):
        path = normalize_path("a/b/../../c/d.py")
        assert path == "c/d.py"


class TestValidateFilePathAccess:
    """Integration tests for the full validate_file_path_access function."""

    ALLOWED = ["src/components/", "*.tsx", "src/App.*", "package.json"]
    FORBIDDEN = ["api/", "server/", "*.py", "db/models/"]

    def test_write_to_allowed_dir_passes(self):
        assert validate_file_path_access(
            "write_file", {"path": "src/components/App.tsx"},
            "frontend_dev", self.ALLOWED, self.FORBIDDEN,
        ) is None

    def test_write_to_forbidden_dir_blocked(self):
        result = validate_file_path_access(
            "write_file", {"path": "api/routes.py"},
            "frontend_dev", self.ALLOWED, self.FORBIDDEN,
        )
        assert result is not None
        assert "forbidden" in result

    def test_write_to_unlisted_path_blocked(self):
        result = validate_file_path_access(
            "write_file", {"path": "config/settings.yml"},
            "frontend_dev", self.ALLOWED, self.FORBIDDEN,
        )
        assert result is not None
        assert "not allowed" in result

    def test_read_file_not_enforced(self):
        assert validate_file_path_access(
            "read_file", {"path": "api/secrets.py"},
            "frontend_dev", self.ALLOWED, self.FORBIDDEN,
        ) is None

    def test_grep_not_enforced(self):
        assert validate_file_path_access(
            "grep", {"path": "server/", "pattern": "password"},
            "frontend_dev", self.ALLOWED, self.FORBIDDEN,
        ) is None

    def test_bash_not_enforced(self):
        assert validate_file_path_access(
            "bash", {"command": "cat api/secrets.py"},
            "frontend_dev", self.ALLOWED, self.FORBIDDEN,
        ) is None

    def test_delete_forbidden_blocked(self):
        result = validate_file_path_access(
            "delete_file", {"path": "db/models/user.py"},
            "frontend_dev", self.ALLOWED, self.FORBIDDEN,
        )
        assert result is not None
        assert "forbidden" in result

    def test_edit_allowed_passes(self):
        assert validate_file_path_access(
            "edit_file", {"file_path": "src/components/Header.tsx"},
            "frontend_dev", self.ALLOWED, self.FORBIDDEN,
        ) is None

    def test_no_constraints_passes(self):
        assert validate_file_path_access(
            "write_file", {"path": "anything.py"},
            "agent", None, None,
        ) is None

    def test_traversal_blocked(self):
        result = validate_file_path_access(
            "write_file", {"path": "src/components/../api/hack.py"},
            "frontend_dev", self.ALLOWED, self.FORBIDDEN,
        )
        assert result is not None
        assert "forbidden" in result

    def test_batch_write_partial_forbidden(self):
        result = validate_file_path_access(
            "batch_write_files",
            {"files": [
                {"path": "src/components/Ok.tsx"},
                {"path": "api/bad.py"},
            ]},
            "frontend_dev", self.ALLOWED, self.FORBIDDEN,
        )
        assert result is not None
        assert "api/bad.py" in result

    def test_multi_segment_pattern_write(self):
        assert validate_file_path_access(
            "write_file", {"path": "src/App.tsx"},
            "frontend_dev", self.ALLOWED, self.FORBIDDEN,
        ) is None

    def test_forbidden_takes_precedence_over_allowed(self):
        result = validate_file_path_access(
            "write_file", {"path": "api/routes.tsx"},
            "frontend_dev", self.ALLOWED, self.FORBIDDEN,
        )
        assert result is not None
        assert "forbidden" in result


class TestFileWriteToolsSet:
    """Verify FILE_WRITE_TOOLS contains only write operations."""

    def test_write_tools_present(self):
        for tool in ["write_file", "edit_file", "delete_file", "batch_write_files"]:
            assert tool in FILE_WRITE_TOOLS

    def test_read_tools_absent(self):
        for tool in ["read_file", "grep", "find", "ls", "list_dir", "bash"]:
            assert tool not in FILE_WRITE_TOOLS
