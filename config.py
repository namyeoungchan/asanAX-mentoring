import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN: str = os.environ["DISCORD_TOKEN"]
GUILD_ID: int = int(os.environ["GUILD_ID"])
ADMIN_ROLE_ID: int = int(os.environ["ADMIN_ROLE_ID"])
DB_PATH: str = os.getenv("DB_PATH", "data/mentoring.db")
SYNC_GLOBALLY: bool = os.getenv("SYNC_GLOBALLY", "false").lower() == "true"

# ── Team channels (팀-채팅) ───────────────────────────────────────────────────
TEAM_CHANNELS: dict[str, int] = {
    "팀1": 1506304242355277854,
    "팀2": 1507372300247502958,
    "팀3": 1507372438470787082,
    "팀4": 1507372720860434552,
    "팀5": 1507373054710517830
}

# ── Q&A Forum ────────────────────────────────────────────────────────────────
QA_FORUM_CHANNEL_ID: int = int(os.getenv("QA_FORUM_CHANNEL_ID", "1506313964848676966"))
QA_NOTIFY_ROLE_IDS: list[int] = [1503760172995313775, 1503760174207471787]
QA_UNANSWERED_HOURS: int = int(os.getenv("QA_UNANSWERED_HOURS", "24"))

# ── Assignment ────────────────────────────────────────────────────────────────
ASSIGNMENT_DASHBOARD_CHANNEL_ID: int = 1507392706647822438
ASSIGNMENT_SUBMIT_CHANNEL_ID: int = 1507392606571856103

# ── Onboarding ────────────────────────────────────────────────────────────────
# Role assigned immediately on join (restricted access)
STUDENT_ROLE_ID: int = int(os.getenv("STUDENT_ROLE_ID", "1503760182281244743"))
# Channel where the welcome+onboarding message is pinned
ONBOARDING_CHANNEL_ID: int = int(os.environ["ONBOARDING_CHANNEL_ID"])
# Channel where members post their self-introductions
INTRO_CHANNEL_ID: int = int(os.environ["INTRO_CHANNEL_ID"])
# Role granted after self-intro is submitted (unlocks full access); optional
_ONBOARDING_COMPLETE_ROLE_ID: str = os.getenv("ONBOARDING_COMPLETE_ROLE_ID", "")
ONBOARDING_COMPLETE_ROLE_ID: int | None = int(_ONBOARDING_COMPLETE_ROLE_ID) if _ONBOARDING_COMPLETE_ROLE_ID else None
