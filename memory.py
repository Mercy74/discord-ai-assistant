
import os
import asyncpg


# =========================================================
# CONFIGURATION
# =========================================================

DATABASE_URL = os.getenv("DATABASE_URL")

CONVERSATION_RETENTION_DAYS = 30
MAX_RECENT_MESSAGES = 20
MAX_MESSAGE_LENGTH = 12000
MAX_MEMORY_LENGTH = 2000

SERVER_MEMORY_USER_ID = "__ORDAT_SERVER_MEMORY__"

PERSONAL_MEMORY_CATEGORIES = ("personal", "general")
SERVER_MEMORY_CATEGORIES = ("shared", "behavioral")

_pool = None


# =========================================================
# DATABASE CONNECTION
# =========================================================

async def initialize_database():
    global _pool

    if not DATABASE_URL:
        raise RuntimeError("Missing DATABASE_URL environment variable")

    if _pool is not None:
        return

    _pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=3,
        command_timeout=30,
        ssl="require",
    )

    print("DEBUG: Memory database connected.")


async def close_database():
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_pool():
    if _pool is None:
        await initialize_database()

    return _pool


# =========================================================
# CONVERSATION HISTORY
# =========================================================

async def save_message(guild_id, user_id, role, content):
    if role not in ("user", "assistant"):
        raise ValueError("Invalid conversation role")

    if not content:
        return

    content = str(content)[:MAX_MESSAGE_LENGTH]

    pool = await get_pool()

    await pool.execute(
        """
        INSERT INTO conversation_messages
            (guild_id, user_id, role, content)
        VALUES ($1, $2, $3, $4)
        """,
        str(guild_id),
        str(user_id),
        role,
        content,
    )


async def get_recent_messages(guild_id, user_id, limit=10):
    pool = await get_pool()

    limit = max(1, min(int(limit), MAX_RECENT_MESSAGES))

    rows = await pool.fetch(
        """
        SELECT role, content
        FROM conversation_messages
        WHERE guild_id = $1
          AND user_id = $2
        ORDER BY created_at DESC
        LIMIT $3
        """,
        str(guild_id),
        str(user_id),
        limit,
    )

    return list(reversed(rows))


# =========================================================
# MEMORY DUPLICATE DETECTION
# =========================================================

def normalize_memory_content(content):
    """
    Normalize whitespace and capitalization for duplicate checks.

    Example:
    'My favorite color is Blue'
    ' my   favorite color is blue '
    """

    return " ".join(str(content).split()).casefold()


async def _save_deduplicated_memory(
    guild_id,
    user_id,
    content,
    category,
    protected,
    duplicate_categories,
):
    """
    Save a memory only if an equivalent memory does not already exist.

    PostgreSQL advisory locks prevent simultaneous identical requests
    from normally creating duplicate entries.
    """

    content = " ".join(str(content).split())[:MAX_MEMORY_LENGTH]

    if not content:
        raise ValueError("Memory content cannot be empty")

    normalized_content = normalize_memory_content(content)

    pool = await get_pool()

    async with pool.acquire() as connection:
        async with connection.transaction():

            # Serialize identical memory-save attempts.
            await connection.execute(
                """
                SELECT pg_advisory_xact_lock(
                    hashtext($1),
                    hashtext($2)
                )
                """,
                f"{guild_id}:{user_id}:{category}",
                normalized_content,
            )

            existing = await connection.fetchrow(
                """
                SELECT id, protected
                FROM memories
                WHERE guild_id = $1
                  AND user_id = $2
                  AND category = ANY($3::text[])
                  AND LOWER(
                      REGEXP_REPLACE(BTRIM(content), '\\s+', ' ', 'g')
                  ) = LOWER(
                      REGEXP_REPLACE(BTRIM($4), '\\s+', ' ', 'g')
                  )
                LIMIT 1
                """,
                str(guild_id),
                str(user_id),
                list(duplicate_categories),
                content,
            )

            if existing:
                # A protected memory must never become unprotected
                # merely because the same memory is saved again.
                if protected and not existing["protected"]:
                    await connection.execute(
                        """
                        UPDATE memories
                        SET protected = TRUE
                        WHERE id = $1
                        """,
                        existing["id"],
                    )

                return existing["id"]

            memory_id = await connection.fetchval(
                """
                INSERT INTO memories
                    (guild_id, user_id, content, category, protected)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                str(guild_id),
                str(user_id),
                content,
                category,
                bool(protected),
            )

            return memory_id


# =========================================================
# PERSONAL MEMORIES
# =========================================================

async def save_memory(
    guild_id,
    user_id,
    content,
    category="personal",
    protected=False,
):
    """
    Save a memory belonging to one specific Discord user.

    Personal memories are never shared with other server members.

    The categories 'personal' and 'general' are checked together
    to avoid duplicates from older versions of Ordat.
    """

    return await _save_deduplicated_memory(
        guild_id=guild_id,
        user_id=user_id,
        content=content,
        category=category,
        protected=protected,
        duplicate_categories=PERSONAL_MEMORY_CATEGORIES,
    )


async def get_memories(guild_id, user_id):
    pool = await get_pool()

    rows = await pool.fetch(
        """
        SELECT id, content, category, protected, created_at
        FROM memories
        WHERE guild_id = $1
          AND user_id = $2
          AND category = ANY($3::text[])
        ORDER BY protected DESC, created_at DESC
        """,
        str(guild_id),
        str(user_id),
        list(PERSONAL_MEMORY_CATEGORIES),
    )

    return rows


# =========================================================
# SERVER-WIDE MEMORIES
# =========================================================

async def save_server_memory(
    guild_id,
    content,
    category="shared",
    protected=False,
):
    """
    Save a memory shared by the entire Discord server.

    Shared and behavioral memories remain separate categories.
    """

    if category not in SERVER_MEMORY_CATEGORIES:
        raise ValueError(
            "Server memory category must be 'shared' or 'behavioral'"
        )

    return await _save_deduplicated_memory(
        guild_id=guild_id,
        user_id=SERVER_MEMORY_USER_ID,
        content=content,
        category=category,
        protected=protected,
        duplicate_categories=(category,),
    )


async def get_server_memories(guild_id):
    pool = await get_pool()

    rows = await pool.fetch(
        """
        SELECT id, content, category, protected, created_at
        FROM memories
        WHERE guild_id = $1
          AND user_id = $2
          AND category = ANY($3::text[])
        ORDER BY
            CASE
                WHEN category = 'behavioral' THEN 0
                ELSE 1
            END,
            protected DESC,
            created_at DESC
        """,
        str(guild_id),
        SERVER_MEMORY_USER_ID,
        list(SERVER_MEMORY_CATEGORIES),
    )

    return rows


# =========================================================
# MEMORY DELETION
# =========================================================

async def delete_server_memory(
    memory_id,
    guild_id,
    allow_protected=False,
):
    pool = await get_pool()

    result = await pool.execute(
        """
        DELETE FROM memories
        WHERE id = $1
          AND guild_id = $2
          AND user_id = $3
          AND category = ANY($4::text[])
          AND ($5 OR protected = FALSE)
        """,
        memory_id,
        str(guild_id),
        SERVER_MEMORY_USER_ID,
        list(SERVER_MEMORY_CATEGORIES),
        bool(allow_protected),
    )

    return result.endswith("1")


async def delete_memory(
    memory_id,
    guild_id,
    user_id,
    allow_protected=False,
):
    pool = await get_pool()

    result = await pool.execute(
        """
        DELETE FROM memories
        WHERE id = $1
          AND guild_id = $2
          AND user_id = $3
          AND category = ANY($4::text[])
          AND ($5 OR protected = FALSE)
        """,
        memory_id,
        str(guild_id),
        str(user_id),
        list(PERSONAL_MEMORY_CATEGORIES),
        bool(allow_protected),
    )

    return result.endswith("1")


# =========================================================
# AUTOMATIC CONVERSATION CLEANUP
# =========================================================


async def cleanup_old_conversations():
    """
    Delete conversation history older than the retention period
    and check the database size.

    Long-term memories are never deleted by this function.
    """

    pool = await get_pool()

    result = await pool.execute(
        """
        DELETE FROM conversation_messages
        WHERE created_at < NOW() - ($1 * INTERVAL '1 day')
        """,
        CONVERSATION_RETENTION_DAYS,
    )

    try:
        deleted = int(result.split()[-1])
    except (ValueError, IndexError):
        deleted = 0

    # Check Supabase database size.
    try:
        size_bytes = await get_database_size()
        size_mb = size_bytes / (1024 * 1024)

        warning_limit_mb = 400

        if size_mb >= warning_limit_mb:
            print(
                "WARNING: Ordat database is approaching "
                f"its Supabase quota! "
                f"Current size: {size_mb:.1f} MB. "
                f"Warning threshold: {warning_limit_mb} MB."
            )
        else:
            print(
                "DEBUG: Ordat database size: "
                f"{size_mb:.1f} MB "
                f"(warning at {warning_limit_mb} MB)."
            )

    except Exception as error:
        print(
            "WARNING: Could not check Supabase database size:",
            repr(error),
        )

    return deleted


# =========================================================
# DATABASE SIZE
# =========================================================

async def get_database_size():
    pool = await get_pool()

    size = await pool.fetchval(
        """
        SELECT pg_database_size(current_database())
        """
    )

    return size
