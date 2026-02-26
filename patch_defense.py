import sys
import re

file_path = r"x:\Desktop\projects\discordBot\miniG\cogs\liar\liar_game.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. PostGameView -> '한 번 더 하기' 완전 수정
post_game_old = """    @discord.ui.button(label="한 번 더 하기", style=discord.ButtonStyle.primary, custom_id="play_again")
    async def play_again_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 게임을 다시 시작할 수 있습니다!", ephemeral=True)
            return
            
        # 게임 정보 초기화 후 새로운 로비 뷰 띄우기 (플레이어 유지)
        self.game.phase = "LOBBY"
        self.game.votes = {}
        self.game.turn_order = []
        self.game.current_turn_index = 0
        self.game.round_count = 1
        
        embed = discord.Embed(
            title="🕵️ 다시 시작된 라이어 게임 모집!", 
            description="참가 버튼을 눌러 게임에 들어오세요.\\n충분한 인원이 모이면 방장이 `게임 시작`을 누를 수 있습니다.", 
            color=0x2b2d31
        )
        
        player_list = "\\n".join([f"- {p.mention}" for p in self.game.players])
        embed.add_field(name=f"현재 참가자 ({len(self.game.players)}명)", value=player_list or "없음", inline=False)
        
        # 이전 메시지 버튼 비활성화
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        
        await interaction.channel.send(embed=embed, view=LobbyView(self.game))"""

post_game_new = """    @discord.ui.button(label="한 번 더 하기", style=discord.ButtonStyle.primary, custom_id="play_again")
    async def play_again_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            await interaction.response.send_message("방장만 게임을 다시 시작할 수 있습니다!", ephemeral=True)
            return
            
        # 타이머 안전하게 해제
        if self.game.timer_task:
            self.game.timer_task.cancel()
            
        cog = getattr(self.game, 'cog', None)
        
        # 새로운 게임 인스턴스 생성 (아예 기존 상태 찌꺼기 없앰)
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

if post_game_old in content:
    content = content.replace(post_game_old, post_game_new)
else:
    print("Warning: post_game_old mismatch")

# 2. process_final_vote 수정
#  방향: Kill/Save 투표를 부르기 직전에 phase를 FINAL_DEFENSE 로 바꾸고 타이머 실행
process_final_replace_old = """    # Kill or Save vote
    embed = discord.Embed(
        title="⚖️ 최후의 심판대",
        description=f"가장 많은 표를 받은 {top_voted_player.mention} 님이 심판대에 올랐습니다.\\n이 플레이어를 처형하시겠습니까?",
        color=0xe67e22
    )
    game.phase = "KILL_SAVE_VOTE"
    view = KillSaveVoteView(game, top_voted_player)
    msg = await channel.send(embed=embed, view=view)
    view.message = msg"""

process_final_replace_new = """    game.phase = "FINAL_DEFENSE"
    embed = discord.Embed(
        title="🗣️ 최후의 변론",
        description=f"가장 많은 표를 받은 {top_voted_player.mention} 님이 심판대에 올랐습니다.\\n\\n👉 **{top_voted_player.mention} 님, 채널에 채팅을 쳐서 마지막으로 자신을 변호하세요!** (제한시간: {game.turn_limit}초)",
        color=0xf39c12
    )
    await channel.send(embed=embed)
    
    if getattr(game, 'cog', None):
        if game.timer_task: game.timer_task.cancel()
        game.timer_task = __import__('asyncio').create_task(game.cog.defense_timer(game, top_voted_player))"""

if process_final_replace_old in content:
    content = content.replace(process_final_replace_old, process_final_replace_new)
else:
    print("Warning: process_final_replace_old mismatch")

# 3. process_tiebreaker_vote 수정 (동일)
if process_final_replace_old in content: # It's identical text in process_tiebreaker_vote
    content = content.replace(process_final_replace_old, process_final_replace_new)
else:
    print("Warning: process_tiebreaker_vote replace mismatch (handled mostly already)")
    
# Manual second pass for tiebreaker
tiebreaker_search = """    embed = discord.Embed(
        title="⚖️ 최후의 심판대",
        description=f"가장 많은 표를 받은 {top_voted_player.mention} 님이 심판대에 올랐습니다.\\n이 플레이어를 처형하시겠습니까?",
        color=0xe67e22
    )
    game.phase = "KILL_SAVE_VOTE"
    view = KillSaveVoteView(game, top_voted_player)
    msg = await channel.send(embed=embed, view=view)
    view.message = msg"""
if tiebreaker_search in content:
    content = content.replace(tiebreaker_search, process_final_replace_new)


# 4. LiarGameCog 수정
cog_old_start = """    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):"""

cog_methods_addition = """    async def defense_timer(self, game: 'LiarGame', target: discord.Member):
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
    async def on_message(self, message: discord.Message):"""

content = content.replace(cog_old_start, cog_methods_addition)

# 5. on_message FINAL_DEFENSE handling
on_message_old_playing_check = """        # 게임 진행 중(발언 단계)이 아닌 경우 무시
        if game.phase != "PLAYING":
            return"""
            
on_message_new_playing_check = """        # 최후의 변론 처리
        if game.phase == "FINAL_DEFENSE":
            # 변론할 수 있는 사람을 특정하기가 구조적으로 까다롭지만,
            # 앞서 timer_task를 돌리는 시점에서 target을 캐치 중입니다.
            # 방어적으로 단순 처리
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
            await self.trigger_kill_save_vote(game, message.author)
            return

        # 게임 진행 중(발언 단계)이 아닌 경우 무시
        if game.phase != "PLAYING":
            return"""

content = content.replace(on_message_old_playing_check, on_message_new_playing_check)


with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Patching complete!")
