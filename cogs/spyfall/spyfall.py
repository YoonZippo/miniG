import discord
import logging
from discord.ext import commands
import random
import asyncio
import os
from typing import List, Dict

logger = logging.getLogger('gameBot.spyfall')
from .locations import SPYFALL_LOCATIONS
from database.manager import DatabaseManager

db = DatabaseManager()

# 활성화된 스파이폴 게임들을 관리하는 딕셔너리
# Key: channel_id, Value: SpyfallGame 객체
active_spyfall_games = {}

class SpyfallGame:
    """스파이폴 게임의 상태를 관리하는 클래스"""
    def __init__(self, host: discord.Member, channel: discord.TextChannel):
        self.host = host
        self.channel = channel
        self.players: List[discord.Member] = [host]
        self.spy: discord.Member = None
        self.location: str = None
        self.roles: Dict[discord.Member, str] = {}
        self.phase: str = "LOBBY" # LOBBY, DISCUSSION, VOTING, SPY_GUESS, ENDED
        self.timer_task: asyncio.Task = None
        self.votes: Dict[discord.Member, int] = {}
        self.discussion_message: discord.Message = None
        self.discussion_limit: int = 5 # 분 단위
        self.vote_limit: int = 30 # 초 단위
        
async def cleanup_spyfall(interaction: discord.Interaction, channel_id: int):
    """게임 종료 및 리소스 정리 유틸리티"""
    if channel_id in active_spyfall_games:
        game = active_spyfall_games[channel_id]
        if game.timer_task and not game.timer_task.done():
            game.timer_task.cancel()
        active_spyfall_games.pop(channel_id, None)

    # 음성 채널 연결 해제 시도
    if interaction.guild.voice_client:
        await interaction.guild.voice_client.disconnect()


class SpyfallTimerSettingModal(discord.ui.Modal, title="제한시간 설정"):
    def __init__(self, game: SpyfallGame, view: discord.ui.View):
        super().__init__()
        self.game = game
        self.lobby_view = view

        self.discussion_time = discord.ui.TextInput(
            label="토론 제한시간 (분)",
            default=str(game.discussion_limit),
            placeholder="숫자만 입력 (최소 1)",
            min_length=1,
            max_length=2
        )
        self.add_item(self.discussion_time)

        self.vote_time = discord.ui.TextInput(
            label="투표 제한시간 (초)",
            default=str(game.vote_limit),
            placeholder="숫자만 입력 (최소 10)",
            min_length=1,
            max_length=3
        )
        self.add_item(self.vote_time)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_disc = int(self.discussion_time.value)
            new_vote = int(self.vote_time.value)
            if new_disc < 1 or new_vote < 10:
                await interaction.response.send_message("올바른 범위를 입력해주세요.", ephemeral=True)
                return
            self.game.discussion_limit = new_disc
            self.game.vote_limit = new_vote
            await self.lobby_view.update_lobby(interaction)
        except ValueError:
            await interaction.response.send_message("올바른 숫자를 입력해주세요.", ephemeral=True)

class SpyfallLobbyView(discord.ui.View):
    """스파이폴 게임 대기실 뷰"""
    def __init__(self, game: SpyfallGame):
        super().__init__(timeout=None)
        self.game = game

    async def update_lobby(self, interaction: discord.Interaction):
        embed = interaction.message.embeds[0]
        # 시간설정 안내문 추가/수정
        embed.description = f"참가 버튼을 눌러 게임에 들어오세요.\n최소 3인의 인원이 모이면 방장이 `게임 시작`을 누를 수 있습니다.\n\n⏱️ **현재 설정된 시간:** 토론 {self.game.discussion_limit}분 / 투표 {self.game.vote_limit}초"
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="참가하기", style=discord.ButtonStyle.success, custom_id="spyfall_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.game.players:
            await interaction.response.send_message("이미 참가하셨습니다!", ephemeral=True)
            return
            
        self.game.players.append(interaction.user)
        embed = interaction.message.embeds[0]
        player_list = "\n".join([f"- {p.mention}" for p in self.game.players])
        embed.set_field_at(0, name=f"현재 참가자 ({len(self.game.players)}명)", value=player_list, inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="시간 설정", style=discord.ButtonStyle.secondary, custom_id="spyfall_timer")
    async def timer_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 설정할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(SpyfallTimerSettingModal(self.game, self))

    @discord.ui.button(label="나가기", style=discord.ButtonStyle.secondary, custom_id="spyfall_leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user == self.game.host:
            await interaction.response.send_message("방장은 나갈 수 없습니다. 게임을 취소하려면 `종료`를 선택하세요.", ephemeral=True)
            return
            
        if interaction.user in self.game.players:
            self.game.players.remove(interaction.user)
            embed = interaction.message.embeds[0]
            player_list = "\n".join([f"- {p.mention}" for p in self.game.players])
            embed.set_field_at(0, name=f"현재 참가자 ({len(self.game.players)}명)", value=player_list or "없음", inline=False)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.send_message("참가하지 않으셨습니다.", ephemeral=True)

    @discord.ui.button(label="게임 시작", style=discord.ButtonStyle.primary, custom_id="spyfall_start")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 게임을 시작할 수 있습니다!", ephemeral=True)
            return
            
        if len(self.game.players) < 3:
            await interaction.response.send_message("최소 3명 이상이 필요합니다!", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        
        await start_spyfall_roles(self.game, interaction)

    @discord.ui.button(label="게임 취소", style=discord.ButtonStyle.danger, custom_id="spyfall_cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 완료할 수 있습니다.", ephemeral=True)
            return
            
        await cleanup_spyfall(interaction, self.game.channel.id)
        embed = discord.Embed(title="🛑 스파이폴 게임 취소됨", description="방장이 게임을 취소했습니다.", color=0xff0000)
        
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(embed=embed)


async def start_spyfall_roles(game: SpyfallGame, interaction: discord.Interaction):
    """장소와 역할을 무작위로 분배하고 DM 전송"""
    game.phase = "DISCUSSION"
    
    # 1. 장소 선택
    game.location = random.choice(list(SPYFALL_LOCATIONS.keys()))
    available_roles = SPYFALL_LOCATIONS[game.location].copy()
    
    # 역할 수가 모자라면 부족한 만큼 일반인으로 채움
    while len(available_roles) < len(game.players) - 1:
        available_roles.append("일반 시민")
    
    random.shuffle(available_roles)
    
    # 2. 스파이 선택
    game.spy = random.choice(game.players)
    
    # 3. 역할 분배 및 DM 전송
    await interaction.channel.send("🕵️ **역할을 배정하고 있습니다. DM을 확인해주세요!**")
    
    for player in game.players:
        try:
            if player == game.spy:
                game.roles[player] = "스파이"
                embed = discord.Embed(
                    title="🕵️ 당신은 스파이입니다!", 
                    description="당신은 현재 장소를 모릅니다.\n다른 사람들의 대화를 듣고 장소를 추리하며, 스파이인 것을 들키지 않게 연기하세요!\n\n*(게임 중 기습적으로 정체를 밝히고 장소를 맞히면 역전승을 거둘 수 있습니다)*",
                    color=0xe74c3c
                )
                await player.send(embed=embed)
            else:
                role = available_roles.pop(0)
                game.roles[player] = role
                embed = discord.Embed(
                    title="🏢 시민 역할 배정", 
                    description=f"우리가 모인 장소는 **[{game.location}]** 입니다.\n당신의 역할은 **[{role}]** 입니다.\n\n스파이가 눈치채지 못하게 은밀한 질문을 던져 서로 시민임을 확인하고, 스파이를 색출하세요!",
                    color=0x2ecc71
                )
                
                # 장소 이미지 추가
                img_path = f"assets/images/spyfall/{game.location}.png"
                if os.path.exists(img_path):
                    file = discord.File(img_path, filename="location.png")
                    embed.set_image(url="attachment://location.png")
                    await player.send(file=file, embed=embed)
                else:
                    await player.send(embed=embed)
        except discord.Forbidden:
            await interaction.channel.send(f"⚠️ {player.mention} 님에게 DM을 보낼 수 없습니다. 서버 설정에서 서버 멤버가 보내는 다이렉트 메시지 허용을 켜주세요.")
            await cleanup_spyfall(interaction, game.channel.id)
            return

    game_duration_minutes = game.discussion_limit
    embed = discord.Embed(
        title="⏱️ 토론 시간 시작!",
        description=f"역할 확인을 마쳤습니다. 지금부터 **{game_duration_minutes}분** 동안 자유롭게 질문과 답변을 진행해주세요!\n선택된 사람부터 아무에게나 질문을 시작하세요.",
        color=0x3498db
    )
    first_player = random.choice(game.players)
    embed.add_field(name="👉 첫 질문자", value=first_player.mention)
    
    view = DiscussionView(game)
    game.discussion_message = await interaction.channel.send(embed=embed, view=view)
    
    # 백그라운드 타이머 시작
    game.timer_task = asyncio.create_task(discussion_timer(game, game.discussion_message, game_duration_minutes * 60))

async def discussion_timer(game: SpyfallGame, message: discord.Message, duration: int):
    """지정된 시간 동안 토론을 진행하고, 알람을 울린 뒤 튜표 페이즈로 자동 전환"""
    try:
        # 종료 30초 전까지 대기
        alert_points = [30, 10, 5]
        last_sleep = 0
        
        for point in alert_points:
            sleep_time = duration - point - last_sleep
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                if game.phase == "DISCUSSION":
                    await game.channel.send(f"⚠️ **토론 종료 {point}초 전입니다!**")
                last_sleep += sleep_time
        
        # 남은 5초 대기
        await asyncio.sleep(5)
        
        if game.phase == "DISCUSSION":
            # 시간 초과 시 자동 투표 시작
            await message.edit(view=None)
            await start_spyfall_voting(game, message.channel)
    except asyncio.CancelledError:
        pass # 타이머가 의도적으로 취소된 경우 조용히 종료


class DiscussionView(discord.ui.View):
    """토론 페이즈 뷰 (스파이 역전 선언 / 방장 투표 조기 시작)"""
    def __init__(self, game: SpyfallGame):
        super().__init__(timeout=None)
        self.game = game
        
    @discord.ui.button(label="지금 바로 투표 시작 (방장)", style=discord.ButtonStyle.secondary, custom_id="spyfall_early_vote", row=0)
    async def early_vote_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 투표를 조기 시작할 수 있습니다.", ephemeral=True)
            return
            
        if self.game.phase != "DISCUSSION":
            return
            
        if self.game.timer_task:
            self.game.timer_task.cancel()
            
        await interaction.response.edit_message(view=None)
        await start_spyfall_voting(self.game, interaction.channel)

    @discord.ui.button(label="🕵️ 🚨 스파이 정체 밝히기 (스파이용, 역전 기회!)", style=discord.ButtonStyle.danger, custom_id="spyfall_reveal", row=1)
    async def spy_reveal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.spy:
            await interaction.response.send_message("당신은 스파이가 아닙니다!", ephemeral=True)
            return
            
        if self.game.phase != "DISCUSSION":
            return
            
        if self.game.timer_task:
            self.game.timer_task.cancel()
            
        self.game.phase = "SPY_GUESS"
        await interaction.response.edit_message(view=None)
        
        embed = discord.Embed(
            title="🚨 스파이 정체 공개!", 
            description=f"{self.game.spy.mention} 님이 스스로 스파이임을 밝혔습니다!\n\n**스파이는 지금 바로 채팅창에 현재 장소가 어디인지 정답을 입력해주세요!**\n\n*(예비 목록: {', '.join(SPYFALL_LOCATIONS.keys())})*", 
            color=0xe74c3c
        )
        await interaction.channel.send(embed=embed)


async def start_spyfall_voting(game: SpyfallGame, channel: discord.TextChannel):
    """토론 종료 후 스파이 지목 투표 시작"""
    game.phase = "VOTING"
    game.votes = {}
    
    embed = discord.Embed(
        title="🗳️ 스파이 지목 투표",
        description=f"토론 시간이 종료되었습니다.\n아래 메뉴에서 **가장 스파이로 의심되는 사람**을 선택하세요! ({game.vote_limit}초 제한)\n\n(모두가 투표하거나 시간이 초과되면 결과가 공개됩니다.)",
        color=0xf1c40f
    )
    
    view = SpyfallVoteView(game)
    msg = await channel.send(embed=embed, view=view)
    view.message = msg


class SpyfallVoteSelect(discord.ui.Select):
    """스파이 지목용 투표 선택 메뉴"""
    def __init__(self, game: SpyfallGame):
        self.game = game
        options = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in game.players]
        super().__init__(placeholder="스파이로 의심되는 플레이어를 선택하세요...", options=options, custom_id="spyfall_vote_select")
        
    async def callback(self, interaction: discord.Interaction):
        if self.game.phase != "VOTING":
            await interaction.response.send_message("현재 투표 시간이 아닙니다.", ephemeral=True)
            return
            
        if interaction.user not in self.game.players:
            await interaction.response.send_message("투표 권한이 없습니다.", ephemeral=True)
            return
            
        target_id = int(self.values[0])
        self.game.votes[interaction.user] = target_id
        
        await interaction.response.send_message("투표가 완료되었습니다.", ephemeral=True)
        
        # 모든 플레이어가 투표를 마쳤다면 결과 처리
        if len(self.game.votes) >= len(self.game.players):
            await process_spyfall_vote(self.game, interaction)

class SpyfallVoteView(discord.ui.View):
    def __init__(self, game: SpyfallGame):
        super().__init__(timeout=game.vote_limit)
        self.message = None
        self.add_item(SpyfallVoteSelect(game))
        
    async def on_timeout(self):
        self.stop()
        await process_spyfall_vote(self.game, interaction=None, message_obj=self.message)

async def process_spyfall_vote(game: SpyfallGame, interaction: discord.Interaction = None, message_obj: discord.Message = None):
    """투표 결과 집계 및 승패 처리"""
    if interaction:
        try: await interaction.message.edit(view=None)
        except: pass
    elif message_obj:
        try: await message_obj.edit(view=None)
        except: pass
        
    channel = interaction.channel if interaction else game.channel
    
    from collections import Counter
    # 유저 ID 목록을 리스트로 명시적으로 변환하여 전달
    vote_list = [v for v in game.votes.values()]
    vote_counts = Counter(vote_list)
    max_votes = max(vote_counts.values()) if vote_counts else 0
    max_voted_ids = [uid for uid, count in vote_counts.items() if count == max_votes]
    
    # 투표 결과 텍스트 생성
    result_text = "📊 **최종 투표 결과**\n"
    for player in game.players:
        count = list(game.votes.values()).count(player.id)
        result_text += f"- {player.display_name}: {count}표\n"
        
    await channel.send(result_text)
    
    # 동점일 경우 스파이 승리 (시민 합의 실패)
    if len(max_voted_ids) > 1:
        embed = discord.Embed(
            title="🚨 시민 분열! 라이어 검거 실패!", 
            description=f"가장 많은 표를 받은 동점자가 발생하여 시민들이 합의에 도달하지 못했습니다!\n\n진짜 스파이는 바로 {game.spy.mention} 님이었습니다!\n(실제 장소: **{game.location}**)\n\n**🎉 스파이의 승리입니다! 🎉**", 
            color=0xff0000
        )
        game.phase = "ENDED"
        await channel.send(embed=embed, view=SpyfallPostGameView(game))
        # 전적 기록: 스파이 승리 (시민 분열)
        for p in game.players:
            db.update_stats(p.id, 'spyfall', won=(p == game.spy))
        return
        
    top_voted_id = max_voted_ids[0]
    top_voted_player = channel.guild.get_member(top_voted_id) or await game.host.client.fetch_user(top_voted_id)
    
    # 스파이를 정확히 지목한 경우
    if top_voted_id == game.spy.id:
        game.phase = "SPY_GUESS"
        embed = discord.Embed(
            title="🚨 스파이 검거 완료!", 
            description=f"가장 많은 표를 받은 {top_voted_player.mention} 님은 **스파이가 맞습니다!**\n\n하지만 아직 끝이 아닙니다. 스파이에게는 역전을 위한 **장소 맞추기 기회**가 주어집니다!\n\n👉 **{game.spy.mention} 님, 지금 바로 채팅창에 우리가 있던 '장소'를 입력해주세요!**\n\n*(예비 목록: {', '.join(SPYFALL_LOCATIONS.keys())})*", 
            color=0x3498db
        )
        await channel.send(embed=embed)
    else:
        # 엄한 시민을 지목한 경우
        actual_role = game.roles.get(top_voted_player, "일반 시민")
        embed = discord.Embed(
            title="🚨 스파이 검거 실패!", 
            description=f"가장 많은 표를 받은 {top_voted_player.mention} 님은 선량한 시민(**{actual_role}**)이었습니다!\n\n진짜 스파이는 바로 {game.spy.mention} 님이었습니다!\n(실제 장소: **{game.location}**)\n\n**🎉 스파이 무사 생환! 스파이의 승리입니다! 🎉**", 
            color=0xff0000
        )
        game.phase = "ENDED"
        await channel.send(embed=embed, view=SpyfallPostGameView(game))
        # 전적 기록: 스파이 승리 (엄한 시민 지목)
        for p in game.players:
            db.update_stats(p.id, 'spyfall', won=(p == game.spy))

class SpyfallPostGameView(discord.ui.View):
    """게임 종료 후 다시하기 또는 종료를 선택하는 뷰"""
    def __init__(self, game: SpyfallGame):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="한 번 더 하기", style=discord.ButtonStyle.primary, custom_id="spyfall_play_again")
    async def play_again_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 게임을 다시 시작할 수 있습니다!", ephemeral=True)
            return
            
        self.game.phase = "LOBBY"
        self.game.votes = {}
        self.game.roles = {}
        self.game.location = None
        self.game.spy = None
        if self.game.timer_task and not self.game.timer_task.done():
            self.game.timer_task.cancel()
        
        embed = discord.Embed(
            title="🕵️ 다시 시작된 스파이폴 게임 모집!", 
            description="참가 버튼을 눌러 게임에 들어오세요.\n최소 3인의 인원이 모이면 방장이 `게임 시작`을 누를 수 있습니다.", 
            color=0x2b2d31
        )
        player_list = "\n".join([f"- {p.mention}" for p in self.game.players])
        embed.add_field(name=f"현재 참가자 ({len(self.game.players)}명)", value=player_list or "없음", inline=False)
        
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(embed=embed, view=SpyfallLobbyView(self.game))

    @discord.ui.button(label="게임 완전히 종료", style=discord.ButtonStyle.danger, custom_id="spyfall_end_completely")
    async def end_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 게임을 종료할 수 있습니다!", ephemeral=True)
            return
            
        await cleanup_spyfall(interaction, self.game.channel.id)
        embed = discord.Embed(title="🛑 스파이폴 게임 종료", description="게임을 완전히 종료했습니다.", color=0xff0000)
        
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(embed=embed)

# 진입점 함수
async def start_spyfall_ui(interaction: discord.Interaction):
    """스파이폴 대기실 생성"""
    if interaction.channel.id in active_spyfall_games:
        await interaction.response.send_message("이 채널에서 이미 스파이폴 게임이 진행 중입니다.", ephemeral=True)
        return
        
    game = SpyfallGame(interaction.user, interaction.channel)
    active_spyfall_games[interaction.channel.id] = game
    
    # 음성 채널 자동 접속
    if interaction.user.voice and interaction.user.voice.channel:
        try:
            if not interaction.guild.voice_client:
                await interaction.user.voice.channel.connect()
        except:
            pass

    embed = discord.Embed(
        title="🕵️ 스파이폴 게임 모집!", 
        description=f"참가 버튼을 눌러 게임에 들어오세요.\n최소 3인의 인원이 모이면 방장이 `게임 시작`을 누를 수 있습니다.\n\n⏱️ **현재 설정된 시간:** 토론 {game.discussion_limit}분 / 투표 {game.vote_limit}초", 
        color=0x2b2d31
    )
    
    player_list = f"- {interaction.user.mention}"
    embed.add_field(name=f"현재 참가자 (1명)", value=player_list, inline=False)
    
    await interaction.response.send_message(embed=embed, view=SpyfallLobbyView(game))


class SpyfallCog(commands.Cog):
    """스파이폴 로드용 Cog"""
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="스파이폴", description="스파이폴 게임 모집을 시작합니다.")
    async def start_spyfall(self, ctx):
        await start_spyfall_ui(ctx)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        game = active_spyfall_games.get(message.channel.id)
        if not game:
            return

        # 스파이 정답 제출 단계인 경우 채팅 감지
        if game.phase == "SPY_GUESS":
            if message.author != game.spy:
                return
                
            user_guess = message.content.strip()
            
            # 정답 비교 (공백을 제거하여 너그럽게 판정)
            if user_guess.replace(" ", "") == game.location.replace(" ", ""):
                embed = discord.Embed(
                    title="🚨 스파이의 정답 확인!", 
                    description=f"스파이가 정확한 장소 **[{game.location}]** 을(를) 맞췄습니다!\n\n**🎉 스파이가 시민을 속이고 훌륭히 역전했습니다! 🎉**", 
                    color=0xff0000
                )
                # 전적 기록: 스파이 승리
                for p in game.players:
                    db.update_stats(p.id, 'spyfall', won=(p == game.spy))
            else:
                embed = discord.Embed(
                    title="🚨 스파이의 정답 확인!", 
                    description=f"스파이가 **오답**({user_guess})을(를) 입력했습니다! (진짜 장소: **{game.location}**)\n\n**🎉 시민들의 완벽한 승리입니다! 🎉**", 
                    color=0x00ff00
                )
                # 전적 기록: 시민 승리
                for p in game.players:
                    db.update_stats(p.id, 'spyfall', won=(p != game.spy))
                
            game.phase = "ENDED"
            await message.channel.send(embed=embed, view=SpyfallPostGameView(game))

async def setup(bot):
    await bot.add_cog(SpyfallCog(bot))
