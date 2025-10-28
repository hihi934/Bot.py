import os
import random
import time
import json
from decimal import Decimal, getcontext
from datetime import datetime
from pyvi import ViTokenizer
import discord
from discord.ext import commands
import asyncio

# -------------------- CẤU HÌNH --------------------
getcontext().prec = 28
PREFIX = '!'
SAVE_FILE = 'save.txt'
TEXT_FILE = 'text2.txt'
DAY_SECONDS = 86400
COIN_PER_WORD = Decimal('5')
WIN_COIN = Decimal('20')
MAX_BET = Decimal('250000')
BET_TIME = 45
ENERGY_MAX = 5

# -------------------- TOKEN BOT --------------------
import os
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Điền token vào đây

# -------------------- LOAD TỪ ĐIỂN --------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEXT_PATH = os.path.join(BASE_DIR, TEXT_FILE)
try:
    with open(TEXT_PATH,'r',encoding='utf-8') as f:
        word_list = [line.strip().lower() for line in f if line.strip()]
except FileNotFoundError:
    print(f"⚠️ Không tìm thấy {TEXT_FILE}. Game nối từ không thể chạy.")
    word_list = []

# -------------------- LOAD / SAVE DỮ LIỆU --------------------
SAVE_PATH = os.path.join(BASE_DIR, SAVE_FILE)
if os.path.exists(SAVE_PATH):
    with open(SAVE_PATH,'r',encoding='utf-8') as f:
        try:
            players = json.load(f)
        except:
            players = {}
else:
    players = {}

# Locks
data_lock = asyncio.Lock()
game_lock = asyncio.Lock()
bet_locks = {}

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
            "combo":0,
            "inventory":{},
            "hunger":ENERGY_MAX,
            "thirst":ENERGY_MAX,
            "last_status_ts": int(time.time())
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

# -------------------- HUNGER / THIRST --------------------
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

# -------------------- WORD CHAIN --------------------
game_active = False
last_word = None
used_words = set()
player_scores = {}
bot_turn = False

def last_syllable(word):
    tokens = ViTokenizer.tokenize(word).split()
    return tokens[-1] if tokens else None

def first_syllable(word):
    tokens = ViTokenizer.tokenize(word).split()
    return tokens[0] if tokens else None

def is_valid_word(word):
    return bool(word.strip())

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

# -------------------- BANK --------------------
@bot.group(invoke_without_command=True)
async def bank(ctx):
    embed=discord.Embed(title="🏦 Ngân hàng",description=f"Sử dụng `{PREFIX}bank <subcommand>`",color=discord.Color.blue())
    embed.add_field(name="Xem số dư ví", value=f"`{PREFIX}bank balance`", inline=False)
    await ctx.send(embed=embed)

@bank.command()
async def balance(ctx):
    user_id = str(ctx.author.id)
    try:
        async with data_lock:
            # show players keys size
            print("DEBUG: players keys count:", len(players))
            player = players.get(user_id)
            if player is None:
                print(f"DEBUG: no player entry for {user_id}, creating get_player")
                player = get_player(user_id)
                await async_save_data()
            apply_daily_status(player)
            pocket = player.get('pocket','0')
        await ctx.send(f"💰 Ví của {ctx.author.display_name}: {pocket} xu")
    except Exception as e:
        print("ERROR in balance:", e)
        await ctx.send("❌ Có lỗi khi lấy số dư, xem console server để biết chi tiết.")
@bank.command(name="set")
@commands.has_permissions(administrator=True)
async def bank_set(ctx, member: discord.Member = None, amount: str = None):
    """
    Admin-only: đặt tiền ví (pocket) cho 1 user.
    Cú pháp: !bank set @user <số_tiền>
    Ví dụ: !bank set @An 100000
    """
    if not member or amount is None:
        await ctx.send(f"⚠️ Cú pháp: `{PREFIX}bank set @user <số_tiền>`")
        return

    # hỗ trợ từ khoá 'inf' để đặt 1 số rất lớn coi như vô hạn (tùy bạn)
    if isinstance(amount, str) and amount.lower() == "inf":
        big_amount = Decimal('999999999999999999999999')
        amt = big_amount
    else:
        try:
            amt = to_decimal(amount)
            if amt < 0:
                raise ValueError("negative")
        except Exception:
            await ctx.send("⚠️ Số tiền không hợp lệ. Vui lòng nhập số dương hợp lệ hoặc `inf`.")
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

    sender = get_player(str(ctx.author.id))
    receiver = get_player(str(member.id))
    apply_daily_status(sender)
    apply_daily_status(receiver)

    sender_pocket = to_decimal(sender['pocket'])
    if sender_pocket < amount:
        await ctx.send(f"💸 Bạn không đủ xu để chuyển! Ví của bạn: {fmt_decimal(sender_pocket)}")
        return

    sender_pocket -= amount
    receiver_pocket = to_decimal(receiver['pocket']) + amount
    sender['pocket'] = str(sender_pocket)
    receiver['pocket'] = str(receiver_pocket)
    save_data()

    await ctx.send(f"✅ {ctx.author.display_name} đã chuyển {fmt_decimal(amount)} xu cho {member.display_name} 💰")
# -------------------- WORD CHAIN --------------------
# We will protect mutation with game_lock to avoid race when nhiều người nhắn gần như cùng lúc
@bot.command()
async def start(ctx):
    global game_active,last_word,used_words,player_scores,bot_turn
    if not word_list:
        await ctx.send("⚠️ Danh sách từ không có. Không thể bắt đầu trò chơi.")
        return
    async with game_lock:
        if game_active:
            await ctx.send("⚠️ Trò chơi đang diễn ra!")
            return
        game_active = True
        used_words.clear()
        player_scores.clear()
        last_word = random.choice(word_list)
        used_words.add(last_word)
        bot_turn = True
    await ctx.send(f"🎮 Trò chơi Nối từ bắt đầu! Bot đi trước: **{last_word}**")

@bot.command()
async def stop(ctx):
    global game_active
    async with game_lock:
        if not game_active:
            await ctx.send("⚠️ Không có trò chơi nào đang diễn ra.")
            return
        game_active = False
    await ctx.send("⛔ Trò chơi đã dừng.")

@bot.command()
async def score(ctx):
    async with game_lock:
        if not player_scores:
            await ctx.send("Chưa có điểm số nào.")
            return
        sorted_scores = sorted(player_scores.items(), key=lambda x:x[1], reverse=True)
        msg="🏆 **Điểm hiện tại:**\n"
        for player,score in sorted_scores:
            msg+=f"{player}: {score} điểm\n"
    await ctx.send(msg)

# -------------------- TÀI XỈU (đa người cùng lúc, theo channel) --------------------
# active_bets: channel_id -> { user_id: {'choice','amount','name'} }
active_bets = {}
countdown_tasks = {}  # channel_id -> task

# helper to get/create bet lock for a channel
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
            await ctx.send("⚠️ Vui lòng nhập một số hợp lệ.")
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
            await ctx.send("⚠️ Vui lòng chọn Tài/Xỉu/Chẵn/Lẻ hoặc số từ 3 đến 18.")
            return

        # trừ tiền ngay trong data lock
        async with data_lock:
            player = get_player(user_id)
            pocket = to_decimal(player['pocket'])
            pocket -= amount
            player['pocket'] = str(pocket)
            await async_save_data()

        # khởi tạo container bets cho channel
        if channel_id not in active_bets:
            active_bets[channel_id] = {}

        active_bets[channel_id][user_id] = {'choice':choice,'amount':amount,'name':ctx.author.display_name}
        await ctx.send(f"✅ {ctx.author.display_name} đã cược {fmt_decimal(amount)} xu vào {choice} trong {BET_TIME}s.")

        # Nếu chưa có countdown task chạy cho kênh này, khởi tạo 1 task
        if channel_id not in countdown_tasks or countdown_tasks[channel_id].done():
            countdown_tasks[channel_id] = bot.loop.create_task(countdown_and_roll(ctx.channel))

async def countdown_and_roll(channel):
    channel_id = str(channel.id)
    try:
        await channel.send(f"⏱️ Đếm ngược {BET_TIME} giây...")
        await asyncio.sleep(BET_TIME)
        # copy bets safely
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
        # xử lý từng cược
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
                player['pocket']=str(pocket)
                await async_save_data()
        await channel.send(msg)
    except Exception as e:
        print("Error in countdown_and_roll:", e)
        await channel.send("❌ Có lỗi xảy ra khi xử lý cược. Mình đã ghi log.")
    finally:
        countdown_tasks.pop(channel_id, None)

# -------------------- BOT EVENTS --------------------
@bot.event
async def on_ready():
    print(f"✅ Đăng nhập với tên {bot.user}")
    await bot.change_presence(activity=discord.Game(name=f"Sử dụng {PREFIX}help để xem lệnh"))

# -------------------- MESSAGE HANDLER --------------------
@bot.event
async def on_message(message):
    global game_active, last_word, used_words, player_scores, bot_turn

    # bỏ qua tin nhắn từ bot
    if message.author == bot.user:
        return

    # xử lý lệnh đầu tiên để giữ commands hoạt động
    await bot.process_commands(message)

    # Nếu là lệnh bot (bắt đầu bằng prefix), bỏ qua (không tính là từ nối)
    if message.content.startswith(PREFIX):
        return

    # Nếu không có game nối từ thì bỏ qua
    async with game_lock:
        if not game_active:
            return
    # tiếp tục xử lý nối từ (những phần thay đổi trạng thái game sẽ chịu lock)
    content = message.content.strip().lower()
    if not is_valid_word(content):
        return

    author = str(message.author.id)
    author_name = message.author.display_name

    async with game_lock:
        # kiểm tra lượt
        if not bot_turn:  # chỉ kiểm tra nếu tới lượt người chơi
            last_syl = last_syllable(last_word) if last_word else None
            first_syl = first_syllable(content)
            if last_syl and first_syl != last_syl:
                await message.channel.send(f"🚫 **{author_name}**, từ phải bắt đầu bằng '{last_syl}'!")
                return

        if content in used_words:
            await message.channel.send(f"⚠️ **{author_name}**, từ này đã được sử dụng!")
            return

        if content in word_list:
            used_words.add(content)
            player_scores[author_name] = player_scores.get(author_name,0)+1
            player = get_player(author)
            pocket = to_decimal(player['pocket'])
            pocket += COIN_PER_WORD
            player['pocket'] = str(pocket)
            player['exp'] +=1
            if player['exp'] >= player['level']*20:
                player['level']+=1
                player['exp']=0
                pocket+=50
                player['pocket']=str(pocket)
            await async_save_data()
            last_word = content
            await message.channel.send(f"✅ **{author_name}** đúng: '{content}' (+1 điểm, +{fmt_decimal(COIN_PER_WORD)} xu)")

            # Bot đi tiếp (tìm từ nối)
            last_syl_bot = last_syllable(last_word)
            next_words = [w for w in word_list if first_syllable(w)==last_syl_bot and w not in used_words]
            if not next_words:
                pocket += WIN_COIN
                player['pocket'] = str(pocket)
                await async_save_data()
                await message.channel.send(f"🏆 **{author_name} thắng!** +{fmt_decimal(WIN_COIN)} xu")
                # game kết thúc
                game_active = False
                if player_scores:
                    sorted_scores = sorted(player_scores.items(), key=lambda x:x[1], reverse=True)
                    msg='🏆 **Điểm cuối cùng:**\n'
                    for p,s in sorted_scores:
                        msg+=f'{p}: {s} điểm\n'
                    await message.channel.send(msg)
                return

            bot_word = random.choice(next_words)
            used_words.add(bot_word)
            last_word = bot_word
            bot_turn = False  # vẫn để False (bot vừa đi nên tới người)
            await message.channel.send(f"🤖 Bot nối từ: **{bot_word}**")
        else:
            await message.channel.send(f"❌ **{author_name}**, '{content}' không có trong từ điển.")

# -------------------- RUN BOT --------------------
if BOT_TOKEN:
    bot.run(BOT_TOKEN)
else:
    print("⚠️ BOT_TOKEN chưa được cài đặt.")

