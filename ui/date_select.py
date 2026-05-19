"""Step 1: User selects a date from available dates."""
from datetime import date as date_cls

import discord
import database
from ui import embeds

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _date_label(ds: str) -> str:
    d = date_cls.fromisoformat(ds)
    return f"{d.month}/{d.day} ({WEEKDAYS[d.weekday()]})"


class DateSelectView(discord.ui.View):
    def __init__(self, mentor: dict, dates: list[str]) -> None:
        super().__init__(timeout=120)
        self.mentor = mentor

        if not dates:
            sel = discord.ui.Select(
                placeholder="예약 가능한 날짜가 없습니다",
                options=[discord.SelectOption(label="없음", value="none")],
                disabled=True,
            )
            sel.callback = self._noop
            self.add_item(sel)
            return

        sel = discord.ui.Select(
            placeholder="날짜를 선택하세요",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=_date_label(ds), value=ds)
                for ds in dates[:25]
            ],
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _noop(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

    async def _on_select(self, interaction: discord.Interaction) -> None:
        from ui.time_select import TimeSelectView

        selected_date = interaction.data["values"][0]  # type: ignore[index]
        slots = await database.get_slots_for_mentor_date(self.mentor["id"], selected_date)

        await interaction.response.edit_message(
            embed=embeds.time_slot_embed(self.mentor, selected_date, slots),
            view=TimeSelectView(self.mentor, selected_date, slots),
        )
