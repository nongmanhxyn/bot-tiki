import os
import time
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# Load file .env nếu chạy ở máy local (trên Render/VPS thì nó tự đọc từ Environment Variables)
load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
TARGET_CHANNEL_ID = 1566724665265619005

# 3 bucket lưu trữ tối ưu
ban_1h = {}        # Key: user_id, Value: {"guild_id": 123, "hours_left": 168}
ban_15m = {}       # Key: user_id, Value: {"guild_id": 123, "minutes_left": 60}
ban_sub_15m = {}   # Key: user_id, Value: {"guild_id": 123, "unban_timestamp": 1700000000}

# Listrate theo dõi số lần ban trong 3 tháng
listrate = {}
THREE_MONTHS_SECONDS = 90 * 24 * 3600

@bot.event
async def on_ready():
    print(f"Bot đã online: {bot.user}")
    hourly_check.start()
    fifteen_min_check.start()
    sub_15m_check.start()

@bot.event
async def on_message(message):
    if message.author == bot.user or not message.guild:
        return

    if message.channel.id == TARGET_CHANNEL_ID:
        user = message.author
        guild = message.guild
        user_id = user.id
        now = time.time()

        # Quản lý listrate (3 tháng)
        if user_id in listrate:
            if now - listrate[user_id]["last_ban_time"] > THREE_MONTHS_SECONDS:
                listrate[user_id] = {"name": str(user), "count": 1, "last_ban_time": now}
            else:
                listrate[user_id]["count"] += 1
                listrate[user_id]["last_ban_time"] = now
                listrate[user_id]["name"] = str(user)
        else:
            listrate[user_id] = {"name": str(user), "count": 1, "last_ban_time": now}

        current_count = listrate[user_id]["count"]

        try:
            # Kiểm tra tái phạm >= 3 lần thì ban vĩnh viễn
            if current_count >= 3:
                await guild.ban(user, reason="Vi phạm quá 3 lần trong 3 tháng (Ban vĩnh viễn)", delete_message_days=0)
                print(f"Đã BAN VĨNH VIỄN {user} do vi phạm lần thứ {current_count}.")
                return

            # Ban tạm thời 7 ngày
            await guild.ban(user, reason=f"Nhắn tin vào channel cấm (Lần {current_count}/3)", delete_message_days=0)
            
            ban_1h[user_id] = {
                "guild_id": guild.id,
                "hours_left": 168
            }
            print(f"Đã ban {user} 7 ngày. Tổng số lần vi phạm trong 3 tháng: {current_count}")

        except discord.Forbidden:
            print(f"Không đủ quyền ban {user}")
        except Exception as e:
            print(f"Lỗi khi ban: {e}")

    await bot.process_commands(message)

# Task 1: Check mỗi 1 giờ
@tasks.loop(hours=1.0)
async def hourly_check():
    now = time.time()
    
    expired_rate_users = []
    for uid, data in listrate.items():
        if now - data["last_ban_time"] > THREE_MONTHS_SECONDS:
            expired_rate_users.append(uid)
    for uid in expired_rate_users:
        del listrate[uid]

    users_to_move = []
    for user_id, info in ban_1h.items():
        info["hours_left"] -= 1
        if info["hours_left"] <= 1:
            users_to_move.append(user_id)
            ban_15m[user_id] = {
                "guild_id": info["guild_id"],
                "minutes_left": max(info["hours_left"] * 60, 60)
            }

    for uid in users_to_move:
        del ban_1h[uid]

# Task 2: Check mỗi 15 phút
@tasks.loop(minutes=15.0)
async def fifteen_min_check():
    now = time.time()
    users_to_final = []

    for user_id, info in ban_15m.items():
        info["minutes_left"] -= 15
        if info["minutes_left"] <= 15:
            users_to_final.append(user_id)
            ban_sub_15m[user_id] = {
                "guild_id": info["guild_id"],
                "unban_timestamp": now + (max(info["minutes_left"], 0) * 60)
            }

    for uid in users_to_final:
        if uid in ban_15m:
            del ban_15m[uid]

# Task 3: Check mỗi 30 giây để unban
@tasks.loop(seconds=30.0)
async def sub_15m_check():
    now = time.time()
    unbanned_users = []

    for user_id, info in list(ban_sub_15m.items()):
        if now >= info["unban_timestamp"]:
            guild = bot.get_guild(info["guild_id"])
            if guild:
                try:
                    user = await bot.fetch_user(user_id)
                    await guild.unban(user, reason="Hết hạn ban 7 ngày")
                    print(f"Đã unban thành công cho {user} (ID: {user_id})")
                except Exception as e:
                    print(f"Lỗi khi unban user {user_id}: {e}")
            
            unbanned_users.append(user_id)

    for uid in unbanned_users:
        if uid in ban_sub_15m:
            del ban_sub_15m[uid]

@hourly_check.before_loop
@fifteen_min_check.before_loop
@sub_15m_check.before_loop
async def before_loops():
    await bot.wait_until_ready()

# Lấy token an toàn từ biến môi trường (Environment Variable)
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("Không tìm thấy biến môi trường DISCORD_TOKEN! Hãy kiểm tra lại.")

bot.run(TOKEN)
