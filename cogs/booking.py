import discord
from discord import app_commands
from discord.ext import commands

import database
from ui import embeds
from ui.slot_select import SlotSelectView
from ui.confirm_view import CancelConfirmView


class Booking(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ── Autocomplete ──────────────────────────────────────────────────────

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

    @mentor_group.command(name="slots", description="특정 멘토의 예약 가능 시간을 확인합니다.")
    @app_commands.describe(mentor="멘토 이름")
    @app_commands.autocomplete(mentor=_mentor_autocomplete)
    async def mentor_slots(self, interaction: discord.Interaction, mentor: str) -> None:
        await self._show_slots(interaction, mentor)

    # ── /book ─────────────────────────────────────────────────────────────

    @app_commands.command(name="book", description="멘토링 세션을 예약합니다.")
    @app_commands.describe(mentor="예약할 멘토")
    @app_commands.autocomplete(mentor=_mentor_autocomplete)
    async def book(self, interaction: discord.Interaction, mentor: str) -> None:
        await self._show_slots(interaction, mentor)

    async def _show_slots(self, interaction: discord.Interaction, mentor_id_str: str) -> None:
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

        slots = await database.get_slots_for_mentor(mentor_id, active_only=True)
        slot_ids = [s["id"] for s in slots]
        bookings_map = await database.get_bookings_by_slot_ids(slot_ids)

        await interaction.response.send_message(
            embed=embeds.slot_list_embed(mentor, slots, bookings_map),
            view=SlotSelectView(mentor, slots, bookings_map),
            ephemeral=True,
        )

    # ── /mybooking ────────────────────────────────────────────────────────

    @app_commands.command(name="mybooking", description="내 멘토링 예약을 확인합니다.")
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

    @app_commands.command(name="cancel", description="내 멘토링 예약을 취소합니다.")
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
