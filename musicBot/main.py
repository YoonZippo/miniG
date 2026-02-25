import discord
import os
import asyncio
from discord.ext import commands
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()
TOKEN = os.getenv('MUSIC_BOT_TOKEN') # 기존 봇과 다른 토큰 사용

# 봇 설정
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!!', intents=intents) # 접두사도 차별화 (!!)

@bot.event
async def on_ready():
    print(f'🎵 Music Bot Logged in as: {bot.user.name} ({bot.user.id})')
    print('------')

async def main():
    async with bot:
        # music cog 로드
        await bot.load_extension('cogs.music')
        await bot.start(TOKEN)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
