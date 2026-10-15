import discord
import logging
from discord.ext import commands
from discord import app_commands
from typing import Dict, List
import random
import asyncio
import uuid
from collections import Counter, deque
from database.manager import DatabaseManager

logger = logging.getLogger('gameBot.liar')

db = DatabaseManager()
# 현재 채널별로 진행 중인 게임 상태를 저장할 딕셔너리
active_games: Dict[int, 'LiarGame'] = {}
# 최근 사용된 제시어 30개 추적
recent_words = deque(maxlen=30)

async def cleanup_game(interaction: discord.Interaction, channel_id: int):
    """현재 채널의 진행 중인 게임과 음성 연결을 안전하게 종료하는 헬퍼 함수"""
    if interaction.guild and interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()
    if channel_id in active_games:
        active_games.pop(channel_id, None)

from cogs.liar.words import NORMAL_WORDS

class LiarGame:
    """단일 라이어 게임의 상태를 관리하는 클래스"""
    def __init__(self, host: discord.Member, channel: discord.TextChannel):
        self.session_id = uuid.uuid4().hex
        self.host = host
        self.channel = channel
        self.players: List[discord.Member] = [host]
        self.liar: discord.Member = None
        self.game_mode: str = "NORMAL" # NORMAL 또는 IDIOT
        self.category: str = None
        self.word: str = None
        self.liar_word: str = None
        
        self.turn_order: List[discord.Member] = []
        self.current_turn_index: int = 0
        self.round_count: int = 1
        
        self.phase: str = "LOBBY" # 게임 단계: LOBBY, PLAYING, VOTING, RESOLUTION
        self.votes: Dict[discord.Member, int] = {}
        self.turn_limit: int = 20 # 기본 턴 제한시간 (초)
        self.vote_limit: int = 30 # 기본 투표 제한시간 (초)
        self.timer_task: asyncio.Task = None # 턴 제한시간 타이머 태스크
        
        self.final_target: discord.Member = None
        self.hints_log: list = []

class TimerSettingModal(discord.ui.Modal, title="제한시간 설정"):
    def __init__(self, game: LiarGame, view: discord.ui.View):
        super().__init__()
        self.game = game
        self.lobby_view = view

        self.turn_time = discord.ui.TextInput(
            label="발언 제한시간 (초)",
            default=str(game.turn_limit),
            placeholder="숫자만 입력 (최소 5)",
            min_length=1,
            max_length=3
        )
        self.add_item(self.turn_time)

        self.vote_time = discord.ui.TextInput(
            label="투표 제한시간 (초)",
            default=str(game.vote_limit),
            placeholder="숫자만 입력 (최소 5)",
            min_length=1,
            max_length=3
        )
        self.add_item(self.vote_time)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_turn = int(self.turn_time.value)
            new_vote = int(self.vote_time.value)
            if new_turn < 5 or new_vote < 5:
                await interaction.response.send_message("제한시간은 최소 5초 이상이어야 합니다.", ephemeral=True)
                return
            self.game.turn_limit = new_turn
            self.game.vote_limit = new_vote
            await self.lobby_view.update_lobby(interaction)
        except ValueError:
            await interaction.response.send_message("올바른 숫자를 입력해주세요.", ephemeral=True)

class LobbyView(discord.ui.View):
    """참가자를 모집하는 로비 뷰 (버튼 포함)"""
    def __init__(self, game: LiarGame):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="참가하기", style=discord.ButtonStyle.success, custom_id="join_game")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 이미 참가한 유저인지 확인
        if interaction.user in self.game.players:
            await interaction.response.send_message("이미 참가하셨습니다!", ephemeral=True)
            return
        
        self.game.players.append(interaction.user)
        await self.update_lobby(interaction)

    @discord.ui.button(label="게임 시작", style=discord.ButtonStyle.primary, custom_id="start_game")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 방장만 시작할 수 있도록 제한
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 게임을 시작할 수 있습니다!", ephemeral=True)
            return
        
        # 최소 인원 체크 (테스트를 위해 일단 2명 이상으로 변경 가능. 정상적인 게임은 3명 추천)
        if len(self.game.players) < 3:
            await interaction.response.send_message("최소 3명 이상의 플레이어가 필요합니다!", ephemeral=True)
            return

        # 모드 선택 뷰로 넘어가기 (방장에게만 보임)
        view = ModeView(self.game)
        await interaction.response.send_message("게임 모드를 선택해주세요!", view=view, ephemeral=True)
        
        # 이전 모집 로비 메시지의 버튼 비활성화
        await interaction.message.edit(view=None)

    @discord.ui.button(label="제한시간 변경", style=discord.ButtonStyle.secondary, custom_id="change_timer")
    async def timer_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 방장만 변경 가능
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 제한시간을 변경할 수 있습니다!", ephemeral=True)
            return
        
        await interaction.response.send_modal(TimerSettingModal(self.game, self))

    @discord.ui.button(label="강제 중단", style=discord.ButtonStyle.danger, custom_id="cancel_game")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 방장만 취소할 수 있도록 제한
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 게임을 강제 중단할 수 있습니다!", ephemeral=True)
            return

        # 게임 삭제 및 음성 채널 퇴장
        await cleanup_game(interaction, interaction.channel_id)

        embed = discord.Embed(
            title="🚫 모집 취소", 
            description="방장에 의해 게임 모집이 강제 중단되었습니다.", 
            color=0xff0000
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def update_lobby(self, interaction: discord.Interaction):
        # 로비 임베드 메시지 업데이트
        embed = discord.Embed(
            title="🕵️ 라이어 게임 모집 중!", 
            description=f"참가 버튼을 눌러 게임에 들어오세요.\n\n⏱️ **현재 설정된 시간:** 발언 {self.game.turn_limit}초 / 투표 {self.game.vote_limit}초", 
            color=0x2b2d31
        )
        players_str = "\n".join([f"👤 {p.display_name}" for p in self.game.players])
        embed.add_field(name=f"현재 참가자 ({len(self.game.players)}명)", value=players_str)
        
        await interaction.response.edit_message(embed=embed, view=self)

class ModeView(discord.ui.View):
    """일반 모드 또는 바보 라이어 모드를 선택하는 뷰"""
    def __init__(self, game: LiarGame):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="일반 모드", style=discord.ButtonStyle.primary, custom_id="mode_normal")
    async def normal_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.game.game_mode = "NORMAL"
        await interaction.response.edit_message(content="카테고리를 선택해주세요! (일반 모드)", view=CategoryView(self.game))

    @discord.ui.button(label="바보 라이어 모드 🤪", style=discord.ButtonStyle.success, custom_id="mode_idiot")
    async def idiot_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.game.game_mode = "IDIOT"
        await interaction.response.edit_message(content="카테고리를 선택해주세요! (바보 라이어 모드)", view=CategoryView(self.game))

class CategorySelect(discord.ui.Select):
    """카테고리를 선택하는 드롭다운 메뉴"""
    def __init__(self, game: LiarGame):
        self.game = game
        options = [
            discord.SelectOption(label="음식", description="먹는 것과 관련된 카테고리", emoji="🍔"),
            discord.SelectOption(label="장소", description="특정 장소 카테고리", emoji="🏫"),
            discord.SelectOption(label="직업", description="다양한 직업 카테고리", emoji="👮"),
            discord.SelectOption(label="동물", description="동물 카테고리", emoji="🐶"),
            discord.SelectOption(label="물건", description="우리 주변의 다양한 물건들", emoji="📦"),
            discord.SelectOption(label="취미/스포츠", description="취미 및 스포츠 관련 활동", emoji="⚽"),
            discord.SelectOption(label="애니메이션", description="인기 애니메이션 카테고리", emoji="📺")
        ]
        super().__init__(placeholder="카테고리를 선택하세요...", options=options, custom_id="category_select")

    async def callback(self, interaction: discord.Interaction):
        # 1. 카테고리 및 제시어 선정
        self.game.category = self.values[0]
        
        category_words = NORMAL_WORDS[self.game.category]
        
        # 최근 50번 이내에 나오지 않았던 단어만 필터링 (가용 단어 부족 시 롤백 방지)
        available_words = [w for w in category_words if w not in recent_words]
        
        if self.game.game_mode == "IDIOT":
            if len(available_words) >= 2:
                sampled = random.sample(available_words, 2)
            else:
                sampled = random.sample(category_words, 2) # 필터링 된 단어가 부족하면 전체에서 무작위 추출
            self.game.word = sampled[0]
            self.game.liar_word = sampled[1]
            recent_words.append(self.game.word)
            recent_words.append(self.game.liar_word)
        else:
            if len(available_words) >= 1:
                self.game.word = random.choice(available_words)
            else:
                self.game.word = random.choice(category_words) # 필터링 된 단어가 부족하면 전체에서 무작위 추출
            recent_words.append(self.game.word)

        # 2. 역할 분배 (라이어 1명 랜덤 선정)
        self.game.liar = random.choice(self.game.players)

        # 3. 개인 메시지(DM) 전송
        mode_text = "일반 모드" if self.game.game_mode == "NORMAL" else "바보 라이어 모드 🤪"
        await interaction.response.send_message(f"[{mode_text}] '{self.game.category}' 카테고리가 선택되었습니다! 게임을 시작합니다.", ephemeral=True)
        
        for player in self.game.players:
            try:
                if player == self.game.liar:
                    if self.game.game_mode == "IDIOT":
                        await player.send(f"👤 당신은 시민입니다.\n이번 라운드의 제시어는 **[{self.game.liar_word}]** 입니다. 라이어에게 정답을 들키지 않게 모호하게 설명하세요!")
                    else:
                        await player.send(f"🕵️ **당신은 라이어입니다.**\n카테고리는 **[{self.game.category}]** 입니다. 제시어를 들키지 않고 시민들의 설명을 듣고 정답을 눈치껏 유추하세요!")
                else:
                    await player.send(f"👤 당신은 시민입니다.\n이번 라운드의 제시어는 **[{self.game.word}]** 입니다. 라이어에게 정답을 들키지 않게 모호하게 설명하세요!")
            except discord.Forbidden:
                await self.game.channel.send(f"⚠️ {player.mention} 님에게 DM을 보낼 수 없습니다. 서버의 개인 메시지 허용 설정을 확인해주세요.")

        # 4. 턴 순서 정하기
        self.game.turn_order = self.game.players.copy()
        random.shuffle(self.game.turn_order)
        self.game.phase = "PLAYING"

        # 5. 게임 시작 알림 및 첫 번째 턴 안내
        embed = discord.Embed(title="🎮 라이어 게임 시작!", description=f"카테고리: **{self.game.category}**\n모두 DM을 확인해주세요!", color=0xff0000)
        
        turn_list = "\n".join([f"{i+1}. {p.display_name}" for i, p in enumerate(self.game.turn_order)])
        embed.add_field(name="발언 순서", value=turn_list, inline=False)
        
        current_player = self.game.turn_order[self.game.current_turn_index]
        embed.add_field(name="현재 차례", value=f"👉 {current_player.mention} 님, 채널에 채팅을 쳐서 제시어에 대해 설명해주세요! (제한시간: {self.game.turn_limit}초)", inline=False)

        await self.game.channel.send(embed=embed)
        
        # 첫 번째 턴 타이머 시작
        liar_cog = interaction.client.get_cog("LiarGameCog")
        if liar_cog:
            self.game.timer_task = asyncio.create_task(liar_cog.turn_timer(self.game))


class CategoryView(discord.ui.View):
    """방장이 카테고리를 선택할 수 있는 뷰"""
    def __init__(self, game: LiarGame):
        super().__init__(timeout=None)
        self.add_item(CategorySelect(game))

class ExtensionVoteView(discord.ui.View):
    """모든 발언이 한 바퀴 돌았을 때 연장 여부를 투표하는 뷰"""
    def __init__(self, game):
        super().__init__(timeout=game.vote_limit)
        self.game = game
        self.yes_votes = set()
        self.no_votes = set()
        self.voted = set()
        self.message = None

    async def on_timeout(self):
        await self.check_votes()

    async def check_votes(self, interaction: discord.Interaction = None):
        total_players = len(self.game.players)
        yes_threshold = (total_players + 1) // 2
        no_threshold = total_players // 2 + 1
        
        is_finished = interaction is None # timeout means finished
        if len(self.yes_votes) >= yes_threshold: is_finished = True
        elif len(self.no_votes) >= no_threshold: is_finished = True
        elif len(self.voted) >= total_players: is_finished = True
            
        if is_finished:
            for item in self.children: item.disabled = True
            if interaction:
                await interaction.message.edit(view=self)
            elif self.message:
                try: await self.message.edit(view=self)
                except: pass
            
            self.stop()
            
            if len(self.yes_votes) >= len(self.no_votes):
                self.game.round_count += 1
                self.game.current_turn_index = 0
                self.game.phase = "PLAYING"
                
                current_player = self.game.turn_order[0]
                channel = interaction.channel if interaction else self.game.channel
                await channel.send(
                    f"✅ 연장 투표가 가결되었습니다! 두 번째 라운드를 시작합니다.\n👉 첫 번째 차례: {current_player.mention} 님, 설명해주세요! (제한시간: {self.game.turn_limit}초)"
                )
                if getattr(self.game, 'cog', None):
                    if self.game.timer_task: self.game.timer_task.cancel()
                    self.game.timer_task = asyncio.create_task(self.game.cog.turn_timer(self.game))
            else:
                self.game.phase = "VOTING_FINAL"
                view = FinalVoteView(self.game)
                channel = interaction.channel if interaction else self.game.channel
                text = "❌ 연장 투표가 부결되었습니다. 바로 라이어 지목 투표를 시작합니다!" if interaction else "⏱️ 시간 초과! 과반수 반대가 아니므로(또는 기권) 바로 라이어 투표를 시작합니다."
                msg = await channel.send(text, view=view)
                view.message = msg

    @discord.ui.button(label="한 바퀴 더! (찬성)", style=discord.ButtonStyle.success, custom_id="ext_yes")
    async def vote_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.game.players or interaction.user in self.voted:
            return await interaction.response.send_message("투표 권한이 없거나 이미 투표하셨습니다.", ephemeral=True)
        self.voted.add(interaction.user)
        self.yes_votes.add(interaction.user)
        await interaction.response.send_message("찬성에 투표하셨습니다.", ephemeral=True)
        await self.check_votes(interaction)

    @discord.ui.button(label="바로 투표 (반대)", style=discord.ButtonStyle.danger, custom_id="ext_no")
    async def vote_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.game.players or interaction.user in self.voted:
            return await interaction.response.send_message("투표 권한이 없거나 이미 투표하셨습니다.", ephemeral=True)
        self.voted.add(interaction.user)
        self.no_votes.add(interaction.user)
        await interaction.response.send_message("반대에 투표하셨습니다.", ephemeral=True)
        await self.check_votes(interaction)

class FinalVoteSelect(discord.ui.Select):
    def __init__(self, game):
        self.game = game
        options = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in game.players]
        super().__init__(placeholder="가장 의심되는 라이어를 선택하세요...", options=options, custom_id="final_vote_select")
        
    async def callback(self, interaction: discord.Interaction):
        if interaction.user not in self.game.players:
            return await interaction.response.send_message("투표 권한이 없습니다.", ephemeral=True)
            
        target_id = int(self.values[0])
        self.game.votes[interaction.user] = target_id
        await interaction.response.send_message("투표가 완료되었습니다.", ephemeral=True)
        
        if len(self.game.votes) >= len(self.game.players):
            self.view.stop()
            await process_final_vote(self.game, self.view.message, interaction)

class FinalVoteView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=game.vote_limit)
        self.game = game
        self.message = None
        self.add_item(FinalVoteSelect(game))
        
    async def on_timeout(self):
        # 시간 초과 시 남은 건 랜덤 투표가 아니라 그냥 기권 처리 후 결과 확인
        self.stop()
        await process_final_vote(self.game, self.message, None)

class TiebreakerVoteSelect(discord.ui.Select):
    def __init__(self, game, tied_players):
        self.game = game
        self.tied_players = tied_players
        self.game.votes = {}
        options = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in tied_players]
        super().__init__(placeholder="결선 투표: 라이어를 다시 선택하세요...", options=options, custom_id="tiebreaker_vote_select")
        
    async def callback(self, interaction: discord.Interaction):
        if interaction.user not in self.game.players:
            return await interaction.response.send_message("투표 권한이 없습니다.", ephemeral=True)
            
        target_id = int(self.values[0])
        self.game.votes[interaction.user] = target_id
        await interaction.response.send_message("결선 투표가 완료되었습니다.", ephemeral=True)
        
        if len(self.game.votes) >= len(self.game.players):
            self.view.stop()
            await process_tiebreaker_vote(self.game, self.view.message, self.tied_players, interaction)

class TiebreakerVoteView(discord.ui.View):
    def __init__(self, game, tied_players):
        super().__init__(timeout=game.vote_limit)
        self.game = game
        self.message = None
        self.tied_players = tied_players
        self.add_item(TiebreakerVoteSelect(game, tied_players))
        
    async def on_timeout(self):
        self.stop()
        await process_tiebreaker_vote(self.game, self.message, self.tied_players, None)

class KillSaveVoteView(discord.ui.View):
    """특정 플레이어를 죽일지 살릴지 결정하는 뷰"""
    def __init__(self, game, target: discord.Member):
        super().__init__(timeout=game.vote_limit)
        self.game = game
        self.target = target
        self.kill_votes = set()
        self.save_votes = set()
        self.voted = set()
        self.message = None

    async def on_timeout(self):
        await self.check_votes(None)

    async def check_votes(self, interaction: discord.Interaction = None):
        total_players = len(self.game.players)
        eligible_players = total_players - 1 # 본인 제외
        
        is_finished = interaction is None
        kill_threshold = eligible_players // 2 + 1
        save_threshold = eligible_players // 2 + 1 if eligible_players % 2 != 0 else eligible_players // 2
        
        if len(self.kill_votes) >= kill_threshold: is_finished = True
        elif len(self.save_votes) >= save_threshold: is_finished = True
        elif len(self.voted) >= eligible_players: is_finished = True
            
        if is_finished:
            for item in self.children: item.disabled = True
            if interaction: await interaction.message.edit(view=self)
            elif self.message: 
                try: await self.message.edit(view=self)
                except: pass
            self.stop()
                
            channel = interaction.channel if interaction else self.game.channel
            if len(self.kill_votes) > len(self.save_votes):
                await execute_player(self.game, self.target, channel)
            else:
                await channel.send(f"🛡️ {self.target.mention} 님이 과반수 찬성(또는 동점)을 얻지 못해 살아남았습니다! 재투표를 진행합니다.")
                self.game.phase = "VOTING_FINAL"
                self.game.votes = {}
                view = FinalVoteView(self.game)
                msg = await channel.send("다시 라이어로 의심되는 사람을 투표해주세요.", view=view)
                view.message = msg

    @discord.ui.button(label="처형 (찬성)", style=discord.ButtonStyle.danger, custom_id="ks_kill")
    async def vote_kill(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.game.players or interaction.user in self.voted:
            return await interaction.response.send_message("권한이 없거나 이미 투표했습니다.", ephemeral=True)
        if interaction.user == self.target:
            return await interaction.response.send_message("본인에 대한 투표에는 참여할 수 없습니다.", ephemeral=True)
        self.voted.add(interaction.user)
        self.kill_votes.add(interaction.user)
        await interaction.response.send_message("처형에 투표했습니다.", ephemeral=True)
        await self.check_votes(interaction)

    @discord.ui.button(label="무죄 (반대)", style=discord.ButtonStyle.success, custom_id="ks_save")
    async def vote_save(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.game.players or interaction.user in self.voted:
            return await interaction.response.send_message("권한이 없거나 이미 투표했습니다.", ephemeral=True)
        if interaction.user == self.target:
            return await interaction.response.send_message("본인에 대한 투표에는 참여할 수 없습니다.", ephemeral=True)
        self.voted.add(interaction.user)
        self.save_votes.add(interaction.user)
        await interaction.response.send_message("무죄에 투표했습니다.", ephemeral=True)
        await self.check_votes(interaction)

async def process_final_vote(game, message_obj, interaction=None):
    game.phase = "RESOLUTION"
    if message_obj: 
        try: await message_obj.edit(view=None)
        except: pass
    
    vote_counts = Counter(list(game.votes.values()))
    if not vote_counts:
        channel = interaction.channel if interaction else game.channel
        await channel.send("⚠️ 아무도 투표하지 않아 라이어 판별을 건너뜁니다! (라이어 승리)")
        return await execute_player(game, game.liar, channel, force_fail=True)

    max_votes = max(vote_counts.values())
    max_voted_ids = [uid for uid, count in vote_counts.items() if count == max_votes]
    channel = interaction.channel if interaction else game.channel
    
    result_text = "📊 **최종 투표 결과**\n"
    for player in game.players:
        count = list(game.votes.values()).count(player.id)
        result_text += f"- {player.display_name}: {count}표\n"
    await channel.send(result_text)
    
    if len(max_voted_ids) > 1:
        tied_players = [p for p in game.players if p.id in max_voted_ids]
        embed = discord.Embed(
            title="⚠️ 투표 동점자 발생! 결선 투표 진행",
            description="가장 많은 표를 받은 동점자들을 대상으로 다시 한번 투표를 진행합니다.",
            color=0xf1c40f
        )
        game.phase = "TIEBREAKER_VOTE"
        embed.add_field(name="결선 투표 후보", value=", ".join(p.mention for p in tied_players))
        
        view = TiebreakerVoteView(game, tied_players)
        msg = await channel.send(embed=embed, view=view)
        view.message = msg
        return
        
    top_voted_id = max_voted_ids[0]
    top_voted_player = channel.guild.get_member(top_voted_id)
    if not top_voted_player and getattr(game, 'cog', None):
        top_voted_player = await game.cog.bot.fetch_user(top_voted_id)

    game.final_target = top_voted_player
    game.phase = "FINAL_DEFENSE"
    embed = discord.Embed(
        title="🗣️ 최후의 변론",
        description=f"가장 많은 표를 받은 {top_voted_player.mention} 님이 심판대에 올랐습니다.\n\n👉 **{top_voted_player.mention} 님, 채널에 채팅을 쳐서 마지막으로 자신을 변호하세요!** (제한시간: {game.turn_limit}초)",
        color=0xf39c12
    )
    await channel.send(embed=embed)
    
    if getattr(game, 'cog', None):
        if game.timer_task: game.timer_task.cancel()
        game.timer_task = __import__('asyncio').create_task(game.cog.defense_timer(game, top_voted_player))

async def process_tiebreaker_vote(game, message_obj, tied_players, interaction=None):
    game.phase = "RESOLUTION"
    if message_obj: 
        try: await message_obj.edit(view=None)
        except: pass
    
    vote_counts = Counter(list(game.votes.values()))
    channel = interaction.channel if interaction else game.channel
    
    result_text = "📊 **결선 투표 결과**\n"
    for player in tied_players:
        count = list(game.votes.values()).count(player.id)
        result_text += f"- {player.display_name}: {count}표\n"
    await channel.send(result_text)
    
    if not vote_counts:
        await channel.send("⚠️ 아무도 투표하지 않아 라이어 판별을 건너뜁니다! (라이어 승리)")
        return await execute_player(game, game.liar, channel, force_fail=True)

    max_votes = max(vote_counts.values())
    max_voted_ids = [uid for uid, count in vote_counts.items() if count == max_votes]
    
    if len(max_voted_ids) > 1:
        embed = discord.Embed(title="🚨 2차 투표 무효! 라이어 검거 실패!", description=f"결선 투표에서도 동점자가 발생하여 시민들이 합의에 도달하지 못했습니다!\n\n진짜 라이어는 바로 {game.liar.mention} 님이었습니다! (제시어: **{game.word}**)\n\n**🎉 라이어의 승리입니다! 🎉**", color=0xff0000)
        db.record_game_result(
            game.session_id,
            "liar",
            [player.id for player in game.players],
            [game.liar.id],
            special_winner_ids=[game.liar.id],
        )
        await channel.send(embed=embed, view=PostGameView(game))
        return
        
    top_voted_id = max_voted_ids[0]
    top_voted_player = channel.guild.get_member(top_voted_id)
    if not top_voted_player and getattr(game, 'cog', None):
        top_voted_player = await game.cog.bot.fetch_user(top_voted_id)
        
    game.final_target = top_voted_player
    game.phase = "FINAL_DEFENSE"
    embed = discord.Embed(
        title="🗣️ 최후의 변론",
        description=f"가장 많은 표를 받은 {top_voted_player.mention} 님이 심판대에 올랐습니다.\n\n👉 **{top_voted_player.mention} 님, 채널에 채팅을 쳐서 마지막으로 자신을 변호하세요!** (제한시간: {game.turn_limit}초)",
        color=0xf39c12
    )
    await channel.send(embed=embed)
    
    if getattr(game, 'cog', None):
        if game.timer_task: game.timer_task.cancel()
        game.timer_task = __import__('asyncio').create_task(game.cog.defense_timer(game, top_voted_player))

async def execute_player(game, target, channel, force_fail=False):
    if target.id == game.liar.id and not force_fail:
        embed = discord.Embed(title="🚨 라이어 지목 완료!", description=f"처형된 {target.mention} 님은 **라이어가 맞습니다!**\n\n하지만 아직 끝이 아닙니다. {'바보 ' if game.game_mode == 'IDIOT' else ''}라이어에게도 역전의 기회가 있습니다! ({'바보 ' if game.game_mode == 'IDIOT' else ''}라이어 제시어: **{game.liar_word if game.game_mode == 'IDIOT' else '비밀'}**)\n\n👉 **{target.mention} 님, 지금 바로 채팅창에 '시민들의 진짜 제시어'를 유추해서 입력해주세요!**", color=0x3498db)
        game.phase = "LIAR_GUESS"
        await channel.send(embed=embed)
    else:
        embed = discord.Embed(title="🚨 라이어 검거 실패!", description=f"{'처형된 '+target.mention+' 님은 선량한 시민이었습니다!' if not force_fail else '라이어를 검거하지 못했습니다.'}\n\n진짜 라이어는 바로 {game.liar.mention} 님이었습니다! (제시어: **{game.word}**)\n\n**🎉 라이어의 승리입니다! 🎉**", color=0xff0000)
        db.record_game_result(
            game.session_id,
            "liar",
            [player.id for player in game.players],
            [game.liar.id],
            special_winner_ids=[game.liar.id],
        )
        await channel.send(embed=embed, view=PostGameView(game))
class PostGameView(discord.ui.View):
    """게임 종료 후 다시하기 또는 종료를 선택하는 뷰"""
    def __init__(self, game: LiarGame):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="한 번 더 하기", style=discord.ButtonStyle.primary, custom_id="play_again")
    async def play_again_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 게임을 다시 시작할 수 있습니다!", ephemeral=True)
            return
            
        # 타이머 안전하게 해제
        if self.game.timer_task:
            self.game.timer_task.cancel()
            
        cog = getattr(self.game, 'cog', None)
        
        # 새로운 게임 인스턴스 생성
        new_game = LiarGame(host=self.game.host, channel=self.game.channel)
        new_game.players = self.game.players.copy()
        new_game.turn_limit = self.game.turn_limit
        new_game.vote_limit = self.game.vote_limit
        new_game.cog = cog
        
        # 전역 딕셔너리에 갱신
        active_games[interaction.channel_id] = new_game
        
        embed = discord.Embed(
            title="🕵️ 다시 시작된 라이어 게임 모집!", 
            description=f"방장이 `게임 시작`을 누르면 바로 시작합니다.\n\n⏱️ **현재 설정된 시간:** 발언 {new_game.turn_limit}초 / 투표 {new_game.vote_limit}초", 
            color=0x2b2d31
        )
        
        player_list = "\n".join([f"👤 {p.display_name}" for p in new_game.players])
        embed.add_field(name=f"현재 참가자 ({len(new_game.players)}명)", value=player_list or "없음", inline=False)
        
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        
        await interaction.channel.send(embed=embed, view=LobbyView(new_game))

    @discord.ui.button(label="게임 완전히 종료", style=discord.ButtonStyle.danger, custom_id="end_game_completely")
    async def end_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 게임을 종료할 수 있습니다!", ephemeral=True)
            return
            
        await cleanup_game(interaction, self.game.channel.id)
        embed = discord.Embed(title="🛑 게임 종료", description="라이어 게임 시스템을 완전히 종료했습니다.", color=0xff0000)
        
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(embed=embed)


class LiarGameCog(commands.Cog):
    """라이어 게임 관련 명령어를 모아둔 Cog"""
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="라이어", description="라이어 게임 모집을 시작합니다.")
    async def start_liar(self, ctx):
        await self.start_liar_game_ui(ctx)

    async def turn_timer(self, game: 'LiarGame'):
        """턴 제한시간을 관리하는 코루틴"""
        try:
            await asyncio.sleep(game.turn_limit)
            # 시간이 다 되면 자동 스킵 처리
            current_player = game.turn_order[game.current_turn_index]
            await game.channel.send(f"⚠️ **{current_player.mention} 님이 시간 내에 대답하지 않았습니다!** (자동 넘김)")
            await self.process_turn(game, game.channel)
        except asyncio.CancelledError:
            # 시간 내에 대답하면 타이머 취소됨
            pass

    async def process_turn(self, game: 'LiarGame', channel):
        """턴을 실제로 넘기는 로직 (시간 초과나 메시지 입력 시 공통 사용)"""
        if game.timer_task:
            game.timer_task.cancel()
            
        game.current_turn_index += 1

        # 모든 플레이어가 한 바퀴 발언을 마친 경우
        if game.current_turn_index >= len(game.turn_order):
            if game.round_count < 2:
                game.phase = "VOTING_EXTENSION"
                await channel.send("모든 플레이어의 발언이 끝났습니다! 한 바퀴 더 듣고 싶으신가요?", view=ExtensionVoteView(game))
            else:
                game.phase = "VOTING_FINAL"
                view = FinalVoteView(game)
                
                hints_str = "\n".join(game.hints_log) if game.hints_log else "기록된 단서가 없습니다."
                embed = discord.Embed(
                    title="⚖️ 최종 투표: 라이어를 잡아라!",
                    description="두 바퀴가 모두 종료되었습니다! 아래 단서들을 참고하여 라이어로 의심되는 사람을 골라주세요.",
                    color=0xf1c40f
                )
                embed.add_field(name="📜 그동안의 단서 기록", value=hints_str, inline=False)
                
                msg = await channel.send(embed=embed, view=view)
                view.message = msg
        else:
            # 턴이 남았다면 다음 플레이어 호출 및 타이머 재시작
            next_player = game.turn_order[game.current_turn_index]
            await channel.send(f"👉 다음 차례: {next_player.mention} 님, 설명해주세요! (제한시간: {game.turn_limit}초)")
            game.timer_task = asyncio.create_task(self.turn_timer(game))

    async def defense_timer(self, game: 'LiarGame', target: discord.Member):
        try:
            await __import__('asyncio').sleep(game.turn_limit)
            await game.channel.send(f"⚠️ **{target.mention} 님이 시간 내에 최후의 변론을 하지 못했습니다!** 바로 투표를 진행합니다.")
            await self.trigger_kill_save_vote(game, target)
        except __import__('asyncio').CancelledError:
            pass

    async def trigger_kill_save_vote(self, game: 'LiarGame', target: discord.Member):
        game.phase = "KILL_SAVE_VOTE"
        embed = discord.Embed(
            title="⚖️ 최후의 심판대",
            description=f"{target.mention} 님의 처형 여부를 투표해주세요! ({game.vote_limit}초)",
            color=0xe67e22
        )
        from cogs.liar.liar_game import KillSaveVoteView
        view = KillSaveVoteView(game, target)
        msg = await game.channel.send(embed=embed, view=view)
        view.message = msg

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # 현재 채널에서 진행 중인 게임 확인
        game = active_games.get(message.channel.id)
        if not game:
            return

        # 라이어 정답 제출 단계인 경우
        if game.phase == "LIAR_GUESS":
            if message.author != game.liar:
                return
                
            user_guess = message.content.strip()
            
            # 정답 비교 (공백을 제거하여 조금 더 너그럽게 판정)
            if user_guess.replace(" ", "") == game.word.replace(" ", ""):
                embed = discord.Embed(title="🚨 라이어의 정답 확인!", description=f"라이어가 정답 **[{game.word}]** 을(를) 맞췄습니다!\n\n**🎉 라이어가 정체를 들키고도 승리했습니다! 🎉**", color=0xff0000)
                db.record_game_result(
                    game.session_id,
                    "liar",
                    [player.id for player in game.players],
                    [game.liar.id],
                    special_winner_ids=[game.liar.id],
                )
            else:
                embed = discord.Embed(title="🚨 라이어의 정답 확인!", description=f"라이어가 **오답**({user_guess})을(를) 입력했습니다! (정답: **{game.word}**)\n\n**🎉 시민들의 완벽한 승리입니다! 🎉**", color=0x00ff00)
                db.record_game_result(
                    game.session_id,
                    "liar",
                    [player.id for player in game.players],
                    [player.id for player in game.players if player != game.liar],
                )
                
            game.phase = "ENDED"
            await message.channel.send(embed=embed, view=PostGameView(game))
            return

        # 최후의 변론 처리
        if game.phase == "FINAL_DEFENSE":
            # 변론 타겟 본인의 채팅만 허용
            if message.author != game.final_target:
                return
                
            if getattr(game, 'timer_task', None):
                game.timer_task.cancel()
                
            embed = discord.Embed(description=f"🗣️ **{message.content}**", color=0xf39c12)
            if message.author.display_avatar:
                embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
            else:
                embed.set_author(name=message.author.display_name)
                
            try: await message.delete()
            except discord.Forbidden: pass
            
            await message.channel.send(embed=embed)
            await self.trigger_kill_save_vote(game, game.final_target)
            return

        # 게임 진행 중(발언 단계)이 아닌 경우 무시
        if game.phase != "PLAYING":
            return

        # 현재 턴인 유저가 맞는지 확인
        current_player = game.turn_order[game.current_turn_index]
        if message.author != current_player:
            return

        # 힌트 로그 저장
        game.hints_log.append(f"**{message.author.display_name}**: {message.content}")

        # 메시지 텍스트 강조 Embed 생성
        embed = discord.Embed(description=f"🗣️ **{message.content}**", color=0x3498db)
        
        # 안전한 아바타 URL 가져오기
        avatar_url = message.author.display_avatar.url if message.author.display_avatar else None
        embed.set_author(name=message.author.display_name, icon_url=avatar_url)
        
        try:
            await message.delete()  # 원본 메시지 깔끔하게 삭제
        except discord.Forbidden:
            pass  # 봇에게 메시지 관리 권한이 없으면 무시
            
        await message.channel.send(embed=embed)

        # 턴 진행 공통 로직 호출
        await self.process_turn(game, message.channel)

    async def start_liar_game_ui(self, interaction: discord.Interaction):
        """메인 메뉴의 버튼을 통해 라이어 게임 로비를 생성하는 함수"""
        # 해당 채널에 이미 진행 중인 게임이 있는지 확인
        if interaction.channel_id in active_games:
            await interaction.response.send_message("이 채널에서는 이미 게임이 진행 중입니다! 게임이 끝날 때까지 기다려주세요.", ephemeral=True)
            return

        # 새 게임 인스턴스 생성 및 저장
        game = LiarGame(host=interaction.user, channel=interaction.channel)
        game.cog = self
        active_games[interaction.channel_id] = game

        # 음성 채널 접속 시도
        if hasattr(interaction.user, "voice") and interaction.user.voice:
            try:
                await interaction.user.voice.channel.connect()
            except discord.ClientException:
                pass # 이미 봇이 음성 채널에 들어가있는 경우 무시
        
        # 초기 임베드 생성
        embed = discord.Embed(
            title="🕵️ 라이어 게임 모집 중!", 
            description="참가 버튼을 눌러 게임에 들어오세요.\n충분한 인원이 모이면 방장이 `게임 시작`을 누를 수 있습니다.\n\n"
                        "📍 **현재 지원 카테고리:**\n"
                        "🍔 음식, 🏫 장소, 👮 직업, 🐶 동물, 📦 물건, ⚽ 취미/스포츠, 📺 애니메이션", 
            color=0x2b2d31
        )
        embed.add_field(name=f"현재 참가자 (1명)", value=f"👑 {interaction.user.display_name}")

        view = LobbyView(game)
        
        # 메시지 전송
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(LiarGameCog(bot))
