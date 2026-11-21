
import os
import asyncpg


# =========================================================
# CONFIGURATION
# =========================================================

DATABASE_URL = os.getenv("DATABASE_URL")

_pool = None

CONVERSATION_RETENTION_DAYS = 30
MAX_RECENT_MESSAGES = 20
MAX_MESSAGE_LENGTH = 12000
MAX_MEMORY_LENGTH = 2000

# Reserved database user ID for memories shared by the entire server.
# This is not a real Discord user ID.
SERVER_MEMORY_USER_ID = "__ORDAT_SERVER_MEMORY__"

PERSONAL_MEMORY_CATEGORIES = (
    "personal",
    "general",
)

SERVER_MEMORY_CATEGORIES = (
    "shared",
    "behavioral",
)


# =========================================================
# DATABASE CONNECTION
# =========================================================

async def initialize_database():
    """Connect Ordat to the Supabase PostgreSQL database."""

    global _pool

    if _pool is not None:
        return

    if not DATABASE_URL:
        raise RuntimeError("Missing DATABASE_URL environment variable")

    _pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=1,
        max_size=3,
        command_timeout=30,
        ssl="require"
    )

    async with _pool.acquire() as connection:
        await connection.fetchval("SELECT 1")

    print("DEBUG: Ordat memory database connected!")


async def close_database():
    """Close the database connection."""

    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None

    print("DEBUG: Ordat memory database disconnected.")


def get_pool():
    """Return the active database connection pool."""

    if _pool is None:
        raise RuntimeError("Memory database has not been initialized")

    return _pool


# =========================================================
# CONVERSATION MEMORY
# =========================================================

async def save_message(guild_id, user_id, role, content):
    """Save one user or assistant message."""

    if role not in ("user", "assistant"):
        raise ValueError("Invalid conversation role")

    content = str(content).strip()

    if not content:
        return

    content = content[:MAX_MESSAGE_LENGTH]

    pool = get_pool()

    await pool.execute(
        """
        INSERT INTO public.conversation_messages
        (guild_id, user_id, role, content)
        VALUES ($1, $2, $3, $4)
        """,
        str(guild_id),
        str(user_id),
        role,
        content
    )


async def get_recent_messages(guild_id, user_id, limit=10):
    """Retrieve recent conversation messages in chronological order."""

    limit = max(1, min(int(limit), MAX_RECENT_MESSAGES))

    pool = get_pool()

    rows = await pool.fetch(
        """
        SELECT role, content, created_at
        FROM (
            SELECT role, content, created_at, id
            FROM public.conversation_messages
            WHERE guild_id = $1
              AND user_id = $2
            ORDER BY created_at DESC, id DESC
            LIMIT $3
        ) AS recent
        ORDER BY created_at ASC, id ASC
        """,
        str(guild_id),
        str(user_id),
        limit
    )

    return [dict(row) for row in rows]


# =========================================================
# PERSONAL LONG-TERM MEMORY
# =========================================================

async def save_memory(
    guild_id,
    user_id,
    content,
    category="general",
    protected=False
):
    """
    Save a personal long-term memory for one user in one server.

    Existing memories using category='general' remain supported.
    """

    content = str(content).strip()

    if not content:
        return None

    if len(content) > MAX_MEMORY_LENGTH:
        raise ValueError(
            f"Memory exceeds {MAX_MEMORY_LENGTH} characters"
        )

    pool = get_pool()

    memory_id = await pool.fetchval(
        """
        INSERT INTO public.memories
        (guild_id, user_id, content, category, protected)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        str(guild_id),
        str(user_id),
        content,
        str(category)[:50],
        bool(protected)
    )

    return memory_id


async def get_memories(guild_id, user_id):
    """
    Retrieve personal memories belonging only to this user
    in this server.

    Server-wide memories are stored under a separate reserved
    user ID and are not returned by this function.
    """

    pool = get_pool()

    rows = await pool.fetch(
        """
        SELECT id, content, category, protected, created_at, updated_at
        FROM public.memories
        WHERE guild_id = $1
          AND user_id = $2
        ORDER BY protected DESC, updated_at DESC
        """,
        str(guild_id),
        str(user_id)
    )

    return [dict(row) for row in rows]


# =========================================================
# SHARED AND BEHAVIORAL SERVER MEMORY
# =========================================================

async def save_server_memory(
    guild_id,
    content,
    category="shared",
    protected=False
):
    """
    Save a memory for the entire server.

    Valid server memory categories:
    - shared
    - behavioral

    These memories are available to authorized staff in
    the same server, regardless of who saved them.
    """

    category = str(category).strip().lower()

    if category not in SERVER_MEMORY_CATEGORIES:
        raise ValueError(
            "Server memory category must be 'shared' "
            "or 'behavioral'"
        )

    content = str(content).strip()

    if not content:
        return None

    if len(content) > MAX_MEMORY_LENGTH:
        raise ValueError(
            f"Memory exceeds {MAX_MEMORY_LENGTH} characters"
        )

    pool = get_pool()

    # Avoid saving an identical server memory repeatedly.
    existing_id = await pool.fetchval(
        """
        SELECT id
        FROM public.memories
        WHERE guild_id = $1
          AND user_id = $2
          AND category = $3
          AND LOWER(content) = LOWER($4)
        LIMIT 1
        """,
        str(guild_id),
        SERVER_MEMORY_USER_ID,
        category,
        content
    )

    if existing_id is not None:
        return existing_id

    memory_id = await pool.fetchval(
        """
        INSERT INTO public.memories
        (guild_id, user_id, content, category, protected)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        str(guild_id),
        SERVER_MEMORY_USER_ID,
        content,
        category,
        bool(protected)
    )

    return memory_id


async def get_server_memories(guild_id, categories=None):
    """
    Retrieve shared server memories.

    By default, retrieves both shared and behavioral memories.
    Personal memories are never returned here.
    """

    pool = get_pool()

    if categories is None:
        categories = list(SERVER_MEMORY_CATEGORIES)
    else:
        categories = [
            str(category).strip().lower()
            for category in categories
        ]

    categories = [
        category for category in categories
        if category in SERVER_MEMORY_CATEGORIES
    ]

    if not categories:
        return []

    rows = await pool.fetch(
        """
        SELECT id, content, category, protected, created_at, updated_at
        FROM public.memories
        WHERE guild_id = $1
          AND user_id = $2
          AND category = ANY($3::text[])
        ORDER BY
            protected DESC,
            CASE WHEN category = 'behavioral' THEN 0 ELSE 1 END,
            updated_at DESC
        """,
        str(guild_id),
        SERVER_MEMORY_USER_ID,
        categories
    )

    return [dict(row) for row in rows]


async def delete_server_memory(
    memory_id,
    guild_id,
    allow_protected=False
):
    """
    Delete a shared or behavioral server memory.

    Protected memories cannot be deleted unless explicitly allowed.
    """

    pool = get_pool()

    result = await pool.execute(
        """
        DELETE FROM public.memories
        WHERE id = $1
          AND guild_id = $2
          AND user_id = $3
          AND category = ANY($4::text[])
          AND ($5 OR protected = FALSE)
        """,
        int(memory_id),
        str(guild_id),
        SERVER_MEMORY_USER_ID,
        list(SERVER_MEMORY_CATEGORIES),
        bool(allow_protected)
    )

    return result == "DELETE 1"


# =========================================================
# DELETE PERSONAL MEMORY
# =========================================================

async def delete_memory(
    memory_id,
    guild_id,
    user_id,
    allow_protected=False
):
    """
    Delete a personal memory belonging to the specified user.

    This function cannot delete another user's personal memory
    or a server-wide memory.
    """

    pool = get_pool()

    result = await pool.execute(
        """
        DELETE FROM public.memories
        WHERE id = $1
          AND guild_id = $2
          AND user_id = $3
          AND ($4 OR protected = FALSE)
        """,
        int(memory_id),
        str(guild_id),
        str(user_id),
        bool(allow_protected)
    )

    return result == "DELETE 1"


# =========================================================
# AUTOMATIC DATA CLEANUP
# =========================================================

async def cleanup_old_conversations():
    """Delete conversation history older than the retention period."""

    pool = get_pool()

    result = await pool.execute(
        """
        DELETE FROM public.conversation_messages
        WHERE created_at < NOW() - ($1 * INTERVAL '1 day')
        """,
        CONVERSATION_RETENTION_DAYS
    )

    deleted_count = int(result.split()[-1])

    print(
        f"DEBUG: Memory cleanup removed "
        f"{deleted_count} expired conversation messages."
    )

    return deleted_count


# =========================================================
# STORAGE INFORMATION
# =========================================================

async def get_database_size():
    """Return the current PostgreSQL database size in bytes."""

    pool = get_pool()

    size = await pool.fetchval(
        "SELECT pg_database_size(current_database())"
    )

    return int(size)
