import sys

file_path = r"x:\Desktop\projects\discordBot\miniG\cogs\liar\liar_game.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

start_marker = 'class ExtensionVoteView(discord.ui.View):'
end_marker = 'class PostGameView(discord.ui.View):'

if start_marker not in content or end_marker not in content:
    print("Markers not found.")
    sys.exit(1)

pre_content = content.split(start_marker)[0]
post_content = end_marker + content.split(end_marker)[1]

new_views = """class ExtensionVoteView(discord.ui.View):
    \"\"\"모든 발언이 한 바퀴 돌았을 때 연장 여부를 투표하는 뷰\"\"\"
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
                    f"✅ 연장 투표가 가결되었습니다! 두 번째 라운드를 시작합니다.\\n👉 첫 번째 차례: {current_player.mention} 님, 설명해주세요! (제한시간: {self.game.turn_limit}초)"
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
    \"\"\"특정 플레이어를 죽일지 살릴지 결정하는 뷰\"\"\"
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
    
    result_text = "📊 **최종 투표 결과**\\n"
    for player in game.players:
        count = list(game.votes.values()).count(player.id)
        result_text += f"- {player.display_name}: {count}표\\n"
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

    # Kill or Save vote
    embed = discord.Embed(
        title="⚖️ 최후의 심판대",
        description=f"가장 많은 표를 받은 {top_voted_player.mention} 님이 심판대에 올랐습니다.\\n이 플레이어를 처형하시겠습니까?",
        color=0xe67e22
    )
    game.phase = "KILL_SAVE_VOTE"
    view = KillSaveVoteView(game, top_voted_player)
    msg = await channel.send(embed=embed, view=view)
    view.message = msg

async def process_tiebreaker_vote(game, message_obj, tied_players, interaction=None):
    game.phase = "RESOLUTION"
    if message_obj: 
        try: await message_obj.edit(view=None)
        except: pass
    
    vote_counts = Counter(list(game.votes.values()))
    channel = interaction.channel if interaction else game.channel
    
    result_text = "📊 **결선 투표 결과**\\n"
    for player in tied_players:
        count = list(game.votes.values()).count(player.id)
        result_text += f"- {player.display_name}: {count}표\\n"
    await channel.send(result_text)
    
    if not vote_counts:
        await channel.send("⚠️ 아무도 투표하지 않아 라이어 판별을 건너뜁니다! (라이어 승리)")
        return await execute_player(game, game.liar, channel, force_fail=True)

    max_votes = max(vote_counts.values())
    max_voted_ids = [uid for uid, count in vote_counts.items() if count == max_votes]
    
    if len(max_voted_ids) > 1:
        embed = discord.Embed(title="🚨 2차 투표 무효! 라이어 검거 실패!", description=f"결선 투표에서도 동점자가 발생하여 시민들이 합의에 도달하지 못했습니다!\\n\\n진짜 라이어는 바로 {game.liar.mention} 님이었습니다! (제시어: **{game.word}**)\\n\\n**🎉 라이어의 승리입니다! 🎉**", color=0xff0000)
        from database.manager import DatabaseManager
        db = DatabaseManager()
        for p in game.players: db.update_stats(p.id, 'liar', won=(p == game.liar))
        await channel.send(embed=embed, view=PostGameView(game))
        return
        
    top_voted_id = max_voted_ids[0]
    top_voted_player = channel.guild.get_member(top_voted_id)
    if not top_voted_player and getattr(game, 'cog', None):
        top_voted_player = await game.cog.bot.fetch_user(top_voted_id)
        
    embed = discord.Embed(
        title="⚖️ 최후의 심판대",
        description=f"가장 많은 표를 받은 {top_voted_player.mention} 님이 심판대에 올랐습니다.\\n이 플레이어를 처형하시겠습니까?",
        color=0xe67e22
    )
    game.phase = "KILL_SAVE_VOTE"
    view = KillSaveVoteView(game, top_voted_player)
    msg = await channel.send(embed=embed, view=view)
    view.message = msg

async def execute_player(game, target, channel, force_fail=False):
    from database.manager import DatabaseManager
    db = DatabaseManager()
    if target.id == game.liar.id and not force_fail:
        embed = discord.Embed(title="🚨 라이어 지목 완료!", description=f"처형된 {target.mention} 님은 **라이어가 맞습니다!**\\n\\n하지만 아직 끝이 아닙니다. {'바보 ' if game.game_mode == 'IDIOT' else ''}라이어에게도 역전의 기회가 있습니다! ({'바보 ' if game.game_mode == 'IDIOT' else ''}라이어 제시어: **{game.liar_word if game.game_mode == 'IDIOT' else '비밀'}**)\\n\\n👉 **{target.mention} 님, 지금 바로 채팅창에 '시민들의 진짜 제시어'를 유추해서 입력해주세요!**", color=0x3498db)
        game.phase = "LIAR_GUESS"
        await channel.send(embed=embed)
    else:
        embed = discord.Embed(title="🚨 라이어 검거 실패!", description=f"{'처형된 '+target.mention+' 님은 선량한 시민이었습니다!' if not force_fail else '라이어를 검거하지 못했습니다.'}\\n\\n진짜 라이어는 바로 {game.liar.mention} 님이었습니다! (제시어: **{game.word}**)\\n\\n**🎉 라이어의 승리입니다! 🎉**", color=0xff0000)
        for p in game.players: db.update_stats(p.id, 'liar', won=(p == game.liar))
        await channel.send(embed=embed, view=PostGameView(game))
"""

with open(file_path, "w", encoding="utf-8") as f:
    f.write(pre_content + new_views + post_content)
print("done")
