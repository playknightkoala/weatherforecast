#!/usr/bin/env python3
"""天氣 Telegram 機器人。

功能:
  • 每天早上 08:00 (台北時間) 自動推送訂閱者所在縣市的當天天氣預報
  • /setcounty [編號]   無參數顯示縣市清單; 帶數字依編號設定所在縣市
  • /weather            立即取得所在縣市當天預報
  • /radar              取得當天 00:00 ~ 現在的雷達回波動畫 GIF
  • /mycounty /unsubscribe /start
  • 啟動時設定 Telegram 指令選單 (漢堡); 定期清除產生的檔案

設定來自環境變數或同目錄 .env: bot_token, chat_id, authorization
"""
import os
import glob
import json
import time
import asyncio
import logging
import functools
from datetime import time as dtime

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.error import TimedOut
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          ContextTypes)

import cwa

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("weatherbot")

HERE = os.path.dirname(os.path.abspath(__file__))
# 訂閱資料存放目錄 (容器可用 DATA_DIR 指向掛載的 volume)
DATA_DIR = os.environ.get("DATA_DIR", HERE)
SUBS_FILE = os.path.join(DATA_DIR, "subscribers.json")
# 雷達快取目錄 (逐幀 npz + 成品影片), 會被定期清除
RADAR_CACHE_DIR = os.path.join(DATA_DIR, "radarcache")
os.makedirs(RADAR_CACHE_DIR, exist_ok=True)
# 清理設定: 每隔幾小時掃一次, 刪除超過幾小時的產生檔
CLEAN_EVERY_HOURS = 6
CLEAN_AGE_HOURS = 6


def load_env():
    """先讀環境變數 (容器), 缺的再從 .env 補。"""
    env = {}
    path = os.path.join(HERE, ".env")
    if os.path.exists(path):
        env = dict(l.strip().split("=", 1) for l in open(path)
                   if "=" in l and not l.startswith("#"))
    for k in ("bot_token", "chat_id", "authorization"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


# ---------- 存取控制 (白名單) ----------
# 只有名單內的 chat_id 能使用; 其他人一律拒絕, 完全不觸發任何 API。
ALLOWED_CHAT_IDS = set()


def load_allowed(env):
    ids = set()
    if env.get("chat_id"):
        ids.add(str(env["chat_id"]).strip())
    # 可選多人: 從 .env 檔或環境變數讀 ALLOWED_CHAT_IDS (逗號分隔)
    raw = env.get("ALLOWED_CHAT_IDS") or os.environ.get("ALLOWED_CHAT_IDS", "")
    for x in raw.split(","):
        if x.strip():
            ids.add(x.strip())
    return ids


def restricted(func):
    """裝飾器: 擋下不在白名單的使用者。白名單為空時 fail-open (避免鎖死)。"""
    @functools.wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE, *a, **k):
        uid = str(update.effective_chat.id) if update.effective_chat else None
        if ALLOWED_CHAT_IDS and uid not in ALLOWED_CHAT_IDS:
            log.warning("blocked unauthorized chat_id=%s", uid)
            if update.callback_query:
                await update.callback_query.answer("⛔ 未授權", show_alert=True)
            elif update.message:
                await update.message.reply_text("⛔ 你沒有使用此機器人的權限。")
            return
        return await func(update, ctx, *a, **k)
    return wrapper


# ---------- 訂閱者儲存 (chat_id -> 縣市) ----------
def load_subs():
    if os.path.exists(SUBS_FILE):
        return json.load(open(SUBS_FILE, encoding="utf-8"))
    return {}


def save_subs(subs):
    json.dump(subs, open(SUBS_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


# ---------- 指令 ----------
HELP = (
    "🤖 *天氣機器人*\n\n"
    "/setcounty — 顯示縣市清單；`/setcounty 1` 即設定為第 1 個縣市，"
    "設定後每天早上 8 點自動推播當天預報\n"
    "/weather — 立即查詢你所在縣市的當天預報\n"
    "/radar — 雷達回波動畫；可選全台或北/中/南/東部區域 (亦可 `/radar 北部`)\n"
    "/mycounty — 查看目前設定的縣市\n"
    "/unsubscribe — 取消每日推播\n")


@restricted
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_markdown(HELP)


@restricted
async def cmd_setcounty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # 無參數: 顯示編號清單
    if not ctx.args:
        await update.message.reply_text(
            "請選擇你所在的縣市，輸入對應數字，例如 `/setcounty 1`：\n\n"
            + cwa.counties_menu(),
            parse_mode="Markdown")
        return

    arg = "".join(ctx.args).strip()
    county = None
    if arg.isdigit():                       # 數字 -> 依編號
        county = cwa.county_by_index(int(arg))
    if county is None:                      # 也容許直接打縣市名
        county = cwa.normalize_county(arg)
    if not county:
        await update.message.reply_text(
            "輸入無效，請輸入清單中的數字，例如 `/setcounty 1`：\n\n"
            + cwa.counties_menu(),
            parse_mode="Markdown")
        return

    subs = load_subs()
    subs[str(update.effective_chat.id)] = county
    save_subs(subs)
    await update.message.reply_text(
        f"✅ 已將你的縣市設定為「{county}」，每天早上 8 點會自動推播當天預報。\n"
        f"可用 /weather 立即查看。")


@restricted
async def cmd_mycounty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    c = load_subs().get(str(update.effective_chat.id))
    await update.message.reply_text(
        f"你目前設定的縣市是「{c}」。" if c else "你尚未設定縣市，請用 /setcounty <縣市>。")


@restricted
async def cmd_unsubscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    subs = load_subs()
    if subs.pop(str(update.effective_chat.id), None):
        save_subs(subs)
        await update.message.reply_text("已取消每日推播。")
    else:
        await update.message.reply_text("你原本就沒有訂閱。")


@restricted
async def cmd_weather(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    c = load_subs().get(str(update.effective_chat.id))
    if not c:
        await update.message.reply_text("請先用 /setcounty <縣市> 設定縣市。")
        return
    await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    text = await asyncio.to_thread(cwa.county_forecast, c)
    await update.message.reply_markdown(text)


async def _send_radar(ctx, chat_id, region):
    """產生並傳送指定區域的雷達回波影片。"""
    await ctx.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
    try:
        sent, n, t0, t1, cached = await asyncio.to_thread(
            cwa.build_today_radar, RADAR_CACHE_DIR, region)
        log.info("radar %s %s (%d 幀, cached=%s)", region, t1, n, cached)
        caption = f"📡 {region}雷達回波 {t0[5:16].replace('T',' ')} ~ {t1[11:16]}（{n} 幀）"
        tmo = dict(read_timeout=300, write_timeout=300, connect_timeout=30, pool_timeout=60)
        with open(sent, "rb") as f:
            try:
                if sent.endswith(".mp4"):
                    await ctx.bot.send_video(chat_id, f, caption=caption,
                                             supports_streaming=True, **tmo)
                else:                               # 無 ffmpeg 退回 GIF
                    await ctx.bot.send_animation(chat_id, f, caption=caption, **tmo)
            except TimedOut:
                # client 等回應逾時, 但檔案通常已送達; 不自動重傳以免重複
                log.warning("send timed out (影片可能已送達): %s", sent)
                await ctx.bot.send_message(
                    chat_id, "⚠️ 影片上傳等待回應逾時，但通常已送達；若未收到請再點一次。")
    except Exception as e:
        log.exception("radar failed")
        await ctx.bot.send_message(chat_id, f"產生雷達動畫失敗：{e}")


def _region_keyboard():
    """區域選擇按鈕: 全台一排, 北中 / 南東 各一排。"""
    rows = [[InlineKeyboardButton("🌏 全台", callback_data="radar:全台")],
            [InlineKeyboardButton("北部", callback_data="radar:北部"),
             InlineKeyboardButton("中部", callback_data="radar:中部")],
            [InlineKeyboardButton("南部", callback_data="radar:南部"),
             InlineKeyboardButton("東部", callback_data="radar:東部")]]
    return InlineKeyboardMarkup(rows)


@restricted
async def cmd_radar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    arg = "".join(ctx.args).strip() if ctx.args else ""
    if arg in cwa.REGION_SLUG:                      # /radar 北部 直接產生
        await update.message.reply_text(f"⏳ 正在產生「{arg}」雷達回波動畫，請稍候…")
        await _send_radar(ctx, chat_id, arg)
        return
    # 否則顯示區域選擇按鈕
    await update.message.reply_text("請選擇要看的雷達回波區域：",
                                    reply_markup=_region_keyboard())


@restricted
async def on_radar_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    region = q.data.split(":", 1)[1]
    await q.edit_message_text(f"⏳ 正在產生「{region}」雷達回波動畫，請稍候…")
    await _send_radar(ctx, q.message.chat_id, region)


# ---------- 每日 08:00 推播 ----------
async def daily_push(ctx: ContextTypes.DEFAULT_TYPE):
    subs = load_subs()
    log.info("daily_push to %d subscribers", len(subs))
    for chat_id, county in subs.items():
        try:
            text = await asyncio.to_thread(cwa.county_forecast, county)
            await ctx.bot.send_message(chat_id, "☀️ *早安！今日天氣預報*\n\n" + text,
                                       parse_mode="Markdown")
        except Exception:
            log.exception("push failed for %s", chat_id)


# ---------- 定期清除產生的資料 ----------
def _sweep_old_files():
    """成品影片較大且每 10 分鐘即過期, 超過 CLEAN_AGE_HOURS 就刪;
    逐幀 npz 很小且在 12 小時滾動視窗內可重用 (過期者另由 cwa._prune_expired
    依資料時間精準清除, 這裡只是 mtime 後援, 清掉長期未碰的孤兒檔)。"""
    now = time.time()
    removed = 0
    rules = [                                   # (glob, 最大保留小時)
        (os.path.join(RADAR_CACHE_DIR, "rvideo_*"), CLEAN_AGE_HOURS),
        (os.path.join(HERE, "radar_today*"), CLEAN_AGE_HOURS),
        (os.path.join(RADAR_CACHE_DIR, "rframe_*.npz"), cwa.RADAR_HOURS),
        (os.path.join(RADAR_CACHE_DIR, "rpng_*.png"), cwa.RADAR_HOURS),
    ]
    for pat, age_h in rules:
        cutoff = now - age_h * 3600
        for f in glob.glob(pat):
            try:
                if os.path.isfile(f) and os.path.getmtime(f) < cutoff:
                    os.remove(f)
                    removed += 1
            except OSError:
                pass
    return removed


async def cleanup_job(ctx: ContextTypes.DEFAULT_TYPE):
    removed = await asyncio.to_thread(_sweep_old_files)
    if removed:
        log.info("cleanup removed %d stale file(s)", removed)


# ---------- 啟動時設定指令選單 (漢堡選單) ----------
async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("setcounty", "設定所在縣市 (顯示清單)"),
        BotCommand("weather", "查詢今日天氣預報"),
        BotCommand("radar", "雷達回波動畫 (可選區域)"),
        BotCommand("mycounty", "查看目前設定的縣市"),
        BotCommand("unsubscribe", "取消每日推播"),
        BotCommand("start", "顯示使用說明"),
    ])
    log.info("已設定 Telegram 指令選單")


def main():
    env = load_env()
    ALLOWED_CHAT_IDS.update(load_allowed(env))
    if ALLOWED_CHAT_IDS:
        log.info("存取控制啟用, 白名單 chat_id: %s", ", ".join(sorted(ALLOWED_CHAT_IDS)))
    else:
        log.warning("未設定 chat_id / ALLOWED_CHAT_IDS, 機器人對所有人開放!")
    app = (Application.builder().token(env["bot_token"])
           .post_init(post_init)
           .read_timeout(60).write_timeout(300)
           .connect_timeout(30).pool_timeout(60)
           .media_write_timeout(300)
           .build())

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("setcounty", cmd_setcounty))
    app.add_handler(CommandHandler("mycounty", cmd_mycounty))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("weather", cmd_weather))
    app.add_handler(CommandHandler("radar", cmd_radar))
    app.add_handler(CallbackQueryHandler(on_radar_button, pattern="^radar:"))

    # 每天 08:00 (Asia/Taipei) 推播
    app.job_queue.run_daily(daily_push, time=dtime(8, 0, tzinfo=cwa.TZ),
                            name="daily_push")
    # 定期清除產生的檔案 (啟動後 1 分鐘先掃一次, 之後每 CLEAN_EVERY_HOURS 小時)
    app.job_queue.run_repeating(cleanup_job, interval=CLEAN_EVERY_HOURS * 3600,
                                first=60, name="cleanup")

    log.info("Bot 啟動，每日推播 08:00、每 %dh 清除產生檔", CLEAN_EVERY_HOURS)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
