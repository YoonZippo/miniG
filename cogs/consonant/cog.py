import discord
from discord.ext import commands
import asyncio
import random
from .words import WORDS, get_chosung

active_consonant_games = set()

class ConsonantGameCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def start_game_ui(self, interaction: discord.Interaction):
        if interaction.channel.id in active_consonant_games:
            await interaction.response.send_message("이미 이 채널에서 초성게임이 진행 중입니다!", ephemeral=True)
            return

        category = random.choice(list(WORDS.keys()))
        word = random.choice(WORDS[category])
        chosung = get_chosung(word)

        active_consonant_games.add(interaction.channel.id)

        embed = discord.Embed(
            title="🔠 초성 퀴즈!",
            description=f"**주제**: {category}\n**초성**: `{chosung}`\n\n가장 먼저 정답을 타자로 치는 사람이 승리합니다! (제한시간 30초)",
            color=0xf1c40f
        )
        
        await interaction.response.send_message(embed=embed)
        
        def check(m):
            return m.channel.id == interaction.channel.id and not m.author.bot

        try:
            while True:
                msg = await self.bot.wait_for('message', timeout=30.0, check=check)
                if msg.content.replace(" ", "") == word:
                    win_embed = discord.Embed(
                        title="🎉 정답입니다!",
                        description=f"<@{msg.author.id}>님이 정답 **'{word}'**을(를) 맞히셨습니다!",
                        color=0x2ecc71
                    )
                    await msg.reply(embed=win_embed)
                    break
        except asyncio.TimeoutError:
            timeout_embed = discord.Embed(
                title="⏰ 시간 초과!",
                description=f"아무도 맞히지 못했습니다.\n정답은 **'{word}'** 입니다!",
                color=0xe74c3c
            )
            await interaction.channel.send(embed=timeout_embed)
        finally:
            active_consonant_games.discard(interaction.channel.id)

async def setup(bot):
    await bot.add_cog(ConsonantGameCog(bot))
