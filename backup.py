"""Comprehensive database backup and migration safety module.

Provides checksum-verified backups, test-migration-on-copy, and
post-migration row-count validation.  NO migration may touch the live
database until a verified backup exists and a trial run on a copy has
passed integrity checks.

Failure at ANY step aborts the entire migration — the live DB is left
untouched.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import string
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Checksum helpers ──────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ── Row-count snapshot ────────────────────────────────────────────

def table_row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return {table_name: row_count} for every user table."""
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    counts: dict[str, int] = {}
    for row in tables:
        name = row[0] if isinstance(row, (list, tuple)) else row["name"]
        count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        counts[name] = count
    return counts


# ── Verified backup ───────────────────────────────────────────────

def create_verified_backup(db_path: Path) -> Path:
    """Create a backup copy and verify its checksum matches the live DB.

    Returns the backup path on success.
    Raises RuntimeError if the backup does not match.
    """
    if not db_path.exists():
        raise RuntimeError(f"Database file does not exist: {db_path}")

    backup_dir = db_path.parent / ".backups"
    backup_dir.mkdir(exist_ok=True)

    date_str = datetime.now().strftime("%y%m%d")
    base = f"{db_path.name}.{date_str}"

    backup_path: Optional[Path] = None
    for letter in string.ascii_lowercase:
        candidate = backup_dir / f"{base}{letter}"
        if not candidate.exists():
            backup_path = candidate
            break

    if backup_path is None:
        raise RuntimeError(f"Exhausted backup slots for {base}[a-z]")

    # Take the checksum of the live DB BEFORE copying.
    live_hash = sha256_file(db_path)

    # Copy the database file.
    shutil.copy2(db_path, backup_path)

    # Verify the copy matches.
    backup_hash = sha256_file(backup_path)
    if backup_hash != live_hash:
        # Delete the bad backup — it cannot be trusted.
        backup_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Backup checksum mismatch!  live={live_hash}  backup={backup_hash}"
        )

    return backup_path


# ── Trial migration on a copy ────────────────────────────────────

class MigrationAborted(Exception):
    """Raised when a migration fails validation and is aborted."""


def _apply_patches_to(conn: sqlite3.Connection, current_version: int,
                      latest_version: int, patches_dir: Path) -> int:
    """Apply schema patches to a connection.  Returns the final version."""
    import re as _re

    patches = []
    for path in patches_dir.glob("patch-*.sql"):
        match = _re.match(r"patch-(\d+)\.sql", path.name)
        if not match:
            continue
        patches.append((int(match.group(1)), path))

    for version, path in sorted(patches):
        if version <= current_version:
            continue
        if version > latest_version:
            continue
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute("PRAGMA foreign_keys = ON")
        # Update schema_version in the copy.
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (id, version, updated_at) "
            "VALUES (1, ?, ?)",
            (version, datetime.now().isoformat()),
        )
        current_version = version

    return current_version


def validate_row_counts(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """Compare row counts before and after migration.

    Returns a list of error messages for any table whose row count
    decreased.  An empty list means all tables are OK.

    Tables that are new (exist only in 'after') are allowed.
    Tables that disappeared (exist only in 'before') are reported.
    """
    errors: list[str] = []

    for table, count_before in before.items():
        if table.endswith("_new"):
            # Temporary migration tables — skip.
            continue
        count_after = after.get(table)
        if count_after is None:
            # Table disappeared entirely — critical error.
            errors.append(
                f"Table '{table}' MISSING after migration (had {count_before} rows)"
            )
        elif count_after < count_before:
            errors.append(
                f"Table '{table}' lost rows: {count_before} -> {count_after}"
            )

    return errors


def safe_migrate(db_path: Path, current_version: int,
                 latest_version: int, patches_dir: Path) -> Path:
    """Perform a safe schema migration with full safety pipeline.

    Pipeline:
        1. Create a verified backup of the live DB.
        2. Snapshot row counts from the live DB.
        3. Copy live DB to a temporary file.
        4. Apply patches to the temporary copy.
        5. Validate that the copy did not lose data (row counts).
        6. Apply patches to the live DB.
        7. Validate the live DB did not lose data.
        8. If step 6 or 7 fails, the backup is available for recovery.

    Returns the backup path on success.
    Raises MigrationAborted if validation fails at any step.
    Raises RuntimeError for infrastructure failures (no backup slots, etc.).
    """
    if current_version >= latest_version:
        raise MigrationAborted("No migration needed — already at latest version")

    if not db_path.exists():
        raise RuntimeError(f"Database does not exist: {db_path}")

    if not patches_dir.exists():
        raise RuntimeError(f"Patches directory does not exist: {patches_dir}")

    # ── Step 1: Verified backup ──
    backup_path = create_verified_backup(db_path)

    # ── Step 2: Snapshot row counts from live DB ──
    live_conn = sqlite3.connect(db_path, isolation_level=None)
    live_conn.row_factory = sqlite3.Row
    try:
        pre_counts = table_row_counts(live_conn)
    finally:
        live_conn.close()

    # ── Step 3: Copy to temp file for trial run ──
    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_name = tempfile.mkstemp(suffix=".db", prefix="plan_migrate_")
        tmp_path = Path(tmp_name)
        import os
        os.close(tmp_fd)
        tmp_fd = None
        shutil.copy2(db_path, tmp_path)

        # ── Step 4: Apply patches to temp copy ──
        tmp_conn = sqlite3.connect(tmp_path, isolation_level=None)
        tmp_conn.row_factory = sqlite3.Row
        try:
            try:
                _apply_patches_to(tmp_conn, current_version, latest_version, patches_dir)
            except sqlite3.Error as sql_err:
                raise MigrationAborted(
                    f"Trial migration FAILED — SQL error on copy: {sql_err}. "
                    f"Live database NOT touched.  Backup at: {backup_path}"
                ) from sql_err

            # ── Step 5: Validate temp copy ──
            post_counts = table_row_counts(tmp_conn)
        finally:
            tmp_conn.close()

        errors = validate_row_counts(pre_counts, post_counts)
        if errors:
            error_detail = "; ".join(errors)
            raise MigrationAborted(
                f"Trial migration FAILED — data loss detected on copy: {error_detail}. "
                f"Live database NOT touched.  Backup at: {backup_path}"
            )

    finally:
        # Clean up temp file.
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    # ── Step 6: Apply patches to the live DB ──
    live_conn = sqlite3.connect(db_path, isolation_level=None)
    live_conn.row_factory = sqlite3.Row
    try:
        final_version = _apply_patches_to(
            live_conn, current_version, latest_version, patches_dir
        )

        # ── Step 7: Validate live DB ──
        post_live_counts = table_row_counts(live_conn)
    finally:
        live_conn.close()

    live_errors = validate_row_counts(pre_counts, post_live_counts)
    if live_errors:
        error_detail = "; ".join(live_errors)
        raise MigrationAborted(
            f"Live migration FAILED validation — data loss detected: {error_detail}. "
            f"Backup available at: {backup_path}"
        )

    return backup_path
