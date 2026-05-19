import discord
from discord import app_commands
from discord.ext import commands

import database
from ui import embeds
from ui.date_select import DateSelectView
from ui.confirm_view import CancelConfirmView


class Booking(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _mentor_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        mentors = await database.get_mentors()
        return [
            app_commands.Choice(name=m["name"], value=str(m["id"]))
            for m in mentors
            if current.lower() in m["name"].lower()
        ][:25]

    # ── /mentor list ──────────────────────────────────────────────────────

    mentor_group = app_commands.Group(name="mentor", description="멘토 관련 명령어")

    @mentor_group.command(name="list", description="등록된 멘토 목록을 확인합니다.")
    async def mentor_list(self, interaction: discord.Interaction) -> None:
        mentors = await database.get_mentors()
        await interaction.response.send_message(
            embed=embeds.mentor_list_embed(mentors), ephemeral=True
        )

    @mentor_group.command(name="slots", description="특정 멘토의 예약 가능 날짜를 확인합니다.")
    @app_commands.describe(mentor="멘토 이름")
    @app_commands.autocomplete(mentor=_mentor_autocomplete)
    async def mentor_slots(self, interaction: discord.Interaction, mentor: str) -> None:
        await self._open_date_select(interaction, mentor)

    # ── /book ─────────────────────────────────────────────────────────────

    @app_commands.command(name="book", description="멘토링 세션을 신청합니다.")
    @app_commands.describe(mentor="신청할 멘토")
    @app_commands.autocomplete(mentor=_mentor_autocomplete)
    async def book(self, interaction: discord.Interaction, mentor: str) -> None:
        await self._open_date_select(interaction, mentor)

    async def _open_date_select(self, interaction: discord.Interaction, mentor_id_str: str) -> None:
        try:
            mentor_id = int(mentor_id_str)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error_embed("올바른 멘토를 선택해주세요."), ephemeral=True
            )
            return

        mentor = await database.get_mentor_by_id(mentor_id)
        if not mentor:
            await interaction.response.send_message(
                embed=embeds.error_embed("해당 멘토를 찾을 수 없습니다."), ephemeral=True
            )
            return

        dates = await database.get_dates_with_available_slots(mentor_id)
        await interaction.response.send_message(
            embed=embeds.date_select_embed(mentor, dates),
            view=DateSelectView(mentor, dates),
            ephemeral=True,
        )

    # ── /mybooking ────────────────────────────────────────────────────────

    @app_commands.command(name="mybooking", description="내 멘토링 신청 현황을 확인합니다.")
    async def my_booking(self, interaction: discord.Interaction) -> None:
        booking = await database.get_booking_by_user(str(interaction.user.id))
        if not booking:
            await interaction.response.send_message(
                embed=embeds.no_booking_embed(), ephemeral=True
            )
            return
        mentor = await database.get_mentor_by_id(booking["mentor_id"])
        await interaction.response.send_message(
            embed=embeds.my_booking_embed(booking, mentor), ephemeral=True
        )

    # ── /cancel ───────────────────────────────────────────────────────────

    @app_commands.command(name="cancel", description="내 멘토링 신청을 취소합니다.")
    async def cancel(self, interaction: discord.Interaction) -> None:
        booking = await database.get_booking_by_user(str(interaction.user.id))
        if not booking:
            await interaction.response.send_message(
                embed=embeds.no_booking_embed(), ephemeral=True
            )
            return
        mentor = await database.get_mentor_by_id(booking["mentor_id"])
        await interaction.response.send_message(
            embed=embeds.cancel_confirm_embed(booking, mentor),
            view=CancelConfirmView(booking, mentor),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Booking(bot))
