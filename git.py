"""Git operations for mcpp-plan.

Wraps git subprocess calls with user/task/step awareness.
Commit messages contain a structured tag that associates commits
with mcpp-plan users, tasks, and steps.

No database imports — pure git operations.
"""

from __future__ import annotations

import logging
import re
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


def build_message(message: str, tag: McppTag) -> str:
    """Build a commit message with the mcpp tag appended."""
    return f"{message}\n{tag.format()}"


def strip_tag(message: str) -> str:
    """Remove the mcpp tag line from a commit message."""
    return TAG_PATTERN.sub("", message).rstrip("\n")


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
    """Stage all modified, new, and deleted files."""
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

    Each entry: {sha, author, date, subject, body, tag}
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
        entries.append({
            "sha": sha,
            "author": author,
            "date": date,
            "subject": subject,
            "body": body.strip(),
            "tag": tag,
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
    """Push to remote. Returns (success, message)."""
    result = _run(["push"], cwd, check=False)
    if result.returncode == 0:
        return True, result.stderr.strip() or "Pushed successfully."
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
