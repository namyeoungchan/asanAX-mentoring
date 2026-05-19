"""Step 2: User selects a time slot for the chosen date."""
import discord
import database
from ui import embeds


def _hm(iso: str) -> str:
    """Extract HH:MM from ISO datetime string."""
    return iso[11:16]


class TimeSelectView(discord.ui.View):
    def __init__(self, mentor: dict, selected_date: str, slots: list[dict]) -> None:
        super().__init__(timeout=120)
        self.mentor = mentor
        self.selected_date = selected_date
        self.slots = slots

        available = [s for s in slots if not s.get("booking_status")]

        if not available:
            sel = discord.ui.Select(
                placeholder="선택 가능한 시간이 없습니다",
                options=[discord.SelectOption(label="없음", value="none")],
                disabled=True,
            )
        else:
            sel = discord.ui.Select(
                placeholder="시간을 선택하세요",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(
                        label=f"{_hm(s['start_time'])} ~ {_hm(s['end_time'])}",
                        value=str(s["id"]),
                    )
                    for s in available
                ],
            )
        sel.callback = self._on_select
        self.add_item(sel)

        back = discord.ui.Button(
            label="날짜 다시 선택",
            style=discord.ButtonStyle.secondary,
            emoji="◀️",
            row=1,
        )
        back.callback = self._on_back
        self.add_item(back)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        from ui.confirm_view import BookingConfirmView

        value = interaction.data["values"][0]  # type: ignore[index]
        if value == "none":
            await interaction.response.defer()
            return

        slot_id = int(value)
        slot = await database.get_slot(slot_id)
        if not slot:
            await interaction.response.edit_message(
                embed=embeds.error_embed("슬롯 정보를 찾을 수 없습니다."), view=None
            )
            return

        existing = await database.get_booking_for_slot(slot_id)
        if existing:
            await interaction.response.edit_message(
                embed=embeds.booking_taken_embed(), view=None
            )
            return

        await interaction.response.edit_message(
            embed=embeds.booking_request_confirm_embed(slot, self.mentor),
            view=BookingConfirmView(slot, self.mentor),
        )

    async def _on_back(self, interaction: discord.Interaction) -> None:
        from ui.date_select import DateSelectView

        dates = await database.get_dates_with_available_slots(self.mentor["id"])
        await interaction.response.edit_message(
            embed=embeds.date_select_embed(self.mentor, dates),
            view=DateSelectView(self.mentor, dates),
        )
