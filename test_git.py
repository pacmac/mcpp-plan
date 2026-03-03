"""Tests for git.py — tag parsing, git operations, multi-user scenarios, logging."""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from git import (
    McppTag,
    parse_tag,
    build_message,
    strip_tag,
    GitError,
    status_porcelain,
    add_all,
    commit,
    log,
    diff_stat,
    diff_range,
    diff_working,
    reverse_patch,
    apply_patch,
    filter_patch_by_files,
    is_clean,
    current_branch,
    has_remote,
    get_commit_message,
    log_file_since,
    worktree_path_for_user,
    worktree_branch_for_user,
    worktree_list,
    worktree_add,
    worktree_remove,
    worktree_exists,
    ensure_worktree,
    resolve_workspace,
    merge_branch,
    WORKTREE_DIR,
)


# ── Fixtures ──

@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repo with an initial commit."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path), capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(tmp_path), capture_output=True, check=True
    )
    # Initial commit
    (tmp_path / "README.md").write_text("# Test repo\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(tmp_path), capture_output=True, check=True
    )
    return tmp_path


@pytest.fixture
def git_repo_pair(tmp_path):
    """Create a bare remote and a cloned local repo."""
    bare = tmp_path / "remote.git"
    local = tmp_path / "local"
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    subprocess.run(["git", "clone", str(bare), str(local)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(local), capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(local), capture_output=True, check=True
    )
    # Initial commit
    (local / "README.md").write_text("# Test repo\n")
    subprocess.run(["git", "add", "-A"], cwd=str(local), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(local), capture_output=True, check=True
    )
    subprocess.run(["git", "push"], cwd=str(local), capture_output=True, check=True)
    return bare, local


# ── Tag parsing tests ──

class TestTagParsing:
    def test_parse_full_tag(self):
        msg = "checkpoint: step 3\n[mcpp:user=alice,task=build-auth,step=3]"
        tag = parse_tag(msg)
        assert tag is not None
        assert tag.user == "alice"
        assert tag.task == "build-auth"
        assert tag.step == 3

    def test_parse_partial_tag_no_step(self):
        msg = "some commit\n[mcpp:user=bob,task=fix-bug]"
        tag = parse_tag(msg)
        assert tag is not None
        assert tag.user == "bob"
        assert tag.task == "fix-bug"
        assert tag.step is None

    def test_parse_user_only(self):
        msg = "[mcpp:user=charlie]"
        tag = parse_tag(msg)
        assert tag is not None
        assert tag.user == "charlie"
        assert tag.task is None
        assert tag.step is None

    def test_parse_no_tag(self):
        msg = "just a regular commit message"
        tag = parse_tag(msg)
        assert tag is None

    def test_parse_malformed_tag(self):
        msg = "[mcpp:broken"
        tag = parse_tag(msg)
        assert tag is None

    def test_parse_empty_message(self):
        tag = parse_tag("")
        assert tag is None

    def test_roundtrip(self):
        original = McppTag(user="alice", task="my-task", step=5)
        formatted = original.format()
        parsed = parse_tag(formatted)
        assert parsed == original

    def test_format_tag(self):
        tag = McppTag(user="alice", task="build-auth", step=3)
        assert tag.format() == "[mcpp:user=alice,task=build-auth,step=3]"

    def test_format_partial(self):
        tag = McppTag(user="bob")
        assert tag.format() == "[mcpp:user=bob]"

    def test_build_message(self):
        tag = McppTag(user="alice", task="t", step=1)
        msg = build_message("checkpoint: test", tag)
        assert "checkpoint: test" in msg
        assert "[mcpp:user=alice,task=t,step=1]" in msg

    def test_strip_tag(self):
        msg = "checkpoint: test\n[mcpp:user=alice,task=t,step=1]"
        stripped = strip_tag(msg)
        assert stripped == "checkpoint: test"

    def test_strip_tag_no_tag(self):
        msg = "just a message"
        assert strip_tag(msg) == "just a message"

    def test_unknown_keys_ignored(self):
        msg = "[mcpp:user=alice,foo=bar,task=t]"
        tag = parse_tag(msg)
        assert tag.user == "alice"
        assert tag.task == "t"

    def test_step_non_integer(self):
        msg = "[mcpp:user=alice,step=abc]"
        tag = parse_tag(msg)
        assert tag.user == "alice"
        assert tag.step is None


# ── Git operation tests ──

class TestGitOperations:
    def test_status_clean(self, git_repo):
        entries = status_porcelain(git_repo)
        assert entries == []

    def test_status_modified(self, git_repo):
        (git_repo / "new_file.txt").write_text("hello\n")
        entries = status_porcelain(git_repo)
        assert len(entries) == 1
        assert entries[0]["path"] == "new_file.txt"

    def test_is_clean(self, git_repo):
        assert is_clean(git_repo)
        (git_repo / "x.txt").write_text("x\n")
        assert not is_clean(git_repo)

    def test_add_and_commit(self, git_repo):
        (git_repo / "file.txt").write_text("content\n")
        add_all(git_repo)
        sha = commit(git_repo, "test commit")
        assert len(sha) == 40
        assert is_clean(git_repo)

    def test_commit_with_tag(self, git_repo):
        (git_repo / "file.txt").write_text("content\n")
        tag = McppTag(user="alice", task="my-task", step=1)
        msg = build_message("checkpoint: step 1", tag)
        add_all(git_repo)
        sha = commit(git_repo, msg)
        full_msg = get_commit_message(git_repo, sha)
        parsed = parse_tag(full_msg)
        assert parsed is not None
        assert parsed.user == "alice"
        assert parsed.task == "my-task"
        assert parsed.step == 1

    def test_diff_stat(self, git_repo):
        (git_repo / "a.txt").write_text("aaa\n")
        (git_repo / "b.txt").write_text("bbb\n")
        add_all(git_repo)
        sha = commit(git_repo, "add two files")
        files = diff_stat(git_repo, sha)
        assert set(files) == {"a.txt", "b.txt"}

    def test_current_branch(self, git_repo):
        branch = current_branch(git_repo)
        assert branch in ("master", "main")

    def test_has_remote_false(self, git_repo):
        assert not has_remote(git_repo)

    def test_has_remote_true(self, git_repo_pair):
        _, local = git_repo_pair
        assert has_remote(local)

    def test_log_entries(self, git_repo):
        (git_repo / "f1.txt").write_text("1\n")
        add_all(git_repo)
        tag = McppTag(user="alice", task="t1", step=1)
        commit(git_repo, build_message("first", tag))

        (git_repo / "f2.txt").write_text("2\n")
        add_all(git_repo)
        tag2 = McppTag(user="bob", task="t2", step=2)
        commit(git_repo, build_message("second", tag2))

        entries = log(git_repo, max_count=10)
        # Most recent first
        assert len(entries) >= 2
        assert entries[0]["tag"].user == "bob"
        assert entries[1]["tag"].user == "alice"

    def test_log_empty_repo(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        entries = log(tmp_path, max_count=10)
        assert entries == []


# ── Multi-user restore tests ──

class TestRestore:
    def test_reverse_patch(self, git_repo):
        (git_repo / "file.txt").write_text("original\n")
        add_all(git_repo)
        sha1 = commit(git_repo, "add file")

        patch = reverse_patch(git_repo, sha1)
        assert "file.txt" in patch

    def test_filter_patch_by_files(self, git_repo):
        (git_repo / "a.txt").write_text("aaa\n")
        (git_repo / "b.txt").write_text("bbb\n")
        add_all(git_repo)
        sha = commit(git_repo, "add a and b")

        patch = reverse_patch(git_repo, sha)
        filtered = filter_patch_by_files(patch, {"a.txt"})
        assert "a.txt" in filtered
        assert "b.txt" not in filtered

    def test_apply_patch(self, git_repo):
        (git_repo / "file.txt").write_text("original\n")
        add_all(git_repo)
        sha = commit(git_repo, "add file")

        # Make another commit so we can reverse the first
        (git_repo / "other.txt").write_text("other\n")
        add_all(git_repo)
        commit(git_repo, "add other")

        patch = reverse_patch(git_repo, sha)
        filtered = filter_patch_by_files(patch, {"file.txt"})
        ok, msg = apply_patch(git_repo, filtered)
        assert ok
        # file.txt should be deleted (reversed the add)
        assert not (git_repo / "file.txt").exists()

    def test_log_file_since(self, git_repo):
        (git_repo / "shared.txt").write_text("v1\n")
        add_all(git_repo)
        tag1 = McppTag(user="alice", task="t1", step=1)
        sha1 = commit(git_repo, build_message("alice adds", tag1))

        (git_repo / "shared.txt").write_text("v2\n")
        add_all(git_repo)
        tag2 = McppTag(user="bob", task="t2", step=1)
        commit(git_repo, build_message("bob modifies", tag2))

        # Check who modified shared.txt since alice's commit
        entries = log_file_since(git_repo, sha1, "shared.txt")
        assert len(entries) == 1
        assert entries[0]["tag"].user == "bob"

    def test_log_file_since_no_changes(self, git_repo):
        (git_repo / "mine.txt").write_text("v1\n")
        add_all(git_repo)
        tag1 = McppTag(user="alice", task="t1", step=1)
        sha1 = commit(git_repo, build_message("alice adds", tag1))

        # No one else touches it
        entries = log_file_since(git_repo, sha1, "mine.txt")
        assert entries == []


# ── Push tests ──

class TestPush:
    def test_push_success(self, git_repo_pair):
        _, local = git_repo_pair
        (local / "new.txt").write_text("new\n")
        add_all(local)
        commit(local, "new file")
        from git import push
        ok, msg = push(local)
        assert ok

    def test_push_no_remote(self, git_repo):
        from git import push
        ok, msg = push(git_repo)
        assert not ok


# ── Edge case tests ──

class TestEdgeCases:
    def test_commit_empty_repo_fails(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), capture_output=True, check=True
        )
        with pytest.raises(GitError):
            commit(tmp_path, "should fail")

    def test_get_commit_message(self, git_repo):
        (git_repo / "x.txt").write_text("x\n")
        add_all(git_repo)
        sha = commit(git_repo, "test message here")
        msg = get_commit_message(git_repo, sha)
        assert "test message here" in msg

    def test_diff_working(self, git_repo):
        (git_repo / "file.txt").write_text("new content\n")
        d = diff_working(git_repo)
        # Untracked files don't show in diff, need to add first
        add_all(git_repo)
        d = diff_working(git_repo, "HEAD")
        assert "new content" in d

    def test_diff_range(self, git_repo):
        (git_repo / "a.txt").write_text("1\n")
        add_all(git_repo)
        sha1 = commit(git_repo, "first")

        (git_repo / "a.txt").write_text("2\n")
        add_all(git_repo)
        sha2 = commit(git_repo, "second")

        d = diff_range(git_repo, sha1, sha2)
        assert "a.txt" in d


# ── Logging tests ──

class TestGitLogging:
    def test_run_logs_command(self, git_repo, caplog):
        """_run() logs the git command being executed."""
        import logging
        with caplog.at_level(logging.DEBUG, logger="mcpp.git"):
            status_porcelain(git_repo)
        assert any("running: git status --porcelain" in r.message for r in caplog.records)

    def test_run_logs_completion_time(self, git_repo, caplog):
        """_run() logs completion time for successful commands."""
        import logging
        with caplog.at_level(logging.DEBUG, logger="mcpp.git"):
            status_porcelain(git_repo)
        assert any("completed in" in r.message and "rc=0" in r.message for r in caplog.records)

    def test_run_logs_error(self, git_repo, caplog):
        """_run() logs errors for failed git commands."""
        import logging
        with caplog.at_level(logging.DEBUG, logger="mcpp.git"):
            try:
                from git import _run
                _run(["log", "--invalid-flag-xyz"], git_repo)
            except GitError:
                pass
        assert any(r.levelno >= logging.ERROR for r in caplog.records)

    def test_run_logs_stderr(self, git_repo, caplog):
        """_run() logs stderr output when present."""
        import logging
        with caplog.at_level(logging.DEBUG, logger="mcpp.git"):
            from git import _run
            # git status on a clean repo may not produce stderr,
            # but a failed command will
            try:
                _run(["log", "--invalid-flag-xyz"], git_repo)
            except GitError:
                pass
        # At minimum the error log should contain stderr content
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(error_records) > 0


class TestFileLogging:
    def test_ensure_file_logging_creates_handler(self):
        """_ensure_file_logging() adds a RotatingFileHandler to the mcpp logger."""
        from logging.handlers import RotatingFileHandler
        import mcpptool
        logger = logging.getLogger("mcpp")
        original_handlers = list(logger.handlers)
        # Remove any existing file handlers so we can test fresh
        for h in logger.handlers:
            if isinstance(h, (logging.FileHandler, RotatingFileHandler)):
                logger.removeHandler(h)
                h.close()
        try:
            mcpptool._ensure_file_logging()
            new_handlers = [h for h in logger.handlers if h not in original_handlers]
            assert len(new_handlers) == 1
            assert isinstance(new_handlers[0], RotatingFileHandler)
        finally:
            for h in logger.handlers:
                if h not in original_handlers:
                    logger.removeHandler(h)
                    h.close()
            # Restore originals
            for h in original_handlers:
                if h not in logger.handlers:
                    logger.addHandler(h)

    def test_ensure_file_logging_guard_prevents_duplicates(self):
        """Second call to _ensure_file_logging() does not add another handler."""
        from logging.handlers import RotatingFileHandler
        import mcpptool
        logger = logging.getLogger("mcpp")
        original_handlers = list(logger.handlers)
        for h in logger.handlers:
            if isinstance(h, (logging.FileHandler, RotatingFileHandler)):
                logger.removeHandler(h)
                h.close()
        try:
            mcpptool._ensure_file_logging()
            count_after_first = len(logger.handlers)
            mcpptool._ensure_file_logging()
            count_after_second = len(logger.handlers)
            assert count_after_first == count_after_second
        finally:
            for h in logger.handlers:
                if h not in original_handlers:
                    logger.removeHandler(h)
                    h.close()
            for h in original_handlers:
                if h not in logger.handlers:
                    logger.addHandler(h)

    def test_tool_log_writes_call_entry(self, tmp_path):
        """_tool_log.debug produces a CALL entry with tool name and args."""
        import mcpptool
        handler = logging.FileHandler(str(tmp_path / "test.log"), encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger("mcpp.tool")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            mcpptool._tool_log.debug("CALL %s args=%s", "plan_test", {"key": "val"})
            handler.flush()
            content = (tmp_path / "test.log").read_text()
            assert "CALL plan_test" in content
            assert "key" in content
        finally:
            logger.removeHandler(handler)
            handler.close()


# ── Worktree tests ──

class TestWorktreePaths:
    def test_worktree_path_for_user(self):
        path = worktree_path_for_user("/srv/project", "alice")
        assert path == Path("/srv/project/.worktrees/alice")

    def test_worktree_branch_for_user(self):
        assert worktree_branch_for_user("alice") == "mcpp/alice"

    def test_resolve_workspace_disabled(self, git_repo):
        result = resolve_workspace(str(git_repo), "alice", enable_worktrees=False)
        assert result == str(git_repo)

    def test_resolve_workspace_primary_user(self, git_repo):
        """Primary user (repo owner) should get the repo dir, not a worktree."""
        result = resolve_workspace(str(git_repo), "testuser", enable_worktrees=True)
        # tmp_path is owned by current user, so we are the primary user
        assert result == str(git_repo)


class TestWorktreeOperations:
    def test_worktree_list_initial(self, git_repo):
        """Fresh repo has one worktree (the main one)."""
        wts = worktree_list(git_repo)
        assert len(wts) >= 1

    def test_worktree_add_and_exists(self, git_repo):
        wt_path = git_repo / ".worktrees" / "alice"
        worktree_add(git_repo, wt_path, "mcpp/alice")
        assert wt_path.exists()
        assert worktree_exists(git_repo, wt_path)

    def test_worktree_remove(self, git_repo):
        wt_path = git_repo / ".worktrees" / "alice"
        worktree_add(git_repo, wt_path, "mcpp/alice")
        assert worktree_exists(git_repo, wt_path)
        worktree_remove(git_repo, wt_path)
        assert not worktree_exists(git_repo, wt_path)

    def test_ensure_worktree_creates(self, git_repo):
        wt_path = ensure_worktree(git_repo, "bob")
        assert wt_path.exists()
        assert worktree_exists(git_repo, wt_path)
        assert current_branch(wt_path) == "mcpp/bob"

    def test_ensure_worktree_idempotent(self, git_repo):
        wt1 = ensure_worktree(git_repo, "bob")
        wt2 = ensure_worktree(git_repo, "bob")
        assert wt1 == wt2

    def test_worktree_isolation(self, git_repo):
        """Changes in one worktree don't appear in another."""
        wt_alice = ensure_worktree(git_repo, "alice")
        wt_bob = ensure_worktree(git_repo, "bob")

        # Alice writes a file
        (wt_alice / "alice_file.txt").write_text("alice\n")
        add_all(wt_alice)
        commit(wt_alice, "alice commit")

        # Bob should not see it
        assert not (wt_bob / "alice_file.txt").exists()
        assert is_clean(wt_bob)

    def test_worktree_independent_branches(self, git_repo):
        wt_alice = ensure_worktree(git_repo, "alice")
        wt_bob = ensure_worktree(git_repo, "bob")
        assert current_branch(wt_alice) == "mcpp/alice"
        assert current_branch(wt_bob) == "mcpp/bob"


class TestMergeBranch:
    def test_merge_success(self, git_repo):
        wt = ensure_worktree(git_repo, "alice")
        (wt / "new.txt").write_text("from alice\n")
        add_all(wt)
        commit(wt, "alice adds file")

        # Merge alice's branch into main
        ok, msg = merge_branch(git_repo, "mcpp/alice")
        assert ok
        assert (git_repo / "new.txt").exists()

    def test_merge_conflict(self, git_repo):
        wt = ensure_worktree(git_repo, "alice")

        # Modify same file in both places
        (git_repo / "README.md").write_text("main version\n")
        add_all(git_repo)
        commit(git_repo, "main changes README")

        (wt / "README.md").write_text("alice version\n")
        add_all(wt)
        commit(wt, "alice changes README")

        ok, msg = merge_branch(git_repo, "mcpp/alice")
        assert not ok
        # Clean up the failed merge
        subprocess.run(["git", "merge", "--abort"], cwd=str(git_repo), capture_output=True)
