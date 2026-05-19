"""
Background task: sends DM reminders for approved mentoring sessions.
Checks every 5 minutes. Sends reminders at:
  - day_before  : 23h ~ 25h before start
  - day_of      : 8h ~ 10h before start  (morning of the session day)
  - hour_before : 50min ~ 70min before start
All times are compared in KST (UTC+9).
"""
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

import database
from ui.embeds import reminder_embed

log = logging.getLogger("asanAX.reminder")

KST = timezone(timedelta(hours=9))

# (type, lower_seconds, upper_seconds)
REMINDER_WINDOWS = [
    ("day_before",  23 * 3600, 25 * 3600),
    ("day_of",       8 * 3600, 10 * 3600),
    ("hour_before",     50 * 60,     70 * 60),
]


class Reminder(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.check_reminders.start()

    def cog_unload(self) -> None:
        self.check_reminders.cancel()

    @tasks.loop(minutes=5)
    async def check_reminders(self) -> None:
        try:
            await self._run()
        except Exception as e:
            log.error("Reminder check failed: %s", e)

    @check_reminders.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()

    async def _run(self) -> None:
        now = datetime.now(KST)
        bookings = await database.get_approved_bookings_for_reminder()

        for b in bookings:
            start = datetime.fromisoformat(b["start_time"]).replace(tzinfo=KST)
            seconds_until = (start - now).total_seconds()

            if seconds_until < 0:
                continue  # past session

            for r_type, lo, hi in REMINDER_WINDOWS:
                if lo <= seconds_until < hi:
                    if await database.is_reminder_sent(b["booking_id"], r_type):
                        continue

                    await self._send(b, r_type)
                    await database.mark_reminder_sent(b["booking_id"], r_type)

    async def _send(self, booking: dict, reminder_type: str) -> None:
        # DM to user (mentee)
        try:
            user = await self.bot.fetch_user(int(booking["user_id"]))
            await user.send(embed=reminder_embed(booking, reminder_type, for_mentor=False))
            log.info("Sent %s reminder to user %s", reminder_type, booking["user_name"])
        except Exception as e:
            log.warning("Failed to DM user %s: %s", booking["user_id"], e)

        # DM to mentor
        try:
            mentor = await self.bot.fetch_user(int(booking["mentor_discord_id"]))
            await mentor.send(embed=reminder_embed(booking, reminder_type, for_mentor=True))
            log.info("Sent %s reminder to mentor %s", reminder_type, booking["mentor_name"])
        except Exception as e:
            log.warning("Failed to DM mentor %s: %s", booking["mentor_discord_id"], e)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Reminder(bot))
