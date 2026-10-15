import discord
from discord.ext import commands
import os
import logging
import logging.handlers

# 로그 디렉토리 자동 생성
os.makedirs('logs', exist_ok=True)

# 로깅 설정
logger = logging.getLogger('gameBot')
logger.setLevel(logging.INFO)

# 로그 포맷 설정
formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(name)s: %(message)s')

# 파일 핸들러 (로그 회전 포함)
file_handler = logging.handlers.RotatingFileHandler(
    filename='logs/bot.log',
    encoding='utf-8',
    maxBytes=5*1024*1024, # 5MB
    backupCount=5
)
file_handler.setFormatter(formatter)

# 콘솔 핸들러
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

intents = discord.Intents.default()
intents.message_content = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        # cogs 폴더와 그 하위 폴더 내의 파일들을 찾아 확장(cog)으로 불러옵니다.
        for foldername, subfolders, filenames in os.walk('./cogs'):
            for filename in filenames:
                if filename.endswith('.py') and not filename.startswith('__') and filename not in ['words.py', 'locations.py', 'topics.py']:
                    # Windows 경로(역슬래시)를 파이썬 패키지 경로(점)로 변환
                    rel_path = os.path.relpath(foldername, '.')
                    cog_path = f"{rel_path.replace(os.sep, '.')}.{filename[:-3]}"
                    await self.load_extension(cog_path)
        
        # 슬래시 명령어 동기화 (디스코드 서버에 명령어 등록)
        await self.tree.sync()
        logger.info("슬래시 명령어 동기화가 완료되었습니다!")

bot = MyBot()

@bot.event
async def on_ready():
    logger.info(f'{bot.user.name} 봇이 성공적으로 로그인했습니다!')

class MainMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="라이어 게임(3인~)", style=discord.ButtonStyle.primary, custom_id="menu_liar_game", emoji="🕵️")
    async def liar_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # cogs.liar_game 모듈에서 봇을 통해 게임 시작 함수를 호출합니다.
        liar_cog = bot.get_cog("LiarGameCog")
        if liar_cog:
            await liar_cog.start_liar_game_ui(interaction)
        else:
            await interaction.response.send_message("라이어 게임 시스템을 불러올 수 없습니다!", ephemeral=True)

    @discord.ui.button(label="스파이폴(3인~7인)", style=discord.ButtonStyle.danger, custom_id="menu_spyfall_game", emoji="🕵️‍♂️")
    async def spyfall_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.spyfall.spyfall import start_spyfall_ui
        await start_spyfall_ui(interaction)



    @discord.ui.button(label="훈민정음", style=discord.ButtonStyle.success, custom_id="menu_consonant_game", emoji="🗣️")
    async def consonant_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        consonant_cog = bot.get_cog("ConsonantGameCog")
        if consonant_cog:
            await consonant_cog.start_game_ui(interaction)
        else:
            await interaction.response.send_message("훈민정음 게임을 불러올 수 없습니다!", ephemeral=True)

    @discord.ui.button(label="5초준다(베타)", style=discord.ButtonStyle.secondary, custom_id="menu_fivesec_game", emoji="⏱️")
    async def fivesec_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        fivesec_cog = bot.get_cog("FiveSecGameCog")
        if fivesec_cog:
            await fivesec_cog.start_game_ui(interaction)
        else:
            await interaction.response.send_message("5초준다 시스템을 불러올 수 없습니다!", ephemeral=True)

    @discord.ui.button(label="치즈 도둑(4~8인)", style=discord.ButtonStyle.primary, custom_id="menu_cheese_thief_game", emoji="🧀")
    async def cheese_thief_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.cheese_thief.cheese_thief import start_cheese_ui
        await start_cheese_ui(interaction)

    @discord.ui.button(label="죄수들의 밤(4~10인)", style=discord.ButtonStyle.danger, custom_id="menu_prisoners_night_game", emoji="⛓️")
    async def prisoners_night_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.prisoners_night.prisoners_night import start_prisoners_ui
        await start_prisoners_ui(interaction)

    @discord.ui.button(label="블랙잭(1~5인)", style=discord.ButtonStyle.success, custom_id="menu_blackjack_game", emoji="🂡")
    async def blackjack_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from cogs.blackjack.blackjack import start_blackjack_ui
        await start_blackjack_ui(interaction)

    @discord.ui.button(label="업데이트 목록", style=discord.ButtonStyle.secondary, custom_id="menu_update_list", emoji="📜")
    async def update_list_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            with open('CHANGELOG.md', 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # 최신 업데이트 블록만 추출 (첫 번째 ### 부터 다음 ### 전까지)
            latest_content = ""
            capture = False
            for line in lines:
                if line.startswith('###'):
                    if not capture:
                        capture = True
                    else:
                        break # 두 번째 ###를 만나면 중단
                if capture:
                    latest_content += line
            
            embed = discord.Embed(
                title="🆕 최신 업데이트 소식",
                description=latest_content or "기록된 업데이트 내용이 없습니다.",
                color=0x3498db
            )
            
            # 리포지토리가 퍼블릭이므로 깃허브 링크 버튼 제공
            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                label="전체 업데이트 기록 보기 (GitHub)", 
                url="https://github.com/YoonZippo/miniG/blob/main/CHANGELOG.md",
                style=discord.ButtonStyle.link
            ))
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"업데이트 기록을 불러오는 중 오류가 발생했습니다: {e}", ephemeral=True)

@bot.hybrid_command(name="시작", description="미니게임 메인 메뉴를 보여줍니다.")
async def show_menu(ctx):
    embed = discord.Embed(
        title="🎮 미니게임 봇 메인 메뉴",
        description="원하시는 게임을 아래 버튼에서 선택해주세요!",
        color=0x00ff00
    )
    await ctx.send(embed=embed, view=MainMenuView())

@bot.hybrid_command(name="종료", description="현재 진행 중인 모든 게임을 강제로 종료합니다.")
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

    try:
        from cogs.consonant.cog import active_consonant_games
        active_consonant_games.discard(ctx.channel.id)
    except ImportError:
        pass

    try:
        from cogs.cheese_thief.cheese_thief import active_cheese_games
        if ctx.channel.id in active_cheese_games:
            game = active_cheese_games[ctx.channel.id]
            if game.timer_task and not game.timer_task.done():
                game.timer_task.cancel()
            game.phase = "CANCELLED"
            active_cheese_games.pop(ctx.channel.id, None)
    except ImportError:
        pass

    try:
        from cogs.prisoners_night.prisoners_night import active_prisoners_games
        if ctx.channel.id in active_prisoners_games:
            game = active_prisoners_games[ctx.channel.id]
            if game.timer_task and not game.timer_task.done():
                game.timer_task.cancel()
            game.phase = "CANCELLED"
            active_prisoners_games.pop(ctx.channel.id, None)
    except ImportError:
        pass

    try:
        from cogs.blackjack.blackjack import active_blackjack_games
        if ctx.channel.id in active_blackjack_games:
            game = active_blackjack_games[ctx.channel.id]
            if game.timer_task and not game.timer_task.done():
                game.timer_task.cancel()
            game.phase = "CANCELLED"
            active_blackjack_games.pop(ctx.channel.id, None)
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