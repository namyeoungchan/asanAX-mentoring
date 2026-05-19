"""Mentor DM approval view — sent when a user requests a mentoring session."""
import discord
import database
from ui import embeds


class RejectModal(discord.ui.Modal, title="신청 반려"):
    reason = discord.ui.TextInput(
        label="반려 사유",
        style=discord.TextStyle.paragraph,
        placeholder="반려 사유를 입력하세요. 빈칸이면 사유 없음으로 전달됩니다.",
        required=False,
        max_length=300,
    )
    alternative = discord.ui.TextInput(
        label="대안 일정 제안 (선택)",
        placeholder="예: 6/2 오후 7시~7시30분 또는 6/3 오후 8시~8시30분",
        required=False,
        max_length=200,
    )

    def __init__(self, slot: dict, mentor: dict, booking_user_id: str, booking_user_name: str) -> None:
        super().__init__()
        self.slot = slot
        self.mentor = mentor
        self.booking_user_id = booking_user_id
        self.booking_user_name = booking_user_name

    async def on_submit(self, interaction: discord.Interaction) -> None:
        booking = await database.reject_booking(self.slot["id"], self.reason.value)
        if not booking:
            await interaction.response.edit_message(
                embed=embeds.error_embed("이미 처리된 신청입니다."), view=None
            )
            return

        # DM user with rejection + alternative
        try:
            user = await interaction.client.fetch_user(int(self.booking_user_id))
            await user.send(
                embed=embeds.booking_rejected_embed(
                    slot=self.slot,
                    mentor=self.mentor,
                    reason=self.reason.value.strip(),
                    alternative=self.alternative.value.strip(),
                )
            )
        except Exception:
            pass

        await interaction.response.edit_message(
            embed=embeds.approval_done_embed(
                approved=False,
                user_name=self.booking_user_name,
                reason=self.reason.value.strip(),
                alternative=self.alternative.value.strip(),
            ),
            view=None,
        )

        from cogs.admin import refresh_all_panels
        await refresh_all_panels(interaction.client)


class ApprovalView(discord.ui.View):
    """Sent to mentor's DM. timeout=7 days."""

    def __init__(self, slot: dict, mentor: dict, booking_user_id: str, booking_user_name: str) -> None:
        super().__init__(timeout=60 * 60 * 24 * 7)
        self.slot = slot
        self.mentor = mentor
        self.booking_user_id = booking_user_id
        self.booking_user_name = booking_user_name

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        booking = await database.approve_booking(self.slot["id"])
        if not booking:
            await interaction.response.edit_message(
                embed=embeds.error_embed("이미 처리된 신청입니다."), view=None
            )
            return

        # DM user: approved
        try:
            user = await interaction.client.fetch_user(int(self.booking_user_id))
            await user.send(
                embed=embeds.booking_approved_embed(self.slot, self.mentor)
            )
        except Exception:
            pass

        await interaction.response.edit_message(
            embed=embeds.approval_done_embed(
                approved=True,
                user_name=self.booking_user_name,
            ),
            view=None,
        )

        from cogs.admin import refresh_all_panels
        await refresh_all_panels(interaction.client)

    @discord.ui.button(label="반려", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            RejectModal(self.slot, self.mentor, self.booking_user_id, self.booking_user_name)
        )
