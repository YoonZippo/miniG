"""
블랙잭 (Blackjack) — MINIG Discord Bot Cog
계획서 기준: blackjack_discord_bot_plan.md v1.0
- 1~5인 (솔로 모드 즉시 플레이 및 멀티 테이블 지원)
- 6덱 슈, S17 룰, 내추럴 블랙잭 3:2 배당
"""

import discord
import logging
import asyncio
import secrets
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from discord.ext import commands

logger = logging.getLogger('gameBot.blackjack')

# ──────────────────────────────────────────────
# 상수 및 카드 정의
# ──────────────────────────────────────────────
MIN_PLAYERS = 1
MAX_PLAYERS = 5
INITIAL_CHIPS = 1000
DEFAULT_TURN_SECONDS = 45

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]

active_blackjack_games: Dict[int, 'BlackjackGame'] = {}


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str

    def __str__(self) -> str:
        return f"[{self.suit}{self.rank}]"


def create_shoe(num_decks: int = 6) -> List[Card]:
    shoe = [Card(rank, suit) for _ in range(num_decks) for suit in SUITS for rank in RANKS]
    # secrets 모듈을 통한 안전한 무작위 셔플
    rng = secrets.SystemRandom()
    rng.shuffle(shoe)
    return shoe


def evaluate_hand(cards: List[Card]) -> Tuple[int, bool]:
    """(best_score, is_soft) 반환"""
    values = [11 if c.rank == "A" else 10 if c.rank in {"J", "Q", "K"} else int(c.rank) for c in cards]
    total = sum(values)
    ace_count = sum(1 for c in cards if c.rank == "A")

    while total > 21 and ace_count > 0:
        total -= 10
        ace_count -= 1

    is_soft = ace_count > 0
    return total, is_soft


def is_natural_blackjack(cards: List[Card]) -> bool:
    return len(cards) == 2 and evaluate_hand(cards)[0] == 21


# ──────────────────────────────────────────────
# 플레이어 상태
# ──────────────────────────────────────────────

class PlayerHand:
    def __init__(self, member: discord.Member, chips: int = INITIAL_CHIPS):
        self.member = member
        self.cards: List[Card] = []
        self.bet: int = 0
        self.chips: int = chips
        self.status: str = "WAITING"
        # WAITING | BETTING | PLAYING | STAND | BUST | BLACKJACK | DONE
        self.result_text: str = ""
        self.net_gain: int = 0

    @property
    def display_name(self) -> str:
        return self.member.display_name

    @property
    def mention(self) -> str:
        return self.member.mention

    def score(self) -> int:
        return evaluate_hand(self.cards)[0]

    def is_soft(self) -> bool:
        return evaluate_hand(self.cards)[1]

    def format_cards(self, hide_second: bool = False) -> str:
        if not self.cards:
            return "카드 없음"
        if hide_second and len(self.cards) >= 2:
            return f"{self.cards[0]} [??]"
        return " ".join(str(c) for c in self.cards)


# ──────────────────────────────────────────────
# 게임 상태 관리
# ──────────────────────────────────────────────

class BlackjackGame:
    def __init__(self, host: discord.Member, channel: discord.TextChannel):
        self.host = host
        self.channel = channel
        self.players: List[PlayerHand] = [PlayerHand(host)]
        self.dealer_cards: List[Card] = []
        self.shoe: List[Card] = create_shoe(6)

        self.phase: str = "LOBBY"
        # LOBBY -> BETTING -> PLAYER_TURN -> DEALER_TURN -> SETTLEMENT -> FINISHED -> CANCELLED
        self.round_num: int = 1
        self.current_turn_idx: int = 0
        self.timer_task: Optional[asyncio.Task] = None

        self.lobby_message: Optional[discord.Message] = None
        self.game_message: Optional[discord.Message] = None

    def get_player(self, user_id: int) -> Optional[PlayerHand]:
        for p in self.players:
            if p.member.id == user_id:
                return p
        return None

    def draw_card(self) -> Card:
        if len(self.shoe) < 20:
            self.shoe = create_shoe(6)
        return self.shoe.pop()

    def current_player(self) -> Optional[PlayerHand]:
        if 0 <= self.current_turn_idx < len(self.players):
            return self.players[self.current_turn_idx]
        return None

    def reset_round(self):
        self.dealer_cards = []
        for p in self.players:
            p.cards = []
            p.bet = 0
            p.status = "WAITING"
            p.result_text = ""
            p.net_gain = 0
        self.current_turn_idx = 0


# ──────────────────────────────────────────────
# UI: 로비 및 베팅
# ──────────────────────────────────────────────

class BlackjackLobbyView(discord.ui.View):
    def __init__(self, game: BlackjackGame):
        super().__init__(timeout=None)
        self.game = game

    def _build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🂡 블랙잭 (Blackjack) — 테이블 로비",
            description=(
                "**딜러를 상대로 21점에 가장 가까운 점수를 만드는 카지노 카드 게임!**\n\n"
                "• **내추럴 블랙잭(A+10)**: 1.5배(3:2) 배당\n"
                "• **딜러 규칙**: S17 (모든 17 이상에서 딜러는 스탠드)\n"
                "• **테이블 칩**: 참가자당 1,000칩 지급 (게임 내 가상 칩)\n\n"
                f"👥 **참가 인원:** {len(self.game.players)}/{MAX_PLAYERS}명\n"
                f"👑 **호스트:** {self.game.host.mention}"
            ),
            color=0x1b4332
        )
        player_list = "\n".join([f"{i+1}. {p.display_name} (보유: {p.chips} 칩)" for i, p in enumerate(self.game.players)])
        embed.add_field(name="테이블 좌석", value=player_list or "없음", inline=False)
        embed.set_footer(text="혼자 바로 시작하려면 [솔로 즉시 시작], 친구와 함께라면 [참가] 후 시작하세요.")
        return embed

    @discord.ui.button(label="솔로 즉시 시작", style=discord.ButtonStyle.success, emoji="⚡", custom_id="bj_solo_start")
    async def solo_start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host.id:
            await interaction.response.send_message("호스트만 시작할 수 있습니다.", ephemeral=True)
            return
        # 솔로 모드: 호스트 1명으로 즉시 시작
        self.game.players = [self.game.players[0]]
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await start_betting_phase(self.game)

    @discord.ui.button(label="참가", style=discord.ButtonStyle.primary, emoji="✋", custom_id="bj_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.get_player(interaction.user.id):
            await interaction.response.send_message("이미 테이블에 착석하셨습니다!", ephemeral=True)
            return
        if len(self.game.players) >= MAX_PLAYERS:
            await interaction.response.send_message("테이블 정원(5명)이 꽉 찼습니다!", ephemeral=True)
            return

        self.game.players.append(PlayerHand(interaction.user))
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="나가기", style=discord.ButtonStyle.secondary, emoji="🚪", custom_id="bj_leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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
                active_blackjack_games.pop(self.game.channel.id, None)
                await interaction.response.edit_message(content="🛑 모든 플레이어가 퇴장하여 테이블이 종료되었습니다.", embed=None, view=None)
                return
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="테이블 시작", style=discord.ButtonStyle.primary, emoji="▶️", custom_id="bj_multi_start")
    async def multi_start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host.id:
            await interaction.response.send_message("호스트만 시작할 수 있습니다.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await start_betting_phase(self.game)


# ──────────────────────────────────────────────
# 베팅 단계
# ──────────────────────────────────────────────

class BetSelectView(discord.ui.View):
    def __init__(self, game: BlackjackGame):
        super().__init__(timeout=60)
        self.game = game

    @discord.ui.select(
        placeholder="베팅할 칩 금액을 선택하세요",
        options=[
            discord.SelectOption(label="10 칩", value="10", emoji="🪙"),
            discord.SelectOption(label="20 칩", value="20", emoji="🪙"),
            discord.SelectOption(label="50 칩 (추천)", value="50", emoji="🪙", default=True),
            discord.SelectOption(label="100 칩", value="100", emoji="💰"),
            discord.SelectOption(label="200 칩", value="200", emoji="💎"),
        ]
    )
    async def select_bet(self, interaction: discord.Interaction, select: discord.ui.Select):
        player = self.game.get_player(interaction.user.id)
        if not player:
            await interaction.response.send_message("테이블 참가자가 아닙니다.", ephemeral=True)
            return

        amount = int(select.values[0])
        if amount > player.chips:
            await interaction.response.send_message(f"보유 칩({player.chips} 칩)보다 많이 베팅할 수 없습니다!", ephemeral=True)
            return

        player.bet = amount
        player.status = "BET_PLACED"
        await interaction.response.send_message(f"✅ **{amount} 칩** 베팅을 완료했습니다!", ephemeral=True)

        # 모든 플레이어가 베팅 완료했는지 확인
        all_bet = all(p.bet > 0 for p in self.game.players)
        if all_bet:
            if self.game.timer_task and not self.game.timer_task.done():
                self.game.timer_task.cancel()


async def start_betting_phase(game: BlackjackGame):
    game.phase = "BETTING"
    game.reset_round()

    embed = discord.Embed(
        title=f"🪙 [ROUND {game.round_num}] 베팅 단계",
        description=(
            "딜러가 카드를 배분하기 전, 이번 라운드에 걸 칩을 선택하세요.\n"
            "아래 선택 메뉴에서 베팅 금액(10~200 칩)을 선택하세요.\n\n"
            "⏱️ 제한시간: **30초** (시간 초과 시 기본 50칩 자동 베팅)"
        ),
        color=0xf39c12
    )
    for p in game.players:
        embed.add_field(name=f"{p.display_name}", value=f"보유 칩: {p.chips} 칩", inline=True)

    view = BetSelectView(game)
    game.game_message = await game.channel.send(embed=embed, view=view)

    async def betting_timer():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass
        # 미베팅자 기본값(50칩 또는 남은 칩 전액) 처리
        for p in game.players:
            if p.bet == 0:
                p.bet = min(50, p.chips) if p.chips > 0 else 0
        await deal_initial_cards(game)

    game.timer_task = asyncio.create_task(betting_timer())


# ──────────────────────────────────────────────
# 카드 배분 및 플레이어 턴
# ──────────────────────────────────────────────

async def deal_initial_cards(game: BlackjackGame):
    game.phase = "PLAYER_TURN"

    # 플레이어마다 2장, 딜러 2장
    for p in game.players:
        p.cards = [game.draw_card(), game.draw_card()]
        p.status = "PLAYING"

    game.dealer_cards = [game.draw_card(), game.draw_card()]

    # 내추럴 블랙잭 확인
    dealer_score, _ = evaluate_hand(game.dealer_cards)
    dealer_has_bj = is_natural_blackjack(game.dealer_cards)

    for p in game.players:
        if is_natural_blackjack(p.cards):
            p.status = "BLACKJACK"

    # 딜러가 내추럴 블랙잭인 경우 즉시 정산으로 이동
    if dealer_has_bj:
        embed = discord.Embed(
            title="🃏 딜러 내추럴 블랙잭!",
            description=f"딜러의 카드가 **{game.dealer_cards[0]} {game.dealer_cards[1]}** (블랙잭) 입니다!\n즉시 라운드 정산으로 넘어갑니다.",
            color=0xe74c3c
        )
        await game.channel.send(embed=embed)
        await asyncio.sleep(2)
        await settlement_phase(game)
        return

    # 플레이어 턴 순차 진행
    game.current_turn_idx = 0
    await proceed_player_turn(game)


class PlayerActionView(discord.ui.View):
    def __init__(self, game: BlackjackGame, player: PlayerHand):
        super().__init__(timeout=DEFAULT_TURN_SECONDS)
        self.game = game
        self.player = player

        # 더블다운 가능 여부 (카드 2장이고 보유 칩이 베팅액만큼 더 있을 때)
        if len(player.cards) != 2 or player.chips < player.bet * 2:
            self.double_down_button.disabled = True

    async def _handle_next(self, interaction: discord.Interaction):
        # 턴 타이머 취소 후 다음 처리
        if self.game.timer_task and not self.game.timer_task.done():
            self.game.timer_task.cancel()

    @discord.ui.button(label="히트 (Hit)", style=discord.ButtonStyle.primary, emoji="➕", custom_id="bj_hit")
    async def hit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.member.id:
            await interaction.response.send_message("현재 당신의 차례가 아닙니다!", ephemeral=True)
            return

        new_card = self.game.draw_card()
        self.player.cards.append(new_card)
        score = self.player.score()

        if score > 21:
            self.player.status = "BUST"
            await interaction.response.send_message(f"💥 카드: {new_card} (합계: **{score}점**) — **버스트(Bust)!**", ephemeral=False)
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            await self._handle_next(interaction)
        elif score == 21:
            self.player.status = "STAND"
            await interaction.response.send_message(f"🎯 카드: {new_card} (합계: **21점**) — 자동 스탠드!", ephemeral=False)
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            await self._handle_next(interaction)
        else:
            await interaction.response.send_message(f"🃏 카드: {new_card} (현재 합계: **{score}점**)", ephemeral=False)
            # 히트 후에는 더블다운 불가
            self.double_down_button.disabled = True
            await interaction.message.edit(embed=self._build_turn_embed(), view=self)

    @discord.ui.button(label="스탠드 (Stand)", style=discord.ButtonStyle.secondary, emoji="🛑", custom_id="bj_stand")
    async def stand_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.member.id:
            await interaction.response.send_message("현재 당신의 차례가 아닙니다!", ephemeral=True)
            return

        self.player.status = "STAND"
        await interaction.response.send_message(f"🛑 **{self.player.display_name}**님이 **{self.player.score()}점**으로 스탠드했습니다.", ephemeral=False)
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        await self._handle_next(interaction)

    @discord.ui.button(label="더블다운 (Double)", style=discord.ButtonStyle.success, emoji="✖️2", custom_id="bj_double")
    async def double_down_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.member.id:
            await interaction.response.send_message("현재 당신의 차례가 아닙니다!", ephemeral=True)
            return

        self.player.bet *= 2
        new_card = self.game.draw_card()
        self.player.cards.append(new_card)
        score = self.player.score()

        if score > 21:
            self.player.status = "BUST"
            await interaction.response.send_message(f"💥 더블다운! 카드: {new_card} (합계: **{score}점**) — **버스트!** (베팅: {self.player.bet} 칩)", ephemeral=False)
        else:
            self.player.status = "STAND"
            await interaction.response.send_message(f"💰 더블다운! 카드: {new_card} (합계: **{score}점**) — 스탠드 (베팅: {self.player.bet} 칩)", ephemeral=False)

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        await self._handle_next(interaction)

    def _build_turn_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🂡 블랙잭 — {self.player.display_name}님의 차례",
            description=(
                f"🎩 **딜러 공개 카드:** {self.game.dealer_cards[0]} [??]\n\n"
                f"👤 **{self.player.display_name}님의 패:** {self.player.format_cards()}\n"
                f"📊 **현재 점수:** **{self.player.score()}점** {'(소프트)' if self.player.is_soft() else ''}\n"
                f"🪙 **베팅액:** {self.player.bet} 칩 (남은 칩: {self.player.chips - self.player.bet} 칩)\n\n"
                "원하시는 행동을 선택하세요:"
            ),
            color=0x2980b9
        )
        embed.set_footer(text=f"제한시간 {DEFAULT_TURN_SECONDS}초 (시간 초과 시 자동 스탠드)")
        return embed


async def proceed_player_turn(game: BlackjackGame):
    while game.current_turn_idx < len(game.players):
        player = game.players[game.current_turn_idx]

        # 이미 블랙잭인 경우 자동 스탠드
        if player.status == "BLACKJACK":
            await game.channel.send(f"🎉 **{player.display_name}**님 내추럴 블랙잭! (21점)")
            game.current_turn_idx += 1
            continue

        player.status = "PLAYING"
        view = PlayerActionView(game, player)
        embed = view._build_turn_embed()
        await game.channel.send(embed=embed, view=view)

        async def turn_timer():
            try:
                await asyncio.sleep(DEFAULT_TURN_SECONDS)
                if player.status == "PLAYING":
                    player.status = "STAND"
                    await game.channel.send(f"⏰ 시간 초과! **{player.display_name}**님이 {player.score()}점으로 자동 스탠드 처리되었습니다.")
            except asyncio.CancelledError:
                pass

        game.timer_task = asyncio.create_task(turn_timer())
        await game.timer_task

        game.current_turn_idx += 1

    # 모든 플레이어 턴 종료 -> 딜러 턴
    await dealer_turn(game)


# ──────────────────────────────────────────────
# 딜러 턴 및 정산
# ──────────────────────────────────────────────

async def dealer_turn(game: BlackjackGame):
    game.phase = "DEALER_TURN"

    # 모든 플레이어가 버스트인 경우 딜러는 추가 카드를 뽑지 않고 즉시 정산
    all_busted = all(p.status == "BUST" for p in game.players)

    dealer_score, is_soft = evaluate_hand(game.dealer_cards)
    embed = discord.Embed(
        title="🎩 딜러 카드 공개",
        description=f"딜러의 숨겨진 카드를 공개합니다: **{game.dealer_cards[0]} {game.dealer_cards[1]}** (합계: **{dealer_score}점**)",
        color=0x8e44ad
    )
    await game.channel.send(embed=embed)
    await asyncio.sleep(1.5)

    if not all_busted:
        # S17: 17 이상이면 스탠드
        while dealer_score < 17:
            new_card = game.draw_card()
            game.dealer_cards.append(new_card)
            dealer_score, is_soft = evaluate_hand(game.dealer_cards)
            await game.channel.send(f"딜러 히트: {new_card} (현재 합계: **{dealer_score}점**)")
            await asyncio.sleep(1.5)

        if dealer_score > 21:
            await game.channel.send(f"💥 **딜러 버스트! ({dealer_score}점)** 버스트하지 않은 모든 플레이어가 승리합니다!")
        else:
            await game.channel.send(f"🛑 딜러 **{dealer_score}점**으로 스탠드!")

    await asyncio.sleep(1)
    await settlement_phase(game)


class SettlementView(discord.ui.View):
    def __init__(self, game: BlackjackGame):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="다음 라운드", style=discord.ButtonStyle.primary, emoji="🔁", custom_id="bj_next_round")
    async def next_round_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host.id:
            await interaction.response.send_message("호스트만 다음 라운드를 시작할 수 있습니다.", ephemeral=True)
            return

        # 칩이 0 이하인 플레이어 퇴장 처리
        alive_players = [p for p in self.game.players if p.chips > 0]
        if not alive_players:
            await interaction.response.send_message("모든 플레이어의 칩이 소진되었습니다! 새 게임을 시작해주세요.", ephemeral=True)
            return

        self.game.players = alive_players
        self.game.round_num += 1
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await start_betting_phase(self.game)

    @discord.ui.button(label="테이블 종료", style=discord.ButtonStyle.danger, emoji="🛑", custom_id="bj_end_game")
    async def end_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host.id:
            await interaction.response.send_message("호스트만 종료할 수 있습니다.", ephemeral=True)
            return
        self.game.phase = "FINISHED"
        active_blackjack_games.pop(self.game.channel.id, None)
        await interaction.response.edit_message(content="🏁 블랙잭 테이블이 종료되었습니다. 수고하셨습니다!", view=None)


async def settlement_phase(game: BlackjackGame):
    game.phase = "SETTLEMENT"
    dealer_score, _ = evaluate_hand(game.dealer_cards)
    dealer_bust = dealer_score > 21
    dealer_has_bj = is_natural_blackjack(game.dealer_cards)

    embed = discord.Embed(
        title=f"📊 [ROUND {game.round_num}] 라운드 결과 정산",
        color=0x2ecc71
    )
    embed.add_field(
        name="🎩 딜러 최종 패",
        value=f"{' '.join(str(c) for c in game.dealer_cards)}\n최종 점수: **{dealer_score}점** {'(버스트)' if dealer_bust else ''}",
        inline=False
    )

    result_lines = []
    for p in game.players:
        p_score = p.score()
        p_bj = is_natural_blackjack(p.cards)

        if p.status == "BUST":
            # 플레이어 버스트: 패배
            p.chips -= p.bet
            p.net_gain = -p.bet
            status_desc = f"❌ 버스트 패배 (-{p.bet} 칩)"
        elif dealer_has_bj:
            if p_bj:
                # 둘 다 블랙잭: 푸시
                p.net_gain = 0
                status_desc = f"🤝 딜러와 블랙잭 동점 (Push, 0 칩)"
            else:
                p.chips -= p.bet
                p.net_gain = -p.bet
                status_desc = f"❌ 딜러 블랙잭으로 패배 (-{p.bet} 칩)"
        elif p_bj:
            # 내추럴 블랙잭 승리 (3:2)
            win_amount = int(p.bet * 1.5)
            p.chips += win_amount
            p.net_gain = win_amount
            status_desc = f"🎉 **내추럴 블랙잭 승리! (+{win_amount} 칩)**"
        elif dealer_bust:
            # 딜러 버스트: 플레이어 승리 (1:1)
            p.chips += p.bet
            p.net_gain = p.bet
            status_desc = f"🎉 딜러 버스트로 승리 (+{p.bet} 칩)"
        elif p_score > dealer_score:
            # 점수 승리 (1:1)
            p.chips += p.bet
            p.net_gain = p.bet
            status_desc = f"🎉 점수 승리 ({p_score} vs {dealer_score}) (+{p.bet} 칩)"
        elif p_score == dealer_score:
            # 동점 (Push)
            p.net_gain = 0
            status_desc = f"🤝 무승부 ({p_score}점 동점, 0 칩)"
        else:
            # 점수 패배
            p.chips -= p.bet
            p.net_gain = -p.bet
            status_desc = f"❌ 점수 패배 ({p_score} vs {dealer_score}) (-{p.bet} 칩)"

        card_str = " ".join(str(c) for c in p.cards)
        result_lines.append(f"• **{p.display_name}**: {card_str} ({p_score}점)\n  결과: {status_desc} | 남은 보유 칩: **{p.chips} 칩**")

    embed.add_field(name="👥 플레이어 결과", value="\n\n".join(result_lines), inline=False)
    view = SettlementView(game)
    await game.channel.send(embed=embed, view=view)


# ──────────────────────────────────────────────
# 진입점 및 Cog 등록
# ──────────────────────────────────────────────

async def start_blackjack_ui(interaction: discord.Interaction):
    channel = interaction.channel
    if channel.id in active_blackjack_games:
        existing = active_blackjack_games[channel.id]
        if existing.phase not in ("FINISHED", "CANCELLED"):
            await interaction.response.send_message("이 채널에 이미 진행 중인 블랙잭 테이블이 있습니다!", ephemeral=True)
            return

    game = BlackjackGame(interaction.user, channel)
    active_blackjack_games[channel.id] = game

    lobby_view = BlackjackLobbyView(game)
    embed = lobby_view._build_embed()
    await interaction.response.send_message(embed=embed, view=lobby_view)
    game.lobby_message = await interaction.original_response()


class BlackjackCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="블랙잭", description="블랙잭 카드 게임을 시작합니다.")
    async def blackjack_command(self, ctx):
        channel = ctx.channel
        if channel.id in active_blackjack_games:
            existing = active_blackjack_games[channel.id]
            if existing.phase not in ("FINISHED", "CANCELLED"):
                await ctx.send("이 채널에 이미 진행 중인 블랙잭 테이블이 있습니다!", ephemeral=True)
                return

        game = BlackjackGame(ctx.author, channel)
        active_blackjack_games[channel.id] = game

        lobby_view = BlackjackLobbyView(game)
        embed = lobby_view._build_embed()
        await ctx.send(embed=embed, view=lobby_view)


async def setup(bot):
    await bot.add_cog(BlackjackCog(bot))
