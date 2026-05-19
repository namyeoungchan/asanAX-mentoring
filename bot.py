import asyncio
import logging
import os

import discord
from discord.ext import commands

import config
import database
from ui.mentor_panel import MentorPanelView

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("asanAX")

COGS = [
    "cogs.error_handler",
    "cogs.booking",
    "cogs.admin",
    "cogs.mentor",
    "cogs.reminder",
    "cogs.onboarding",
    "cogs.qa",
]


class AsanAXBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        db_dir = os.path.dirname(config.DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        await database.init_db()
        log.info("Database initialised at %s", config.DB_PATH)

        for cog in COGS:
            await self.load_extension(cog)
            log.info("Loaded cog: %s", cog)

        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info("Slash commands synced to guild %d", config.GUILD_ID)

        if config.SYNC_GLOBALLY:
            await self.tree.sync()
            log.info("Slash commands synced globally")

        # Restore persistent panel views so buttons work after restart
        mentors = await database.get_mentors()
        self.add_view(MentorPanelView(mentors))
        log.info("Persistent panel view registered")

    async def on_ready(self) -> None:
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)  # type: ignore[union-attr]


async def main() -> None:
    bot = AsanAXBot()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
