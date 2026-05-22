"""
온보딩 플로우
1. 멤버 서버 참여 → 수강생 역할 부여 → DM으로 온보딩 안내 (DM 차단 시 채널 fallback)
2. 버튼 클릭 → 팀 선택 드롭다운 → 자기소개 Modal
3. Modal 제출 → #자기소개 채널에 포스트 → 온보딩완료 역할 부여 → DM 알림
"""
import logging

import discord
from discord.ext import commands

import config
import database

log = logging.getLogger("asanAX.onboarding")

TEAMS = ["팀 1", "팀 2", "팀 3", "팀 4", "팀 5", "팀 6"]


# ── Embeds ─────────────────────────────────────────────────────────────────────

def _welcome_embed(member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="👋 Welcome to FOUNDERS 42",
        description=(
            f"**{member.display_name}** 님, 아산시 AX 글로벌 인재 양성 프로그램에 오신 것을 환영합니다!\n\n"
            "아래 온보딩 체크리스트를 순서대로 완료해주세요."
        ),
        color=discord.Color.from_str("#2B5CE6"),
    )
    embed.add_field(
        name="✅ 온보딩 체크리스트",
        value=(
            "① 디스코드 닉네임 변경 → `실명_팀명`\n"
            "② **자기소개 작성** ← 아래 버튼으로 진행\n"
            "③ 팀 배정 확인\n"
            "④ 협업 툴 접속 확인 (Notion / Google Drive)"
        ),
        inline=False,
    )
    embed.add_field(
        name="💡 이 과정에서 중요한 것",
        value="✔ 완벽보다 실행  ✔ 아이디어보다 검증\n✔ 혼자보다 협업  ✔ 스펙보다 결과물",
        inline=False,
    )
    embed.set_footer(text="자기소개까지 완료하면 모든 채널 접근 권한이 부여됩니다 · 아산 AX")
    return embed


def _intro_submitted_embed(member: discord.Member) -> discord.Embed:
    return discord.Embed(
        title="🎉 온보딩 완료!",
        description=(
            f"**{member.display_name}** 님의 자기소개가 등록되었습니다.\n"
            "이제 모든 채널을 이용할 수 있습니다. 함께해요! 🚀"
        ),
        color=discord.Color.green(),
    )


# ── Modal ──────────────────────────────────────────────────────────────────────

class IntroModal(discord.ui.Modal, title="자기소개 작성"):
    name_field = discord.ui.TextInput(
        label="이름 (실명)",
        placeholder="홍길동",
        max_length=20,
    )
    intro_field = discord.ui.TextInput(
        label="자기소개",
        placeholder="안녕하세요! 저는 ...",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )
    background_field = discord.ui.TextInput(
        label="배경 / 관심사 (선택)",
        placeholder="개발, 디자인, 마케팅 등",
        required=False,
        max_length=200,
    )
    goal_field = discord.ui.TextInput(
        label="이루고 싶은 것 (선택)",
        placeholder="예: AI 서비스 MVP 출시",
        required=False,
        max_length=200,
    )

    def __init__(self, bot: commands.Bot, team: str) -> None:
        super().__init__()
        self.bot = bot
        self.team = team

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await _process_intro(
            bot=self.bot,
            member=interaction.user,  # type: ignore[arg-type]
            guild=interaction.guild,  # type: ignore[arg-type]
            name=self.name_field.value.strip(),
            team=self.team,
            intro=self.intro_field.value.strip(),
            background=self.background_field.value.strip(),
            goal=self.goal_field.value.strip(),
        )
        await interaction.followup.send(
            embed=_intro_submitted_embed(interaction.user),  # type: ignore[arg-type]
            ephemeral=True,
        )


# ── Team select view ───────────────────────────────────────────────────────────

class TeamSelectView(discord.ui.View):
    """Step 1: select team before opening the intro modal."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=120)
        self.bot = bot

        options = [discord.SelectOption(label=t, value=t, emoji="👥") for t in TEAMS]
        select = discord.ui.Select(
            placeholder="소속 팀을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )
        select.callback = self._on_team_select
        self.add_item(select)

    async def _on_team_select(self, interaction: discord.Interaction) -> None:
        team = interaction.data["values"][0]  # type: ignore[index]
        await interaction.response.send_modal(IntroModal(self.bot, team))


# ── Persistent onboarding view ─────────────────────────────────────────────────

class OnboardingView(discord.ui.View):
    """Persistent view — survives bot restarts via custom_id."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="✍️ 자기소개 작성하기",
        style=discord.ButtonStyle.primary,
        custom_id="onboarding:intro",
    )
    async def write_intro(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        record = await database.get_onboarding(str(interaction.user.id))
        if record and record["intro_done"]:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="이미 완료되었습니다",
                    description="자기소개를 이미 작성하셨습니다 🎉",
                    color=discord.Color.green(),
                ),
                ephemeral=True,
            )
            return

        # Show team select first (ephemeral — only visible to the user)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="👥 소속 팀 선택",
                description="먼저 소속 팀을 선택해주세요.",
                color=discord.Color.from_str("#2B5CE6"),
            ),
            view=TeamSelectView(self.bot),
            ephemeral=True,
        )


# ── Helper: process intro submission ──────────────────────────────────────────

async def _process_intro(
    bot: commands.Bot,
    member: discord.Member,
    guild: discord.Guild,
    name: str,
    team: str,
    intro: str,
    background: str,
    goal: str,
) -> None:
    # 1. Post to #자기소개 channel
    intro_ch = guild.get_channel(config.INTRO_CHANNEL_ID)
    if intro_ch and isinstance(intro_ch, discord.TextChannel):
        embed = discord.Embed(
            title=f"👤 {name} ({team})",
            description=intro,
            color=discord.Color.from_str("#2B5CE6"),
        )
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        if background:
            embed.add_field(name="배경 / 관심사", value=background, inline=False)
        if goal:
            embed.add_field(name="이루고 싶은 것", value=goal, inline=False)
        embed.set_footer(text="아산 AX · 자기소개")
        await intro_ch.send(embed=embed)

    # 2. Set nickname to 실명_팀명
    new_nick = f"{name}_{team}"[:32]
    try:
        await member.edit(nick=new_nick, reason="온보딩 자기소개 제출 — 닉네임 자동 설정")
    except discord.Forbidden:
        log.warning("Could not change nickname for %s", member)

    # 3. Mark DB complete
    first_time = await database.complete_onboarding(str(member.id))
    if not first_time:
        return

    # 4. Grant onboarding-complete role
    if config.ONBOARDING_COMPLETE_ROLE_ID:
        role = guild.get_role(config.ONBOARDING_COMPLETE_ROLE_ID)
        if role:
            try:
                await member.add_roles(role, reason="온보딩 완료")
            except discord.Forbidden:
                log.warning("Could not assign complete role to %s", member)

    # 5. DM the member
    try:
        await member.send(embed=_intro_submitted_embed(member))
    except discord.Forbidden:
        pass


# ── Cog ────────────────────────────────────────────────────────────────────────

class Onboarding(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(OnboardingView(self.bot))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild

        # 1. Assign 수강생 role
        student_role = guild.get_role(config.STUDENT_ROLE_ID)
        if student_role:
            try:
                await member.add_roles(student_role, reason="서버 참여 — 수강생 역할 자동 부여")
            except discord.Forbidden:
                log.warning("Cannot assign 수강생 role to %s", member)

        # 2. Record onboarding
        await database.create_onboarding(str(member.id), str(guild.id))

        # 3. DM welcome message (only visible to the member)
        dm_sent = False
        try:
            await member.send(
                embed=_welcome_embed(member),
                view=OnboardingView(self.bot),
            )
            dm_sent = True
        except discord.Forbidden:
            log.warning("Cannot DM %s — falling back to channel", member)

        # 4. Fallback: post in onboarding channel if DM failed
        if not dm_sent:
            onboarding_ch = guild.get_channel(config.ONBOARDING_CHANNEL_ID)
            if onboarding_ch and isinstance(onboarding_ch, discord.TextChannel):
                await onboarding_ch.send(
                    content=f"{member.mention} 님, 환영합니다! (DM이 차단되어 여기에 안내드립니다)",
                    embed=_welcome_embed(member),
                    view=OnboardingView(self.bot),
                )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not message.guild:
            return
        if message.channel.id != config.INTRO_CHANNEL_ID:
            return
        if len(message.content) < 20:
            return

        record = await database.get_onboarding(str(message.author.id))
        if record and record["intro_done"]:
            return

        first_time = await database.complete_onboarding(str(message.author.id))
        if not first_time:
            return

        member = message.author
        guild = message.guild

        if config.ONBOARDING_COMPLETE_ROLE_ID:
            role = guild.get_role(config.ONBOARDING_COMPLETE_ROLE_ID)
            if role:
                try:
                    await member.add_roles(role, reason="온보딩 완료 (자기소개 채널 직접 작성)")  # type: ignore[union-attr]
                except discord.Forbidden:
                    pass

        try:
            await member.send(embed=_intro_submitted_embed(member))  # type: ignore[arg-type]
        except discord.Forbidden:
            pass

        try:
            await message.add_reaction("🎉")
        except discord.Forbidden:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Onboarding(bot))
