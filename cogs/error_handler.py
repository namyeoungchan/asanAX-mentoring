import discord
from discord import app_commands
from discord.ext import commands

from ui import embeds


class ErrorHandler(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.tree.on_error = self.on_app_command_error  # type: ignore[method-assign]

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.CheckFailure):
            msg = "이 명령어를 사용할 권한이 없습니다."
        else:
            msg = f"오류가 발생했습니다: {error}"

        embed = embeds.error_embed(msg)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ErrorHandler(bot))
