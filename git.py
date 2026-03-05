"""Git operations for mcpp-plan.

Wraps git subprocess calls with user/task/step awareness.
Commit messages contain a structured tag that associates commits
with mcpp-plan users, tasks, and steps.

No database imports — pure git operations.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ── Tag format ──
# Embedded in commit messages as the last line:
#   [mcpp:user=alice,task=build-auth,step=3]

TAG_PREFIX = "[mcpp:"
TAG_PATTERN = re.compile(
    r"\[mcpp:"
    r"(?P<pairs>[^\]]+)"
    r"\]"
)

KNOWN_KEYS = {"user", "task", "step"}


@dataclass(frozen=True)
class McppTag:
    user: Optional[str] = None
    task: Optional[str] = None
    step: Optional[int] = None

    def format(self) -> str:
        parts = []
        if self.user is not None:
            parts.append(f"user={self.user}")
        if self.task is not None:
            parts.append(f"task={self.task}")
        if self.step is not None:
            parts.append(f"step={self.step}")
        return f"[mcpp:{','.join(parts)}]"


# ── Per-file metadata ──
# Pipe-delimited lines in commit body, one per changed file:
#   name|ver|uid|flags|notes
# ver and flags are empty until mcpp-dev fills them.

FILE_LINE_PATTERN = re.compile(
    r"^(?P<name>[^|]+)\|(?P<ver>[^|]*)\|(?P<uid>[^|]*)\|(?P<flags>[^|]*)\|(?P<notes>.*)$"
)


@dataclass(frozen=True)
class FileEntry:
    name: str
    ver: str = ""
    uid: str = ""
    flags: str = ""
    notes: str = ""

    def format(self) -> str:
        return f"{self.name}|{self.ver}|{self.uid}|{self.flags}|{self.notes}"


def parse_tag(message: str) -> Optional[McppTag]:
    """Extract an McppTag from a commit message, or None if not present."""
    m = TAG_PATTERN.search(message)
    if not m:
        return None
    pairs_str = m.group("pairs")
    kv: dict[str, str] = {}
    for part in pairs_str.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip()
        value = value.strip()
        if key in KNOWN_KEYS:
            kv[key] = value
    step_val = None
    if "step" in kv:
        try:
            step_val = int(kv["step"])
        except ValueError:
            pass
    return McppTag(
        user=kv.get("user"),
        task=kv.get("task"),
        step=step_val,
    )


def parse_file_lines(message: str) -> list[FileEntry]:
    """Extract per-file metadata lines from a commit message body."""
    entries = []
    for line in message.splitlines():
        m = FILE_LINE_PATTERN.match(line.strip())
        if m:
            entries.append(FileEntry(
                name=m.group("name"),
                ver=m.group("ver"),
                uid=m.group("uid"),
                flags=m.group("flags"),
                notes=m.group("notes"),
            ))
    return entries


def build_message(message: str, tag: McppTag, file_entries: Optional[list[FileEntry]] = None) -> str:
    """Build a commit message with optional per-file lines and the mcpp tag appended."""
    parts = [message]
    if file_entries:
        parts.append("")  # blank line before file lines
        for entry in file_entries:
            parts.append(entry.format())
    parts.append(tag.format())
    return "\n".join(parts)


def strip_tag(message: str) -> str:
    """Remove the mcpp tag line and file metadata lines from a commit message."""
    lines = []
    for line in message.splitlines():
        if TAG_PATTERN.search(line):
            continue
        if FILE_LINE_PATTERN.match(line.strip()):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


# ── Git subprocess helpers ──

class GitError(Exception):
    """Raised when a git command fails."""
    def __init__(self, message: str, returncode: int = 1, stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


_log = logging.getLogger("mcpp.git")


def _run(args: list[str], cwd: str | Path, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd_str = f"git {' '.join(args)}"
    _log.debug("running: %s", cmd_str)
    t0 = time.monotonic()
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=30,
    )
    elapsed = time.monotonic() - t0
    if elapsed > 2:
        _log.warning("%s took %.1fs", cmd_str, elapsed)
    else:
        _log.debug("%s completed in %.1fs (rc=%d)", cmd_str, elapsed, result.returncode)
    if result.stderr.strip():
        _log.debug("%s stderr: %s", cmd_str, result.stderr.strip())
    if check and result.returncode != 0:
        _log.error("%s failed (rc=%d): %s", cmd_str, result.returncode, result.stderr.strip())
        raise GitError(
            f"git {' '.join(args)} failed: {result.stderr.strip()}",
            returncode=result.returncode,
            stderr=result.stderr.strip(),
        )
    return result


def status_porcelain(cwd: str | Path) -> list[dict]:
    """Return list of {status, path} from git status --porcelain."""
    result = _run(["status", "--porcelain"], cwd)
    entries = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        status_code = line[:2].strip()
        filepath = line[3:]
        entries.append({"status": status_code, "path": filepath})
    return entries


def add_all(cwd: str | Path) -> None:
    """Stage all modified, new, and deleted files.

    .worktrees/ is excluded via .git/info/exclude (set by ensure_worktree).
    """
    _run(["add", "-A"], cwd)


def commit(cwd: str | Path, message: str) -> str:
    """Create a commit and return the SHA."""
    _run(["commit", "-m", message], cwd)
    result = _run(["rev-parse", "HEAD"], cwd)
    return result.stdout.strip()


def log(
    cwd: str | Path,
    max_count: int = 50,
    format_str: str = "%H%n%an%n%ai%n%s%n%b%n---END---",
) -> list[dict]:
    """Return parsed git log entries.

    Each entry: {sha, author, date, subject, body, tag, file_entries}
    """
    result = _run(
        ["log", f"--max-count={max_count}", f"--format={format_str}"],
        cwd,
        check=False,
    )
    if result.returncode != 0:
        return []

    entries = []
    raw_entries = result.stdout.split("---END---\n")
    for raw in raw_entries:
        raw = raw.strip()
        if not raw:
            continue
        lines = raw.split("\n", 4)
        if len(lines) < 4:
            continue
        sha = lines[0]
        author = lines[1]
        date = lines[2]
        subject = lines[3]
        body = lines[4] if len(lines) > 4 else ""
        full_message = f"{subject}\n{body}".strip()
        tag = parse_tag(full_message)
        file_entries = parse_file_lines(full_message)
        entries.append({
            "sha": sha,
            "author": author,
            "date": date,
            "subject": subject,
            "body": body.strip(),
            "tag": tag,
            "file_entries": file_entries,
        })
    return entries


def diff_stat(cwd: str | Path, sha: str) -> list[str]:
    """Return list of files changed in a specific commit."""
    result = _run(["diff-tree", "--no-commit-id", "-r", "--name-only", sha], cwd)
    return [f for f in result.stdout.splitlines() if f.strip()]


def diff_range(cwd: str | Path, from_ref: str, to_ref: str = "HEAD") -> str:
    """Return diff between two refs."""
    result = _run(["diff", from_ref, to_ref], cwd)
    return result.stdout


def diff_working(cwd: str | Path, from_ref: str = "HEAD") -> str:
    """Return diff from a ref to the working tree (staged + unstaged)."""
    result = _run(["diff", from_ref], cwd)
    return result.stdout


def show_commit_diff(cwd: str | Path, sha: str) -> str:
    """Return the patch for a specific commit."""
    result = _run(["show", "--format=", "--patch", sha], cwd)
    return result.stdout


def log_file_since(cwd: str | Path, sha: str, filepath: str) -> list[dict]:
    """Return commits that touched a file since a given SHA (exclusive)."""
    result = _run(
        ["log", f"{sha}..HEAD", "--format=%H%n%an%n%s%n%b%n---END---", "--", filepath],
        cwd,
        check=False,
    )
    if result.returncode != 0:
        return []
    entries = []
    for raw in result.stdout.split("---END---\n"):
        raw = raw.strip()
        if not raw:
            continue
        lines = raw.split("\n", 3)
        if len(lines) < 3:
            continue
        sha_val = lines[0]
        author = lines[1]
        subject = lines[2]
        body = lines[3] if len(lines) > 3 else ""
        full_message = f"{subject}\n{body}".strip()
        tag = parse_tag(full_message)
        entries.append({
            "sha": sha_val,
            "author": author,
            "subject": subject,
            "tag": tag,
        })
    return entries


def pull_ff_only(cwd: str | Path) -> tuple[bool, str]:
    """Pull with --ff-only. Returns (success, message)."""
    result = _run(["pull", "--ff-only"], cwd, check=False)
    if result.returncode == 0:
        return True, result.stdout.strip() or "Already up to date."
    return False, result.stderr.strip()


def push(cwd: str | Path) -> tuple[bool, str]:
    """Push to remote. Sets upstream tracking on first push. Returns (success, message)."""
    result = _run(["push"], cwd, check=False)
    if result.returncode == 0:
        return True, result.stderr.strip() or "Pushed successfully."
    # If push failed because no upstream is set, try with -u
    if "no upstream" in result.stderr.lower() or "has no upstream" in result.stderr.lower():
        branch = current_branch(cwd)
        result = _run(["push", "-u", "origin", branch], cwd, check=False)
        if result.returncode == 0:
            return True, result.stderr.strip() or f"Pushed {branch} (upstream set)."
    return False, result.stderr.strip()


def has_remote(cwd: str | Path) -> bool:
    """Check if the repo has a remote configured."""
    result = _run(["remote"], cwd, check=False)
    return bool(result.stdout.strip())


def current_branch(cwd: str | Path) -> str:
    """Return the current branch name."""
    result = _run(["branch", "--show-current"], cwd)
    return result.stdout.strip()


def is_clean(cwd: str | Path) -> bool:
    """Return True if the working tree is clean."""
    return len(status_porcelain(cwd)) == 0


def get_commit_message(cwd: str | Path, sha: str) -> str:
    """Return the full commit message for a SHA."""
    result = _run(["log", "-1", "--format=%B", sha], cwd)
    return result.stdout.strip()


def reverse_patch(cwd: str | Path, sha: str) -> str:
    """Generate a reverse patch for a commit."""
    result = _run(["diff", sha, f"{sha}~1"], cwd)
    return result.stdout


def apply_patch(cwd: str | Path, patch: str) -> tuple[bool, str]:
    """Apply a patch to the working tree. Returns (success, message)."""
    result = subprocess.run(
        ["git", "apply", "--check", "-"],
        cwd=str(cwd),
        input=patch,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    # Apply for real
    result = subprocess.run(
        ["git", "apply", "-"],
        cwd=str(cwd),
        input=patch,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, "Patch applied."


# ── Worktree management ──

WORKTREE_DIR = ".worktrees"


def worktree_path_for_user(repo_dir: str | Path, username: str) -> Path:
    """Return the deterministic worktree path for a user."""
    return Path(repo_dir) / WORKTREE_DIR / username


def worktree_branch_for_user(username: str) -> str:
    """Return the branch name for a user's worktree."""
    return f"mcpp/{username}"


def worktree_list(repo_dir: str | Path) -> list[dict]:
    """Return list of worktrees: {path, branch, head}."""
    result = _run(["worktree", "list", "--porcelain"], repo_dir)
    worktrees = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[len("worktree "):]
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]
        elif line == "bare":
            current["bare"] = True
    if current:
        worktrees.append(current)
    return worktrees


def branch_exists(repo_dir: str | Path, branch: str) -> bool:
    """Check if a local branch exists."""
    result = _run(["branch", "--list", branch], repo_dir, check=False)
    return bool(result.stdout.strip())


def worktree_add(repo_dir: str | Path, path: str | Path, branch: str) -> None:
    """Create a new worktree. Uses existing branch if it exists, otherwise creates one."""
    if branch_exists(repo_dir, branch):
        _run(["worktree", "add", str(path), branch], repo_dir)
    else:
        _run(["worktree", "add", "-b", branch, str(path)], repo_dir)


def merge_branch(cwd: str | Path, branch: str) -> tuple[bool, str]:
    """Merge a branch into the current branch. Returns (success, message)."""
    result = _run(["merge", branch, "--no-edit"], cwd, check=False)
    if result.returncode == 0:
        return True, result.stdout.strip() or "Merge successful."
    return False, result.stderr.strip() or result.stdout.strip()


def worktree_remove(repo_dir: str | Path, path: str | Path) -> None:
    """Remove a worktree."""
    _run(["worktree", "remove", str(path), "--force"], repo_dir)


def worktree_exists(repo_dir: str | Path, path: str | Path) -> bool:
    """Check if a worktree exists at the given path."""
    for wt in worktree_list(repo_dir):
        if wt.get("path") == str(Path(path).resolve()):
            return True
    return False


def ensure_worktree(repo_dir: str | Path, username: str) -> Path:
    """Ensure a worktree exists for a user, creating it if needed. Returns the worktree path."""
    wt_path = worktree_path_for_user(repo_dir, username)
    if worktree_exists(repo_dir, wt_path):
        return wt_path
    branch = worktree_branch_for_user(username)
    # Handle stale directory: exists on disk but not registered in git
    if wt_path.exists():
        _log.warning("Stale worktree directory at %s — removing before recreation", wt_path)
        shutil.rmtree(wt_path)
    # Prune any stale worktree references in git
    _run(["worktree", "prune"], repo_dir)
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        worktree_add(repo_dir, wt_path, branch)
    except GitError:
        # Clean up partial state on failure
        if wt_path.exists():
            shutil.rmtree(wt_path)
        raise
    _ensure_git_exclude(repo_dir)
    _log.info("Created worktree for user %s at %s (branch %s)", username, wt_path, branch)
    return wt_path


def _ensure_git_exclude(repo_dir: str | Path) -> None:
    """Ensure .worktrees is listed in .git/info/exclude."""
    exclude_path = Path(repo_dir) / ".git" / "info" / "exclude"
    entry = ".worktrees"
    try:
        if exclude_path.exists():
            content = exclude_path.read_text()
            if entry in content.splitlines():
                return
            exclude_path.write_text(content.rstrip("\n") + "\n" + entry + "\n")
        else:
            exclude_path.parent.mkdir(parents=True, exist_ok=True)
            exclude_path.write_text(entry + "\n")
    except OSError as e:
        _log.warning("Could not update .git/info/exclude: %s", e)


def resolve_workspace(repo_dir: str | Path, username: str, enable_worktrees: bool) -> str:
    """Resolve the working directory for git operations.

    If worktrees are disabled, returns repo_dir.
    Otherwise ensures a worktree exists for this user and returns its path.
    Main branch stays clean — only updated via plan_sync.
    """
    if not enable_worktrees:
        return str(repo_dir)
    wt_path = ensure_worktree(repo_dir, username)
    return str(wt_path)


def filter_patch_by_files(patch: str, keep_files: set[str]) -> str:
    """Filter a unified diff to only include hunks for specified files."""
    lines = patch.split("\n")
    result_lines = []
    include = False
    for line in lines:
        if line.startswith("diff --git"):
            # Extract file path: diff --git a/path b/path
            parts = line.split()
            if len(parts) >= 4:
                filepath = parts[3].lstrip("b/")
                include = filepath in keep_files
            else:
                include = False
        if include:
            result_lines.append(line)
    return "\n".join(result_lines)
