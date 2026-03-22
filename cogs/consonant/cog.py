import discord
from discord.ext import commands
import asyncio
import random

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

class ConsonantGameCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def start_game_ui(self, interaction: discord.Interaction):
        if interaction.channel.id in active_consonant_games:
            await interaction.response.send_message("이미 이 채널에서 훈민정음 게임이 진행 중입니다!", ephemeral=True)
            return

        c1 = random.choice(CHOSUNG_LIST)
        c2 = random.choice(CHOSUNG_LIST)
        target_chosung = c1 + c2

        active_consonant_games.add(interaction.channel.id)

        embed = discord.Embed(
            title="🗣️ 훈민정음 게임!",
            description=f"**제시된 초성**: `{target_chosung}`\n\n이 초성으로 시작하는 **2글자 단어**를 가장 먼저 채팅으로 쳐주세요! (제한시간 30초)\n*(봇은 초성 일치 여부만 검사하므로, 말이 안 되는 단어라면 알아서 무효 처리하세요!)*",
            color=0xf1c40f
        )
        
        await interaction.response.send_message(embed=embed)
        
        def check(m):
            return m.channel.id == interaction.channel.id and not m.author.bot

        try:
            while True:
                msg = await self.bot.wait_for('message', timeout=30.0, check=check)
                user_word = msg.content.replace(" ", "")
                
                if len(user_word) == 2 and get_chosung(user_word) == target_chosung:
                    win_embed = discord.Embed(
                        title="🎉 성공!",
                        description=f"<@{msg.author.id}>님이 **'{user_word}'**(으)로 조건을 맞추셨습니다!",
                        color=0x2ecc71
                    )
                    await msg.reply(embed=win_embed)
                    break
        except asyncio.TimeoutError:
            timeout_embed = discord.Embed(
                title="⏰ 시간 초과!",
                description=f"제한시간 내에 아무도 맞추지 못했습니다.",
                color=0xe74c3c
            )
            await interaction.channel.send(embed=timeout_embed)
        finally:
            active_consonant_games.discard(interaction.channel.id)

async def setup(bot):
    await bot.add_cog(ConsonantGameCog(bot))
