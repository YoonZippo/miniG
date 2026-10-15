"""
죄수들의 밤 (Prisoners' Night) — MINIG Discord Bot Cog
계획서 기준: prisoners_night_discord_bot_plan.md v1.0
"""

import discord
import logging
import asyncio
import json
import os
import random
from discord.ext import commands
from typing import Dict, List, Optional, Set

logger = logging.getLogger('gameBot.prisoners_night')

# ──────────────────────────────────────────────
# 상수 및 기본 설정
# ──────────────────────────────────────────────
MIN_PLAYERS = 4
MAX_PLAYERS = 10

DEFAULT_PREPARE_SECONDS = 30
DEFAULT_DISCUSSION_SECONDS = 5 * 60  # 5분
DEFAULT_VOTE_SECONDS = 45
DEFAULT_RUNOFF_SECONDS = 30

active_prisoners_games: Dict[int, 'PrisonersNightGame'] = {}

# 사건 데이터 캐시
CASES_FILE = os.path.join(os.path.dirname(__file__), 'cases.json')


def load_cases() -> List[dict]:
    if not os.path.exists(CASES_FILE):
        return []
    with open(CASES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


# ──────────────────────────────────────────────
# 도메인 모델
# ──────────────────────────────────────────────

class PlayerState:
    def __init__(self, member: discord.Member):
        self.member = member
        self.role: str = "prisoner"  # "prisoner" | "infiltrator" (잠입 교도관)
        self.secret_info: str = ""
        self.voted_for: Optional[int] = None
        self.has_voted: bool = False

    @property
    def display_name(self) -> str:
        return self.member.display_name

    @property
    def mention(self) -> str:
        return self.member.mention


class PrisonersNightGame:
    def __init__(self, host: discord.Member, channel: discord.TextChannel):
        self.host = host
        self.channel = channel
        self.players: List[PlayerState] = [PlayerState(host)]
        self.phase: str = "LOBBY"
        # LOBBY -> PREPARE -> DISCUSSION -> VOTING -> RUNOFF -> FINISHED -> CANCELLED

        self.infiltrator: Optional[PlayerState] = None
        self.case: Optional[dict] = None

        # 타이머
        self.timer_task: Optional[asyncio.Task] = None
        self.prepare_seconds: int = DEFAULT_PREPARE_SECONDS
        self.discussion_seconds: int = DEFAULT_DISCUSSION_SECONDS
        self.vote_seconds: int = DEFAULT_VOTE_SECONDS
        self.runoff_seconds: int = DEFAULT_RUNOFF_SECONDS

        # 조기 진행 투표 (심문 스킵 등)
        self.ready_for_next: Set[int] = set()

        # 투표 결과
        self.votes: Dict[int, int] = {}  # voter_id -> target_id
        self.runoff_candidates: List[PlayerState] = []
        self.runoff_votes: Dict[int, int] = {}
        self.winner: Optional[str] = None  # "PRISONERS" | "INFILTRATOR"

        # UI 메시지 참조
        self.lobby_message: Optional[discord.Message] = None
        self.game_message: Optional[discord.Message] = None

    def get_player(self, user_id: int) -> Optional[PlayerState]:
        for p in self.players:
            if p.member.id == user_id:
                return p
        return None

    def assign_roles_and_case(self):
        cases = load_cases()
        if not cases:
            # 기본 비상 케이스
            self.case = {
                "title": "비상 탈옥 미수 사건",
                "summary": "교도소 비상구 자물쇠가 파손되어 있습니다.",
                "location": "지하 1층 비상계단",
                "time": "자정 무렵",
                "tool": "쇠지렛대",
                "evidence": "계단참에 떨어진 푸른색 페인트 조각",
                "secret_keyword": "쇠지렛대",
                "guard_hint": "비상구 쪽 센서가 울렸다는 일지만 알고 있음"
            }
        else:
            self.case = random.choice(cases)

        # 잠입자 1명 무작위 선정
        self.infiltrator = random.choice(self.players)
        for p in self.players:
            if p.member.id == self.infiltrator.member.id:
                p.role = "infiltrator"
                p.secret_info = (
                    f"🕵️ **당신의 신분: 잠입 교도관 (Infiltrator)**\n\n"
                    f"당신은 죄수들 틈에 비밀리에 잠입한 교도관입니다!\n"
                    f"죄수들은 이번 사건의 전모를 알고 있으나, 당신은 단편적인 소문만 알고 있습니다.\n\n"
                    f"📋 **사건명:** {self.case['title']}\n"
                    f"🔍 **당신이 알고 있는 단서:** {self.case.get('guard_hint', '사건 현장 소문만 들음')}\n\n"
                    f"⚠️ **주의:** 죄수들이 이야기하는 단서(시간, 장소, 사용 도구, 암호)를 재빠르게 유추하여 마치 죄수인 것처럼 행동하세요!\n"
                    f"🎯 **승리 조건:** 투표에서 최다 득표를 피해 정체를 들키지 않기"
                )
            else:
                p.role = "prisoner"
                p.secret_info = (
                    f"⛓️ **당신의 신분: 죄수 (Prisoner)**\n\n"
                    f"동료 죄수들과 힘을 합쳐 교도관 잠입자를 색출해야 합니다!\n\n"
                    f"📋 **사건명:** {self.case['title']}\n"
                    f"📌 **사건 개요:** {self.case['summary']}\n"
                    f"📍 **발생 장소:** {self.case['location']}\n"
                    f"⏰ **발생 시각:** {self.case['time']}\n"
                    f"🔧 **사용 도구:** {self.case['tool']}\n"
                    f"🔎 **결정적 증거:** {self.case['evidence']}\n"
                    f"🔑 **공통 암호/키워드:** ||{self.case['secret_keyword']}||\n\n"
                    f"💡 **행동 지침:** 대화 중 잠입자만 모를 만한 질문을 던져 어색한 답변을 하는 자를 찾아내세요!\n"
                    f"🎯 **승리 조건:** 최종 투표에서 잠입자를 지목하여 색출하기"
                )


# ──────────────────────────────────────────────
# Views
# ──────────────────────────────────────────────

class LobbyView(discord.ui.View):
    def __init__(self, game: PrisonersNightGame):
        super().__init__(timeout=None)
        self.game = game

    def _build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="⛓️ 죄수들의 밤 (Prisoners' Night) — 로비",
            description=(
                "**교도소 잠입 추리 & 블러핑 파티게임**\n\n"
                "교도소 안 죄수들 사이에 교도관 1명이 신분을 숨긴 채 잠입했습니다.\n"
                "사건의 진상을 파악하고 서로를 심문하여 잠입자를 색출하세요!\n\n"
                f"👥 **참가 인원:** {len(self.game.players)}/{MAX_PLAYERS}명 (최소 {MIN_PLAYERS}명)\n"
                f"👑 **호스트:** {self.game.host.mention}\n"
                f"⏱️ **설정:** 준비 {self.game.prepare_seconds}초 | 심문 {self.game.discussion_seconds//60}분 | 투표 {self.game.vote_seconds}초"
            ),
            color=0x2c3e50
        )
        player_list = "\n".join([f"{i+1}. {p.display_name} {p.mention}" for i, p in enumerate(self.game.players)])
        embed.add_field(name="참가자 목록", value=player_list or "없음", inline=False)
        embed.set_footer(text="버튼을 눌러 참가하거나 게임을 시작하세요.")
        return embed

    @discord.ui.button(label="참가", style=discord.ButtonStyle.primary, emoji="✋", custom_id="pn_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.phase != "LOBBY":
            await interaction.response.send_message("이미 게임이 시작되었습니다.", ephemeral=True)
            return
        if self.game.get_player(interaction.user.id):
            await interaction.response.send_message("이미 참가하셨습니다!", ephemeral=True)
            return
        if len(self.game.players) >= MAX_PLAYERS:
            await interaction.response.send_message("인원이 꽉 찼습니다!", ephemeral=True)
            return

        self.game.players.append(PlayerState(interaction.user))
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="나가기", style=discord.ButtonStyle.secondary, emoji="🚪", custom_id="pn_leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.phase != "LOBBY":
            await interaction.response.send_message("진행 중인 게임에서는 나갈 수 없습니다.", ephemeral=True)
            return
        player = self.game.get_player(interaction.user.id)
        if not player:
            await interaction.response.send_message("참가 중이 아닙니다.", ephemeral=True)
            return

        self.game.players.remove(player)
        if interaction.user.id == self.game.host.id:
            if self.game.players:
                self.game.host = self.game.players[0].member
            else:
                self.game.phase = "CANCELLED"
                active_prisoners_games.pop(self.game.channel.id, None)
                await interaction.response.edit_message(content="❌ 호스트가 나가고 남은 플레이어가 없어 로비가 취소되었습니다.", embed=None, view=None)
                return

        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="게임 시작", style=discord.ButtonStyle.success, emoji="▶️", custom_id="pn_start")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host.id:
            await interaction.response.send_message("호스트만 게임을 시작할 수 있습니다!", ephemeral=True)
            return
        if len(self.game.players) < MIN_PLAYERS:
            await interaction.response.send_message(f"최소 {MIN_PLAYERS}명 이상 참가해야 시작할 수 있습니다! (현재 {len(self.game.players)}명)", ephemeral=True)
            return

        self.game.phase = "PREPARE"
        self.game.assign_roles_and_case()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        await start_prepare_phase(self.game)

    @discord.ui.button(label="설정", style=discord.ButtonStyle.secondary, emoji="⚙️", custom_id="pn_settings")
    async def settings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host.id:
            await interaction.response.send_message("호스트만 설정을 변경할 수 있습니다.", ephemeral=True)
            return
        view = SettingsView(self.game, self)
        await interaction.response.send_message("⚙️ 심문 및 토론 시간 설정", view=view, ephemeral=True)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.danger, emoji="✖️", custom_id="pn_cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host.id:
            await interaction.response.send_message("호스트만 취소할 수 있습니다.", ephemeral=True)
            return
        self.game.phase = "CANCELLED"
        active_prisoners_games.pop(self.game.channel.id, None)
        await interaction.response.edit_message(content="🛑 호스트에 의해 게임이 취소되었습니다.", embed=None, view=None)


class SettingsView(discord.ui.View):
    def __init__(self, game: PrisonersNightGame, lobby_view: LobbyView):
        super().__init__(timeout=60)
        self.game = game
        self.lobby_view = lobby_view

    @discord.ui.select(
        placeholder="심문 시간 선택",
        options=[
            discord.SelectOption(label="3분", value="180"),
            discord.SelectOption(label="4분", value="240"),
            discord.SelectOption(label="5분 (기본)", value="300", default=True),
            discord.SelectOption(label="7분", value="420"),
            discord.SelectOption(label="10분", value="600"),
        ]
    )
    async def select_discussion_time(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.game.discussion_seconds = int(select.values[0])
        await interaction.response.send_message(f"✅ 심문 시간이 {self.game.discussion_seconds // 60}분으로 변경되었습니다.", ephemeral=True)
        if self.game.lobby_message:
            try:
                await self.game.lobby_message.edit(embed=self.lobby_view._build_embed(), view=self.lobby_view)
            except Exception:
                pass


# ──────────────────────────────────────────────
# 단계별 뷰 & 진행 로직
# ──────────────────────────────────────────────

class InfoCheckView(discord.ui.View):
    """비공개 정보 열람 및 스킵 공용 View"""
    def __init__(self, game: PrisonersNightGame, phase: str):
        super().__init__(timeout=None)
        self.game = game
        self.phase = phase

    @discord.ui.button(label="🔒 내 신분/단서 확인", style=discord.ButtonStyle.primary, emoji="🔍", custom_id="pn_check_info")
    async def check_info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.game.get_player(interaction.user.id)
        if not player:
            await interaction.response.send_message("이 게임의 참가자가 아닙니다.", ephemeral=True)
            return
        await interaction.response.send_message(player.secret_info, ephemeral=True)

    @discord.ui.button(label="⏭️ 다음 단계로 넘어가기", style=discord.ButtonStyle.secondary, emoji="⏩", custom_id="pn_skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.game.get_player(interaction.user.id)
        if not player:
            await interaction.response.send_message("참가자만 투표할 수 있습니다.", ephemeral=True)
            return

        self.game.ready_for_next.add(interaction.user.id)
        ready_count = len(self.game.ready_for_next)
        total_count = len(self.game.players)

        # 과반수 이상 또는 호스트가 눌렀을 때
        if interaction.user.id == self.game.host.id or ready_count >= (total_count // 2 + 1):
            if self.game.timer_task and not self.game.timer_task.done():
                self.game.timer_task.cancel()
            await interaction.response.send_message(f"⏩ {interaction.user.display_name}님의 요청(또는 과반수 동의)으로 다음 단계로 바로 진행합니다!", ephemeral=False)
        else:
            await interaction.response.send_message(f"다음 단계 동의 완료 ({ready_count}/{total_count}명 동의)", ephemeral=True)


async def start_prepare_phase(game: PrisonersNightGame):
    game.phase = "PREPARE"
    game.ready_for_next.clear()

    embed = discord.Embed(
        title="🤫 [준비 단계] 각자 자신의 신분과 단서를 확인하세요!",
        description=(
            f"사건: **{game.case['title']}**\n\n"
            f"아래 **[🔒 내 신분/단서 확인]** 버튼을 눌러 자신의 비공개 역할과 사건 단서를 확인하세요.\n"
            f"준비 시간: **{game.prepare_seconds}초**\n"
            f"시간이 끝나면 음성 심문 단계가 시작됩니다."
        ),
        color=0xf39c12
    )
    view = InfoCheckView(game, "PREPARE")
    game.game_message = await game.channel.send(embed=embed, view=view)

    async def prepare_timer():
        try:
            await asyncio.sleep(game.prepare_seconds)
            await start_discussion_phase(game)
        except asyncio.CancelledError:
            await start_discussion_phase(game)

    game.timer_task = asyncio.create_task(prepare_timer())


async def start_discussion_phase(game: PrisonersNightGame):
    game.phase = "DISCUSSION"
    game.ready_for_next.clear()

    embed = discord.Embed(
        title="🗣️ [심문 단계] 음성 채널에서 잠입자를 심문하세요!",
        description=(
            f"사건: **{game.case['title']}**\n\n"
            f"교도관 잠입자는 사건의 전체 단서를 온전히 알지 못합니다!\n"
            f"각자 질문과 답변을 주고받으며 의심스러운 자를 찾아내세요.\n\n"
            f"⏱️ 심문 제한시간: **{game.discussion_seconds // 60}분**\n"
            f"대화가 충분히 끝나면 **[⏭️ 다음 단계로 넘어가기]**를 눌러 투표로 진행할 수 있습니다."
        ),
        color=0x3498db
    )
    view = InfoCheckView(game, "DISCUSSION")
    await game.channel.send(embed=embed, view=view)

    async def discussion_timer():
        try:
            await asyncio.sleep(game.discussion_seconds)
            await start_voting_phase(game)
        except asyncio.CancelledError:
            await start_voting_phase(game)

    game.timer_task = asyncio.create_task(discussion_timer())


# ──────────────────────────────────────────────
# 투표 단계
# ──────────────────────────────────────────────

class VoteSelect(discord.ui.Select):
    def __init__(self, game: PrisonersNightGame, voter: discord.Member, candidates: List[PlayerState], is_runoff: bool = False):
        self.game = game
        self.voter = voter
        self.is_runoff = is_runoff

        options = []
        for p in candidates:
            if p.member.id != voter.id:  # 본인 제외
                options.append(discord.SelectOption(
                    label=p.display_name,
                    value=str(p.member.id),
                    emoji="🎯"
                ))

        if not options:
            options.append(discord.SelectOption(label="투표 가능한 대상 없음", value="none"))

        super().__init__(
            placeholder="잠입자(교도관)로 의심되는 죄수를 지목하세요",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"pn_vote_select_{voter.id}"
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("투표 대상이 없습니다.", ephemeral=True)
            return

        target_id = int(self.values[0])
        target_player = self.game.get_player(target_id)
        if not target_player:
            await interaction.response.send_message("유효하지 않은 대상입니다.", ephemeral=True)
            return

        if self.is_runoff:
            self.game.runoff_votes[self.voter.id] = target_id
            votes_count = len(self.game.runoff_votes)
        else:
            self.game.votes[self.voter.id] = target_id
            player = self.game.get_player(self.voter.id)
            if player:
                player.has_voted = True
                player.voted_for = target_id
            votes_count = len(self.game.votes)

        await interaction.response.send_message(
            f"✅ **{target_player.display_name}**님에게 비밀 투표를 완료했습니다! (언제든 변경 가능)",
            ephemeral=True
        )

        # 전원 투표 완료 시 즉시 개표
        if votes_count >= len(self.game.players):
            if self.game.timer_task and not self.game.timer_task.done():
                self.game.timer_task.cancel()


class VotePanelButtonView(discord.ui.View):
    """공용 메시지에 뜨는 '내 투표용지 열기' 버튼 뷰"""
    def __init__(self, game: PrisonersNightGame, is_runoff: bool = False):
        super().__init__(timeout=None)
        self.game = game
        self.is_runoff = is_runoff

    @discord.ui.button(label="🗳️ 비밀 투표하기", style=discord.ButtonStyle.danger, emoji="🎯", custom_id="pn_open_vote")
    async def open_vote_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.game.get_player(interaction.user.id)
        if not player:
            await interaction.response.send_message("참가자만 투표할 수 있습니다.", ephemeral=True)
            return

        candidates = self.game.runoff_candidates if self.is_runoff else self.game.players
        vote_view = discord.ui.View(timeout=120)
        vote_view.add_item(VoteSelect(self.game, interaction.user, candidates, self.is_runoff))
        await interaction.response.send_message("아래 목록에서 의심자를 선택하세요 (비밀 투표):", view=vote_view, ephemeral=True)

    @discord.ui.button(label="🔒 내 신분/단서 확인", style=discord.ButtonStyle.secondary, emoji="🔍", custom_id="pn_vote_info")
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.game.get_player(interaction.user.id)
        if player:
            await interaction.response.send_message(player.secret_info, ephemeral=True)


async def start_voting_phase(game: PrisonersNightGame):
    game.phase = "VOTING"
    game.votes.clear()

    embed = discord.Embed(
        title="🗳️ [최종 투표] 교도관 잠입자를 지목하세요!",
        description=(
            f"심문 시간이 종료되었습니다!\n"
            f"아래 **[🗳️ 비밀 투표하기]** 버튼을 눌러 잠입자로 의심되는 사람을 지목하세요.\n\n"
            f"⏱️ 투표 제한시간: **{game.vote_seconds}초**\n"
            f"⚠️ 본인에게는 투표할 수 없으며, 미투표 시 기권 처리됩니다.\n"
            f"최다 득표 동률 시 1회 결선 투표가 진행됩니다."
        ),
        color=0xe74c3c
    )
    view = VotePanelButtonView(game, is_runoff=False)
    await game.channel.send(embed=embed, view=view)

    async def vote_timer():
        try:
            await asyncio.sleep(game.vote_seconds)
            await tally_votes(game)
        except asyncio.CancelledError:
            await tally_votes(game)

    game.timer_task = asyncio.create_task(vote_timer())


async def tally_votes(game: PrisonersNightGame):
    # 득표수 집계
    tally: Dict[int, int] = {}
    for target_id in game.votes.values():
        tally[target_id] = tally.get(target_id, 0) + 1

    if not tally:
        # 전원 기권 -> 잠입자 승리
        await finish_game(game, winner="INFILTRATOR", reason="모든 참가자가 기권하여 잠입 교도관이 무사히 탈출했습니다!")
        return

    max_votes = max(tally.values())
    top_candidates_ids = [uid for uid, count in tally.items() if count == max_votes]

    if len(top_candidates_ids) == 1:
        # 단독 1위 -> 개표 결과 확정
        top_player = game.get_player(top_candidates_ids[0])
        if top_player and top_player.role == "infiltrator":
            await finish_game(game, winner="PRISONERS", reason=f"최다 득표자 **{top_player.display_name}**님은 잠입 교도관이 맞았습니다!", tally=tally)
        else:
            accused_name = top_player.display_name if top_player else "지목된 자"
            await finish_game(game, winner="INFILTRATOR", reason=f"최다 득표자 **{accused_name}**님은 무고한 죄수였습니다!", tally=tally)
    else:
        # 동률 발생 -> 1회 결선 투표 진행
        game.runoff_candidates = [p for p in game.players if p.member.id in top_candidates_ids]
        await start_runoff_phase(game, tally)


async def start_runoff_phase(game: PrisonersNightGame, prev_tally: Dict[int, int]):
    game.phase = "RUNOFF"
    game.runoff_votes.clear()

    names = ", ".join([f"**{p.display_name}**" for p in game.runoff_candidates])
    embed = discord.Embed(
        title="⚖️ [동점 결선 투표] 최다 득표 동률 발생!",
        description=(
            f"동률 후보: {names}\n\n"
            f"동점자들을 대상으로 30초간 1회 결선 투표를 진행합니다.\n"
            f"아래 **[🗳️ 비밀 투표하기]**를 눌러 동점자 중 1명을 선택하세요.\n"
            f"결선에서도 동률이 나오면 **잠입 교도관의 승리**로 종료됩니다!"
        ),
        color=0x9b59b6
    )
    view = VotePanelButtonView(game, is_runoff=True)
    await game.channel.send(embed=embed, view=view)

    async def runoff_timer():
        try:
            await asyncio.sleep(game.runoff_seconds)
            await tally_runoff(game)
        except asyncio.CancelledError:
            await tally_runoff(game)

    game.timer_task = asyncio.create_task(runoff_timer())


async def tally_runoff(game: PrisonersNightGame):
    tally: Dict[int, int] = {}
    for target_id in game.runoff_votes.values():
        tally[target_id] = tally.get(target_id, 0) + 1

    if not tally:
        await finish_game(game, winner="INFILTRATOR", reason="결선 투표 전원 기권으로 잠입 교도관이 승리했습니다!")
        return

    max_votes = max(tally.values())
    top_candidates = [uid for uid, count in tally.items() if count == max_votes]

    if len(top_candidates) == 1:
        top_player = game.get_player(top_candidates[0])
        if top_player and top_player.role == "infiltrator":
            await finish_game(game, winner="PRISONERS", reason=f"결선 최다 득표자 **{top_player.display_name}**님은 잠입 교도관이었습니다!", tally=tally)
        else:
            accused_name = top_player.display_name if top_player else "지목된 자"
            await finish_game(game, winner="INFILTRATOR", reason=f"결선 지목자 **{accused_name}**님은 무고한 죄수였습니다!", tally=tally)
    else:
        # 재동점 -> 잠입자 승리
        await finish_game(game, winner="INFILTRATOR", reason="결선 투표에서도 동률이 발생하여 잠입 교도관이 승리했습니다!", tally=tally)


# ──────────────────────────────────────────────
# 결과 및 재경기
# ──────────────────────────────────────────────

class ResultView(discord.ui.View):
    def __init__(self, game: PrisonersNightGame):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="🔄 같은 멤버로 다시 하기", style=discord.ButtonStyle.primary, emoji="🔁", custom_id="pn_restart")
    async def restart_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = self.game.channel
        new_game = PrisonersNightGame(interaction.user, channel)
        # 기존 플레이어 승계
        new_game.players = [PlayerState(p.member) for p in self.game.players]
        active_prisoners_games[channel.id] = new_game

        lobby_view = LobbyView(new_game)
        embed = lobby_view._build_embed()
        await interaction.response.send_message("🔄 새로운 게임 로비가 생성되었습니다!", ephemeral=True)
        new_game.lobby_message = await channel.send(embed=embed, view=lobby_view)


async def finish_game(game: PrisonersNightGame, winner: str, reason: str, tally: Optional[Dict[int, int]] = None):
    game.phase = "FINISHED"
    game.winner = winner

    infiltrator_name = game.infiltrator.display_name if game.infiltrator else "없음"
    infiltrator_mention = game.infiltrator.mention if game.infiltrator else ""

    if winner == "PRISONERS":
        title = "🎉 죄수 진영 승리!"
        color = 0x2ecc71
    else:
        title = "🚨 잠입 교도관 승리!"
        color = 0xe74c3c

    embed = discord.Embed(
        title=title,
        description=f"### {reason}\n\n"
                    f"🕵️ **잠입 교도관:** {infiltrator_name} ({infiltrator_mention})\n"
                    f"📋 **사건 테마:** {game.case['title']}\n"
                    f"🔑 **공통 암호/키워드:** {game.case['secret_keyword']}\n"
                    f"🔧 **도구:** {game.case['tool']} | 📍 **장소:** {game.case['location']}",
        color=color
    )

    # 득표 결과 표시
    if tally:
        vote_lines = []
        for uid, count in sorted(tally.items(), key=lambda x: x[1], reverse=True):
            p = game.get_player(uid)
            p_name = p.display_name if p else f"User {uid}"
            role_tag = "(🕵️잠입자)" if p and p.role == "infiltrator" else "(⛓️죄수)"
            vote_lines.append(f"• **{p_name}** {role_tag}: {count}표")
        embed.add_field(name="📊 투표 집계", value="\n".join(vote_lines) or "집계 없음", inline=False)

    view = ResultView(game)
    await game.channel.send(embed=embed, view=view)


# ──────────────────────────────────────────────
# 진입점 및 Cog 등록
# ──────────────────────────────────────────────

async def start_prisoners_ui(interaction: discord.Interaction):
    """메인 메뉴 버튼에서 호출되는 진입 함수"""
    channel = interaction.channel
    if channel.id in active_prisoners_games:
        existing = active_prisoners_games[channel.id]
        if existing.phase not in ("FINISHED", "CANCELLED"):
            await interaction.response.send_message("이 채널에 이미 진행 중인 죄수들의 밤 게임이 있습니다!", ephemeral=True)
            return

    game = PrisonersNightGame(interaction.user, channel)
    active_prisoners_games[channel.id] = game

    lobby_view = LobbyView(game)
    embed = lobby_view._build_embed()
    await interaction.response.send_message(embed=embed, view=lobby_view)
    game.lobby_message = await interaction.original_response()


class PrisonersNightCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="죄수들의밤", description="죄수들의 밤 게임을 시작합니다.")
    async def prisoners_night_command(self, ctx):
        channel = ctx.channel
        if channel.id in active_prisoners_games:
            existing = active_prisoners_games[channel.id]
            if existing.phase not in ("FINISHED", "CANCELLED"):
                await ctx.send("이 채널에 이미 진행 중인 죄수들의 밤 게임이 있습니다!", ephemeral=True)
                return

        game = PrisonersNightGame(ctx.author, channel)
        active_prisoners_games[channel.id] = game

        lobby_view = LobbyView(game)
        embed = lobby_view._build_embed()
        await ctx.send(embed=embed, view=lobby_view)


async def setup(bot):
    await bot.add_cog(PrisonersNightCog(bot))
