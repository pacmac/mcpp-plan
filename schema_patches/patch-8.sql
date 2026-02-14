-- Patch 8: Normalise user names to lowercase, merge duplicates.

-- Reassign contexts owned by uppercase duplicates to the lowercase original.
UPDATE contexts
SET user_id = (
    SELECT MIN(u2.id) FROM users u2 WHERE LOWER(u2.name) = LOWER(
        (SELECT name FROM users WHERE id = contexts.user_id)
    )
)
WHERE user_id NOT IN (
    SELECT MIN(id) FROM users GROUP BY LOWER(name)
);

-- Reassign user_state entries.
UPDATE user_state
SET user_id = (
    SELECT MIN(u2.id) FROM users u2 WHERE LOWER(u2.name) = LOWER(
        (SELECT name FROM users WHERE id = user_state.user_id)
    )
)
WHERE user_id NOT IN (
    SELECT MIN(id) FROM users GROUP BY LOWER(name)
);

-- Delete duplicate user rows (keep lowest id per lowercase name).
DELETE FROM users
WHERE id NOT IN (
    SELECT MIN(id) FROM users GROUP BY LOWER(name)
);

-- Normalise remaining user names to lowercase.
UPDATE users SET name = LOWER(name) WHERE name != LOWER(name);

-- Enforce case-insensitive uniqueness going forward.
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_name_lower ON users(LOWER(name));
