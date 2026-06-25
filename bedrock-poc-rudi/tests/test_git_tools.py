"""
Unit tests for src/git_tools.py

Covers:
  - read_application_code: happy path, file-not-found, path-traversal rejection
  - create_github_pr: PyGithub API sequence, missing env vars, GithubException handling
  - GIT_TOOL_CONFIG: schema shape validation for Bedrock toolConfig
  - execute_git_tool: dispatcher routing and return shape
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch, call

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.git_tools import (
    GIT_TOOL_CONFIG,
    GIT_TOOL_NAMES,
    execute_git_tool,
    read_application_code,
    create_github_pr,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dummy_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary dummy_app directory and point DUMMY_APP_DIR at it."""
    app_dir = tmp_path / "dummy_app"
    app_dir.mkdir()
    (app_dir / "services").mkdir()
    (app_dir / "services" / "orders.py").write_text(
        "# N+1 bug here\ndef get_orders(): pass\n", encoding="utf-8"
    )
    monkeypatch.setenv("DUMMY_APP_DIR", str(app_dir))
    return app_dir


# ---------------------------------------------------------------------------
# read_application_code
# ---------------------------------------------------------------------------


class TestReadApplicationCode:
    def test_reads_existing_file(self, dummy_app: Path) -> None:
        content = read_application_code("services/orders.py")
        assert "N+1 bug" in content
        assert "def get_orders" in content

    def test_returns_error_for_missing_file(self, dummy_app: Path) -> None:
        result = read_application_code("nonexistent/file.py")
        assert result.startswith("ERROR:")
        assert "not found" in result

    def test_rejects_path_traversal_dotdot(self, dummy_app: Path) -> None:
        result = read_application_code("../../etc/passwd")
        assert result.startswith("ERROR:")
        assert "traversal" in result

    def test_rejects_absolute_path_outside_base(
        self, dummy_app: Path, tmp_path: Path
    ) -> None:
        secret = tmp_path / "secret.txt"
        secret.write_text("secret", encoding="utf-8")
        result = read_application_code(str(secret))
        # Absolute path that escapes base dir should be rejected
        assert result.startswith("ERROR:")

    def test_returns_error_for_directory(self, dummy_app: Path) -> None:
        result = read_application_code("services")
        assert result.startswith("ERROR:")


# ---------------------------------------------------------------------------
# create_github_pr
# ---------------------------------------------------------------------------


def _make_mock_repo(branch_sha: str = "abc123") -> MagicMock:
    """Build a minimal mock github.Repository."""
    repo = MagicMock()
    repo.default_branch = "main"
    repo.get_branch.return_value.commit.sha = branch_sha

    # Existing file with known SHA
    existing_file = MagicMock()
    existing_file.sha = "file-sha-111"
    repo.get_contents.return_value = existing_file

    # PR returned by create_pull
    pr = MagicMock()
    pr.number = 42
    pr.html_url = "https://github.com/owner/repo/pull/42"
    repo.create_pull.return_value = pr

    return repo


class TestCreateGithubPr:
    def test_returns_error_when_token_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")
        result = create_github_pr("a.py", "code", "msg", "title", "body")
        assert result["success"] is False
        assert "GITHUB_TOKEN" in result["error"]

    def test_returns_error_when_repo_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.delenv("GITHUB_REPO", raising=False)
        result = create_github_pr("a.py", "code", "msg", "title", "body")
        assert result["success"] is False
        assert "GITHUB_REPO" in result["error"]

    @patch("src.git_tools.uuid.uuid4")
    @patch("src.git_tools.Github")
    def test_full_happy_path(
        self,
        MockGithub: MagicMock,
        mock_uuid: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")
        mock_uuid.return_value.hex = "deadbeef12345678"

        repo = _make_mock_repo("sha-abc")
        MockGithub.return_value.get_repo.return_value = repo

        result = create_github_pr(
            filepath="services/orders.py",
            new_code_content="# fixed code",
            commit_message="Fix N+1 query",
            pr_title="Fix N+1 query in orders service",
            pr_body="Root cause: N+1 pattern. This PR batches requests.",
        )

        assert result["success"] is True
        assert result["pr_url"] == "https://github.com/owner/repo/pull/42"
        assert "fix/" in result["branch"]
        assert "deadbeef" in result["branch"]

        # Verify GitHub API call sequence
        MockGithub.assert_called_once_with("tok")
        MockGithub.return_value.get_repo.assert_called_once_with("owner/repo")
        repo.create_git_ref.assert_called_once()
        ref_arg = repo.create_git_ref.call_args.kwargs or repo.create_git_ref.call_args[1]
        # create_git_ref can be called with positional or keyword args
        repo.update_file.assert_called_once()
        repo.create_pull.assert_called_once_with(
            title="Fix N+1 query in orders service",
            body="Root cause: N+1 pattern. This PR batches requests.",
            head=result["branch"],
            base="main",
        )

    @patch("src.git_tools.Github")
    def test_falls_back_to_create_file_when_not_found(
        self,
        MockGithub: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from github import GithubException  # type: ignore[import]

        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")

        repo = _make_mock_repo()
        # Simulate file not existing on the new branch
        repo.get_contents.side_effect = GithubException(404, "Not Found", None)
        MockGithub.return_value.get_repo.return_value = repo

        create_github_pr("new_file.py", "# new", "Add file", "Add new_file", "Body")

        repo.create_file.assert_called_once()
        repo.update_file.assert_not_called()

    @patch("src.git_tools.Github")
    def test_returns_error_on_github_exception(
        self,
        MockGithub: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from github import GithubException  # type: ignore[import]

        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")
        MockGithub.return_value.get_repo.side_effect = GithubException(
            403, "Forbidden", None
        )

        result = create_github_pr("a.py", "code", "msg", "title", "body")
        assert result["success"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# GIT_TOOL_CONFIG schema shape
# ---------------------------------------------------------------------------


class TestGitToolConfig:
    def test_has_tools_list(self) -> None:
        assert "tools" in GIT_TOOL_CONFIG
        assert isinstance(GIT_TOOL_CONFIG["tools"], list)
        assert len(GIT_TOOL_CONFIG["tools"]) == 2

    def test_both_tools_have_toolSpec(self) -> None:
        for entry in GIT_TOOL_CONFIG["tools"]:
            assert "toolSpec" in entry, f"Missing toolSpec in {entry}"

    def test_read_application_code_schema(self) -> None:
        spec = next(
            e["toolSpec"]
            for e in GIT_TOOL_CONFIG["tools"]
            if e["toolSpec"]["name"] == "read_application_code"
        )
        assert "description" in spec
        schema = spec["inputSchema"]["json"]
        assert schema["type"] == "object"
        assert "filepath" in schema["properties"]
        assert "filepath" in schema["required"]

    def test_create_github_pr_schema(self) -> None:
        spec = next(
            e["toolSpec"]
            for e in GIT_TOOL_CONFIG["tools"]
            if e["toolSpec"]["name"] == "create_github_pr"
        )
        required = spec["inputSchema"]["json"]["required"]
        for field in ("filepath", "new_code_content", "commit_message", "pr_title", "pr_body"):
            assert field in required, f"'{field}' missing from required"

    def test_git_tool_names_matches_config(self) -> None:
        config_names = {e["toolSpec"]["name"] for e in GIT_TOOL_CONFIG["tools"]}
        assert config_names == GIT_TOOL_NAMES


# ---------------------------------------------------------------------------
# execute_git_tool dispatcher
# ---------------------------------------------------------------------------


class TestExecuteGitTool:
    def test_routes_read_application_code(self, dummy_app: Path) -> None:
        result = execute_git_tool("read_application_code", {"filepath": "services/orders.py"})
        assert result["success"] is True
        assert "N+1 bug" in result["result"]

    def test_read_returns_failure_on_missing_file(self, dummy_app: Path) -> None:
        result = execute_git_tool("read_application_code", {"filepath": "missing.py"})
        assert result["success"] is False
        assert "error" in result

    @patch("src.git_tools.Github")
    def test_routes_create_github_pr(
        self, MockGithub: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")
        repo = _make_mock_repo()
        MockGithub.return_value.get_repo.return_value = repo

        result = execute_git_tool(
            "create_github_pr",
            {
                "filepath": "services/orders.py",
                "new_code_content": "# fixed",
                "commit_message": "Fix bug",
                "pr_title": "Fix bug",
                "pr_body": "Details here.",
            },
        )
        assert result["success"] is True
        assert "pr_url" in result["result"]

    def test_unknown_tool_returns_failure(self) -> None:
        result = execute_git_tool("does_not_exist", {})
        assert result["success"] is False
        assert "Unknown git tool" in result["error"]
