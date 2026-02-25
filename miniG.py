import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        # cogs 폴더와 그 하위 폴더 내의 파일들을 찾아 확장(cog)으로 불러옵니다.
        for foldername, subfolders, filenames in os.walk('./cogs'):
            for filename in filenames:
                if filename.endswith('.py') and not filename.startswith('__') and filename not in ['words.py', 'locations.py']:
                    # Windows 경로(역슬래시)를 파이썬 패키지 경로(점)로 변환
                    rel_path = os.path.relpath(foldername, '.')
                    cog_path = f"{rel_path.replace(os.sep, '.')}.{filename[:-3]}"
                    await self.load_extension(cog_path)
        
        # 슬래시 명령어 동기화 (디스코드 서버에 명령어 등록)
        await self.tree.sync()
        print("슬래시 명령어 동기화가 완료되었습니다!")

bot = MyBot()

@bot.event
async def on_ready():
    print(f'{bot.user.name} 봇이 성공적으로 로그인했습니다!')

class MainMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="라이어 게임", style=discord.ButtonStyle.primary, custom_id="menu_liar_game", emoji="🕵️")
    async def liar_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # cogs.liar_game 모듈에서 봇을 통해 게임 시작 함수를 호출합니다.
        liar_cog = bot.get_cog("LiarGameCog")
        if liar_cog:
            await liar_cog.start_liar_game_ui(interaction)
        else:
            await interaction.response.send_message("라이어 게임 시스템을 불러올 수 없습니다!", ephemeral=True)

    @discord.ui.button(label="스파이폴", style=discord.ButtonStyle.danger, custom_id="menu_spyfall_game", emoji="🕵️‍♂️")
    async def spyfall_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.spyfall.spyfall import start_spyfall_ui
        await start_spyfall_ui(interaction)

    @discord.ui.button(label="준비 중인 게임", style=discord.ButtonStyle.secondary, custom_id="menu_other_game", disabled=True, emoji="🚧")
    async def other_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("아직 준비 중인 게임입니다.", ephemeral=True)

@bot.command(name="시작")
async def show_menu(ctx):
    embed = discord.Embed(
        title="🎮 미니게임 봇 메인 메뉴",
        description="원하시는 게임을 아래 버튼에서 선택해주세요!",
        color=0x00ff00
    )
    await ctx.send(embed=embed, view=MainMenuView())

@bot.command(name="종료")
async def force_stop(ctx):
    """현재 진행 중인 게임과 음성 연결을 모두 강제로 종료합니다."""
    # 음성 연결이 있다면 종료
    if ctx.guild and ctx.guild.voice_client:
        await ctx.guild.voice_client.disconnect()
        
    # 진행 중인 게임(LiarGame, Spyfall)이 있다면 상태 초기화
    from cogs.liar.liar_game import active_games as liar_games
    if ctx.channel.id in liar_games:
        liar_games.pop(ctx.channel.id, None)

    try:
        from cogs.spyfall.spyfall import active_spyfall_games
        if ctx.channel.id in active_spyfall_games:
            game = active_spyfall_games[ctx.channel.id]
            if game.timer_task and not game.timer_task.done():
                game.timer_task.cancel()
            active_spyfall_games.pop(ctx.channel.id, None)
    except ImportError:
        pass
        
    embed = discord.Embed(
        title="🛑 강제 종료 완료",
        description="진행 중이던 모든 게임 시스템과 음성 연결을 중단했습니다.",
        color=0xff0000
    )
    await ctx.send(embed=embed)

# 봇 토큰 (환경 변수에서 가져오고, 없으면 기존 하드코딩 문자열 사용)
TOKEN = os.getenv('DISCORD_TOKEN', '')

bot.run(TOKEN)