import aiosqlite
from config import DB_PATH


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS mentors (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id  TEXT    NOT NULL UNIQUE,
                name        TEXT    NOT NULL,
                bio         TEXT    DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS slots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                mentor_id   INTEGER NOT NULL REFERENCES mentors(id) ON DELETE CASCADE,
                start_time  TEXT    NOT NULL,
                end_time    TEXT    NOT NULL,
                label       TEXT    NOT NULL,
                is_active   INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                slot_id     INTEGER NOT NULL UNIQUE REFERENCES slots(id) ON DELETE CASCADE,
                user_id     TEXT    NOT NULL,
                user_name   TEXT    NOT NULL,
                booked_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS panels (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id  TEXT    NOT NULL,
                message_id  TEXT    NOT NULL,
                guild_id    TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS slot_templates (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                mentor_id        INTEGER NOT NULL UNIQUE REFERENCES mentors(id) ON DELETE CASCADE,
                start_hour       INTEGER NOT NULL DEFAULT 19,
                start_minute     INTEGER NOT NULL DEFAULT 0,
                end_hour         INTEGER NOT NULL DEFAULT 21,
                end_minute       INTEGER NOT NULL DEFAULT 0,
                interval_minutes INTEGER NOT NULL DEFAULT 30
            );

            CREATE TABLE IF NOT EXISTS blocked_dates (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                mentor_id INTEGER NOT NULL REFERENCES mentors(id) ON DELETE CASCADE,
                date      TEXT    NOT NULL,
                UNIQUE(mentor_id, date)
            );
        """)
        await db.commit()
        # Migration: add status / rejection_reason columns if missing
        await _migrate(db)


async def _migrate(db: aiosqlite.Connection) -> None:
    async with db.execute("PRAGMA table_info(bookings)") as cur:
        columns = {row[1] for row in await cur.fetchall()}
    if "status" not in columns:
        # existing rows → 'approved' (they were already booked)
        await db.execute(
            "ALTER TABLE bookings ADD COLUMN status TEXT NOT NULL DEFAULT 'approved'"
        )
    if "rejection_reason" not in columns:
        await db.execute(
            "ALTER TABLE bookings ADD COLUMN rejection_reason TEXT DEFAULT ''"
        )
    await db.commit()


# ── Mentor helpers ──────────────────────────────────────────────────────────

async def get_mentors() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM mentors ORDER BY name") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_mentor_by_id(mentor_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM mentors WHERE id = ?", (mentor_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_mentor_by_discord_id(discord_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM mentors WHERE discord_id = ?", (discord_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def add_mentor(discord_id: str, name: str, bio: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO mentors (discord_id, name, bio) VALUES (?, ?, ?)",
            (discord_id, name, bio),
        )
        await db.commit()
        return cur.lastrowid


async def remove_mentor(mentor_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM mentors WHERE id = ?", (mentor_id,))
        await db.commit()
        return cur.rowcount > 0


# ── Slot helpers ────────────────────────────────────────────────────────────

async def get_slots_for_mentor(mentor_id: int, active_only: bool = True) -> list[dict]:
    query = "SELECT * FROM slots WHERE mentor_id = ?"
    params: list = [mentor_id]
    if active_only:
        query += " AND is_active = 1"
    query += " ORDER BY start_time"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_slot(slot_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM slots WHERE id = ?", (slot_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def add_slot(
    mentor_id: int, start_time: str, end_time: str, label: str
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO slots (mentor_id, start_time, end_time, label) VALUES (?, ?, ?, ?)",
            (mentor_id, start_time, end_time, label),
        )
        await db.commit()
        return cur.lastrowid


async def deactivate_slot(slot_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE slots SET is_active = 0 WHERE id = ?", (slot_id,)
        )
        await db.commit()
        return cur.rowcount > 0


# ── Booking helpers ─────────────────────────────────────────────────────────

async def get_booking_for_slot(slot_id: int) -> dict | None:
    """Returns active (pending or approved) booking for a slot."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM bookings WHERE slot_id = ? AND status IN ('pending', 'approved')",
            (slot_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_booking_by_user(user_id: str) -> dict | None:
    """Returns the most recent pending/approved booking for the user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT b.*, s.label, s.start_time, s.end_time, s.mentor_id
               FROM bookings b
               JOIN slots s ON b.slot_id = s.id
               WHERE b.user_id = ? AND b.status IN ('pending', 'approved')
               ORDER BY b.booked_at DESC
               LIMIT 1""",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_all_bookings(mentor_id: int | None = None) -> list[dict]:
    query = """
        SELECT b.*, s.label, s.start_time, m.name AS mentor_name
        FROM bookings b
        JOIN slots s ON b.slot_id = s.id
        JOIN mentors m ON s.mentor_id = m.id
    """
    params: list = []
    if mentor_id is not None:
        query += " WHERE s.mentor_id = ?"
        params.append(mentor_id)
    query += " ORDER BY s.start_time"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def create_booking(slot_id: int, user_id: str, user_name: str) -> bool:
    """Creates a pending booking. Returns True on success, False if slot already taken."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO bookings (slot_id, user_id, user_name, status) VALUES (?, ?, ?, 'pending')",
                (slot_id, user_id, user_name),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def approve_booking(slot_id: int) -> dict | None:
    """Approves a pending booking. Returns booking row or None if not found."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM bookings WHERE slot_id = ? AND status = 'pending'", (slot_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        booking = dict(row)
        await db.execute(
            "UPDATE bookings SET status = 'approved' WHERE slot_id = ?", (slot_id,)
        )
        await db.commit()
    return booking


async def reject_booking(slot_id: int, reason: str = "") -> dict | None:
    """Rejects and deletes a booking. Returns deleted booking row or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM bookings WHERE slot_id = ?", (slot_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        booking = dict(row)
        await db.execute("DELETE FROM bookings WHERE slot_id = ?", (slot_id,))
        await db.commit()
    return booking


async def cancel_booking(slot_id: int, user_id: str) -> bool:
    """Cancels a booking only if it belongs to the given user."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM bookings WHERE slot_id = ? AND user_id = ?",
            (slot_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def admin_cancel_booking(slot_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM bookings WHERE slot_id = ?", (slot_id,)
        )
        await db.commit()
        return cur.rowcount > 0


async def get_bookings_by_slot_ids(slot_ids: list[int]) -> dict[int, dict]:
    """Returns a mapping of slot_id -> booking row (pending/approved only)."""
    if not slot_ids:
        return {}
    placeholders = ",".join("?" * len(slot_ids))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT * FROM bookings WHERE slot_id IN ({placeholders})"
            f" AND status IN ('pending','approved')",
            slot_ids,
        ) as cur:
            rows = await cur.fetchall()
    return {row["slot_id"]: dict(row) for row in rows}


async def get_dates_with_available_slots(mentor_id: int) -> list[str]:
    """Returns YYYY-MM-DD dates that have at least one bookable slot."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT DISTINCT substr(start_time, 1, 10) AS date
               FROM slots
               WHERE mentor_id = ? AND is_active = 1
                 AND id NOT IN (
                     SELECT slot_id FROM bookings
                     WHERE status IN ('pending','approved')
                 )
               ORDER BY date""",
            (mentor_id,),
        ) as cur:
            return [row[0] for row in await cur.fetchall()]


async def get_slots_for_mentor_date(mentor_id: int, date: str) -> list[dict]:
    """Returns all active slots for mentor on date, with booking status attached."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT s.*,
                      b.status     AS booking_status,
                      b.user_name  AS booked_by,
                      b.user_id    AS booked_user_id
               FROM slots s
               LEFT JOIN bookings b
                 ON s.id = b.slot_id AND b.status IN ('pending','approved')
               WHERE s.mentor_id = ? AND s.is_active = 1
                 AND substr(s.start_time, 1, 10) = ?
               ORDER BY s.start_time""",
            (mentor_id, date),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ── Panel helpers ────────────────────────────────────────────────────────────

async def save_panel(guild_id: str, channel_id: str, message_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO panels (guild_id, channel_id, message_id)
               VALUES (?, ?, ?)""",
            (guild_id, channel_id, message_id),
        )
        await db.commit()


async def get_panels() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM panels") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def delete_panel(panel_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM panels WHERE id = ?", (panel_id,))
        await db.commit()


# ── Template helpers ──────────────────────────────────────────────────────────

async def set_slot_template(
    mentor_id: int,
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    interval_minutes: int,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO slot_templates
               (mentor_id, start_hour, start_minute, end_hour, end_minute, interval_minutes)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(mentor_id) DO UPDATE SET
                 start_hour=excluded.start_hour,
                 start_minute=excluded.start_minute,
                 end_hour=excluded.end_hour,
                 end_minute=excluded.end_minute,
                 interval_minutes=excluded.interval_minutes""",
            (mentor_id, start_hour, start_minute, end_hour, end_minute, interval_minutes),
        )
        await db.commit()


async def get_slot_template(mentor_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM slot_templates WHERE mentor_id = ?", (mentor_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ── Blocked date helpers ──────────────────────────────────────────────────────

async def block_date(mentor_id: int, date: str) -> bool:
    """Returns False if already blocked."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO blocked_dates (mentor_id, date) VALUES (?, ?)",
                (mentor_id, date),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def unblock_date(mentor_id: int, date: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM blocked_dates WHERE mentor_id = ? AND date = ?",
            (mentor_id, date),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_blocked_dates(mentor_id: int) -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT date FROM blocked_dates WHERE mentor_id = ? ORDER BY date",
            (mentor_id,),
        ) as cur:
            return [row["date"] for row in await cur.fetchall()]


async def is_date_blocked(mentor_id: int, date: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM blocked_dates WHERE mentor_id = ? AND date = ?",
            (mentor_id, date),
        ) as cur:
            return await cur.fetchone() is not None
