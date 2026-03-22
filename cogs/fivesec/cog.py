import discord
from discord.ext import commands
import asyncio
import random
from .topics import TOPICS

class FiveSecGameCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def start_game_ui(self, interaction: discord.Interaction):
        topic = random.choice(TOPICS)

        embed = discord.Embed(
            title="⏱️ 5초준다!",
            description=f"**주제**: {topic}\n\n준비하시고...\n5초 카운트다운을 시작합니다!",
            color=0xe67e22
        )
        await interaction.response.send_message(embed=embed)
        original_msg = await interaction.original_response()

        for i in range(5, 0, -1):
            count_embed = discord.Embed(
                title="⏱️ 카운트다운 진행 중!",
                description=f"**주제**: {topic}\n\n# {i}",
                color=0xe67e22
            )
            await asyncio.sleep(1)
            try:
                await original_msg.edit(embed=count_embed)
            except:
                pass

        end_embed = discord.Embed(
            title="⏰ 땡!",
            description=f"**주제**: {topic}\n\n시간이 다 되었습니다! 참가자는 성공했나요?\n통화방 사람들에게 확인을 받아주세요!",
            color=0xc0392b
        )
        try:
            await original_msg.edit(embed=end_embed)
        except:
            await interaction.channel.send(embed=end_embed)

async def setup(bot):
    await bot.add_cog(FiveSecGameCog(bot))
