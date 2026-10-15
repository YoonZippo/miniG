"""
텍사스 홀덤 포커 (Texas Hold'em Poker) — MINIG Discord Bot Cog
계획서 기준: texas_holdem_discord_bot_plan.md v1.0
- 노리밋 텍사스 홀덤 (No-Limit Texas Hold'em)
- 1인 솔로 모드 (AI 헤즈업 대결) 및 2~8인 멀티플레이 테이블
- 표준 52장 덱, 7장 중 최적 5장 족보 평가 (로열 플러시 ~ 하이카드)
- 프리플롭 → 플롭 → 턴 → 리버 → 쇼다운 자동 진행
"""

import discord
import logging
import asyncio
import secrets
from itertools import combinations
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from discord.ext import commands

logger = logging.getLogger('gameBot.holdem')

# ──────────────────────────────────────────────
# 상수 및 카드 정의
# ──────────────────────────────────────────────
MIN_PLAYERS = 1
MAX_PLAYERS = 8
INITIAL_CHIPS = 1000
SMALL_BLIND = 10
BIG_BLIND = 20
DEFAULT_ACTION_SECONDS = 45

SUITS = ["♠", "♥", "♦", "♣"]
RANK_STRS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_VALUES = {r: i + 2 for i, r in enumerate(RANK_STRS)}  # 2:2 .. A:14
VALUE_TO_STR = {v: r for r, v in RANK_VALUES.items()}

active_holdem_games: Dict[int, 'HoldemGame'] = {}


@dataclass(frozen=True)
class Card:
    rank: int   # 2 ~ 14 (14 = Ace)
    suit: str   # "♠", "♥", "♦", "♣"

    def __str__(self) -> str:
        return f"[{self.suit}{VALUE_TO_STR[self.rank]}]"


def create_deck() -> List[Card]:
    deck = [Card(rank, suit) for suit in SUITS for rank in range(2, 15)]
    rng = secrets.SystemRandom()
    rng.shuffle(deck)
    return deck


# ──────────────────────────────────────────────
# 족보 판정 엔진 (Hand Evaluator)
# ──────────────────────────────────────────────

CATEGORY_NAMES = {
    8: "스트레이트 플러시",
    7: "포카드",
    6: "풀하우스",
    5: "플러시",
    4: "스트레이트",
    3: "트리플",
    2: "투페어",
    1: "원페어",
    0: "하이카드"
}


def evaluate_5_cards(cards: Tuple[Card, ...]) -> Tuple[int, Tuple]:
    """5장 카드의 순위 튜플 반환 (카테고리, 랭크 우선순위...)"""
    ranks = sorted([c.rank for c in cards], reverse=True)
    suits = [c.suit for c in cards]
    is_flush = len(set(suits)) == 1

    # 스트레이트 검사 (Ace-low 5-4-3-2-A 휠 포함)
    is_straight = False
    straight_high = 0
    unique_ranks = sorted(list(set(ranks)), reverse=True)
    if len(unique_ranks) == 5:
        if unique_ranks[0] - unique_ranks[4] == 4:
            is_straight = True
            straight_high = unique_ranks[0]
        elif unique_ranks == [14, 5, 4, 3, 2]:
            is_straight = True
            straight_high = 5  # 5-high straight

    counts = Counter(ranks).most_common()

    # 1. 스트레이트 플러시 (로열 포함)
    if is_flush and is_straight:
        return (8, (straight_high,))

    # 2. 포카드
    if counts[0][1] == 4:
        quad_rank = counts[0][0]
        kicker = counts[1][0]
        return (7, (quad_rank, kicker))

    # 3. 풀하우스
    if counts[0][1] == 3 and counts[1][1] == 2:
        return (6, (counts[0][0], counts[1][0]))

    # 4. 플러시
    if is_flush:
        return (5, tuple(ranks))

    # 5. 스트레이트
    if is_straight:
        return (4, (straight_high,))

    # 6. 트리플
    if counts[0][1] == 3:
        trips_rank = counts[0][0]
        kickers = tuple(sorted([c[0] for c in counts[1:]], reverse=True))
        return (3, (trips_rank,) + kickers)

    # 7. 투페어
    if counts[0][1] == 2 and counts[1][1] == 2:
        pairs = sorted([counts[0][0], counts[1][0]], reverse=True)
        kicker = counts[2][0]
        return (2, (pairs[0], pairs[1], kicker))

    # 8. 원페어
    if counts[0][1] == 2:
        pair_rank = counts[0][0]
        kickers = tuple(sorted([c[0] for c in counts[1:]], reverse=True))
        return (1, (pair_rank,) + kickers)

    # 9. 하이카드
    return (0, tuple(ranks))


def evaluate_7_cards(cards: List[Card]) -> Tuple[int, Tuple, str]:
    """7장 중 최고 5장 조합 평가: (category, rank_tuple, korean_name)"""
    if len(cards) < 5:
        return (-1, (), "카드 부족")

    best_score = (-1, ())
    for combo in combinations(cards, 5):
        score = evaluate_5_cards(combo)
        if score > best_score:
            best_score = score

    cat, details = best_score
    name = CATEGORY_NAMES.get(cat, "미상")

    # 이름 세부 묘사
    if cat == 8:
        name = "로열 플러시" if details[0] == 14 else f"{VALUE_TO_STR[details[0]]}-high 스트레이트 플러시"
    elif cat == 7:
        name = f"{VALUE_TO_STR[details[0]]} 포카드"
    elif cat == 6:
        name = f"{VALUE_TO_STR[details[0]]} & {VALUE_TO_STR[details[1]]} 풀하우스"
    elif cat == 5:
        name = f"{VALUE_TO_STR[details[0]]}-high 플러시"
    elif cat == 4:
        name = f"{VALUE_TO_STR[details[0]]}-high 스트레이트"
    elif cat == 3:
        name = f"{VALUE_TO_STR[details[0]]} 트리플"
    elif cat == 2:
        name = f"{VALUE_TO_STR[details[0]]} & {VALUE_TO_STR[details[1]]} 투페어"
    elif cat == 1:
        name = f"{VALUE_TO_STR[details[0]]} 원페어"
    elif cat == 0:
        name = f"{VALUE_TO_STR[details[0]]} 하이카드"

    return (cat, details, name)


# ──────────────────────────────────────────────
# 플레이어 상태
# ──────────────────────────────────────────────

class Player:
    def __init__(self, member: Optional[discord.Member] = None, is_ai: bool = False, name: str = ""):
        self.member = member
        self.is_ai = is_ai
        self._name = name or (member.display_name if member else "AI봇")
        self.chips: int = INITIAL_CHIPS
        self.hole_cards: List[Card] = []
        self.current_street_bet: int = 0
        self.total_hand_bet: int = 0
        self.folded: bool = False
        self.all_in: bool = False
        self.has_acted: bool = False

    @property
    def display_name(self) -> str:
        return self._name

    @property
    def mention(self) -> str:
        return self.member.mention if self.member else f"**{self._name}**"

    def reset_hand(self):
        self.hole_cards = []
        self.current_street_bet = 0
        self.total_hand_bet = 0
        self.folded = False
        self.all_in = False
        self.has_acted = False

    def format_hole(self) -> str:
        if not self.hole_cards:
            return "카드 없음"
        return f"{self.hole_cards[0]} {self.hole_cards[1]}"


# ──────────────────────────────────────────────
# 게임 상태 관리
# ──────────────────────────────────────────────

class HoldemGame:
    def __init__(self, host: discord.Member, channel: discord.TextChannel):
        self.host = host
        self.channel = channel
        self.players: List[Player] = [Player(member=host)]
        self.deck: List[Card] = []
        self.board: List[Card] = []

        self.pot: int = 0
        self.highest_bet: int = 0
        self.min_raise: int = BIG_BLIND

        self.button_idx: int = 0
        self.current_actor_idx: int = 0

        self.phase: str = "LOBBY"
        # LOBBY -> PREFLOP -> FLOP -> TURN -> RIVER -> SHOWDOWN -> FINISHED -> CANCELLED
        self.round_num: int = 1
        self.timer_task: Optional[asyncio.Task] = None

        self.lobby_message: Optional[discord.Message] = None
        self.game_message: Optional[discord.Message] = None

    def get_player(self, user_id: int) -> Optional[Player]:
        for p in self.players:
            if p.member and p.member.id == user_id:
                return p
        return None

    def active_players(self) -> List[Player]:
        """폴드하지 않고 남아있는 플레이어"""
        return [p for p in self.players if not p.folded]

    def players_can_act(self) -> List[Player]:
        """행동 가능한 플레이어 (폴드 안 하고 올인 안 한 플레이어)"""
        return [p for p in self.players if not p.folded and not p.all_in]

    def current_actor(self) -> Optional[Player]:
        if 0 <= self.current_actor_idx < len(self.players):
            return self.players[self.current_actor_idx]
        return None

    def format_board(self) -> str:
        if not self.board:
            return "[??] [??] [??] [??] [??]"
        known = " ".join(str(c) for c in self.board)
        unknown = " ".join(["[??]"] * (5 - len(self.board)))
        return f"{known} {unknown}".strip()


# ──────────────────────────────────────────────
# UI: 로비
# ──────────────────────────────────────────────

class HoldemLobbyView(discord.ui.View):
    def __init__(self, game: HoldemGame):
        super().__init__(timeout=None)
        self.game = game

    def _build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="♠️ 텍사스 홀덤 포커 (Texas Hold'em) — 테이블 로비",
            description=(
                "**세계에서 가장 인기 있는 노리밋 포커 토너먼트!**\n\n"
                "• **블라인드**: 스몰 10 / 빅 20 칩\n"
                "• **시작 스택**: 1,000 칩\n"
                "• **스트리트**: 프리플롭 → 플롭(3장) → 턴(1장) → 리버(1장) → 쇼다운\n\n"
                f"👥 **참가 좌석:** {len(self.game.players)}/{MAX_PLAYERS}석\n"
                f"👑 **호스트:** {self.game.host.mention}"
            ),
            color=0x2c3e50
        )
        player_list = "\n".join([f"{i+1}. {p.display_name} (스택: {p.chips} 칩)" for i, p in enumerate(self.game.players)])
        embed.add_field(name="테이블 참가자", value=player_list or "없음", inline=False)
        embed.set_footer(text="혼자 바로 시작하려면 [⚡ 솔로 (AI 대결)], 친구와 함께라면 [참가] 후 시작하세요.")
        return embed

    @discord.ui.button(label="솔로 (AI 대결)", style=discord.ButtonStyle.success, emoji="⚡", custom_id="pk_solo_start")
    async def solo_start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host.id:
            await interaction.response.send_message("호스트만 시작할 수 있습니다.", ephemeral=True)
            return

        # 호스트 1명 + AI봇 1명 배치
        self.game.players = [self.game.players[0], Player(is_ai=True, name="🤖 알파봇")]
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await start_new_hand(self.game)

    @discord.ui.button(label="참가", style=discord.ButtonStyle.primary, emoji="✋", custom_id="pk_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.get_player(interaction.user.id):
            await interaction.response.send_message("이미 착석하셨습니다!", ephemeral=True)
            return
        if len(self.game.players) >= MAX_PLAYERS:
            await interaction.response.send_message("테이블이 꽉 찼습니다!", ephemeral=True)
            return

        self.game.players.append(Player(member=interaction.user))
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="나가기", style=discord.ButtonStyle.secondary, emoji="🚪", custom_id="pk_leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.game.get_player(interaction.user.id)
        if not player:
            await interaction.response.send_message("참가 중이 아닙니다.", ephemeral=True)
            return
        self.game.players.remove(player)
        if interaction.user.id == self.game.host.id:
            humans = [p for p in self.game.players if not p.is_ai]
            if humans:
                self.game.host = humans[0].member
            else:
                self.game.phase = "CANCELLED"
                active_holdem_games.pop(self.game.channel.id, None)
                await interaction.response.edit_message(content="🛑 모든 플레이어가 퇴장하여 테이블이 종료되었습니다.", embed=None, view=None)
                return
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="AI봇 추가", style=discord.ButtonStyle.secondary, emoji="🤖", custom_id="pk_add_ai")
    async def add_ai_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host.id:
            await interaction.response.send_message("호스트만 AI를 추가할 수 있습니다.", ephemeral=True)
            return
        if len(self.game.players) >= MAX_PLAYERS:
            await interaction.response.send_message("더 이상 좌석이 없습니다!", ephemeral=True)
            return

        ai_num = sum(1 for p in self.game.players if p.is_ai) + 1
        self.game.players.append(Player(is_ai=True, name=f"🤖 AI봇_{ai_num}"))
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="멀티 시작", style=discord.ButtonStyle.primary, emoji="▶️", custom_id="pk_multi_start")
    async def multi_start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host.id:
            await interaction.response.send_message("호스트만 시작할 수 있습니다.", ephemeral=True)
            return
        if len(self.game.players) < 2:
            await interaction.response.send_message("최소 2명 이상(AI 포함)이어야 시작할 수 있습니다!", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await start_new_hand(self.game)


# ──────────────────────────────────────────────
# 핸드 및 스트리트 진행
# ──────────────────────────────────────────────

async def start_new_hand(game: HoldemGame):
    # 탈락자(칩 0) 제외
    game.players = [p for p in game.players if p.chips > 0]
    if len(game.players) < 2:
        winner = game.players[0] if game.players else None
        winner_name = winner.display_name if winner else "없음"
        await game.channel.send(f"🏆 모든 상대가 탈락했습니다! **{winner_name}**님의 최종 매치 우승!")
        game.phase = "FINISHED"
        active_holdem_games.pop(game.channel.id, None)
        return

    game.deck = create_deck()
    game.board = []
    game.pot = 0
    game.highest_bet = 0
    game.min_raise = BIG_BLIND

    for p in game.players:
        p.reset_hand()
        p.hole_cards = [game.deck.pop(), game.deck.pop()]

    # 딜러 버튼 이동 (핸드마다 1칸씩)
    game.button_idx = (game.button_idx + 1) % len(game.players)
    num_players = len(game.players)

    # 블라인드 포스팅
    # 헤즈업(2인): 버튼이 SB(먼저 베팅), 다른 쪽이 BB
    if num_players == 2:
        sb_idx = game.button_idx
        bb_idx = (game.button_idx + 1) % 2
        first_actor = sb_idx
    else:
        sb_idx = (game.button_idx + 1) % num_players
        bb_idx = (game.button_idx + 2) % num_players
        first_actor = (game.button_idx + 3) % num_players

    # SB 지불
    sb_player = game.players[sb_idx]
    sb_post = min(SMALL_BLIND, sb_player.chips)
    sb_player.chips -= sb_post
    sb_player.current_street_bet = sb_post
    sb_player.total_hand_bet = sb_post
    if sb_player.chips == 0:
        sb_player.all_in = True

    # BB 지불
    bb_player = game.players[bb_idx]
    bb_post = min(BIG_BLIND, bb_player.chips)
    bb_player.chips -= bb_post
    bb_player.current_street_bet = bb_post
    bb_player.total_hand_bet = bb_post
    if bb_player.chips == 0:
        bb_player.all_in = True

    game.pot = sb_post + bb_post
    game.highest_bet = max(sb_post, bb_post)
    game.min_raise = BIG_BLIND

    game.phase = "PREFLOP"
    game.current_actor_idx = first_actor

    await game.channel.send(
        f"♠️ **[HAND {game.round_num}] 시작!**\n"
        f"🔘 버튼: **{game.players[game.button_idx].display_name}** | "
        f"SB(10): **{sb_player.display_name}** | BB(20): **{bb_player.display_name}**"
    )

    await process_betting_round(game)


def build_table_embed(game: HoldemGame, actor: Player) -> discord.Embed:
    embed = discord.Embed(
        title=f"♠️ 텍사스 홀덤 — HAND #{game.round_num} [{game.phase}]",
        description=(
            f"💰 **총 팟(Pot):** **{game.pot} 칩**\n"
            f"🃏 **커뮤니티 카드:** {game.format_board()}\n\n"
            f"👉 **현재 차례:** {actor.mention} (남은 시간: {DEFAULT_ACTION_SECONDS}초)\n"
            f"🪙 **현재 콜 금액:** **{game.highest_bet - actor.current_street_bet} 칩** (기준 베팅: {game.highest_bet} 칩)"
        ),
        color=0x1abc9c
    )

    status_lines = []
    for i, p in enumerate(game.players):
        btn_tag = " [🔘딜러]" if i == game.button_idx else ""
        if p.folded:
            state = "❌ FOLD"
        elif p.all_in:
            state = f"🚀 ALL-IN ({p.current_street_bet} 칩)"
        else:
            state = f"베팅 {p.current_street_bet} 칩"
        status_lines.append(f"• **{p.display_name}**{btn_tag}: 스택 {p.chips} 칩 | {state}")

    embed.add_field(name="테이블 현황", value="\n".join(status_lines), inline=False)
    embed.set_footer(text="자신의 홀 카드는 [🔒 내 카드] 버튼을 눌러 비공개로 확인하세요.")
    return embed


# ──────────────────────────────────────────────
# 액션 UI & 베팅 루프
# ──────────────────────────────────────────────

class RaiseModal(discord.ui.Modal, title="레이즈 금액 입력"):
    amount_input = discord.ui.TextInput(
        label="레이즈 총 베팅 금액 (상대 베팅 포함)",
        placeholder="예: 60",
        required=True
    )

    def __init__(self, game: HoldemGame, player: Player, min_amount: int, max_amount: int):
        super().__init__()
        self.game = game
        self.player = player
        self.min_amount = min_amount
        self.max_amount = max_amount
        self.amount_input.label = f"총 베팅 금액 ({min_amount} ~ {max_amount} 칩)"

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.amount_input.value.strip())
        except ValueError:
            await interaction.response.send_message("숫자만 입력해 주세요!", ephemeral=True)
            return

        if val < self.min_amount:
            val = self.min_amount
        elif val > self.max_amount:
            val = self.max_amount

        to_add = val - self.player.current_street_bet
        self.player.chips -= to_add
        self.player.current_street_bet = val
        self.player.total_hand_bet += to_add
        self.game.pot += to_add

        # 최소 레이즈 폭 갱신
        diff = val - self.game.highest_bet
        if diff > self.game.min_raise:
            self.game.min_raise = diff
        self.game.highest_bet = val

        if self.player.chips == 0:
            self.player.all_in = True

        self.player.has_acted = True
        await interaction.response.send_message(f"🚀 **{self.player.display_name}**님이 **{val} 칩**으로 레이즈했습니다!", ephemeral=False)
        if self.game.timer_task and not self.game.timer_task.done():
            self.game.timer_task.cancel()


class PlayerActionView(discord.ui.View):
    def __init__(self, game: HoldemGame, actor: Player):
        super().__init__(timeout=DEFAULT_ACTION_SECONDS)
        self.game = game
        self.actor = actor

        call_cost = game.highest_bet - actor.current_street_bet
        can_check = (call_cost == 0)

        if can_check:
            self.call_button.disabled = True
            self.check_button.label = "체크 (Check)"
        else:
            self.check_button.disabled = True
            self.call_button.label = f"콜 ({call_cost} 칩)"
            if actor.chips <= call_cost:
                self.call_button.label = f"콜/올인 ({actor.chips} 칩)"

        # 레이즈 가능 여부 (콜 금액 초과로 칩이 있어야 함)
        min_raise_target = game.highest_bet + game.min_raise
        max_possible = actor.chips + actor.current_street_bet
        if max_possible < min_raise_target:
            self.raise_button.disabled = True

    async def _check_authority(self, interaction: discord.Interaction) -> bool:
        if not self.actor.member or interaction.user.id != self.actor.member.id:
            await interaction.response.send_message("현재 당신의 차례가 아닙니다!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="내 카드 확인", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="pk_view_cards")
    async def view_cards_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.game.get_player(interaction.user.id)
        if not player or not player.hole_cards:
            await interaction.response.send_message("카드가 없습니다.", ephemeral=True)
            return

        all_cards = player.hole_cards + self.game.board
        cat, _, rank_name = evaluate_7_cards(all_cards)
        embed = discord.Embed(
            title=f"🔒 {player.display_name}님의 비공개 패",
            description=(
                f"🎴 **홀 카드:** {player.format_hole()}\n"
                f"🃏 **커뮤니티:** {self.game.format_board()}\n"
                f"📊 **현재 족보:** **{rank_name}**\n"
                f"🪙 **남은 칩:** {player.chips} 칩"
            ),
            color=0xf39c12
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="폴드 (Fold)", style=discord.ButtonStyle.danger, emoji="❌", custom_id="pk_fold")
    async def fold_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_authority(interaction):
            return
        self.actor.folded = True
        self.actor.has_acted = True
        await interaction.response.send_message(f"🏳️ **{self.actor.display_name}**님이 폴드했습니다.", ephemeral=False)
        if self.game.timer_task and not self.game.timer_task.done():
            self.game.timer_task.cancel()

    @discord.ui.button(label="체크 (Check)", style=discord.ButtonStyle.secondary, emoji="⚪", custom_id="pk_check")
    async def check_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_authority(interaction):
            return
        self.actor.has_acted = True
        await interaction.response.send_message(f"⚪ **{self.actor.display_name}**님이 체크했습니다.", ephemeral=False)
        if self.game.timer_task and not self.game.timer_task.done():
            self.game.timer_task.cancel()

    @discord.ui.button(label="콜 (Call)", style=discord.ButtonStyle.primary, emoji="📞", custom_id="pk_call")
    async def call_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_authority(interaction):
            return
        call_cost = self.game.highest_bet - self.actor.current_street_bet
        pay = min(call_cost, self.actor.chips)
        self.actor.chips -= pay
        self.actor.current_street_bet += pay
        self.actor.total_hand_bet += pay
        self.game.pot += pay
        if self.actor.chips == 0:
            self.actor.all_in = True

        self.actor.has_acted = True
        await interaction.response.send_message(f"📞 **{self.actor.display_name}**님이 **{pay} 칩** 콜했습니다.", ephemeral=False)
        if self.game.timer_task and not self.game.timer_task.done():
            self.game.timer_task.cancel()

    @discord.ui.button(label="레이즈 (Raise)", style=discord.ButtonStyle.success, emoji="➕", custom_id="pk_raise")
    async def raise_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_authority(interaction):
            return
        min_target = self.game.highest_bet + self.game.min_raise
        max_target = self.actor.chips + self.actor.current_street_bet
        modal = RaiseModal(self.game, self.actor, min_target, max_target)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="올인 (All-In)", style=discord.ButtonStyle.danger, emoji="🚀", custom_id="pk_allin")
    async def allin_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_authority(interaction):
            return
        all_in_amount = self.actor.chips
        total_bet = self.actor.current_street_bet + all_in_amount

        self.actor.chips = 0
        self.actor.current_street_bet = total_bet
        self.actor.total_hand_bet += all_in_amount
        self.game.pot += all_in_amount
        self.actor.all_in = True
        self.actor.has_acted = True

        if total_bet > self.game.highest_bet:
            diff = total_bet - self.game.highest_bet
            if diff > self.game.min_raise:
                self.game.min_raise = diff
            self.game.highest_bet = total_bet

        await interaction.response.send_message(f"🔥 **{self.actor.display_name}**님 **{all_in_amount} 칩** ALL-IN!", ephemeral=False)
        if self.game.timer_task and not self.game.timer_task.done():
            self.game.timer_task.cancel()


# ──────────────────────────────────────────────
# AI 자동 액션 엔진
# ──────────────────────────────────────────────

async def execute_ai_turn(game: HoldemGame, ai: Player):
    await asyncio.sleep(1.5)  # 사람처럼 생각하는 딜레이
    call_cost = game.highest_bet - ai.current_street_bet
    can_check = (call_cost == 0)

    # 족보 평가
    all_cards = ai.hole_cards + game.board
    cat, _, _ = evaluate_7_cards(all_cards)

    # AI 의사결정 (간단한 포커 휴리스틱)
    if can_check:
        # 체크 가능할 때: 강한 패(투페어 이상)면 30% 확률로 가벼운 레이즈, 아니면 체크
        if cat >= 2 and ai.chips >= game.min_raise and secrets.randbelow(100) < 30:
            raise_target = game.highest_bet + game.min_raise
            to_add = min(raise_target - ai.current_street_bet, ai.chips)
            ai.chips -= to_add
            ai.current_street_bet += to_add
            ai.total_hand_bet += to_add
            game.pot += to_add
            game.highest_bet = ai.current_street_bet
            if ai.chips == 0:
                ai.all_in = True
            ai.has_acted = True
            await game.channel.send(f"🤖 **{ai.display_name}**님이 **{game.highest_bet} 칩**으로 레이즈했습니다!")
        else:
            ai.has_acted = True
            await game.channel.send(f"⚪ **{ai.display_name}**님이 체크했습니다.")
    else:
        # 콜해야 할 때
        pot_odds = call_cost / (game.pot + call_cost) if (game.pot + call_cost) > 0 else 1.0

        # 원페어 이상이거나 콜 비용이 아주 작으면 콜
        if cat >= 1 or pot_odds < 0.25 or (call_cost <= BIG_BLIND and secrets.randbelow(100) < 70):
            pay = min(call_cost, ai.chips)
            ai.chips -= pay
            ai.current_street_bet += pay
            ai.total_hand_bet += pay
            game.pot += pay
            if ai.chips == 0:
                ai.all_in = True
            ai.has_acted = True
            await game.channel.send(f"📞 **{ai.display_name}**님이 **{pay} 칩** 콜했습니다.")
        else:
            # 쓰레기 패이고 큰 베팅이면 폴드
            ai.folded = True
            ai.has_acted = True
            await game.channel.send(f"🏳️ **{ai.display_name}**님이 폴드했습니다.")


# ──────────────────────────────────────────────
# 베팅 라운드 오케스트레이션
# ──────────────────────────────────────────────

async def process_betting_round(game: HoldemGame):
    num_players = len(game.players)

    while True:
        # 1. 1명 제외 모두 폴드했는지 확인
        active = game.active_players()
        if len(active) == 1:
            await finish_hand_uncontested(game, active[0])
            return

        # 2. 베팅 라운드 종료 조건:
        # 행동 가능한(안 폴드, 안 올인) 모든 플레이어가 행동을 마쳤고(has_acted),
        # 모든 활성 플레이어의 current_street_bet이 highest_bet과 같거나 올인 상태인 경우
        can_act = game.players_can_act()
        all_matched = all(p.current_street_bet == game.highest_bet or p.all_in for p in active)
        all_acted = all(p.has_acted for p in can_act)

        # 행동 가능한 사람이 0명이거나 1명이고 베팅이 맞춰진 경우 바로 다음 스트리트
        if (len(can_act) <= 1 and all_matched) or (all_acted and all_matched):
            break

        # 다음 차례 찾기
        actor = game.current_actor()
        if not actor or actor.folded or actor.all_in:
            game.current_actor_idx = (game.current_actor_idx + 1) % num_players
            continue

        # 액션 진행
        if actor.is_ai:
            await execute_ai_turn(game, actor)
        else:
            embed = build_table_embed(game, actor)
            view = PlayerActionView(game, actor)
            msg = await game.channel.send(embed=embed, view=view)

            async def action_timer():
                try:
                    await asyncio.sleep(DEFAULT_ACTION_SECONDS)
                    # 타임아웃 시 체크 가능하면 체크, 아니면 폴드
                    call_cost = game.highest_bet - actor.current_street_bet
                    if call_cost == 0:
                        actor.has_acted = True
                        await game.channel.send(f"⏰ 시간 초과! **{actor.display_name}**님이 자동 체크했습니다.")
                    else:
                        actor.folded = True
                        actor.has_acted = True
                        await game.channel.send(f"⏰ 시간 초과! **{actor.display_name}**님이 자동 폴드되었습니다.")
                except asyncio.CancelledError:
                    pass

            game.timer_task = asyncio.create_task(action_timer())
            await game.timer_task

            try:
                for item in view.children:
                    item.disabled = True
                await msg.edit(view=view)
            except Exception:
                pass

        # 다음 플레이어로 이동
        game.current_actor_idx = (game.current_actor_idx + 1) % num_players

    # 스트리트 종료: 다음 단계 진행
    await advance_street(game)


async def advance_street(game: HoldemGame):
    # 스트리트 베팅 초기화
    for p in game.players:
        p.current_street_bet = 0
        p.has_acted = False

    game.highest_bet = 0
    game.min_raise = BIG_BLIND

    # 스트리트 전환
    if game.phase == "PREFLOP":
        game.phase = "FLOP"
        game.deck.pop()  # 번 카드 (Burn)
        game.board.extend([game.deck.pop(), game.deck.pop(), game.deck.pop()])
        await game.channel.send(f"🎴 **[FLOP]** 플롭 오픈: **{game.board[0]} {game.board[1]} {game.board[2]}**")
    elif game.phase == "FLOP":
        game.phase = "TURN"
        game.deck.pop()  # Burn
        game.board.append(game.deck.pop())
        await game.channel.send(f"🎴 **[TURN]** 턴 카드 오픈: **{game.board[3]}** (보드: {game.format_board()})")
    elif game.phase == "TURN":
        game.phase = "RIVER"
        game.deck.pop()  # Burn
        game.board.append(game.deck.pop())
        await game.channel.send(f"🎴 **[RIVER]** 리버 카드 오픈: **{game.board[4]}** (보드: {game.format_board()})")
    elif game.phase == "RIVER":
        # 쇼다운 진행
        await showdown_phase(game)
        return

    # 플롭 이후 첫 행동자는 버튼 왼쪽(시계 방향)의 첫 활성 플레이어
    num_players = len(game.players)
    start_idx = (game.button_idx + 1) % num_players
    game.current_actor_idx = start_idx

    # 플레이어들이 모두 올인 상태면 쇼다운까지 논스톱 자동 진행
    can_act = game.players_can_act()
    if len(can_act) <= 1:
        await asyncio.sleep(2)
        await advance_street(game)
    else:
        await process_betting_round(game)


# ──────────────────────────────────────────────
# 쇼다운 및 정산
# ──────────────────────────────────────────────

class NextHandView(discord.ui.View):
    def __init__(self, game: HoldemGame):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="다음 핸드", style=discord.ButtonStyle.primary, emoji="🔁", custom_id="pk_next_hand")
    async def next_hand_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host.id:
            await interaction.response.send_message("호스트만 다음 핸드를 진행할 수 있습니다.", ephemeral=True)
            return

        self.game.round_num += 1
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await start_new_hand(self.game)

    @discord.ui.button(label="테이블 종료", style=discord.ButtonStyle.danger, emoji="🛑", custom_id="pk_end_table")
    async def end_table_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host.id:
            await interaction.response.send_message("호스트만 종료할 수 있습니다.", ephemeral=True)
            return

        self.game.phase = "FINISHED"
        active_holdem_games.pop(self.game.channel.id, None)
        await interaction.response.edit_message(content="🏁 포커 테이블이 종료되었습니다. 수고하셨습니다!", view=None)


async def finish_hand_uncontested(game: HoldemGame, winner: Player):
    """상대가 모두 폴드하여 쇼다운 없이 승리"""
    winner.chips += game.pot
    embed = discord.Embed(
        title="🏆 승자 결정 (쇼다운 없음)",
        description=(
            f"모든 상대가 폴드하여 **{winner.mention}**님이 승리했습니다!\n"
            f"💰 **획득한 팟:** **{game.pot} 칩** (현재 스택: **{winner.chips} 칩**)"
        ),
        color=0x2ecc71
    )
    view = NextHandView(game)
    await game.channel.send(embed=embed, view=view)


async def showdown_phase(game: HoldemGame):
    game.phase = "SHOWDOWN"
    active = game.active_players()

    results = []
    for p in active:
        all_cards = p.hole_cards + game.board
        cat, rank_tuple, name = evaluate_7_cards(all_cards)
        score = (cat, rank_tuple)
        results.append((p, score, name))

    # 최고 점수 정렬
    results.sort(key=lambda x: x[1], reverse=True)
    best_score = results[0][1]
    winners = [r for r in results if r[1] == best_score]

    # 팟 분배 (동률 시 분할)
    pot_share = game.pot // len(winners)
    for w, _, _ in winners:
        w.chips += pot_share

    embed = discord.Embed(
        title=f"🃏 [HAND {game.round_num} 쇼다운] 최종 결과",
        description=(
            f"커뮤니티 보드: **{game.format_board()}**\n"
            f"총 팟: **{game.pot} 칩**\n\n"
            f"🎉 **우승자:** {', '.join([w.mention for w, _, _ in winners])} (+{pot_share} 칩)"
        ),
        color=0xf1c40f
    )

    lines = []
    for p, _, hand_name in results:
        win_tag = " 👑 **[승자]**" if any(w == p for w, _, _ in winners) else ""
        lines.append(f"• **{p.display_name}**: {p.format_hole()} — **{hand_name}**{win_tag}\n  (남은 스택: **{p.chips} 칩**)")

    embed.add_field(name="핸드 공개", value="\n".join(lines), inline=False)
    view = NextHandView(game)
    await game.channel.send(embed=embed, view=view)


# ──────────────────────────────────────────────
# 진입점 및 Cog 등록
# ──────────────────────────────────────────────

async def start_holdem_ui(interaction: discord.Interaction):
    channel = interaction.channel
    if channel.id in active_holdem_games:
        existing = active_holdem_games[channel.id]
        if existing.phase not in ("FINISHED", "CANCELLED"):
            await interaction.response.send_message("이 채널에 이미 진행 중인 홀덤 포커 테이블이 있습니다!", ephemeral=True)
            return

    game = HoldemGame(interaction.user, channel)
    active_holdem_games[channel.id] = game

    lobby_view = HoldemLobbyView(game)
    embed = lobby_view._build_embed()
    await interaction.response.send_message(embed=embed, view=lobby_view)
    game.lobby_message = await interaction.original_response()


class HoldemCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="포커", description="텍사스 홀덤 포커 게임을 시작합니다.")
    async def holdem_command(self, ctx):
        channel = ctx.channel
        if channel.id in active_holdem_games:
            existing = active_holdem_games[channel.id]
            if existing.phase not in ("FINISHED", "CANCELLED"):
                await ctx.send("이 채널에 이미 진행 중인 홀덤 포커 테이블이 있습니다!", ephemeral=True)
                return

        game = HoldemGame(ctx.author, channel)
        active_holdem_games[channel.id] = game

        lobby_view = HoldemLobbyView(game)
        embed = lobby_view._build_embed()
        await ctx.send(embed=embed, view=lobby_view)


async def setup(bot):
    await bot.add_cog(HoldemCog(bot))
