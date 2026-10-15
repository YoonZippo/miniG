"""
누가 치즈를 훔쳤을까? (Who Stole the Cheese?) — MINIG Discord Bot Cog
계획서 기준: cheese_thief_discord_bot_plan.md v1.0
"""

import discord
import logging
import asyncio
import secrets
import uuid
from discord.ext import commands
from typing import Dict, List, Optional, Set
from database.manager import DatabaseManager

logger = logging.getLogger('gameBot.cheese_thief')
db = DatabaseManager()

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
MIN_PLAYERS = 4
MAX_PLAYERS = 8
NIGHT_HOUR_SECONDS = 15        # 기본 시각당 대기 시간 (초)
DISCUSSION_SECONDS = 5 * 60    # 기본 낮 토론 시간 (초)
VOTE_SECONDS = 45              # 투표 제한시간 (초)
FOLLOWER_SELECT_SECONDS = 30   # 공범 선택 제한시간 (초)
DICE_INSPECT_SECONDS = 15      # 주사위 조사 제한시간 (초)

# 인원별 공범 수
FOLLOWER_COUNTS: Dict[int, int] = {4: 0, 5: 1, 6: 1, 7: 2, 8: 2}

# 활성 게임 관리
active_cheese_games: Dict[int, 'CheeseThiefGame'] = {}

# ──────────────────────────────────────────────
# 도메인 모델
# ──────────────────────────────────────────────

class PlayerState:
    def __init__(self, member: discord.Member):
        self.member = member
        self.base_role: str = "sleepyhead"   # "thief" | "sleepyhead"
        self.current_team: str = "sleepyhead" # "thief_team" | "sleepyhead"
        self.is_follower: bool = False
        self.dice: List[int] = []             # 4인: 2개, 나머지: 1개
        self.chosen_wake_hour: Optional[int] = None  # 4인 잠꾸러기 선택
        self.wake_hours: Set[int] = set()     # 실제 기상 시각 집합
        self.private_clues: List[str] = []    # 개인 사건 기록
        self.ready: bool = False              # 준비 완료
        self.voted_for: Optional[int] = None  # 투표 대상 user_id
        self.has_voted: bool = False

    @property
    def display_name(self):
        return self.member.display_name

    @property
    def mention(self):
        return self.member.mention


class CheeseThiefGame:
    def __init__(self, host: discord.Member, channel: discord.TextChannel):
        self.session_id = uuid.uuid4().hex
        self.host = host
        self.channel = channel
        self.players: List[PlayerState] = [PlayerState(host)]
        self.phase: str = "LOBBY"
        # LOBBY → ASSIGNING → NIGHT_HOUR_1..6 → FOLLOWERS → DISCUSSION → VOTING → FINISHED → CANCELLED

        # 역할
        self.thief: Optional[PlayerState] = None
        self.followers: List[PlayerState] = []

        # 밤 진행
        self.current_hour: int = 0           # 1~6
        self.cheese_stolen_at: int = 0       # 도둑이 깬 시각(4인: 첫 번째)
        self.awake_at: Dict[int, List[PlayerState]] = {h: [] for h in range(1, 7)}
        self.witness_hour: Optional[int] = None  # 도둑 기상 시각

        # 타이머
        self.timer_task: Optional[asyncio.Task] = None

        # 설정
        self.night_hour_seconds: int = NIGHT_HOUR_SECONDS
        self.discussion_seconds: int = DISCUSSION_SECONDS

        # 준비 추적
        self._role_ready_count: int = 0
        self._discussion_ready: Set[int] = set()

        # 4인 기상 선택 추적
        self._pending_wake_choices: Set[int] = set()   # 아직 선택 안 한 잠꾸러기 user_id

        # 주사위 조사 / 공범 선택 인터랙션 이벤트
        self._inspect_done: asyncio.Event = asyncio.Event()
        self._follower_done: asyncio.Event = asyncio.Event()

        # 진행 중 메시지
        self.lobby_message: Optional[discord.Message] = None
        self.night_message: Optional[discord.Message] = None
        self.discussion_message: Optional[discord.Message] = None
        self.vote_message: Optional[discord.Message] = None

    # ─── 플레이어 조회 ───
    def get_player(self, user_id: int) -> Optional[PlayerState]:
        for p in self.players:
            if p.member.id == user_id:
                return p
        return None

    def in_game(self, user_id: int) -> bool:
        return self.get_player(user_id) is not None

    @property
    def player_count(self) -> int:
        return len(self.players)


# ──────────────────────────────────────────────
# 순수 도메인 함수
# ──────────────────────────────────────────────

def assign_roles_and_dice(game: CheeseThiefGame):
    """역할·주사위 배정 (보안 난수)"""
    n = game.player_count

    # 치즈 도둑 선택
    thief_ps = secrets.choice(game.players)
    thief_ps.base_role = "thief"
    thief_ps.current_team = "thief_team"
    game.thief = thief_ps

    # 주사위 배정
    if n == 4:
        # 모두 주사위 2개
        for ps in game.players:
            ps.dice = [secrets.randbelow(6) + 1, secrets.randbelow(6) + 1]
    else:
        for ps in game.players:
            ps.dice = [secrets.randbelow(6) + 1]

    # 기상 시각 계산
    compute_wake_hours(game)


def compute_wake_hours(game: CheeseThiefGame):
    """주사위·선택에서 기상 시각 집합 계산"""
    n = game.player_count

    for ps in game.players:
        if n == 4:
            if ps.base_role == "thief":
                # 도둑: 두 주사위 모두 기상
                ps.wake_hours = set(ps.dice)
            else:
                # 잠꾸러기: chosen_wake_hour (아직 없으면 임시 비워둠)
                if ps.chosen_wake_hour is not None:
                    ps.wake_hours = {ps.chosen_wake_hour}
        else:
            ps.wake_hours = {ps.dice[0]}

    # 4인 전이 아닌 경우 awake_at 바로 계산
    if n != 4:
        _build_awake_at(game)


def _build_awake_at(game: CheeseThiefGame):
    """awake_at 딕셔너리 재계산"""
    for h in range(1, 7):
        game.awake_at[h] = []
    for ps in game.players:
        for h in ps.wake_hours:
            if 1 <= h <= 6:
                game.awake_at[h].append(ps)

    # 치즈 도둑 기상 시각 확정 (첫 번째 기상 = 절도 시각)
    thief_hours = sorted(game.thief.wake_hours)
    game.cheese_stolen_at = thief_hours[0] if thief_hours else 0
    game.witness_hour = game.cheese_stolen_at


def compute_night_observation(game: CheeseThiefGame, hour: int, ps: PlayerState) -> List[str]:
    """
    특정 시각의 개인 관찰 사건 목록 반환.
    규칙 §3.3 전체 구현.
    """
    clues: List[str] = []
    n = game.player_count
    awake = game.awake_at[hour]

    # 다른 기상자 목록
    co_awake = [p for p in awake if p.member.id != ps.member.id]
    if co_awake:
        names = ", ".join(p.display_name for p in co_awake)
        clues.append(f"👀 **{hour}시**에 함께 깨어있는 사람: {names}")
    else:
        clues.append(f"👀 **{hour}시** — 혼자 깨어있습니다.")

    # 치즈 상태
    if hour < game.cheese_stolen_at:
        clues.append("🧀 치즈가 아직 있습니다.")
    elif hour == game.cheese_stolen_at:
        # 도둑이 이 시각에 깨어있어 절도 발생
        if game.thief in awake:
            if ps == game.thief:
                clues.append("🧀 당신이 치즈를 훔쳤습니다!")
            else:
                clues.append("🚨 **치즈 도난 목격!** 누군가 치즈를 훔쳐갔습니다!")
        else:
            clues.append("🧀 치즈가 있습니다.")
    else:
        # 도둑 기상 이후
        if ps == game.thief and len(sorted(game.thief.wake_hours)) > 1:
            # 4인 두 번째 기상
            clues.append("🧀 치즈는 이미 없습니다. (이미 훔쳤습니다)")
        else:
            clues.append("🕳️ 치즈가 없습니다!")

    # 단독 기상 잠꾸러기 → 주사위 조사 (5~8인)
    # (실제 조사 선택은 process_hour에서 별도 처리)

    return clues


# ──────────────────────────────────────────────
# UI Views
# ──────────────────────────────────────────────

class CheeseLobbyView(discord.ui.View):
    def __init__(self, game: CheeseThiefGame):
        super().__init__(timeout=None)
        self.game = game

    def _build_embed(self) -> discord.Embed:
        player_list = "\n".join(
            f"{'👑 ' if p.member == self.game.host else '• '}{p.mention}"
            for p in self.game.players
        )
        embed = discord.Embed(
            title="🧀 누가 치즈를 훔쳤을까?",
            description=(
                "버튼을 눌러 게임에 참가하세요!\n"
                f"최소 **{MIN_PLAYERS}명**, 최대 **{MAX_PLAYERS}명**.\n\n"
                "🎮 **게임 소개**\n"
                "치즈 도둑이 숨어들었습니다! 도둑의 정체를 밝혀내세요.\n"
                "도둑은 들키지 않고 살아남아야 합니다.\n\n"
                f"⏱️ 밤 단계: 시각당 **{self.game.night_hour_seconds}초** | "
                f"토론: **{self.game.discussion_seconds // 60}분**"
            ),
            color=0xF4A261
        )
        embed.add_field(
            name=f"참가자 ({len(self.game.players)}명)",
            value=player_list or "없음",
            inline=False
        )
        embed.set_footer(text="방장이 게임을 시작할 수 있습니다. (4명 이상)")
        return embed

    @discord.ui.button(label="참가", style=discord.ButtonStyle.success, custom_id="cheese_join", emoji="🙋")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.phase != "LOBBY":
            await interaction.response.send_message("게임이 이미 시작되었습니다!", ephemeral=True)
            return
        # 다른 채널에서 이미 참가 중인지 체크
        for ch_id, g in active_cheese_games.items():
            if ch_id != self.game.channel.id and g.phase != "FINISHED" and g.phase != "CANCELLED":
                if g.in_game(interaction.user.id):
                    await interaction.response.send_message(
                        "이미 다른 채널에서 치즈 게임에 참가 중입니다!", ephemeral=True
                    )
                    return

        if self.game.in_game(interaction.user.id):
            await interaction.response.send_message("이미 참가 중입니다!", ephemeral=True)
            return
        if len(self.game.players) >= MAX_PLAYERS:
            await interaction.response.send_message("인원이 가득 찼습니다!", ephemeral=True)
            return

        self.game.players.append(PlayerState(interaction.user))
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="나가기", style=discord.ButtonStyle.secondary, custom_id="cheese_leave", emoji="🚪")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.phase != "LOBBY":
            await interaction.response.send_message("게임이 이미 시작된 후에는 나갈 수 없습니다.", ephemeral=True)
            return
        if interaction.user == self.game.host:
            await interaction.response.send_message("방장은 나갈 수 없습니다. 취소하려면 게임 취소 버튼을 누르세요.", ephemeral=True)
            return
        ps = self.game.get_player(interaction.user.id)
        if ps is None:
            await interaction.response.send_message("참가하지 않으셨습니다.", ephemeral=True)
            return
        self.game.players.remove(ps)
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="규칙 보기", style=discord.ButtonStyle.secondary, custom_id="cheese_rules", emoji="📜")
    async def rules_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📜 누가 치즈를 훔쳤을까? — 규칙",
            color=0x2ECC71,
            description=(
                "**🧀 목표**\n"
                "• 잠꾸러기 팀: 도둑을 최다 득표에 포함시키기\n"
                "• 도둑 팀: 투표에서 살아남기\n\n"
                "**🌙 밤 단계 (1~6시)**\n"
                "• 주사위로 기상 시각이 정해집니다.\n"
                "• 같은 시각에 깬 사람끼리만 서로 보입니다.\n"
                "• 도둑과 같이 깬 사람은 도난을 목격합니다!\n"
                "• 혼자 깬 잠꾸러기(5~8인)는 타인 주사위 1개를 몰래 볼 수 있습니다.\n\n"
                "**👥 공범 (인원별 상이)**\n"
                "• 4인: 공범 없음\n"
                "• 5인: 도둑과 같이 깬 잠꾸러기 중 1명 (해당자 없으면 0명)\n"
                "• 6인: 도둑이 1명 지정\n"
                "• 7인: 도둑이 2명 지정 (공범은 도둑 신원 모름)\n"
                "• 8인: 도둑이 2명 지정\n\n"
                "**☀️ 낮 토론 → 투표**\n"
                "• 자유 토론 후 동시 비공개 투표\n"
                "• 최다 득표자(동률 모두) 공개 → 도둑 포함 여부로 승패 결정\n"
                "• 유효표 0표 = 무효판"
            )
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="게임 시작", style=discord.ButtonStyle.primary, custom_id="cheese_start", emoji="▶️")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 게임을 시작할 수 있습니다!", ephemeral=True)
            return
        if self.game.phase != "LOBBY":
            await interaction.response.send_message("이미 시작된 게임입니다.", ephemeral=True)
            return
        if len(self.game.players) < MIN_PLAYERS:
            await interaction.response.send_message(f"최소 {MIN_PLAYERS}명이 필요합니다! (현재 {len(self.game.players)}명)", ephemeral=True)
            return

        self.game.phase = "ASSIGNING"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

        # 게임 시작
        asyncio.create_task(run_cheese_game(self.game, interaction))

    @discord.ui.button(label="게임 취소", style=discord.ButtonStyle.danger, custom_id="cheese_cancel", emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 게임을 취소할 수 있습니다!", ephemeral=True)
            return
        self.game.phase = "CANCELLED"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(
            embed=discord.Embed(title="🛑 치즈 게임 취소됨", description="방장이 게임을 취소했습니다.", color=0xFF0000)
        )
        active_cheese_games.pop(self.game.channel.id, None)


class CheeseNightView(discord.ui.View):
    """밤 단계 '내 정보 확인' 버튼"""
    def __init__(self, game: CheeseThiefGame, hour: int):
        super().__init__(timeout=None)
        self.game = game
        self.hour = hour

    @discord.ui.button(label="🌙 내 밤 정보 확인", style=discord.ButtonStyle.primary, custom_id="cheese_night_info")
    async def night_info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ps = self.game.get_player(interaction.user.id)
        if ps is None:
            await interaction.response.send_message("이 게임의 참가자가 아닙니다.", ephemeral=True)
            return
        h = self.hour
        if h not in ps.wake_hours:
            await interaction.response.send_message(
                f"😴 **{h}시** — 당신은 자고 있습니다. 아무것도 보이지 않습니다.",
                ephemeral=True
            )
            return
        clues = compute_night_observation(self.game, h, ps)
        embed = discord.Embed(
            title=f"🌙 {h}시 관찰 기록",
            description="\n".join(clues),
            color=0x2C3E50
        )
        embed.set_footer(text="이 정보는 나에게만 보입니다.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class MyCluesView(discord.ui.View):
    """낮 토론 중 '내 단서 보기' 버튼"""
    def __init__(self, game: CheeseThiefGame):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="🔍 내 단서 보기", style=discord.ButtonStyle.secondary, custom_id="cheese_my_clues")
    async def my_clues(self, interaction: discord.Interaction, button: discord.ui.Button):
        ps = self.game.get_player(interaction.user.id)
        if ps is None:
            await interaction.response.send_message("이 게임의 참가자가 아닙니다.", ephemeral=True)
            return
        if not ps.private_clues:
            await interaction.response.send_message("기록된 단서가 없습니다.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🗂️ 나의 사건 기록부",
            description="\n".join(ps.private_clues),
            color=0x8E44AD
        )
        embed.set_footer(text="이 정보는 나에게만 보입니다.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="✅ 투표 준비", style=discord.ButtonStyle.success, custom_id="cheese_vote_ready")
    async def vote_ready(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.phase != "DISCUSSION":
            await interaction.response.send_message("토론 중이 아닙니다.", ephemeral=True)
            return
        ps = self.game.get_player(interaction.user.id)
        if ps is None:
            await interaction.response.send_message("이 게임의 참가자가 아닙니다.", ephemeral=True)
            return
        self.game._discussion_ready.add(interaction.user.id)
        ready_count = len(self.game._discussion_ready)
        total = len(self.game.players)
        await interaction.response.send_message(
            f"투표 준비 완료! 현재 준비 완료: {ready_count}/{total}명",
            ephemeral=True
        )
        # 전원 준비 시 토론 즉시 종료
        if ready_count >= total and self.game.phase == "DISCUSSION":
            if self.game.timer_task and not self.game.timer_task.done():
                self.game.timer_task.cancel()


class WakeHourSelectView(discord.ui.View):
    """4인전: 잠꾸러기 기상 시각 선택"""
    def __init__(self, game: CheeseThiefGame, ps: PlayerState, dice: List[int]):
        super().__init__(timeout=30)
        self.game = game
        self.ps = ps
        self.done = False

        for hour in dice:
            self.add_item(WakeHourButton(hour, ps, game, self))

    async def on_timeout(self):
        if not self.done:
            # 무작위 선택
            import secrets as _sec
            self.ps.chosen_wake_hour = _sec.choice(self.ps.dice)
            self.ps.wake_hours = {self.ps.chosen_wake_hour}
            self.game._pending_wake_choices.discard(self.ps.member.id)


class WakeHourButton(discord.ui.Button):
    def __init__(self, hour: int, ps: PlayerState, game: CheeseThiefGame, parent: WakeHourSelectView):
        super().__init__(
            label=f"{hour}시",
            style=discord.ButtonStyle.primary,
            custom_id=f"cheese_wake_{ps.member.id}_{hour}"
        )
        self.hour = hour
        self.ps = ps
        self.game = game
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ps.member.id:
            await interaction.response.send_message("본인의 선택창이 아닙니다.", ephemeral=True)
            return
        if self.parent_view.done:
            await interaction.response.send_message("이미 선택하셨습니다.", ephemeral=True)
            return

        self.parent_view.done = True
        self.ps.chosen_wake_hour = self.hour
        self.ps.wake_hours = {self.hour}
        self.game._pending_wake_choices.discard(self.ps.member.id)

        await interaction.response.send_message(
            f"⏰ **{self.hour}시**에 기상하도록 설정했습니다!", ephemeral=True
        )


class DiceInspectView(discord.ui.View):
    """단독 기상 잠꾸러기: 주사위 조사 대상 선택"""
    def __init__(self, game: CheeseThiefGame, inspector: PlayerState, candidates: List[PlayerState]):
        super().__init__(timeout=DICE_INSPECT_SECONDS)
        self.game = game
        self.inspector = inspector
        self.done = False

        for c in candidates:
            btn = discord.ui.Button(
                label=c.display_name,
                style=discord.ButtonStyle.secondary,
                custom_id=f"cheese_inspect_{inspector.member.id}_{c.member.id}"
            )
            btn.callback = self._make_callback(c)
            self.add_item(btn)

        # 포기 버튼
        skip_btn = discord.ui.Button(
            label="조사 포기",
            style=discord.ButtonStyle.danger,
            custom_id=f"cheese_inspect_skip_{inspector.member.id}"
        )
        skip_btn.callback = self._skip_callback
        self.add_item(skip_btn)

    def _make_callback(self, target: PlayerState):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.inspector.member.id:
                await interaction.response.send_message("본인의 선택창이 아닙니다.", ephemeral=True)
                return
            if self.done:
                await interaction.response.send_message("이미 선택하셨습니다.", ephemeral=True)
                return
            self.done = True
            self.stop()
            dice_str = ", ".join(str(d) for d in target.dice)
            clue = f"🎲 [{self.game.current_hour}시] {target.display_name}의 주사위: **{dice_str}**"
            self.inspector.private_clues.append(clue)
            embed = discord.Embed(
                title="🎲 주사위 조사 결과",
                description=clue,
                color=0xE67E22
            )
            embed.set_footer(text="이 정보는 나에게만 보입니다.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            self.game._inspect_done.set()
        return callback

    async def _skip_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.inspector.member.id:
            await interaction.response.send_message("본인의 선택창이 아닙니다.", ephemeral=True)
            return
        self.done = True
        self.stop()
        await interaction.response.send_message("주사위 조사를 포기했습니다.", ephemeral=True)
        self.game._inspect_done.set()

    async def on_timeout(self):
        if not self.done:
            self.done = True
            self.game._inspect_done.set()


class FollowerSelectView(discord.ui.View):
    """도둑: 공범 선택"""
    def __init__(self, game: CheeseThiefGame, thief: PlayerState, candidates: List[PlayerState], count: int):
        super().__init__(timeout=FOLLOWER_SELECT_SECONDS)
        self.game = game
        self.thief = thief
        self.candidates = candidates
        self.count = count
        self.selected: List[PlayerState] = []
        self.done = False

        self.select = discord.ui.Select(
            placeholder=f"공범 {count}명 선택",
            min_values=count,
            max_values=count,
            options=[
                discord.SelectOption(label=c.display_name, value=str(c.member.id))
                for c in candidates
            ],
            custom_id=f"cheese_follower_select_{thief.member.id}"
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.thief.member.id:
            await interaction.response.send_message("도둑만 선택할 수 있습니다.", ephemeral=True)
            return
        if self.done:
            await interaction.response.send_message("이미 선택하셨습니다.", ephemeral=True)
            return

        self.done = True
        self.stop()
        chosen_ids = [int(v) for v in self.select.values]
        self.selected = [p for p in self.candidates if p.member.id in chosen_ids]

        await interaction.response.send_message(
            f"공범을 선택했습니다: {', '.join(p.display_name for p in self.selected)}",
            ephemeral=True
        )
        # 게임에 반영
        for ps in self.selected:
            ps.is_follower = True
            ps.current_team = "thief_team"
        self.game.followers = self.selected
        self.game._follower_done.set()

    async def on_timeout(self):
        if not self.done:
            self.done = True
            # 무작위 선택
            chosen = secrets.SystemRandom().sample(self.candidates, min(self.count, len(self.candidates)))
            for ps in chosen:
                ps.is_follower = True
                ps.current_team = "thief_team"
            self.game.followers = chosen
            self.game._follower_done.set()


class VoteView(discord.ui.View):
    """비공개 투표 뷰"""
    def __init__(self, game: CheeseThiefGame):
        super().__init__(timeout=None)
        self.game = game

        options = [
            discord.SelectOption(
                label=ps.display_name,
                value=str(ps.member.id),
                description="이 사람이 도둑이라고 생각합니다"
            )
            for ps in game.players
        ]
        self.select = discord.ui.Select(
            placeholder="도둑으로 의심되는 사람을 선택하세요 (자신 제외)",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="cheese_vote_select"
        )
        self.select.callback = self.vote_callback
        self.add_item(self.select)

    async def vote_callback(self, interaction: discord.Interaction):
        ps = self.game.get_player(interaction.user.id)
        if ps is None:
            await interaction.response.send_message("이 게임의 참가자가 아닙니다.", ephemeral=True)
            return
        if self.game.phase != "VOTING":
            await interaction.response.send_message("투표 단계가 아닙니다.", ephemeral=True)
            return

        target_id = int(self.select.values[0])
        if target_id == interaction.user.id:
            await interaction.response.send_message("자신에게는 투표할 수 없습니다!", ephemeral=True)
            return

        target_ps = self.game.get_player(target_id)
        if target_ps is None:
            await interaction.response.send_message("대상을 찾을 수 없습니다.", ephemeral=True)
            return

        # 기존 투표 덮어쓰기 허용
        ps.voted_for = target_id
        ps.has_voted = True

        await interaction.response.send_message(
            f"✅ **{target_ps.display_name}**에게 투표했습니다. (변경 가능)",
            ephemeral=True
        )

        # 전원 투표 시 즉시 마감
        voted_count = sum(1 for p in self.game.players if p.has_voted)
        if voted_count >= len(self.game.players):
            if self.game.timer_task and not self.game.timer_task.done():
                self.game.timer_task.cancel()


# ──────────────────────────────────────────────
# 게임 진행 로직
# ──────────────────────────────────────────────

async def run_cheese_game(game: CheeseThiefGame, start_interaction: discord.Interaction):
    """전체 게임 진행 코루틴"""
    channel = game.channel

    try:
        # ── 1. 역할·주사위 배정 ──────────────────────
        assign_roles_and_dice(game)

        # 4인전: 잠꾸러기들에게 기상 시각 선택 요청
        n = game.player_count
        if n == 4:
            await _prompt_wake_choices(game, channel)
            # 선택 완료 후 awake_at 재계산
            _build_awake_at(game)

        # 역할 정보 ephemeral 전송
        await _send_role_info(game, channel)

        # 준비 대기 (15초)
        await asyncio.sleep(5)

        # ── 2. 밤 단계 ────────────────────────────────
        await channel.send(
            embed=discord.Embed(
                title="🌙 밤이 찾아왔습니다...",
                description="모든 사람이 잠들었습니다. `🌙 내 밤 정보 확인` 버튼으로 각 시각의 관찰 기록을 확인하세요.",
                color=0x1A1A2E
            )
        )

        for hour in range(1, 7):
            await _process_hour(game, channel, hour)

        # ── 3. 공범 지정 ──────────────────────────────
        await _assign_followers(game, channel)

        # ── 4. 낮 토론 ────────────────────────────────
        await _run_discussion(game, channel)

        # ── 5. 투표 ───────────────────────────────────
        await _run_voting(game, channel)

        # ── 6. 결과 ───────────────────────────────────
        await _show_results(game, channel)

    except asyncio.CancelledError:
        logger.info(f"치즈게임 취소됨 (channel={game.channel.id})")
    except Exception as e:
        logger.exception(f"치즈게임 오류 (channel={game.channel.id}): {e}")
        await channel.send(
            embed=discord.Embed(
                title="⚠️ 오류 발생",
                description=f"게임 진행 중 오류가 발생했습니다: {e}",
                color=0xFF0000
            )
        )
    finally:
        active_cheese_games.pop(game.channel.id, None)


async def _prompt_wake_choices(game: CheeseThiefGame, channel: discord.TextChannel):
    """4인전: 잠꾸러기 기상 시각 선택 ephemeral 요청"""
    sleepyheads = [ps for ps in game.players if ps.base_role == "sleepyhead"]
    game._pending_wake_choices = {ps.member.id for ps in sleepyheads}

    announce_embed = discord.Embed(
        title="🌙 밤 준비 중...",
        description=(
            "**4인 규칙:** 잠꾸러기는 두 주사위 중 하나를 기상 시각으로 선택합니다.\n"
            "도둑은 두 시각 모두 기상합니다.\n\n"
            "잠꾸러기분들께 선택 요청을 보냈습니다. (30초 내 미선택 시 자동 배정)"
        ),
        color=0x2C3E50
    )
    await channel.send(embed=announce_embed)

    for ps in sleepyheads:
        view = WakeHourSelectView(game, ps, ps.dice)
        try:
            await ps.member.send(
                embed=discord.Embed(
                    title="⏰ 기상 시각 선택",
                    description=(
                        f"당신의 주사위: **{ps.dice[0]}시**, **{ps.dice[1]}시**\n"
                        "**두 시각 중 하나**를 선택해 기상 시각을 정하세요."
                    ),
                    color=0x3498DB
                ),
                view=view
            )
        except discord.Forbidden:
            # DM 차단 시 자동 선택
            ps.chosen_wake_hour = secrets.choice(ps.dice)
            ps.wake_hours = {ps.chosen_wake_hour}
            game._pending_wake_choices.discard(ps.member.id)

    # 최대 35초 대기
    deadline = 35
    elapsed = 0
    while game._pending_wake_choices and elapsed < deadline:
        await asyncio.sleep(1)
        elapsed += 1

    # 미선택자 자동 처리
    for ps in sleepyheads:
        if ps.member.id in game._pending_wake_choices:
            ps.chosen_wake_hour = secrets.choice(ps.dice)
            ps.wake_hours = {ps.chosen_wake_hour}
            game._pending_wake_choices.discard(ps.member.id)


async def _send_role_info(game: CheeseThiefGame, channel: discord.TextChannel):
    """역할 정보 ephemeral 전송"""
    announce = await channel.send(
        embed=discord.Embed(
            title="🎭 역할 배정 완료!",
            description="`내 역할 보기` 버튼을 눌러 본인 역할을 확인하세요.",
            color=0xE67E22
        ),
        view=RoleRevealView(game)
    )
    await asyncio.sleep(10)


class RoleRevealView(discord.ui.View):
    def __init__(self, game: CheeseThiefGame):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="🃏 내 역할 보기", style=discord.ButtonStyle.primary, custom_id="cheese_role_reveal")
    async def role_reveal(self, interaction: discord.Interaction, button: discord.ui.Button):
        ps = self.game.get_player(interaction.user.id)
        if ps is None:
            await interaction.response.send_message("이 게임의 참가자가 아닙니다.", ephemeral=True)
            return

        n = self.game.player_count

        if ps.base_role == "thief":
            dice_str = ", ".join(str(d) for d in ps.dice)
            desc = (
                f"당신은 **🧀 치즈 도둑**입니다!\n\n"
                f"🎲 주사위: **{dice_str}**\n"
                f"{'⏰ 두 시각 모두 기상합니다.' if n == 4 else f'⏰ **{ps.dice[0]}시**에 기상합니다.'}\n\n"
                f"들키지 않고 살아남으세요!"
            )
            color = 0xE74C3C
            title = "🦹 당신의 역할: 치즈 도둑"
        else:
            dice_str = ", ".join(str(d) for d in ps.dice)
            if n == 4:
                wake_info = f"선택한 기상 시각: **{ps.chosen_wake_hour}시**" if ps.chosen_wake_hour else f"주사위: **{dice_str}** (선택 대기 중)"
            else:
                wake_info = f"⏰ **{ps.dice[0]}시**에 기상합니다."
            desc = (
                f"당신은 **😴 잠꾸러기**입니다.\n\n"
                f"🎲 주사위: **{dice_str}**\n"
                f"{wake_info}\n\n"
                f"치즈 도둑을 찾아내세요!"
            )
            color = 0x2ECC71
            title = "😴 당신의 역할: 잠꾸러기"

        embed = discord.Embed(title=title, description=desc, color=color)
        embed.set_footer(text="이 정보는 나에게만 보입니다.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def _process_hour(game: CheeseThiefGame, channel: discord.TextChannel, hour: int):
    """밤 시각 1개 처리"""
    game.current_hour = hour
    n = game.player_count
    awake = game.awake_at[hour]

    # 공개 공지 (누가 깼는지는 절대 노출 X)
    night_embed = discord.Embed(
        title=f"🕰️ 새벽 {hour}시...",
        description="누군가 눈을 뜹니다... `🌙 내 밤 정보 확인`으로 본인 관찰 기록을 확인하세요.",
        color=0x1A1A2E
    )
    night_view = CheeseNightView(game, hour)
    msg = await channel.send(embed=night_embed, view=night_view)

    # 단독 기상 잠꾸러기 주사위 조사 (5~8인)
    if n >= 5 and len(awake) == 1 and awake[0] != game.thief:
        inspector = awake[0]
        candidates = [p for p in game.players if p.member.id != inspector.member.id]
        game._inspect_done.clear()
        inspect_view = DiceInspectView(game, inspector, candidates)

        try:
            await inspector.member.send(
                embed=discord.Embed(
                    title="🎲 주사위 조사 기회!",
                    description=(
                        f"**{hour}시**에 혼자 깨어있습니다.\n"
                        "다른 참가자 중 한 명의 주사위를 몰래 확인할 수 있습니다.\n"
                        f"({DICE_INSPECT_SECONDS}초 내 미선택 시 포기)"
                    ),
                    color=0xE67E22
                ),
                view=inspect_view
            )
            # 타이머 혹은 선택 완료 대기
            try:
                await asyncio.wait_for(game._inspect_done.wait(), timeout=DICE_INSPECT_SECONDS + 2)
            except asyncio.TimeoutError:
                pass
        except discord.Forbidden:
            pass  # DM 차단 시 조사 포기

    # 관찰 clue를 private_clues에 축적
    for ps in awake:
        clues = compute_night_observation(game, hour, ps)
        ps.private_clues.extend(clues)

    # 시간 대기
    await asyncio.sleep(game.night_hour_seconds)


async def _assign_followers(game: CheeseThiefGame, channel: discord.TextChannel):
    """공범 지정 단계"""
    game.phase = "FOLLOWERS"
    n = game.player_count

    if n == 4:
        # 공범 없음
        await channel.send(
            embed=discord.Embed(
                title="☀️ 날이 밝아옵니다...",
                description="(4인전: 공범이 없습니다)",
                color=0xF39C12
            )
        )
        return

    follower_count = FOLLOWER_COUNTS[n]
    thief = game.thief

    if n == 5:
        # 도둑 기상 시각에 함께 깬 잠꾸러기 후보
        thief_hour = game.cheese_stolen_at
        candidates = [
            p for p in game.awake_at[thief_hour]
            if p != thief
        ]
        if not candidates:
            await channel.send(
                embed=discord.Embed(
                    title="☀️ 날이 밝아옵니다...",
                    description="(5인전: 도둑과 같이 깬 잠꾸러기가 없어 공범이 발생하지 않습니다)",
                    color=0xF39C12
                )
            )
            return
        if len(candidates) == 1:
            # 자동 지정
            chosen = candidates[0]
            chosen.is_follower = True
            chosen.current_team = "thief_team"
            game.followers = [chosen]
            await _notify_followers(game, channel, n)
            return
        # 후보 다수: 선택
        await _thief_select_followers(game, channel, candidates, 1, n)
    else:
        # 6~8인: 도둑이 자유롭게 지정
        candidates = [p for p in game.players if p != thief]
        await _thief_select_followers(game, channel, candidates, follower_count, n)


async def _thief_select_followers(
    game: CheeseThiefGame,
    channel: discord.TextChannel,
    candidates: List[PlayerState],
    count: int,
    n: int
):
    """도둑에게 공범 선택 ephemeral 전송"""
    game._follower_done.clear()

    if len(candidates) <= count:
        # 후보 수 == 공범 수면 자동 선택
        for ps in candidates:
            ps.is_follower = True
            ps.current_team = "thief_team"
        game.followers = candidates
        game._follower_done.set()
    else:
        view = FollowerSelectView(game, game.thief, candidates, count)
        try:
            await game.thief.member.send(
                embed=discord.Embed(
                    title="🤝 공범 선택",
                    description=(
                        f"공범을 **{count}명** 선택하세요.\n"
                        f"({FOLLOWER_SELECT_SECONDS}초 내 미선택 시 자동 배정)"
                    ),
                    color=0xE74C3C
                ),
                view=view
            )
        except discord.Forbidden:
            # DM 차단 시 자동
            chosen = secrets.SystemRandom().sample(candidates, count)
            for ps in chosen:
                ps.is_follower = True
                ps.current_team = "thief_team"
            game.followers = chosen
            game._follower_done.set()

        try:
            await asyncio.wait_for(game._follower_done.wait(), timeout=FOLLOWER_SELECT_SECONDS + 2)
        except asyncio.TimeoutError:
            pass

    await _notify_followers(game, channel, n)


async def _notify_followers(game: CheeseThiefGame, channel: discord.TextChannel, n: int):
    """공범/도둑에게 신원 통보"""
    thief = game.thief
    followers = game.followers

    # 도둑 → 공범 신원 알림 (7인 제외 시 공범도 도둑 신원 앎)
    if followers:
        follower_names = ", ".join(f.display_name for f in followers)
        thief_msg = f"당신의 공범: **{follower_names}**"
        try:
            await thief.member.send(
                embed=discord.Embed(
                    title="🤝 공범 지정 완료",
                    description=thief_msg,
                    color=0xE74C3C
                )
            )
        except discord.Forbidden:
            pass

        for f in followers:
            if n == 7:
                # 7인: 공범은 도둑 신원 모름, 공범끼리만 앎
                sibling_names = ", ".join(s.display_name for s in followers if s != f)
                desc = (
                    f"당신은 **공범**입니다!\n"
                    f"(도둑의 신원은 알 수 없습니다)\n"
                    + (f"다른 공범: **{sibling_names}**" if sibling_names else "")
                )
            else:
                desc = (
                    f"당신은 **공범**입니다!\n"
                    f"도둑: **{thief.display_name}**\n"
                    + (
                        f"다른 공범: **{', '.join(s.display_name for s in followers if s != f)}**"
                        if len(followers) > 1 else ""
                    )
                )
            try:
                await f.member.send(
                    embed=discord.Embed(
                        title="🦹 당신은 공범입니다!",
                        description=desc,
                        color=0xE74C3C
                    )
                )
            except discord.Forbidden:
                pass

    await channel.send(
        embed=discord.Embed(
            title="☀️ 날이 밝아옵니다...",
            description="밤이 끝났습니다. 치즈가 사라졌습니다! 도둑을 찾아내세요.",
            color=0xF39C12
        )
    )


async def _run_discussion(game: CheeseThiefGame, channel: discord.TextChannel):
    """낮 토론 단계"""
    game.phase = "DISCUSSION"
    game._discussion_ready.clear()

    minutes = game.discussion_seconds // 60
    embed = discord.Embed(
        title="🌅 낮 토론 시작!",
        description=(
            "🧀 **치즈가 사라졌습니다!** 도둑을 찾아내세요.\n\n"
            f"⏱️ 토론 시간: **{minutes}분**\n"
            "🎤 음성 채널에서 자유롭게 토론하세요.\n"
            "✅ **투표 준비** 버튼을 누르면 전원 준비 시 즉시 투표가 시작됩니다."
        ),
        color=0xF4A261
    )
    clues_view = MyCluesView(game)
    disc_msg = await channel.send(embed=embed, view=clues_view)
    game.discussion_message = disc_msg

    # 타이머
    async def discussion_timer():
        secs = game.discussion_seconds
        alert_points = [60, 30, 10]
        elapsed = 0
        for pt in alert_points:
            wait = secs - pt - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
                if game.phase == "DISCUSSION":
                    await channel.send(f"⚠️ 토론 종료 **{pt}초** 전!")
                elapsed += wait
        remaining = secs - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

    try:
        game.timer_task = asyncio.create_task(discussion_timer())
        await game.timer_task
    except asyncio.CancelledError:
        pass

    await disc_msg.edit(view=None)


async def _run_voting(game: CheeseThiefGame, channel: discord.TextChannel):
    """투표 단계"""
    game.phase = "VOTING"

    # 투표 초기화
    for ps in game.players:
        ps.has_voted = False
        ps.voted_for = None

    embed = discord.Embed(
        title="🗳️ 투표 시작!",
        description=(
            f"도둑이라고 생각하는 사람에게 **비공개** 투표하세요.\n"
            f"⏱️ 제한시간: **{VOTE_SECONDS}초** | 자신에게는 투표 불가\n"
            "마지막 선택만 유효합니다."
        ),
        color=0x9B59B6
    )
    vote_view = VoteView(game)
    vote_msg = await channel.send(embed=embed, view=vote_view)
    game.vote_message = vote_msg

    # 투표 타이머
    async def vote_timer():
        await asyncio.sleep(VOTE_SECONDS)

    try:
        game.timer_task = asyncio.create_task(vote_timer())
        await game.timer_task
    except asyncio.CancelledError:
        pass

    await vote_msg.edit(view=None)


async def _show_results(game: CheeseThiefGame, channel: discord.TextChannel):
    """결과 공개"""
    game.phase = "FINISHED"

    # 집계
    from collections import Counter
    tally: Counter = Counter()
    abstain_count = 0

    for ps in game.players:
        if ps.has_voted and ps.voted_for is not None:
            tally[ps.voted_for] += 1
        else:
            abstain_count += 1

    # 무효판 (유효표 0)
    if not tally:
        db.record_game_result(
            game.session_id,
            "cheese_thief",
            [player.member.id for player in game.players],
            draw_ids=[player.member.id for player in game.players],
        )
        embed = discord.Embed(
            title="📊 투표 결과 — 무효판",
            description="유효표가 없습니다. 이 판은 무효 처리됩니다. (승패 기록 없음)",
            color=0x95A5A6
        )
        await _add_full_reveal(game, embed)
        await channel.send(embed=embed, view=RematchView(game))
        return

    max_votes = max(tally.values())
    leaders_ids = [uid for uid, cnt in tally.items() if cnt == max_votes]
    leaders = [p for p in game.players if p.member.id in leaders_ids]
    leader_names = ", ".join(f.display_name for f in leaders)

    thief_caught = game.thief.member.id in leaders_ids
    winning_team = "sleepyhead" if thief_caught else "thief_team"
    db.record_game_result(
        game.session_id,
        "cheese_thief",
        [player.member.id for player in game.players],
        [player.member.id for player in game.players if player.current_team == winning_team],
    )

    if thief_caught:
        winner_text = "🎉 **잠꾸러기 팀 승리!** 도둑이 발각됐습니다!"
        color = 0x2ECC71
    else:
        winner_text = "🦹 **도둑 팀 승리!** 도둑이 살아남았습니다!"
        color = 0xE74C3C

    # 투표 상세
    vote_detail_lines = []
    for ps in game.players:
        if ps.has_voted and ps.voted_for:
            target = game.get_player(ps.voted_for)
            target_name = target.display_name if target else "?"
            vote_detail_lines.append(f"• {ps.display_name} → {target_name}")
        else:
            vote_detail_lines.append(f"• {ps.display_name} → (기권)")

    embed = discord.Embed(
        title="📊 게임 결과 공개!",
        description=winner_text,
        color=color
    )
    embed.add_field(
        name=f"🗳️ 최다 득표자 ({max_votes}표)",
        value=leader_names,
        inline=False
    )
    embed.add_field(
        name="📋 투표 내역",
        value="\n".join(vote_detail_lines) or "없음",
        inline=False
    )

    # 전체 역할 공개
    await _add_full_reveal(game, embed)

    await channel.send(embed=embed, view=RematchView(game))


async def _add_full_reveal(game: CheeseThiefGame, embed: discord.Embed):
    """전체 역할 공개 필드 추가"""
    lines = []
    for ps in game.players:
        if ps.base_role == "thief":
            tag = "🦹 치즈 도둑"
        elif ps.is_follower:
            tag = "🤝 공범"
        else:
            tag = "😴 잠꾸러기"
        dice_str = ", ".join(str(d) for d in ps.dice)
        lines.append(f"• {ps.display_name} — {tag} (주사위: {dice_str})")
    embed.add_field(
        name="🃏 전체 역할 공개",
        value="\n".join(lines),
        inline=False
    )


class RematchView(discord.ui.View):
    def __init__(self, game: CheeseThiefGame):
        super().__init__(timeout=60)
        self.game = game

    @discord.ui.button(label="🔄 재경기", style=discord.ButtonStyle.primary, custom_id="cheese_rematch")
    async def rematch(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.game.in_game(interaction.user.id):
            await interaction.response.send_message("이전 게임 참가자만 재경기를 시작할 수 있습니다.", ephemeral=True)
            return

        channel = interaction.channel
        if channel.id in active_cheese_games and active_cheese_games[channel.id].phase not in ("FINISHED", "CANCELLED"):
            await interaction.response.send_message("이미 진행 중인 게임이 있습니다!", ephemeral=True)
            return

        # 같은 참가자로 새 게임 생성
        new_game = CheeseThiefGame(self.game.host, channel)
        new_game.players = [PlayerState(ps.member) for ps in self.game.players]
        active_cheese_games[channel.id] = new_game

        lobby_embed = discord.Embed(
            title="🧀 재경기 시작!",
            description="이전 참가자들로 새 게임 로비가 열렸습니다.",
            color=0xF4A261
        )
        new_view = CheeseLobbyView(new_game)
        new_game.phase = "LOBBY"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await channel.send(embed=lobby_embed, view=new_view)


# ──────────────────────────────────────────────
# Cog 등록 및 진입점
# ──────────────────────────────────────────────

async def start_cheese_ui(interaction: discord.Interaction):
    """메인메뉴 버튼에서 호출되는 진입 함수"""
    channel = interaction.channel

    if channel.id in active_cheese_games:
        existing = active_cheese_games[channel.id]
        if existing.phase not in ("FINISHED", "CANCELLED"):
            await interaction.response.send_message(
                "이 채널에 이미 진행 중인 치즈 게임이 있습니다!", ephemeral=True
            )
            return

    game = CheeseThiefGame(interaction.user, channel)
    active_cheese_games[channel.id] = game

    lobby_view = CheeseLobbyView(game)
    lobby_embed = lobby_view._build_embed()
    await interaction.response.send_message(embed=lobby_embed, view=lobby_view)
    game.lobby_message = await interaction.original_response()


class CheeseThiefCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="치즈", description="누가 치즈를 훔쳤을까? 게임을 시작합니다.")
    async def cheese_command(self, ctx):
        channel = ctx.channel
        if channel.id in active_cheese_games:
            existing = active_cheese_games[channel.id]
            if existing.phase not in ("FINISHED", "CANCELLED"):
                await ctx.send("이 채널에 이미 진행 중인 치즈 게임이 있습니다!", ephemeral=True)
                return

        game = CheeseThiefGame(ctx.author, channel)
        active_cheese_games[channel.id] = game

        lobby_view = CheeseLobbyView(game)
        lobby_embed = lobby_view._build_embed()
        await ctx.send(embed=lobby_embed, view=lobby_view)


async def setup(bot):
    await bot.add_cog(CheeseThiefCog(bot))
