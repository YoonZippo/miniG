import discord
from discord.ext import commands
import asyncio
import random
import uuid
from database.manager import DatabaseManager

db = DatabaseManager()

active_consonant_games = set()

CHOSUNG_LIST = ['ㄱ', 'ㄴ', 'ㄷ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅅ', 'ㅇ', 'ㅈ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']

def get_chosung(text):
    ALL_CHOSUNG = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']
    result = ""
    for char in text:
        if '가' <= char <= '힣':
            char_code = ord(char) - 0xAC00
            chosung_index = char_code // 588
            result += ALL_CHOSUNG[chosung_index]
        else:
            result += char
    return result

class HunminGameResultView(discord.ui.View):
    def __init__(self, bot, players, time_limit, length):
        super().__init__(timeout=None)
        self.bot = bot
        self.players = players
        self.time_limit = time_limit
        self.length = length

    @discord.ui.button(label="다시 하기", style=discord.ButtonStyle.success, emoji="🔄")
    async def restart_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("ConsonantGameCog")
        if cog:
            # Check if game is already active
            if interaction.channel.id in active_consonant_games:
                await interaction.response.send_message("이미 이 채널에서 게임이 진행 중입니다!", ephemeral=True)
                return
            
            active_consonant_games.add(interaction.channel.id)
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)
            
            await cog.start_game_phase2(interaction, self.players, self.time_limit, self.length)

    @discord.ui.button(label="게임 종료", style=discord.ButtonStyle.danger, emoji="🛑")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        active_consonant_games.discard(interaction.channel.id)
        for child in self.children:
            child.disabled = True
        
        await interaction.response.edit_message(view=self)
        await interaction.channel.send("훈민정음 게임을 완전히 종료합니다! 고생하셨습니다. 👏")

class HunminSetupView(discord.ui.View):
    def __init__(self, host: discord.Member, bot):
        super().__init__(timeout=300)
        self.host = host
        self.bot = bot
        self.players = [host]
        self.time_limit = 10
        self.length = 2

    def update_embed(self):
        player_mentions = ", ".join([p.mention for p in self.players])
        return discord.Embed(
            title="🗣️ 훈민정음 게임 대기실",
            description=f"**방장**: {self.host.mention}\n\n"
                        f"**현재 설정**\n"
                        f"⏱️ 턴 제한 시간: **{self.time_limit}초**\n"
                        f"✏️ 제시어 글자 수: **{self.length}글자**\n\n"
                        f"**참가자 ({len(self.players)}명)**\n{player_mentions}",
            color=0x3498db
        )

    @discord.ui.button(label="참가하기", style=discord.ButtonStyle.primary, custom_id="join_btn", emoji="✋")
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.players:
            await interaction.response.send_message("이미 참가하셨습니다!", ephemeral=True)
            return
        
        self.players.append(interaction.user)
        await interaction.response.edit_message(embed=self.update_embed(), view=self)

    @discord.ui.select(placeholder="제한 시간 설정 (방장 전용)", options=[
        discord.SelectOption(label="5초", value="5"),
        discord.SelectOption(label="10초", value="10", default=True),
        discord.SelectOption(label="15초", value="15"),
    ])
    async def time_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user != self.host:
            await interaction.response.send_message("방장만 설정할 수 있습니다!", ephemeral=True)
            return
        self.time_limit = int(select.values[0])
        for opt in select.options:
            opt.default = (opt.value == select.values[0])
        await interaction.response.edit_message(embed=self.update_embed(), view=self)

    @discord.ui.select(placeholder="글자 수 설정 (방장 전용)", options=[
        discord.SelectOption(label="2글자", value="2", default=True),
        discord.SelectOption(label="3글자", value="3"),
    ])
    async def length_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user != self.host:
            await interaction.response.send_message("방장만 설정할 수 있습니다!", ephemeral=True)
            return
        self.length = int(select.values[0])
        for opt in select.options:
            opt.default = (opt.value == select.values[0])
        await interaction.response.edit_message(embed=self.update_embed(), view=self)

    @discord.ui.button(label="게임 시작", style=discord.ButtonStyle.success, custom_id="start_btn", emoji="▶️", row=3)
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.host:
            await interaction.response.send_message("방장만 시작할 수 있습니다!", ephemeral=True)
            return
        if len(self.players) < 2:
            await interaction.response.send_message("최소 2명 이상 모여야 시작할 수 있습니다!", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=self.update_embed(), view=self)

        cog = self.bot.get_cog("ConsonantGameCog")
        if cog:
            await cog.start_game_phase2(interaction, self.players, self.time_limit, self.length)

class ConsonantGameCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def start_game_ui(self, interaction: discord.Interaction):
        if interaction.channel.id in active_consonant_games:
            await interaction.response.send_message("이미 이 채널에서 훈민정음 게임(또는 대기실)이 진행 중입니다!", ephemeral=True)
            return

        active_consonant_games.add(interaction.channel.id)
        
        view = HunminSetupView(interaction.user, self.bot)
        await interaction.response.send_message(embed=view.update_embed(), view=view)

    async def start_game_phase2(self, interaction: discord.Interaction, players: list, time_limit: int, length: int):
        random.shuffle(players)
        target_chosung = "".join([random.choice(CHOSUNG_LIST) for _ in range(length)])
        order_str = " ➔ ".join([p.display_name for p in players])
        
        start_embed = discord.Embed(
            title="🗣️ 훈민정음 게임 시작!",
            description=f"**순서**: {order_str}\n\n"
                        f"🔥 **오늘의 초성**: `{target_chosung}`\n"
                        f"⏱️ **제한 시간**: {time_limit}초\n\n"
                        f"준비하시고... 바로 첫 번째 턴 시작합니다!",
            color=0xe67e22
        )
        
        if interaction.response.is_done():
            await interaction.channel.send(embed=start_embed)
        else:
            await interaction.response.send_message(embed=start_embed)

        session_id = uuid.uuid4().hex
        asyncio.create_task(self.game_loop(interaction.channel, players, time_limit, length, target_chosung, session_id))

    async def game_loop(self, channel, players, time_limit, length, target_chosung, session_id):
        used_words = []
        current_turn_index = 0

        while True:
            current_player = players[current_turn_index]
            
            turn_msg = await channel.send(f"➡️ {current_player.mention}님의 턴! (`{target_chosung}`, {time_limit}초)")
            
            def check(m):
                return m.channel == channel and m.author == current_player

            try:
                msg = await self.bot.wait_for('message', timeout=time_limit, check=check)
                word = msg.content.replace(" ", "")
                
                if len(word) != length:
                    await self.game_over(channel, current_player, f"글자 수가 {length}글자가 아닙니다. (입력: {word})", used_words, players, time_limit, length, session_id)
                    break
                
                if not all('가' <= char <= '힣' for char in word):
                    await self.game_over(channel, current_player, f"완성된 한글 단어만 입력할 수 있습니다. 자음이나 모음, 기호 등은 인정되지 않습니다. (입력: {word})", used_words, players, time_limit, length, session_id)
                    break
                
                if get_chosung(word) != target_chosung:
                    await self.game_over(channel, current_player, f"초성이 일치하지 않습니다. (입력: {word})", used_words, players, time_limit, length, session_id)
                    break
                
                if word in used_words:
                    await self.game_over(channel, current_player, f"이미 누군가 사용한 단어입니다. (입력: {word})", used_words, players, time_limit, length, session_id)
                    break
                
                used_words.append(word)
                await msg.add_reaction("✅")
                
                current_turn_index = (current_turn_index + 1) % len(players)
                
            except asyncio.TimeoutError:
                await self.game_over(channel, current_player, "시간 초과 ⏰", used_words, players, time_limit, length, session_id)
                break

    async def game_over(self, channel, loser, reason, used_words, players, time_limit, length, session_id):
        active_consonant_games.discard(channel.id)
        db.record_game_result(
            session_id,
            "consonant",
            [player.id for player in players],
            [player.id for player in players if player != loser],
        )
        
        used_words_str = ", ".join(used_words) if used_words else "없음"
        
        embed = discord.Embed(
            title="💥 게임 종료!",
            description=f"**패배자**: {loser.mention}\n"
                        f"**사유**: {reason}\n\n"
                        f"🏆 **성공한 단어 목록 ({len(used_words)}개)**\n"
                        f"```\n{used_words_str}\n```",
            color=0xe74c3c
        )
        
        view = HunminGameResultView(self.bot, players, time_limit, length)
        await channel.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(ConsonantGameCog(bot))
