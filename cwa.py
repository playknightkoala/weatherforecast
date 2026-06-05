#!/usr/bin/env python3
"""CWA 中央氣象署 API 存取與資料處理。

因 macOS Python 對 CWA 伺服器憑證驗證過嚴，所有 CWA 請求改用系統 curl。
提供:
  county_forecast(county)        取得單一縣市當天天氣預報 (格式化文字)
  list_counties()                22 縣市清單
  build_today_radar_gif(out)     下載當天 00:00~現在的雷達, 產生回波動畫 GIF
"""
import os
import re
import glob
import json
import subprocess
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

TZ = ZoneInfo("Asia/Taipei")
FORECAST_ID = "F-C0032-001"
RADAR_ID = "O-A0059-001"
RADAR_HOURS = 12               # 影片涵蓋最近幾小時
RADAR_FRAMES = RADAR_HOURS * 6  # 原始每10分鐘一筆 -> 12h = 72 幀

# 22 縣市 (與 F-C0032-001 一致, 使用「臺」)
COUNTIES = ['臺北市', '新北市', '桃園市', '臺中市', '臺南市', '高雄市',
            '基隆市', '新竹市', '新竹縣', '苗栗縣', '彰化縣', '南投縣',
            '雲林縣', '嘉義市', '嘉義縣', '屏東縣', '宜蘭縣', '花蓮縣',
            '臺東縣', '澎湖縣', '金門縣', '連江縣']


def get_env(key):
    """先讀環境變數 (容器), 找不到再讀同目錄 .env。"""
    if os.environ.get(key):
        return os.environ[key]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(path):
        env = dict(l.strip().split("=", 1) for l in open(path)
                   if "=" in l and not l.startswith("#"))
        return env.get(key)
    return None


def _auth():
    return get_env("authorization")


def _curl(url, binary_out=None):
    """用系統 curl 取得 URL。binary_out 給檔案路徑則存檔, 否則回傳 str。"""
    if binary_out:
        subprocess.run(["curl", "-sS", "-m", "120", "-L", url, "-o", binary_out], check=True)
        return binary_out
    r = subprocess.run(["curl", "-sS", "-m", "120", "-L", url],
                       check=True, capture_output=True)
    return r.stdout.decode("utf-8")


def today_range():
    """回傳今天 (Asia/Taipei) 的 timeFrom, timeTo 字串。"""
    now = datetime.now(TZ)
    d = now.strftime("%Y-%m-%d")
    return f"{d}T00:00:00", f"{d}T23:59:59"


def list_counties():
    return COUNTIES


def counties_menu():
    """回傳編號清單字串: 1. 臺北市\n2. 新北市 ..."""
    return "\n".join(f"{i + 1}. {c}" for i, c in enumerate(COUNTIES))


def county_by_index(n):
    """以 1 起算的編號取得縣市名, 超出範圍回傳 None。"""
    return COUNTIES[n - 1] if 1 <= n <= len(COUNTIES) else None


def normalize_county(name):
    """把使用者輸入正規化成標準縣市名, 找不到回傳 None。"""
    n = name.strip().replace("台", "臺")
    if n in COUNTIES:
        return n
    # 容許省略 縣/市
    for c in COUNTIES:
        if c.startswith(n) or c.rstrip("縣市") == n.rstrip("縣市"):
            return c
    return None


# ---------------- 天氣預報 ----------------
def county_forecast(county):
    county = normalize_county(county) or county
    tf, tt = today_range()
    auth = _auth()
    url = (f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/{FORECAST_ID}"
           f"?Authorization={auth}&timeFrom={tf}&timeTo={tt}")
    data = json.loads(_curl(url))
    locs = data["records"]["location"]
    loc = next((l for l in locs if l["locationName"] == county), None)
    if loc is None:
        return f"找不到「{county}」的預報資料。"

    # 整理成 {(start,end): {Wx,PoP,MinT,MaxT,CI}}
    segs = {}
    for we in loc["weatherElement"]:
        name = we["elementName"]
        for t in we["time"]:
            key = (t["startTime"], t["endTime"])
            segs.setdefault(key, {})[name] = t["parameter"]

    lines = [f"🌤 *{county}* 今日天氣預報"]
    for (start, end) in sorted(segs):
        s = segs[(start, end)]
        sh, eh = start[11:16], end[11:16]
        wx = s.get("Wx", {}).get("parameterName", "—")
        pop = s.get("PoP", {}).get("parameterName", "—")
        mint = s.get("MinT", {}).get("parameterName", "—")
        maxt = s.get("MaxT", {}).get("parameterName", "—")
        ci = s.get("CI", {}).get("parameterName", "")
        day = start[5:10].replace("-", "/")
        lines.append(
            f"\n🕗 {day} {sh}–{eh}\n"
            f"   {wx}\n"
            f"   🌡 {mint}–{maxt}°C   ☔ 降雨機率 {pop}%\n"
            f"   😊 {ci}")
    lines.append(f"\n_資料來源：中央氣象署 {FORECAST_ID}_")
    return "\n".join(lines)


# ---------------- 雷達回波影片 ----------------
RADAR_DPI = 150              # 輸出解析度 (越高越清晰)
RADAR_FPS = 10              # 影片每秒幀數


def _radar_metadata():
    tf, tt = today_range()
    auth = _auth()
    url = (f"https://opendata.cwa.gov.tw/historyapi/v1/getMetadata/{RADAR_ID}"
           f"?Authorization={auth}&timeFrom={tf}&timeTo={tt}")
    data = json.loads(_curl(url))
    return data["dataset"]["resources"]["resource"]["data"]["time"]


def _select_frames(times):
    """取最近 RADAR_FRAMES 幀 (每 10 分鐘一幀, 最近 RADAR_HOURS 小時)。
    當天尚未累積滿時, 就用目前所有可得的幀。"""
    return times[-RADAR_FRAMES:]


def _key(dt):
    """DateTime 字串 -> 快取鍵, 例 '2026-06-05T14:30..' -> '20260605_1430'。"""
    return dt[:16].replace("-", "").replace("T", "_").replace(":", "")


def _daykey(dt):
    return dt[:10].replace("-", "")


def _prune_other_days(cache_dir, today):
    """刪除非今日的快取檔 (跨日自動清除)。"""
    for f in (glob.glob(os.path.join(cache_dir, "rframe_*.npz"))
              + glob.glob(os.path.join(cache_dir, "rvideo_*"))):
        m = re.search(r"_(\d{8})_", os.path.basename(f))
        if m and m.group(1) != today:
            try:
                os.remove(f)
            except OSError:
                pass


def _load_or_download(sel, cache_dir):
    """逐幀取得格點: 已快取者直接讀, 未快取者才下載並寫入快取。
    回傳 (grids, dts, 新下載數)。"""
    from radar_common import parse_grid_only
    grids, dts, n_new = [], [], 0
    tmp = os.path.join(tempfile.gettempdir(), "_radar_bot.xml")
    for e in sel:
        dt = e["DateTime"]
        fp = os.path.join(cache_dir, f"rframe_{_key(dt)}.npz")
        if os.path.exists(fp):                       # 命中快取, 不重打 API
            try:
                grids.append(np.load(fp)["g"].astype(np.float32))
                dts.append(dt)
                continue
            except Exception:
                pass                                 # 快取毀損則重抓
        try:                                         # 下載缺少的幀
            _curl(e["ProductURL"], tmp)
            g, gdt = parse_grid_only(tmp)
            grids.append(g.astype(np.float32))
            dts.append(gdt)
            np.savez_compressed(fp, g=g.astype(np.float16))
            n_new += 1
        except Exception:
            continue
    if os.path.exists(tmp):
        os.remove(tmp)
    if not grids:
        raise RuntimeError("雷達資料下載失敗")
    return grids, dts, n_new


REGION_SLUG = {"全台": "all", "北部": "north", "中部": "central",
               "南部": "south", "東部": "east"}


def build_today_radar(cache_dir="radarcache", region="全台",
                      fps=RADAR_FPS, dpi=RADAR_DPI):
    """產生當天雷達回波影片, 採用逐幀快取 + 同時段影片快取。

    region: 全台 / 北部 / 中部 / 南部 / 東部, 會放大到該區域。

    - 同一時段 (最新幀時間相同) 重複呼叫: 直接回傳已產生的影片, 不下載不重算。
    - 不同時段: 只下載快取中缺少的新幀, 其餘沿用。
    - 跨日: 自動清除前一天的快取。

    回傳 (影片路徑, 幀數, 起始時間, 結束時間, 是否命中快取)。
    若系統無 ffmpeg, 自動退回 GIF。
    """
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
    import shutil
    import matplotlib.pyplot as plt
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    from radar_common import make_cmap, EXTENT, REGIONS, DBZ_BOUNDS, GRIDLABEL_STYLE

    view = REGIONS.get(region, REGIONS["全台"])
    slug = REGION_SLUG.get(region, "all")
    os.makedirs(cache_dir, exist_ok=True)
    times = _radar_metadata()
    if not times:
        raise RuntimeError("當天尚無雷達資料")
    sel = _select_frames(times)
    t0, t1 = sel[0]["DateTime"], sel[-1]["DateTime"]
    _prune_other_days(cache_dir, _daykey(t1))

    # 同時段影片快取: 鍵 = 區域 + 最新幀時間 + 幀數 (逐幀 npz 與區域無關, 跨區共用)
    ext = "mp4" if shutil.which("ffmpeg") else "gif"
    video = os.path.join(cache_dir, f"rvideo_{slug}_{_key(t1)}_{len(sel)}.{ext}")
    if os.path.exists(video):
        return video, len(sel), t0, t1, True         # 命中, 直接回傳

    grids, dts, n_new = _load_or_download(sel, cache_dir)
    out = video
    cmap, norm = make_cmap()

    # 依區域視野比例決定圖面尺寸, 減少留白
    lon_span = view[1] - view[0]
    lat_span = view[3] - view[2]
    w_geo = lon_span * float(np.cos(np.radians((view[2] + view[3]) / 2)))
    map_h = 8.0
    map_w = max(3.5, min(10.0, map_h * w_geo / lat_span))

    # 靜態底圖只建一次, 之後每幀只換資料與時間, 存高解析 PNG
    fig = plt.figure(figsize=(map_w + 2.2, map_h), dpi=dpi)
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent(view, crs=ccrs.PlateCarree())
    ax.set_facecolor("#0a1a33")
    ax.add_feature(cfeature.OCEAN.with_scale("10m"), facecolor="#0a1a33")
    ax.add_feature(cfeature.LAND.with_scale("10m"), facecolor="#2b2b2b")
    ax.add_feature(cfeature.COASTLINE.with_scale("10m"), edgecolor="white", linewidth=0.7)
    ax.add_feature(cfeature.STATES.with_scale("10m"), edgecolor="white", linewidth=0.5, alpha=0.6)
    gl = ax.gridlines(draw_labels=True, color="white", alpha=0.2, linewidth=0.4)
    gl.top_labels = gl.right_labels = False
    gl.xlabel_style = gl.ylabel_style = GRIDLABEL_STYLE      # 經緯度標籤白色
    title = "整合雷達回波圖  O-A0059-001" if region == "全台" else f"整合雷達回波圖（{region}）"
    ax.set_title(title, fontsize=13, pad=8, color="white")
    # bilinear 內插讓回波更平滑, 不再有明顯格點塊狀
    im = ax.imshow(grids[0], origin="lower", extent=EXTENT, transform=ccrs.PlateCarree(),
                   cmap=cmap, norm=norm, interpolation="bilinear", zorder=5)
    cbar = fig.colorbar(im, ax=ax, ticks=DBZ_BOUNDS, shrink=0.8, pad=0.04)
    cbar.set_label("回波強度 (dBZ)", color="white")          # 色階標題白色
    cbar.ax.tick_params(colors="white")                      # 色階刻度白色
    cbar.outline.set_edgecolor("white")
    badge = ax.text(0.015, 0.97, "", transform=ax.transAxes, fontsize=13, color="white",
                    va="top", ha="left", zorder=10,
                    bbox=dict(boxstyle="round,pad=0.3", fc="#1565C0", ec="none", alpha=0.9))

    png_dir = tempfile.mkdtemp(prefix="radarpng_")
    try:
        for i, (g, dt) in enumerate(zip(grids, dts)):
            im.set_data(g)
            badge.set_text(str(dt).replace("T", " ")[:16])
            fig.savefig(os.path.join(png_dir, f"f{i:04d}.png"),
                        dpi=dpi, facecolor="#0a1a33")  # 不用 bbox_inches=tight, 確保每幀同尺寸
        plt.close(fig)

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            # H.264 高畫質; scale 濾鏡確保寬高為偶數 (yuv420p 必要)
            cmd = [ffmpeg, "-y", "-framerate", str(fps),
                   "-i", os.path.join(png_dir, "f%04d.png"),
                   "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                   "-movflags", "+faststart", out]
            subprocess.run(cmd, check=True, capture_output=True)
        else:
            # 無 ffmpeg: 退回 GIF (out 已是 .gif)
            from PIL import Image
            frames = [Image.open(os.path.join(png_dir, f"f{i:04d}.png")).convert("P")
                      for i in range(len(grids))]
            frames[0].save(out, save_all=True, append_images=frames[1:],
                           duration=int(1000 / fps), loop=0)
    finally:
        shutil.rmtree(png_dir, ignore_errors=True)

    return out, len(grids), dts[0], dts[-1], False


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "radar":
        print(build_today_radar(sys.argv[2] if len(sys.argv) > 2 else "radarcache"))
    else:
        print(county_forecast(sys.argv[1] if len(sys.argv) > 1 else "臺北市"))
