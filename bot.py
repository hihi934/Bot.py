import os
import random
import time
import json
from decimal import Decimal, getcontext
from datetime import datetime
import discord
from discord.ext import commands
import asyncio
from dotenv import load_dotenv
# -------------------- CẤU HÌNH --------------------
getcontext().prec = 28
PREFIX = '!'
SAVE_FILE = 'save.txt'
DAY_SECONDS = 86400
COIN_PER_ACTION = Decimal('5')
WIN_COIN = Decimal('20')
MAX_BET = Decimal('250000')
BET_TIME = 45
ENERGY_MAX = 5

# -------------------- TOKEN BOT --------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Nhớ thêm biến môi trường trên Render

# -------------------- SAVE / LOAD DỮ LIỆU --------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_PATH = os.path.join(BASE_DIR, SAVE_FILE)

if os.path.exists(SAVE_PATH):
    with open(SAVE_PATH,'r',encoding='utf-8') as f:
        try:
            players = json.load(f)
        except:
            players = {}
else:
    players = {}

data_lock = asyncio.Lock()

def save_data():
    with open(SAVE_PATH,'w',encoding='utf-8') as f:
        json.dump(players,f,ensure_ascii=False,indent=2)

async def async_save_data():
    loop = asyncio.get_running_loop()
    def write_file():
        with open(SAVE_PATH,'w',encoding='utf-8') as f:
            json.dump(players,f,ensure_ascii=False,indent=2)
    await loop.run_in_executor(None, write_file)

def get_player(user_id):
    if user_id not in players:
        players[user_id] = {
            "pocket":"0",
            "exp":0,
            "level":1,
            "hunger":ENERGY_MAX,
            "thirst":ENERGY_MAX,
            "last_status_ts": int(time.time()),
            "inventory":{}
        }
    return players[user_id]

def to_decimal(x):
    try:
        return Decimal(str(x))
    except:
        return Decimal('0')

def fmt_decimal(d:Decimal)->str:
    q=d.quantize(Decimal('0.01'))
    s = f"{q:,.2f}"
    return s

def apply_daily_status(player):
    now = int(time.time())
    last_ts = player.get("last_status_ts", now)
    days_passed = (now - last_ts) // DAY_SECONDS
    if days_passed >= 1:
        player["hunger"] = max(0, player.get("hunger", ENERGY_MAX)-days_passed)
        player["thirst"] = max(0, player.get("thirst", ENERGY_MAX)-days_passed)
        player["last_status_ts"] = now

# -------------------- SHOP --------------------
shop_items = {
    "nước":{"emoji":"🥤","price":Decimal('10'),"thirst":1,"hunger":0},
    "bánh mì":{"emoji":"🍞","price":Decimal('15'),"thirst":0,"hunger":1},
    "pizza":{"emoji":"🍕","price":Decimal('25'),"thirst":0,"hunger":2},
    "hamburger":{"emoji":"🍔","price":Decimal('30'),"thirst":0,"hunger":2}
}

# -------------------- BOT INIT --------------------
intents = discord.Intents.default()
intents.message_content=True
bot = commands.Bot(command_prefix=PREFIX,intents=intents)

# -------------------- SHOP COMMANDS --------------------
@bot.command()
async def shop(ctx):
    embed = discord.Embed(title="🛒 Cửa hàng", color=discord.Color.gold())
    for name,data in shop_items.items():
        embed.add_field(name=f"{data['emoji']} {name.title()}", value=f"💰 {fmt_decimal(data['price'])} xu", inline=False)
    embed.set_footer(text=f"Dùng {PREFIX}buy <tên món> để mua")
    await ctx.send(embed=embed)

@bot.command()
async def buy(ctx, *, item_name:str=None):
    if not item_name:
        await ctx.send(f"⚠️ Cú pháp: `{PREFIX}buy <tên món>`")
        return
    item_name=item_name.lower().strip()
    if item_name not in shop_items:
        await ctx.send("❌ Món này không có trong cửa hàng.")
        return
    user_id = str(ctx.author.id)
    async with data_lock:
        player=get_player(user_id)
        apply_daily_status(player)
        pocket=to_decimal(player['pocket'])
        price=shop_items[item_name]['price']
        if pocket<price:
            await ctx.send(f"💸 Bạn không đủ xu. Ví của bạn: {fmt_decimal(pocket)}")
            return
        pocket -= price
        player['pocket'] = str(pocket)
        inv = player.get("inventory",{})
        inv[item_name] = inv.get(item_name,0)+1
        player["inventory"]=inv
        await async_save_data()
    await ctx.send(f"✅ {ctx.author.display_name} đã mua {shop_items[item_name]['emoji']} **{item_name}** với giá {fmt_decimal(price)} xu!")

@bot.command()
async def inventory(ctx):
    user_id = str(ctx.author.id)
    async with data_lock:
        player=get_player(user_id)
        apply_daily_status(player)
        inv = player.get("inventory",{})
        if not inv:
            await ctx.send("📦 Kho của bạn đang trống.")
            return
        embed = discord.Embed(title=f"🎒 Kho đồ của {ctx.author.display_name}", color=discord.Color.green())
        for name,qty in inv.items():
            emoji = shop_items.get(name,{}).get('emoji','🪙')
            embed.add_field(name=f"{emoji} {name.title()}", value=f"Số lượng: {qty}", inline=False)
        timestamp=datetime.now().strftime("%H:%M %d/%m/%Y")
        embed.add_field(name="💧 Khát", value=f"{player['thirst']}/5 (cập nhật: {timestamp})", inline=True)
        embed.add_field(name="🍖 Đói", value=f"{player['hunger']}/5 (cập nhật: {timestamp})", inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def eat(ctx, *, item_name:str=None):
    if not item_name:
        await ctx.send(f"⚠️ Cú pháp: `{PREFIX}eat <tên món>`")
        return
    user_id = str(ctx.author.id)
    item_name=item_name.lower().strip()
    async with data_lock:
        player = get_player(user_id)
        apply_daily_status(player)
        inv = player.get("inventory",{})
        if item_name not in inv or inv[item_name]<=0:
            await ctx.send(f"❌ Bạn không có **{item_name}** trong kho.")
            return
        thirst = shop_items.get(item_name,{}).get('thirst',0)
        hunger = shop_items.get(item_name,{}).get('hunger',0)
        player['thirst']=min(ENERGY_MAX,player.get('thirst',ENERGY_MAX)+thirst)
        player['hunger']=min(ENERGY_MAX,player.get('hunger',ENERGY_MAX)+hunger)
        inv[item_name]-=1
        if inv[item_name]==0: del inv[item_name]
        player['inventory']=inv
        await async_save_data()
    await ctx.send(f"✅ {ctx.author.display_name} đã ăn/uống **{item_name}**. Đói: {player['hunger']}/5, Khát: {player['thirst']}/5")

@bot.command()
async def status(ctx):
    user_id = str(ctx.author.id)
    async with data_lock:
        player=get_player(user_id)
        apply_daily_status(player)
        await ctx.send(f"💧 Khát: {player['thirst']}/5\n🍖 Đói: {player['hunger']}/5")

# -------------------- BANK / GIVE --------------------
@bot.group(invoke_without_command=True)
async def bank(ctx):
    embed=discord.Embed(title="🏦 Ngân hàng",description=f"Sử dụng `{PREFIX}bank <subcommand>`",color=discord.Color.blue())
    embed.add_field(name="Xem số dư ví", value=f"`{PREFIX}bank balance`", inline=False)
    await ctx.send(embed=embed)

@bank.command()
async def balance(ctx):
    user_id = str(ctx.author.id)
    async with data_lock:
        player=get_player(user_id)
        apply_daily_status(player)
        pocket = player.get('pocket','0')
    await ctx.send(f"💰 Ví của {ctx.author.display_name}: {pocket} xu")

@bank.command(name="set")
@commands.has_permissions(administrator=True)
async def bank_set(ctx, member: discord.Member = None, amount: str = None):
    if not member or amount is None:
        await ctx.send(f"⚠️ Cú pháp: `{PREFIX}bank set @user <số_tiền>`")
        return
    try:
        amt = to_decimal(amount)
        if amt < 0:
            raise ValueError("negative")
    except Exception:
        await ctx.send("⚠️ Số tiền không hợp lệ. Vui lòng nhập số dương.")
        return

    async with data_lock:
        player = get_player(str(member.id))
        player['pocket'] = str(amt)
        await async_save_data()

    await ctx.send(f"✅ Đã đặt ví của **{member.display_name}** thành **{fmt_decimal(amt)} xu**. (Thao tác bởi admin {ctx.author.display_name})")

# -------------------- GIVE --------------------
@bot.command()
async def give(ctx, member: discord.Member=None, amount: str=None):
    if not member or not amount:
        await ctx.send(f"⚠️ Cú pháp: `{PREFIX}give @người_dùng <số_tiền>`")
        return
    if member.id == ctx.author.id:
        await ctx.send("❌ Bạn không thể chuyển xu cho chính mình.")
        return
    try:
        amount = to_decimal(amount)
        if amount <= 0:
            raise ValueError
    except:
        await ctx.send("⚠️ Số tiền không hợp lệ.")
        return

    async with data_lock:
        sender = get_player(str(ctx.author.id))
        receiver = get_player(str(member.id))
        apply_daily_status(sender)
        apply_daily_status(receiver)
        sender_pocket = to_decimal(sender['pocket'])
        if sender_pocket < amount:
            await ctx.send(f"💸 Bạn không đủ xu! Ví của bạn: {fmt_decimal(sender_pocket)}")
            return
        sender_pocket -= amount
        receiver_pocket = to_decimal(receiver['pocket']) + amount
        sender['pocket'] = str(sender_pocket)
        receiver['pocket'] = str(receiver_pocket)
        await async_save_data()

    await ctx.send(f"✅ {ctx.author.display_name} đã chuyển {fmt_decimal(amount)} xu cho {member.display_name} 💰")

# -------------------- TÀI XỈU --------------------
active_bets = {}
countdown_tasks = {}
bet_locks = {}

def get_bet_lock(channel_id):
    if channel_id not in bet_locks:
        bet_locks[channel_id] = asyncio.Lock()
    return bet_locks[channel_id]

@bot.command()
async def taixiu(ctx, choice: str, amount_str: str):
    channel_id = str(ctx.channel.id)
    user_id = str(ctx.author.id)
    lock = get_bet_lock(channel_id)

    async with lock:
        async with data_lock:
            player = get_player(user_id)
            apply_daily_status(player)
            pocket = to_decimal(player['pocket'])
        try:
            amount = to_decimal(amount_str)
            if amount <=0:
                raise ValueError
        except:
            await ctx.send("⚠️ Vui lòng nhập số hợp lệ.")
            return
        if amount > pocket:
            await ctx.send(f"⚠️ Bạn không đủ xu! Ví của bạn: {fmt_decimal(pocket)}")
            return
        if amount > MAX_BET:
            await ctx.send(f"⚠️ Số tiền cược tối đa: {fmt_decimal(MAX_BET)}")
            return
        choice = choice.lower()
        valid_choices = ['tài','xỉu','tai','xiu','chẵn','lẻ'] + [str(i) for i in range(3,19)]
        if choice not in valid_choices:
            await ctx.send("⚠️ Chọn Tài/Xỉu/Chẵn/Lẻ hoặc số từ 3–18.")
            return

        async with data_lock:
            player['pocket'] = str(pocket - amount)
            await async_save_data()

        if channel_id not in active_bets:
            active_bets[channel_id] = {}
        active_bets[channel_id][user_id] = {'choice':choice,'amount':amount,'name':ctx.author.display_name}
        await ctx.send(f"✅ {ctx.author.display_name} cược {fmt_decimal(amount)} xu vào {choice} ({BET_TIME}s)")

        if channel_id not in countdown_tasks or countdown_tasks[channel_id].done():
            countdown_tasks[channel_id] = bot.loop.create_task(countdown_and_roll(ctx.channel))

async def countdown_and_roll(channel):
    channel_id = str(channel.id)
    try:
        await channel.send(f"⏱️ Đếm ngược {BET_TIME} giây...")
        await asyncio.sleep(BET_TIME)
        lock = get_bet_lock(channel_id)
        async with lock:
            bets = active_bets.get(channel_id, {}).copy()
            active_bets[channel_id] = {}
        if not bets:
            await channel.send("Không có ai cược lần này.")
            return

        dice = [random.randint(1,6) for _ in range(3)]
        total = sum(dice)
        msg=f"🎲 Kết quả: {dice} → Tổng {total}\n"
        for user_id, bet in bets.items():
            async with data_lock:
                player = get_player(user_id)
                pocket = to_decimal(player['pocket'])
                choice = bet['choice']; amount = bet['amount']; name = bet['name']
                win=False; multiplier=Decimal('0')
                if choice in ['tài','tai'] and 11<=total<=17: win=True; multiplier=Decimal('1')
                elif choice in ['xỉu','xiu'] and 4<=total<=10: win=True; multiplier=Decimal('1')
                elif choice=='chẵn' and total%2==0: win=True; multiplier=Decimal('1')
                elif choice=='lẻ' and total%2==1: win=True; multiplier=Decimal('1')
                elif choice.isdigit() and int(choice)==total: win=True; multiplier=Decimal('10')
                if win:
                    win_amount = amount + amount*multiplier
                    pocket += win_amount
                    msg += f"✅ {name} thắng! +{fmt_decimal(win_amount)} xu\n"
                else:
                    msg += f"❌ {name} thua! -{fmt_decimal(amount)} xu\n"
                player['pocket'] = str(pocket)
                await async_save_data()
        await channel.send(msg)
    except Exception as e:
        print("Error in countdown_and_roll:", e)
        await channel.send("❌ Lỗi khi xử lý cược.")
    finally:
        countdown_tasks.pop(channel_id, None)

# -------------------- EVENTS --------------------
@bot.event
async def on_ready():
    print(f"✅ Đăng nhập với tên {bot.user}")
    await bot.change_presence(activity=discord.Game(name=f"Sử dụng {PREFIX}help để xem lệnh"))

# -------------------- RUN BOT --------------------
bot.run(BOT_TOKEN)

