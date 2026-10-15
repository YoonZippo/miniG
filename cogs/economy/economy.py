"""
miniG 경제 및 포인트 시스템 (Economy & G-Point Cog)
- /출석: 매일 1회 출석체크 (기본 100P + 연속 출석 보너스)
- /지갑: 잔여 포인트, 칭호, 연속 출석일수 확인
- /송금: 유저 간 포인트 전송
- /주사위: 봇과 1:1 주사위 배팅 게임
- /상점: 포인트로 전용 칭호 구매 및 장착
- /포인트랭킹: 서버 내 포인트 랭킹 Top 10
"""

import discord
import logging
import secrets
from discord.ext import commands
from database.manager import DatabaseManager

logger = logging.getLogger('gameBot.economy')

TITLES_SHOP = [
    {"name": "새싹 게이머", "cost": 0, "desc": "기본 칭호"},
    {"name": "치즈 장인 🧀", "cost": 500, "desc": "치즈를 누구보다 잘 숨기는 자"},
    {"name": "프로 라이어 🕵️", "cost": 1000, "desc": "속고 속이는 심리전의 달인"},
    {"name": "밤의 지배자 ⛓️", "cost": 1500, "desc": "교도소의 어둠을 꿰뚫어보는 자"},
    {"name": "블랙잭 마스터 🃏", "cost": 2000, "desc": "항상 21점을 노리는 카지노 고수"},
    {"name": "포커 페이스 ♠️", "cost": 3000, "desc": "어떤 패를 쥐어도 흔들리지 않는 표정"},
    {"name": "미니G 황제 👑", "cost": 10000, "desc": "서버 최고의 부자이자 전설의 승부사"},
]


class ShopSelectView(discord.ui.View):
    def __init__(self, db: DatabaseManager, user_id: int):
        super().__init__(timeout=60)
        self.db = db
        self.user_id = user_id

        options = []
        for item in TITLES_SHOP:
            cost_str = "무료" if item["cost"] == 0 else f"{item['cost']}P"
            options.append(discord.SelectOption(
                label=f"{item['name']} ({cost_str})",
                value=item["name"],
                description=item["desc"]
            ))

        select = discord.ui.Select(
            placeholder="구매 및 장착할 칭호를 선택하세요",
            options=options,
            min_values=1,
            max_values=1
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("본인의 상점 메뉴만 선택할 수 있습니다.", ephemeral=True)
            return

        chosen_title = interaction.data["values"][0]
        item = next((i for i in TITLES_SHOP if i["name"] == chosen_title), None)
        if not item:
            await interaction.response.send_message("유효하지 않은 상품입니다.", ephemeral=True)
            return

        success, msg = self.db.set_title(self.user_id, item["name"], item["cost"])
        await interaction.response.send_message(msg, ephemeral=True)


class EconomyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = DatabaseManager()

    @commands.hybrid_command(name="출석", description="매일 1회 출석체크를 하고 G-Point를 받습니다.")
    async def daily(self, ctx):
        success, reward, streak, msg = self.db.claim_daily(ctx.author.id)
        if success:
            embed = discord.Embed(
                title="📅 일일 출석체크 완료!",
                description=msg,
                color=0x2ecc71
            )
        else:
            embed = discord.Embed(
                title="⚠️ 이미 출석하셨습니다!",
                description=msg,
                color=0xe67e22
            )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="지갑", description="보유 포인트와 장착 칭호를 확인합니다.")
    async def wallet(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        eco = self.db.get_user_economy(target.id)

        embed = discord.Embed(
            title=f"🪙 {target.display_name}님의 지갑",
            color=0xf1c40f
        )
        if target.avatar:
            embed.set_thumbnail(url=target.avatar.url)

        embed.add_field(name="보유 G-Point", value=f"**{eco['points']:,} P**", inline=True)
        embed.add_field(name="칭호", value=f"**[{eco['title']}]**", inline=True)
        embed.add_field(name="연속 출석", value=f"**{eco['daily_streak']}일째**", inline=True)

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="송금", description="다른 유저에게 포인트를 송금합니다.")
    async def transfer(self, ctx, member: discord.Member, amount: int):
        success, msg = self.db.transfer_points(ctx.author.id, member.id, amount)
        color = 0x2ecc71 if success else 0xe74c3c
        embed = discord.Embed(
            title="💸 포인트 송금 결과",
            description=f"보낸 사람: {ctx.author.mention}\n받는 사람: {member.mention}\n\n{msg}",
            color=color
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="주사위", description="봇과 1:1 주사위 대결을 하여 2배의 포인트를 노립니다.")
    async def dice_gamble(self, ctx, bet: int):
        if bet <= 0:
            await ctx.send("1P 이상만 베팅할 수 있습니다!")
            return

        eco = self.db.get_user_economy(ctx.author.id)
        if eco["points"] < bet:
            await ctx.send(f"❌ 잔액이 부족합니다! (보유: **{eco['points']:,} P**)")
            return

        # 1~100 주사위 굴리기
        user_roll = secrets.randbelow(100) + 1
        bot_roll = secrets.randbelow(100) + 1

        if user_roll > bot_roll:
            # 승리: 2배 (순수익 = bet)
            new_bal = self.db.add_points(ctx.author.id, bet, "DICE_WIN")
            embed = discord.Embed(
                title="🎲 주사위 배팅 승리!",
                description=(
                    f"👤 **{ctx.author.display_name}**: 🎲 **{user_roll}**\n"
                    f"🤖 **미니G 봇**: 🎲 **{bot_roll}**\n\n"
                    f"🎉 축하합니다! **+{bet:,} P** 획득!\n"
                    f"현재 잔액: **{new_bal:,} P**"
                ),
                color=0x2ecc71
            )
        elif user_roll < bot_roll:
            # 패배: 차감
            new_bal = self.db.add_points(ctx.author.id, -bet, "DICE_LOSE")
            embed = discord.Embed(
                title="🎲 주사위 배팅 패배!",
                description=(
                    f"👤 **{ctx.author.display_name}**: 🎲 **{user_roll}**\n"
                    f"🤖 **미니G 봇**: 🎲 **{bot_roll}**\n\n"
                    f"💥 아쉽네요! **-{bet:,} P** 차감.\n"
                    f"현재 잔액: **{new_bal:,} P**"
                ),
                color=0xe74c3c
            )
        else:
            # 동점: 본전 반환
            embed = discord.Embed(
                title="🎲 주사위 동점 (무승부)!",
                description=(
                    f"👤 **{ctx.author.display_name}**: 🎲 **{user_roll}**\n"
                    f"🤖 **미니G 봇**: 🎲 **{bot_roll}**\n\n"
                    f"동점이므로 베팅 금액이 반환되었습니다."
                ),
                color=0x3498db
            )

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="상점", description="G-Point로 멋진 칭호를 구매하고 장착합니다.")
    async def shop(self, ctx):
        eco = self.db.get_user_economy(ctx.author.id)
        embed = discord.Embed(
            title="🏪 miniG 칭호 상점",
            description=(
                f"보유 포인트로 프로필에 장착할 특별한 칭호를 구매하세요!\n"
                f"현재 보유: **{eco['points']:,} P** | 현재 칭호: **[{eco['title']}]**\n\n"
                "아래 메뉴에서 원하는 칭호를 선택하세요:"
            ),
            color=0x9b59b6
        )
        view = ShopSelectView(self.db, ctx.author.id)
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="포인트랭킹", description="서버 내 최고 부자 Top 10을 확인합니다.")
    async def rich_ranking(self, ctx):
        top_list = self.db.get_top_rich(limit=10)
        embed = discord.Embed(
            title="🏆 miniG 최고 부자 랭킹 (Top 10)",
            color=0xf1c40f
        )

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        lines = []
        for i, (user_id, points, title) in enumerate(top_list):
            user = self.bot.get_user(user_id)
            if not user:
                try:
                    user = await self.bot.fetch_user(user_id)
                except Exception:
                    pass
            name = user.display_name if user else f"User({user_id})"
            medal = medals[i] if i < len(medals) else f"#{i+1}"
            lines.append(f"{medal} **{name}** [{title}] — **{points:,} P**")

        embed.description = "\n".join(lines) or "아직 등록된 랭킹 데이터가 없습니다."
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(EconomyCog(bot))
