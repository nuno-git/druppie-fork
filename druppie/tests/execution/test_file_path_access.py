"""Tests for ToolExecutor file-path access validation."""

import pytest

from druppie.execution.tool_executor import ToolExecutor


class TestNormalizePath:
    def test_strips_leading_slash(self):
        assert ToolExecutor._normalize_path("/src/app.py") == "src/app.py"

    def test_resolves_parent_traversal(self):
        assert ToolExecutor._normalize_path("src/components/../server/app.py") == "src/server/app.py"

    def test_resolves_dot_segments(self):
        assert ToolExecutor._normalize_path("./src/app.py") == "src/app.py"

    def test_normalizes_backslashes(self):
        assert ToolExecutor._normalize_path("src\\components\\app.tsx") == "src/components/app.tsx"

    def test_collapses_double_slashes(self):
        assert ToolExecutor._normalize_path("src//app.py") == "src/app.py"

    def test_plain_filename(self):
        assert ToolExecutor._normalize_path("app.py") == "app.py"


class TestPathMatchesPattern:
    """Tests for _path_matches_pattern with pre-normalized paths."""

    # --- Directory prefix patterns (ending with /) ---

    def test_dir_pattern_matches_file_under_dir(self):
        assert ToolExecutor._path_matches_pattern("src/components/App.tsx", "src/components/")

    def test_dir_pattern_matches_nested_file(self):
        assert ToolExecutor._path_matches_pattern("src/components/sub/deep/File.tsx", "src/components/")

    def test_dir_pattern_does_not_match_sibling(self):
        assert not ToolExecutor._path_matches_pattern("src/componentsFoo/bar.tsx", "src/components/")

    def test_dir_pattern_does_not_match_prefix_substring(self):
        assert not ToolExecutor._path_matches_pattern("api-docs/readme.md", "api/")

    def test_dir_pattern_matches_exact_dir_name(self):
        assert ToolExecutor._path_matches_pattern("src/components", "src/components/")

    def test_dir_pattern_no_match_unrelated(self):
        assert not ToolExecutor._path_matches_pattern("server/app.py", "src/components/")

    def test_single_segment_dir(self):
        assert ToolExecutor._path_matches_pattern("frontend/src/App.tsx", "frontend/")

    def test_single_segment_dir_no_false_positive(self):
        assert not ToolExecutor._path_matches_pattern("frontend2/src/App.tsx", "frontend/")

    # --- Extension glob patterns (*.ext) ---

    def test_ext_glob_matches_at_root(self):
        assert ToolExecutor._path_matches_pattern("app.py", "*.py")

    def test_ext_glob_matches_nested(self):
        assert ToolExecutor._path_matches_pattern("src/deep/app.py", "*.py")

    def test_ext_glob_no_match_wrong_ext(self):
        assert not ToolExecutor._path_matches_pattern("app.tsx", "*.py")

    # --- Multi-segment glob patterns (contain /) ---

    def test_multi_segment_glob_matches(self):
        assert ToolExecutor._path_matches_pattern("src/App.tsx", "src/App.*")

    def test_multi_segment_glob_matches_different_ext(self):
        assert ToolExecutor._path_matches_pattern("src/App.js", "src/App.*")

    def test_multi_segment_glob_no_match_wrong_dir(self):
        assert not ToolExecutor._path_matches_pattern("lib/App.tsx", "src/App.*")

    def test_multi_segment_glob_no_match_wrong_name(self):
        assert not ToolExecutor._path_matches_pattern("src/Main.tsx", "src/App.*")

    def test_config_glob(self):
        assert ToolExecutor._path_matches_pattern("tailwind.config.js", "tailwind.config.*")

    def test_config_glob_ts(self):
        assert ToolExecutor._path_matches_pattern("tailwind.config.ts", "tailwind.config.*")

    def test_docker_compose_glob(self):
        assert ToolExecutor._path_matches_pattern("docker-compose.yml", "docker-compose.*")

    # --- Exact filename patterns ---

    def test_exact_matches_at_root(self):
        assert ToolExecutor._path_matches_pattern("package.json", "package.json")

    def test_exact_matches_nested(self):
        assert ToolExecutor._path_matches_pattern("frontend/package.json", "package.json")

    def test_exact_no_match_different_name(self):
        assert not ToolExecutor._path_matches_pattern("cargo.toml", "package.json")

    def test_exact_dockerfile(self):
        assert ToolExecutor._path_matches_pattern("Dockerfile", "Dockerfile")

    def test_exact_dockerfile_nested(self):
        assert ToolExecutor._path_matches_pattern("services/api/Dockerfile", "Dockerfile")

    # --- Wildcard filename patterns ---

    def test_test_file_pattern(self):
        assert ToolExecutor._path_matches_pattern("tests/test_user.py", "test_*.py")

    def test_test_file_pattern_nested(self):
        assert ToolExecutor._path_matches_pattern("src/tests/test_user.py", "test_*.py")

    def test_test_file_no_match(self):
        assert not ToolExecutor._path_matches_pattern("src/user.py", "test_*.py")

    def test_spec_pattern(self):
        assert ToolExecutor._path_matches_pattern("App.spec.ts", "*.spec.*")

    def test_test_tsx_pattern(self):
        assert ToolExecutor._path_matches_pattern("App.test.tsx", "*.test.tsx")


class TestExtractFilePaths:
    def test_read_file_path(self):
        assert ToolExecutor._extract_file_paths("read_file", {"path": "src/app.py"}) == ["src/app.py"]

    def test_edit_file_file_path(self):
        assert ToolExecutor._extract_file_paths("edit_file", {"file_path": "src/app.py"}) == ["src/app.py"]

    def test_batch_write_files(self):
        args = {"files": [{"path": "a.py"}, {"path": "b.py"}]}
        assert ToolExecutor._extract_file_paths("batch_write_files", args) == ["a.py", "b.py"]

    def test_batch_write_files_skips_invalid(self):
        args = {"files": ["not_a_dict", {"path": "a.py"}]}
        assert ToolExecutor._extract_file_paths("batch_write_files", args) == ["a.py"]

    def test_empty_args(self):
        assert ToolExecutor._extract_file_paths("read_file", {}) == []

    def test_no_args(self):
        assert ToolExecutor._extract_file_paths("bash", {"command": "echo hi"}) == []


class TestPathTraversalPrevention:
    """Verify that ../ traversal is caught by normalization."""

    def test_traversal_out_of_allowed_dir(self):
        path = ToolExecutor._normalize_path("src/components/../server/app.py")
        assert path == "src/server/app.py"
        assert not ToolExecutor._path_matches_pattern(path, "src/components/")
        assert ToolExecutor._path_matches_pattern(path, "src/server/")

    def test_traversal_into_forbidden_dir(self):
        path = ToolExecutor._normalize_path("allowed/../forbidden/secret.py")
        assert path == "forbidden/secret.py"
        assert ToolExecutor._path_matches_pattern(path, "forbidden/")

    def test_double_traversal(self):
        path = ToolExecutor._normalize_path("a/b/../../c/d.py")
        assert path == "c/d.py"
