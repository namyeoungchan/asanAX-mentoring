import discord
import database
from ui import embeds
from ui.confirm_view import BookingConfirmView

PAGE_SIZE = 25


class SlotSelectView(discord.ui.View):
    def __init__(self, mentor: dict, slots: list[dict], bookings_map: dict[int, dict], page: int = 0):
        super().__init__(timeout=120)
        self.mentor = mentor
        self.all_slots = slots
        self.bookings_map = bookings_map
        self.page = page

        # Only unbooked slots are selectable
        available = [s for s in slots if s["id"] not in bookings_map]

        total_pages = max(1, (len(available) + PAGE_SIZE - 1) // PAGE_SIZE)
        page_slots = available[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

        select = discord.ui.Select(
            placeholder="예약할 시간을 선택하세요",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=s["label"][:100],
                    value=str(s["id"]),
                    description=f"슬롯 ID: {s['id']}",
                )
                for s in page_slots
            ]
            if page_slots
            else [discord.SelectOption(label="예약 가능한 슬롯 없음", value="none", default=True)],
            disabled=not page_slots,
        )
        select.callback = self._select_callback
        self.add_item(select)

        if total_pages > 1:
            if page > 0:
                prev_btn = discord.ui.Button(label="이전", style=discord.ButtonStyle.secondary, emoji="◀️", row=1)
                prev_btn.callback = self._prev_page
                self.add_item(prev_btn)
            if page < total_pages - 1:
                next_btn = discord.ui.Button(label="다음", style=discord.ButtonStyle.secondary, emoji="▶️", row=1)
                next_btn.callback = self._next_page
                self.add_item(next_btn)

    async def _select_callback(self, interaction: discord.Interaction) -> None:
        value = interaction.data["values"][0]  # type: ignore[index]
        if value == "none":
            await interaction.response.defer()
            return

        slot_id = int(value)
        slot = await database.get_slot(slot_id)
        if not slot:
            await interaction.response.send_message(
                embed=embeds.error_embed("슬롯 정보를 찾을 수 없습니다."), ephemeral=True
            )
            return

        # Final availability check before showing confirm view
        existing = await database.get_booking_for_slot(slot_id)
        if existing:
            await interaction.response.send_message(
                embed=embeds.booking_taken_embed(), ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=embeds.booking_confirm_embed(slot, self.mentor),
            view=BookingConfirmView(slot, self.mentor),
            ephemeral=True,
        )

    async def _prev_page(self, interaction: discord.Interaction) -> None:
        new_view = SlotSelectView(
            self.mentor, self.all_slots, self.bookings_map, self.page - 1
        )
        await interaction.response.edit_message(
            embed=embeds.slot_list_embed(self.mentor, self.all_slots, self.bookings_map),
            view=new_view,
        )

    async def _next_page(self, interaction: discord.Interaction) -> None:
        new_view = SlotSelectView(
            self.mentor, self.all_slots, self.bookings_map, self.page + 1
        )
        await interaction.response.edit_message(
            embed=embeds.slot_list_embed(self.mentor, self.all_slots, self.bookings_map),
            view=new_view,
        )
