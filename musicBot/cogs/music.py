import discord
import asyncio
import yt_dlp
from discord.ext import commands

# yt-dlp 옵션 설정
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

# FFmpeg 옵션 설정
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = {} # 길드별 대기열: {guild_id: [songs]}
        self.is_playing = {} # 길드별 재생 상태

    async def check_queue(self, ctx):
        """대기열에 다음 곡이 있는지 확인하고 재생"""
        if ctx.guild.id in self.queue and len(self.queue[ctx.guild.id]) > 0:
            song = self.queue[ctx.guild.id].pop(0)
            await self.play_music(ctx, song)
        else:
            self.is_playing[ctx.guild.id] = False

    async def play_music(self, ctx, song):
        """실제로 오디오를 재생하는 함수"""
        self.is_playing[ctx.guild.id] = True
        
        vc = ctx.voice_client
        if not vc:
            await ctx.author.voice.channel.connect()
            vc = ctx.voice_client

        source = await discord.FFmpegOpusAudio.from_probe(song['url'], **FFMPEG_OPTIONS)
        
        def after_playing(error):
            coro = self.check_queue(ctx)
            fut = asyncio.run_coroutine_threadsafe(coro, self.bot.loop)
            try:
                fut.result()
            except Exception as e:
                print(f"Error in after_playing: {e}")

        vc.play(source, after=after_playing)
        await ctx.send(f"🎵 **지금 재생 중:** {song['title']}")

    @commands.command(name="play", help="유튜브 검색 후 재생 (예: !!play 노래제목)")
    async def play(self, ctx, *, search: str):
        # 보이스 채널 확인
        if not ctx.author.voice:
            return await ctx.send("❌ 먼저 음성 채널에 접속해 주세요!")

        async with ctx.typing():
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                try:
                    # 검색 및 정보 추출
                    info = ydl.extract_info(f"ytsearch:{search}", download=False)['entries'][0]
                    song = {
                        'url': info['url'],
                        'title': info['title'],
                        'duration': info.get('duration')
                    }
                except Exception as e:
                    return await ctx.send(f"❌ 검색 중 오류가 발생했습니다: {e}")

            # 대기열 추가 로직
            guild_id = ctx.guild.id
            if guild_id not in self.queue:
                self.queue[guild_id] = []
            
            if self.is_playing.get(guild_id):
                self.queue[guild_id].append(song)
                await ctx.send(f"📂 **대기열 추가:** {song['title']} (현재 {len(self.queue[guild_id])}번째 대기)")
            else:
                await self.play_music(ctx, song)

    @commands.command(name="skip", help="현재 곡 건너뛰기")
    async def skip(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭️ 곡을 건너뛰었습니다.")
        else:
            await ctx.send("❌ 현재 재생 중인 곡이 없습니다.")

    @commands.command(name="queue", help="현재 대기열 목록 확인")
    async def queue_list(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in self.queue or len(self.queue[guild_id]) == 0:
            return await ctx.send("📝 현재 대기열이 비어 있습니다.")
        
        embed = discord.Embed(title="📋 현재 재생 대기열", color=discord.Color.blue())
        description = ""
        for i, song in enumerate(self.queue[guild_id][:10], 1):
            description += f"{i}. {song['title']}\n"
        
        if len(self.queue[guild_id]) > 10:
            description += f"...외 {len(self.queue[guild_id]) - 10}곡"
            
        embed.description = description
        await ctx.send(embed=embed)

    @commands.command(name="stop", help="재생 중지 및 채널 나가기")
    async def stop(self, ctx):
        if ctx.voice_client:
            self.queue[ctx.guild.id] = []
            await ctx.voice_client.disconnect()
            await ctx.send("👋 재생을 중지하고 채널에서 나갔습니다.")
        else:
            await ctx.send("❌ 봇이 이미 음성 채널에 있지 않습니다.")

async def setup(bot):
    await bot.add_cog(Music(bot))
