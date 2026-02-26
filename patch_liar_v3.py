import os

def patch_liar_game():
    file_path = r"x:\Desktop\projects\discordBot\miniG\cogs\liar\liar_game.py"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # 1. Add final_target and hints_log to LiarGame init
    old_init = """        self.votes: Dict[discord.Member, int] = {}
        self.turn_limit: int = 20 # 기본 턴 제한시간 (초)
        self.vote_limit: int = 30 # 기본 투표 제한시간 (초)
        self.timer_task: asyncio.Task = None # 턴 제한시간 타이머 태스크"""
    
    new_init = """        self.votes: Dict[discord.Member, int] = {}
        self.turn_limit: int = 20 # 기본 턴 제한시간 (초)
        self.vote_limit: int = 30 # 기본 투표 제한시간 (초)
        self.timer_task: asyncio.Task = None # 턴 제한시간 타이머 태스크
        
        self.final_target: discord.Member = None
        self.hints_log: list = []"""
    
    if old_init in content:
        content = content.replace(old_init, new_init)
    
    # 2. Append to hints_log during PLAYING phase in on_message
    old_playing_log = """        # 메시지 텍스트 강조 Embed 생성
        embed = discord.Embed(description=f"🗣️ **{message.content}**", color=0x3498db)"""
        
    new_playing_log = """        # 힌트 로그 저장
        game.hints_log.append(f"**{message.author.display_name}**: {message.content}")

        # 메시지 텍스트 강조 Embed 생성
        embed = discord.Embed(description=f"🗣️ **{message.content}**", color=0x3498db)"""
        
    if old_playing_log in content:
        content = content.replace(old_playing_log, new_playing_log)
        
    # 3. Modify FinalVoteView instantiation in ExtensionVoteView to show hints
    old_turn_final_1 = """                game.phase = "VOTING_FINAL"
                view = FinalVoteView(game)
                msg = await channel.send("두 바퀴가 모두 종료되었습니다! 이제 라이어로 의심되는 사람을 투표해주세요.", view=view)
                view.message = msg"""
                
    old_turn_final_2 = """            else:
                game.phase = "VOTING_FINAL"
                view = FinalVoteView(game)
                msg = await channel.send("두 바퀴가 모두 종료되었습니다! 이제 라이어로 의심되는 사람을 투표해주세요.", view=view)
                view.message = msg"""
                
    new_turn_final_2 = """            else:
                game.phase = "VOTING_FINAL"
                view = FinalVoteView(game)
                
                hints_str = "\\n".join(game.hints_log) if game.hints_log else "기록된 단서가 없습니다."
                embed = discord.Embed(
                    title="⚖️ 최종 투표: 라이어를 잡아라!",
                    description="두 바퀴가 모두 종료되었습니다! 아래 단서들을 참고하여 라이어로 의심되는 사람을 골라주세요.",
                    color=0xf1c40f
                )
                embed.add_field(name="📜 그동안의 단서 기록", value=hints_str, inline=False)
                
                msg = await channel.send(embed=embed, view=view)
                view.message = msg"""
                
    if old_turn_final_2 in content:
        content = content.replace(old_turn_final_2, new_turn_final_2)
    elif old_turn_final_1 in content:
         # For safety if there was formatting diff
         pass

    # Now let's just do a specific regex or replace for ExtensionVoteView check_votes
    old_ext_yes_timeout = """        if hasattr(self, 'message') and self.message:
            try: await self.message.edit(view=None)
            except: pass
            
        # 연장 찬성 파
        if len(self.yes_votes) >= required_votes:
            self.game.round_count += 1
            self.game.current_turn_index = 0
            
            # 턴 순서를 그대로 유지할지 섞을지 결정 (보통 그대로 유지)
            await channel.send(f"🟢 연장 투표 결과 **찬성**! 두 번째 바퀴를 시작합니다.")
            
            # 다음 플레이어 호출 및 타이머 재시작
            first_player = self.game.turn_order[0]
            await channel.send(f"👉 첫 번째 차례: {first_player.mention} 님, 설명해주세요! (제한시간: {self.game.turn_limit}초)")
            
            liar_cog = interaction.client.get_cog("LiarGameCog") if interaction else None
            if liar_cog:
                self.game.timer_task = asyncio.create_task(liar_cog.turn_timer(self.game))
        else:
            self.game.phase = "VOTING_FINAL"
            view = FinalVoteView(self.game)
            msg = await channel.send("🔴 연장 투표 결과 **반대(또는 기권)**! 바로 색출 투표를 진행합니다.", view=view)
            view.message = msg"""

    new_ext_yes_timeout = """        if hasattr(self, 'message') and self.message:
            try: await self.message.edit(view=None)
            except: pass
            
        # 연장 찬성 파
        if len(self.yes_votes) >= required_votes:
            self.game.round_count += 1
            self.game.current_turn_index = 0
            
            # 턴 순서를 그대로 유지할지 섞을지 결정 (보통 그대로 유지)
            await channel.send(f"🟢 연장 투표 결과 **찬성**! 두 번째 바퀴를 시작합니다.")
            
            # 다음 플레이어 호출 및 타이머 재시작
            first_player = self.game.turn_order[0]
            await channel.send(f"👉 첫 번째 차례: {first_player.mention} 님, 설명해주세요! (제한시간: {self.game.turn_limit}초)")
            
            liar_cog = interaction.client.get_cog("LiarGameCog") if interaction else None
            if liar_cog:
                self.game.timer_task = asyncio.create_task(liar_cog.turn_timer(self.game))
        else:
            self.game.phase = "VOTING_FINAL"
            view = FinalVoteView(self.game)
            
            hints_str = "\\n".join(self.game.hints_log) if self.game.hints_log else "기록된 단서가 없습니다."
            embed = discord.Embed(
                title="⚖️ 색출 투표: 라이어를 잡아라!",
                description="🔴 연장 투표 결과 **반대(또는 기권)**! 아래 단서들을 참고하여 라이어를 골라주세요.",
                color=0xf1c40f
            )
            embed.add_field(name="📜 그동안의 발언 기록", value=hints_str, inline=False)
            
            msg = await channel.send(embed=embed, view=view)
            view.message = msg"""
    if old_ext_yes_timeout in content:
        content = content.replace(old_ext_yes_timeout, new_ext_yes_timeout)
        
    # 4. Save self.final_target on process_final_vote and process_tiebreaker_vote
    old_target_1 = """    game.phase = "FINAL_DEFENSE"
    embed = discord.Embed(
        title="🗣️ 최후의 변론",
        description=f"가장 많은 표를 받은 {top_voted_player.mention} 님이 심판대에 올랐습니다.\\n\\n👉 **{top_voted_player.mention} 님, 채널에 채팅을 쳐서 마지막으로 자신을 변호하세요!** (제한시간: {game.turn_limit}초)",
        color=0xf39c12
    )"""
    new_target_1 = """    game.final_target = top_voted_player
    game.phase = "FINAL_DEFENSE"
    embed = discord.Embed(
        title="🗣️ 최후의 변론",
        description=f"가장 많은 표를 받은 {top_voted_player.mention} 님이 심판대에 올랐습니다.\\n\\n👉 **{top_voted_player.mention} 님, 채널에 채팅을 쳐서 마지막으로 자신을 변호하세요!** (제한시간: {game.turn_limit}초)",
        color=0xf39c12
    )"""
    if old_target_1 in content:
        content = content.replace(old_target_1, new_target_1)
        
    # 5. Lock down FINAL_DEFENSE trigger in on_message
    old_on_msg_defense = """        # 최후의 변론 처리
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
            return"""
            
    new_on_msg_defense = """        # 최후의 변론 처리
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
            return"""
    if old_on_msg_defense in content:
        content = content.replace(old_on_msg_defense, new_on_msg_defense)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

patch_liar_game()
