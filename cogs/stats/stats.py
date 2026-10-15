import discord
import logging
from discord.ext import commands
from database.manager import DatabaseManager

logger = logging.getLogger('gameBot.stats')

class StatsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager()

    @commands.hybrid_command(name="프로필", description="본인 또는 다른 유저의 전적을 확인합니다.")
    async def profile(self, ctx, member: discord.Member = None):
        """본인 또는 다른 유저의 전적을 확인합니다."""
        member = member or ctx.author
        stats = self.db.get_user_stats(member.id)

        eco = self.db.get_user_economy(member.id)
        liar_wins, liar_plays, spyfall_wins, spyfall_plays = stats if stats else (0, 0, 0, 0)
        
        def safe_div(a, b):
            return (a / b * 100) if b > 0 else 0

        embed = discord.Embed(
            title=f"🏅 {member.display_name}님의 프로필",
            description=f"칭호: **[{eco['title']}]** | 보유 포인트: **🪙 {eco['points']:,} P**",
            color=0x3498db
        )
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        
        embed.add_field(
            name="🕵️ 라이어 게임", 
            value=f"승리: {liar_wins} / 판수: {liar_plays}\n승률: {safe_div(liar_wins, liar_plays):.1f}%", 
            inline=True
        )
        embed.add_field(
            name="🕵️‍♂️ 스파이폴", 
            value=f"승리: {spyfall_wins} / 판수: {spyfall_plays}\n승률: {safe_div(spyfall_wins, spyfall_plays):.1f}%", 
            inline=True
        )

        game_labels = {
            "cheese_thief": "🧀 치즈 도둑",
            "prisoners_night": "⛓️ 죄수들의 밤",
            "blackjack": "🃏 블랙잭 라운드",
            "holdem": "♠️ 텍사스 홀덤",
            "consonant": "🗣️ 훈민정음",
        }
        for game_type, game_stats in self.db.get_game_stats(member.id).items():
            label = game_labels.get(game_type)
            if not label:
                continue
            plays = game_stats["plays"]
            wins = game_stats["wins"]
            draws = game_stats["draws"]
            embed.add_field(
                name=label,
                value=f"승리: {wins} / 판수: {plays} / 무승부: {draws}\n승률: {safe_div(wins, plays):.1f}%",
                inline=True,
            )
        
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="랭킹", description="서버 내 게임별 Top 3 랭킹을 확인합니다.")
    async def ranking(self, ctx):
        """서버 내 게임별 Top 3 랭킹을 확인합니다."""
        liar_top = self.db.get_top_rankings('liar', limit=3)
        spyfall_top = self.db.get_top_rankings('spyfall', limit=3)

        embed = discord.Embed(title="🏆 miniG 서버 명예의 전당 (Top 3)", color=0xf1c40f)

        # 라이어 랭킹
        liar_text = ""
        medals = ["🥇", "🥈", "🥉"]
        for i, (user_id, wins) in enumerate(liar_top):
            user = self.bot.get_user(user_id)
            if not user:
                try:
                    user = await self.bot.fetch_user(user_id)
                except discord.NotFound:
                    pass
            name = user.display_name if user else f"Unknown({user_id})"
            liar_text += f"{medals[i]} **{name}**: {wins}승\n"
        embed.add_field(name="🕵️ 최고의 라이어", value=liar_text or "데이터 부족", inline=False)

        # 스파이폴 랭킹
        spyfall_text = ""
        for i, (user_id, wins) in enumerate(spyfall_top):
            user = self.bot.get_user(user_id)
            if not user:
                try:
                    user = await self.bot.fetch_user(user_id)
                except discord.NotFound:
                    pass
            name = user.display_name if user else f"Unknown({user_id})"
            spyfall_text += f"{medals[i]} **{name}**: {wins}승\n"
        embed.add_field(name="🕵️‍♂️ 최고의 스파이", value=spyfall_text or "데이터 부족", inline=False)

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(StatsCog(bot))
