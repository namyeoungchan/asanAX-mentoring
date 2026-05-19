import discord
import database
from ui import embeds
from ui.approval_view import ApprovalView


class BookingConfirmView(discord.ui.View):
    def __init__(self, slot: dict, mentor: dict):
        super().__init__(timeout=60)
        self.slot = slot
        self.mentor = mentor

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    @discord.ui.button(label="신청 확정", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        # Race condition guard
        existing = await database.get_booking_for_slot(self.slot["id"])
        if existing:
            await interaction.response.edit_message(embed=embeds.booking_taken_embed(), view=None)
            return

        success = await database.create_booking(
            slot_id=self.slot["id"],
            user_id=str(interaction.user.id),
            user_name=interaction.user.display_name,
        )
        if not success:
            await interaction.response.edit_message(embed=embeds.booking_taken_embed(), view=None)
            return

        # Show user: request sent
        await interaction.response.edit_message(
            embed=embeds.booking_request_sent_embed(self.slot, self.mentor), view=None
        )

        # DM mentor with approval buttons
        try:
            mentor_user = await interaction.client.fetch_user(int(self.mentor["discord_id"]))
            await mentor_user.send(
                embed=embeds.mentor_notification_embed(self.slot, interaction.user),
                view=ApprovalView(
                    slot=self.slot,
                    mentor=self.mentor,
                    booking_user_id=str(interaction.user.id),
                    booking_user_name=interaction.user.display_name,
                ),
            )
        except Exception:
            # DM 실패해도 신청은 유효 — 관리자가 /admin bookings 로 처리 가능
            pass

        from cogs.admin import refresh_all_panels
        await refresh_all_panels(interaction.client)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="취소됨", description="신청이 취소되었습니다.", color=discord.Color.greyple()
            ),
            view=None,
        )


class CancelConfirmView(discord.ui.View):
    def __init__(self, booking: dict, mentor: dict):
        super().__init__(timeout=60)
        self.booking = booking
        self.mentor = mentor

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    @discord.ui.button(label="신청 취소 확정", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        success = await database.cancel_booking(
            slot_id=self.booking["slot_id"],
            user_id=str(interaction.user.id),
        )
        if success:
            await interaction.response.edit_message(embed=embeds.cancel_success_embed(), view=None)
            from cogs.admin import refresh_all_panels
            await refresh_all_panels(interaction.client)
        else:
            await interaction.response.edit_message(
                embed=embeds.error_embed("취소에 실패했습니다. 이미 취소되었거나 권한이 없습니다."),
                view=None,
            )

    @discord.ui.button(label="돌아가기", style=discord.ButtonStyle.secondary, emoji="↩️")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="취소하지 않음", description="신청이 유지됩니다.", color=discord.Color.greyple()
            ),
            view=None,
        )


class AdminSlotRemoveView(discord.ui.View):
    def __init__(self, slot_id: int, had_booking: bool):
        super().__init__(timeout=60)
        self.slot_id = slot_id
        self.had_booking = had_booking

    @discord.ui.button(label="확인 (신청 포함 삭제)", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.had_booking:
            await database.admin_cancel_booking(self.slot_id)
        await database.deactivate_slot(self.slot_id)
        await interaction.response.edit_message(
            embed=embeds.admin_slot_removed_embed(self.slot_id, self.had_booking), view=None
        )
        from cogs.admin import refresh_all_panels
        await refresh_all_panels(interaction.client)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, emoji="↩️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="취소됨", description="슬롯이 유지됩니다.", color=discord.Color.greyple()
            ),
            view=None,
        )
