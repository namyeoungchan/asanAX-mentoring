"""
Persistent mentor panel — lives in a channel, survives bot restarts.
Each button opens an ephemeral slot-select flow for that mentor.
"""

import discord
import database
from ui import embeds
from ui.date_select import DateSelectView


def _chunk(lst: list, size: int) -> list[list]:
    return [lst[i : i + size] for i in range(0, len(lst), size)]


class MentorPanelView(discord.ui.View):
    """
    Persistent view — timeout=None so it works after bot restarts.
    Buttons are rebuilt from the live mentors list each time the panel is refreshed.
    """

    def __init__(self, mentors: list[dict]) -> None:
        super().__init__(timeout=None)
        for mentor in mentors[:25]:  # Discord limit: 25 components
            btn = discord.ui.Button(
                label=mentor["name"],
                emoji="📅",
                style=discord.ButtonStyle.primary,
                custom_id=f"mentor_book:{mentor['id']}",
            )
            btn.callback = self._make_callback(mentor)
            self.add_item(btn)

    def _make_callback(self, mentor: dict):
        async def callback(interaction: discord.Interaction) -> None:
            try:
                # Re-fetch mentor in case data changed after bot restart
                fresh_mentor = await database.get_mentor_by_id(mentor["id"])
                if not fresh_mentor:
                    await interaction.response.send_message(
                        embed=embeds.error_embed("멘토 정보를 찾을 수 없습니다. 관리자에게 문의하세요."),
                        ephemeral=True,
                    )
                    return

                dates = await database.get_dates_with_available_slots(fresh_mentor["id"])
                await interaction.response.send_message(
                    embed=embeds.date_select_embed(fresh_mentor, dates),
                    view=DateSelectView(fresh_mentor, dates),
                    ephemeral=True,
                )
            except Exception as e:
                msg = f"오류가 발생했습니다: {e}"
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embeds.error_embed(msg), ephemeral=True)
                else:
                    await interaction.response.send_message(embed=embeds.error_embed(msg), ephemeral=True)

        return callback


async def build_panel_embed(mentors: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="🎓  아산 AX 멘토링 예약",
        description=(
            "아래 버튼을 눌러 멘토를 선택하고 시간을 예약하세요.\n"
            "예약은 본인에게만 보이며, `/mybooking` 으로 확인할 수 있습니다.\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=discord.Color.from_str("#2B5CE6"),
    )

    if not mentors:
        embed.add_field(name="현재 등록된 멘토가 없습니다.", value="관리자에게 문의하세요.", inline=False)
        embed.set_footer(text="아산 AX 멘토링 예약 시스템")
        return embed

    for m in mentors:
        slots = await database.get_slots_for_mentor(m["id"], active_only=True)
        slot_ids = [s["id"] for s in slots]
        bookings_map = await database.get_bookings_by_slot_ids(slot_ids)
        available = sum(1 for s in slots if s["id"] not in bookings_map)

        value_lines = [m["bio"] or "소개 없음", f"📅 예약 가능 슬롯: **{available}개**"]
        embed.add_field(
            name=f"👤  {m['name']}",
            value="\n".join(value_lines),
            inline=False,
        )

    embed.set_footer(text="아산 AX 멘토링 · 버튼을 눌러 예약하세요")
    embed.set_thumbnail(url="https://cdn.discordapp.com/embed/avatars/0.png")
    return embed
