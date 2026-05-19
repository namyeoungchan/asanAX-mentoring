"""
Q&A 포럼 채널 관리

- 새 글 작성 시: ❓미해결 태그 자동 부여 + [✅ 해결됨] 버튼 게시
- [✅ 해결됨] 버튼: 질문자 또는 운영진/멘토만 클릭 가능 → 태그 변경
- 백그라운드 태스크: QA_UNANSWERED_HOURS 시간 이상 미답변 글 → 알림 역할에게 DM
"""
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

import config
import database

log = logging.getLogger("asanAX.qa")

TAG_UNRESOLVED = "미해결"
TAG_RESOLVED = "해결됨"


def _get_tag(channel: discord.ForumChannel, name: str) -> discord.ForumTag | None:
    return next((t for t in channel.available_tags if t.name == name), None)


# ── View ───────────────────────────────────────────────────────────────────────

class ResolvedView(discord.ui.View):
    """Persistent view with a single '해결됨' button posted in every Q&A thread."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="✅ 해결됨으로 표시",
        style=discord.ButtonStyle.success,
        custom_id="qa:resolved",
    )
    async def mark_resolved(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            return

        # Permission check: OP or staff roles
        is_op = thread.owner_id == interaction.user.id
        is_staff = any(
            r.id in config.QA_NOTIFY_ROLE_IDS
            for r in getattr(interaction.user, "roles", [])
        )
        if not is_op and not is_staff:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="질문 작성자 또는 운영진/멘토만 해결됨으로 표시할 수 있습니다.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        forum = thread.parent
        if not isinstance(forum, discord.ForumChannel):
            return

        # Swap tags: remove 미해결, add 해결됨
        unresolved_tag = _get_tag(forum, TAG_UNRESOLVED)
        resolved_tag = _get_tag(forum, TAG_RESOLVED)

        new_tags = [t for t in thread.applied_tags if t.name != TAG_UNRESOLVED]
        if resolved_tag and resolved_tag not in new_tags:
            new_tags.append(resolved_tag)

        try:
            await thread.edit(applied_tags=new_tags)
        except discord.Forbidden:
            log.warning("Cannot edit tags on thread %s — missing Manage Threads permission", thread.id)

        # Disable button so it can't be clicked again
        button.disabled = True
        button.label = "✅ 해결됨"
        await interaction.response.edit_message(view=self)

        await thread.send(
            embed=discord.Embed(
                title="✅ 해결됨",
                description=f"{interaction.user.mention} 님이 이 질문을 해결됨으로 표시했습니다.",
                color=discord.Color.green(),
            )
        )


# ── Cog ────────────────────────────────────────────────────────────────────────

class QA(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(ResolvedView())
        self.check_unanswered.start()

    def cog_unload(self) -> None:
        self.check_unanswered.cancel()

    # ── New thread ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        if thread.parent_id != config.QA_FORUM_CHANNEL_ID:
            return

        forum = thread.parent
        if not isinstance(forum, discord.ForumChannel):
            return

        # Apply ❓미해결 tag
        unresolved_tag = _get_tag(forum, TAG_UNRESOLVED)
        if unresolved_tag:
            current = list(thread.applied_tags)
            if unresolved_tag not in current:
                try:
                    await thread.edit(applied_tags=current + [unresolved_tag])
                except discord.Forbidden:
                    log.warning("Cannot add tag to thread %s", thread.id)

        # Post the resolve button
        await thread.send(
            embed=discord.Embed(
                description=(
                    "질문이 해결되면 아래 버튼을 눌러주세요.\n"
                    "운영진이 최대한 빠르게 답변 드리겠습니다! 💬"
                ),
                color=discord.Color.from_str("#2B5CE6"),
            ),
            view=ResolvedView(),
        )

    # ── Unanswered alert task ─────────────────────────────────────────────────

    @tasks.loop(hours=1)
    async def check_unanswered(self) -> None:
        try:
            await self._alert_unanswered()
        except Exception as e:
            log.error("QA unanswered check failed: %s", e)

    @check_unanswered.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()

    async def _alert_unanswered(self) -> None:
        forum = self.bot.get_channel(config.QA_FORUM_CHANNEL_ID)
        if not isinstance(forum, discord.ForumChannel):
            return

        threshold = datetime.now(timezone.utc) - timedelta(hours=config.QA_UNANSWERED_HOURS)
        unresolved_tag = _get_tag(forum, TAG_UNRESOLVED)

        # Collect all members with notify roles
        guild = forum.guild
        notify_members: set[discord.Member] = set()
        for role_id in config.QA_NOTIFY_ROLE_IDS:
            role = guild.get_role(role_id)
            if role:
                notify_members.update(role.members)

        if not notify_members:
            return

        for thread in forum.threads:
            # Skip archived or threads created after threshold
            if thread.archived:
                continue
            if not thread.created_at or thread.created_at > threshold:
                continue
            # Skip already-resolved threads
            if unresolved_tag and unresolved_tag not in thread.applied_tags:
                continue
            # Skip if already alerted
            if await database.is_qa_alerted(str(thread.id)):
                continue

            await database.mark_qa_alerted(str(thread.id))

            embed = discord.Embed(
                title="❓ 미답변 질문 알림",
                description=f"**{thread.name}**\n\n[질문 바로가기]({thread.jump_url})",
                color=discord.Color.orange(),
            )
            embed.add_field(
                name="작성 시각",
                value=f"<t:{int(thread.created_at.timestamp())}:R>",
                inline=True,
            )
            embed.set_footer(text=f"{config.QA_UNANSWERED_HOURS}시간 이상 미답변 · 아산 AX")

            for member in notify_members:
                try:
                    await member.send(embed=embed)
                    log.info("Sent unanswered alert for thread %s to %s", thread.id, member)
                except discord.Forbidden:
                    pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(QA(bot))
