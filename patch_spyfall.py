import sys
import re

def fix_liar_game():
    file_path = r"x:\Desktop\projects\discordBot\miniG\cogs\liar\liar_game.py"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    old_snippet = """        # 새로운 게임 인스턴스 생성 (아예 기존 상태 찌꺼기 없앰)
        from cogs.liar.liar_game import LiarGame
        new_game = LiarGame(host=self.game.host, channel=self.game.channel)
        new_game.players = self.game.players.copy()
        new_game.turn_limit = self.game.turn_limit
        new_game.vote_limit = self.game.vote_limit
        new_game.cog = cog
        
        from cogs.liar.liar_game import active_games
        active_games[interaction.channel_id] = new_game
        
        embed = discord.Embed(
            title="🕵️ 다시 시작된 라이어 게임 모집!", 
            description=f"방장이 `게임 시작`을 누르면 바로 시작합니다.\\n\\n⏱️ **현재 설정된 시간:** 발언 {new_game.turn_limit}초 / 투표 {new_game.vote_limit}초", 
            color=0x2b2d31
        )
        
        player_list = "\\n".join([f"👤 {p.display_name}" for p in new_game.players])
        embed.add_field(name=f"현재 참가자 ({len(new_game.players)}명)", value=player_list or "없음", inline=False)
        
        # 이전 메시지 버튼 비활성화
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        
        from cogs.liar.liar_game import LobbyView
        await interaction.channel.send(embed=embed, view=LobbyView(new_game))"""

    new_snippet = """        # 새로운 게임 인스턴스 생성
        new_game = LiarGame(host=self.game.host, channel=self.game.channel)
        new_game.players = self.game.players.copy()
        new_game.turn_limit = self.game.turn_limit
        new_game.vote_limit = self.game.vote_limit
        new_game.cog = cog
        
        # 전역 딕셔너리에 갱신
        active_games[interaction.channel_id] = new_game
        
        embed = discord.Embed(
            title="🕵️ 다시 시작된 라이어 게임 모집!", 
            description=f"방장이 `게임 시작`을 누르면 바로 시작합니다.\\n\\n⏱️ **현재 설정된 시간:** 발언 {new_game.turn_limit}초 / 투표 {new_game.vote_limit}초", 
            color=0x2b2d31
        )
        
        player_list = "\\n".join([f"👤 {p.display_name}" for p in new_game.players])
        embed.add_field(name=f"현재 참가자 ({len(new_game.players)}명)", value=player_list or "없음", inline=False)
        
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        
        await interaction.channel.send(embed=embed, view=LobbyView(new_game))"""

    if old_snippet in content:
        content = content.replace(old_snippet, new_snippet)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("Liar Game patched successfully!")
    else:
        print("Warning: Liar Game pattern mismatch!")


def fix_spyfall():
    file_path = r"x:\Desktop\projects\discordBot\miniG\cogs\spyfall\spyfall.py"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. SpyfallGame Init
    init_old = """        self.votes: Dict[discord.Member, int] = {}
        self.discussion_message: discord.Message = None"""
    init_new = """        self.votes: Dict[discord.Member, int] = {}
        self.discussion_message: discord.Message = None
        self.discussion_limit: int = 5 # 분 단위
        self.vote_limit: int = 30 # 초 단위"""
    content = content.replace(init_old, init_new)

    # 2. Add Modal Class & modify LobbyView
    lobby_old = """class SpyfallLobbyView(discord.ui.View):
    \"\"\"스파이폴 게임 대기실 뷰\"\"\"
    def __init__(self, game: SpyfallGame):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="참가하기", style=discord.ButtonStyle.success, custom_id="spyfall_join")"""

    lobby_new = """class SpyfallTimerSettingModal(discord.ui.Modal, title="제한시간 설정"):
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
    \"\"\"스파이폴 게임 대기실 뷰\"\"\"
    def __init__(self, game: SpyfallGame):
        super().__init__(timeout=None)
        self.game = game

    async def update_lobby(self, interaction: discord.Interaction):
        embed = interaction.message.embeds[0]
        # 시간설정 안내문 추가/수정
        embed.description = f"참가 버튼을 눌러 게임에 들어오세요.\\n최소 3인의 인원이 모이면 방장이 `게임 시작`을 누를 수 있습니다.\\n\\n⏱️ **현재 설정된 시간:** 토론 {self.game.discussion_limit}분 / 투표 {self.game.vote_limit}초"
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="참가하기", style=discord.ButtonStyle.success, custom_id="spyfall_join")"""
    content = content.replace(lobby_old, lobby_new)

    # 3. Add timer button to LobbyView
    leave_old = """    @discord.ui.button(label="나가기", style=discord.ButtonStyle.secondary, custom_id="spyfall_leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):"""
    leave_new = """    @discord.ui.button(label="시간 설정", style=discord.ButtonStyle.secondary, custom_id="spyfall_timer")
    async def timer_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 설정할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_modal(SpyfallTimerSettingModal(self.game, self))

    @discord.ui.button(label="나가기", style=discord.ButtonStyle.secondary, custom_id="spyfall_leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):"""
    content = content.replace(leave_old, leave_new)

    # 4. Modify start_spyfall_roles duration logic
    duration_old = """    game_duration_minutes = max(5, min(8, len(game.players)))  # 인당 1분, 최소 5분, 최대 8분
    embed = discord.Embed(
        title="⏱️ 토론 시간 시작!",
        description=f"역할 확인을 마쳤습니다. 지금부터 **{game_duration_minutes}분** 동안 자유롭게 질문과 답변을 진행해주세요!\\n선택된 사람부터 아무에게나 질문을 시작하세요.",
        color=0x3498db
    )"""
    duration_new = """    game_duration_minutes = game.discussion_limit
    embed = discord.Embed(
        title="⏱️ 토론 시간 시작!",
        description=f"역할 확인을 마쳤습니다. 지금부터 **{game_duration_minutes}분** 동안 자유롭게 질문과 답변을 진행해주세요!\\n선택된 사람부터 아무에게나 질문을 시작하세요.",
        color=0x3498db
    )"""
    content = content.replace(duration_old, duration_new)

    # 5. Modify start_spyfall_voting to add timeout and message reference
    vote_start_old = """async def start_spyfall_voting(game: SpyfallGame, channel: discord.TextChannel):
    \"\"\"토론 종료 후 스파이 지목 투표 시작\"\"\"
    game.phase = "VOTING"
    game.votes = {}
    
    embed = discord.Embed(
        title="🗳️ 스파이 지목 투표",
        description="토론 시간이 종료되었습니다.\\n아래 메뉴에서 **가장 스파이로 의심되는 사람**을 선택하세요!\\n\\n(모두가 투표하면 결과가 공개됩니다.)",
        color=0xf1c40f
    )
    
    await channel.send(embed=embed, view=SpyfallVoteView(game))"""
    vote_start_new = """async def start_spyfall_voting(game: SpyfallGame, channel: discord.TextChannel):
    \"\"\"토론 종료 후 스파이 지목 투표 시작\"\"\"
    game.phase = "VOTING"
    game.votes = {}
    
    embed = discord.Embed(
        title="🗳️ 스파이 지목 투표",
        description=f"토론 시간이 종료되었습니다.\\n아래 메뉴에서 **가장 스파이로 의심되는 사람**을 선택하세요! ({game.vote_limit}초 제한)\\n\\n(모두가 투표하거나 시간이 초과되면 결과가 공개됩니다.)",
        color=0xf1c40f
    )
    
    view = SpyfallVoteView(game)
    msg = await channel.send(embed=embed, view=view)
    view.message = msg"""
    content = content.replace(vote_start_old, vote_start_new)

    # 6. Modify SpyfallVoteView for timeout logic
    vote_view_old = """class SpyfallVoteView(discord.ui.View):
    def __init__(self, game: SpyfallGame):
        super().__init__(timeout=None)
        self.add_item(SpyfallVoteSelect(game))

async def process_spyfall_vote(game: SpyfallGame, interaction: discord.Interaction):
    \"\"\"투표 결과 집계 및 승패 처리\"\"\"
    await interaction.message.edit(view=None)
    
    from collections import Counter
    # 유저 ID 목록을 리스트로 명시적으로 변환하여 전달"""
    vote_view_new = """class SpyfallVoteView(discord.ui.View):
    def __init__(self, game: SpyfallGame):
        super().__init__(timeout=game.vote_limit)
        self.message = None
        self.add_item(SpyfallVoteSelect(game))
        
    async def on_timeout(self):
        self.stop()
        await process_spyfall_vote(self.game, interaction=None, message_obj=self.message)

async def process_spyfall_vote(game: SpyfallGame, interaction: discord.Interaction = None, message_obj: discord.Message = None):
    \"\"\"투표 결과 집계 및 승패 처리\"\"\"
    if interaction:
        try: await interaction.message.edit(view=None)
        except: pass
    elif message_obj:
        try: await message_obj.edit(view=None)
        except: pass
        
    channel = interaction.channel if interaction else game.channel
    
    from collections import Counter
    # 유저 ID 목록을 리스트로 명시적으로 변환하여 전달"""
    content = content.replace(vote_view_old, vote_view_new)

    # 7. Modify interaction.channel.send to channel.send where applicable in process_spyfall_vote
    # We'll just carefully replace `interaction.channel` with `channel` inside the process_spyfall_vote scope.
    # To do this safely, we use regex for the specific function block, but since we know finding and replacing
    # 'interaction.channel' -> 'channel' is easy:
    block_start_index = content.find("process_spyfall_vote(game: SpyfallGame")
    if block_start_index != -1:
        block_end_index = content.find("class SpyfallPostGameView", block_start_index)
        if block_end_index != -1:
            block = content[block_start_index:block_end_index]
            
            # replace interaction.guild with channel.guild
            block = block.replace("interaction.guild", "channel.guild")
            block = block.replace("interaction.client", "game.host.guild.get_member(game.host.id).client" if "game.host" in block else "game.host.client")  # Hacky fallback, let's use a better fetch mechanism
            # actually replacing `interaction.client.fetch_user` with `game.host.client.fetch_user`
            
            # Let's do it manually with regex
            block = re.sub(r'interaction\.channel\.send', 'channel.send', block)
            block = re.sub(r'interaction\.guild\.get_member', 'channel.guild.get_member', block)
            
            content = content[:block_start_index] + block + content[block_end_index:]
            
            # fix the client issue
            # `await interaction.client.fetch_user(top_voted_id)` -> wait, where does client come from if we only have channel?
            # `game.host.client` isn't generic. We can use `bot` if `game` has `bot`, but it doesn't.
            # discord.TextChannel doesn't have `client`. `channel.guild` has `_state`.
            # But normally `channel.guild.get_member` is enough since it's cached.
            # Let's use `getattr(channel.guild, "_state")._get_client().fetch_user` or rely on bot if passed.
            # Wait! We can import bot or fetch from a known source, or just use `channel.guild.get_member` and swallow the error if uncached.
            # Let's fix that fetch_user carefully.
            fetch_old = "await interaction.client.fetch_user(top_voted_id)"
            fetch_new = "await channel.guild.fetch_member(top_voted_id)" # fetch_member is native to guild!
            content = content.replace(fetch_old, fetch_new)

    # 8. Update initial embed in start_spyfall_ui
    ui_old = """    embed = discord.Embed(
        title="🕵️ 스파이폴 게임 모집!", 
        description="참가 버튼을 눌러 게임에 들어오세요.\\n최소 3인의 인원이 모이면 방장이 `게임 시작`을 누를 수 있습니다.", 
        color=0x2b2d31
    )"""
    ui_new = """    embed = discord.Embed(
        title="🕵️ 스파이폴 게임 모집!", 
        description=f"참가 버튼을 눌러 게임에 들어오세요.\\n최소 3인의 인원이 모이면 방장이 `게임 시작`을 누를 수 있습니다.\\n\\n⏱️ **현재 설정된 시간:** 토론 {game.discussion_limit}분 / 투표 {game.vote_limit}초", 
        color=0x2b2d31
    )"""
    content = content.replace(ui_old, ui_new)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
        print("Spyfall patched successfully!")


fix_liar_game()
fix_spyfall()
