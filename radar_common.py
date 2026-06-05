#!/usr/bin/env python3
"""CWA 整合雷達回波圖 (O-A0059-001) 共用繪圖模組。

提供:
  parse_product(path)      解析單一時刻 XML -> dict(grid, lons, lats, dt, nx, ny)
  parse_grid_only(path)    只回傳 (grid, dt)，給批次下載用
  make_cmap()              CWA 標準 dBZ 色階 (cmap, norm)
  render_frame(ax, ...)    在給定 axes 上畫一張帶海岸線/縣市界的回波圖 (A 版樣式)
  GRID_META                格點地理資訊 (固定)
"""
import re
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import ListedColormap, BoundaryNorm
import cartopy.crs as ccrs
import cartopy.feature as cfeature

# ---- 中文字型 (macOS 用 Arial Unicode, Linux/容器用 Noto CJK) ----
import glob as _glob
_CJK_CANDIDATES = [
    "/Library/Fonts/Arial Unicode.ttf",                                  # macOS
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",            # Debian fonts-noto-cjk
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
] + _glob.glob("/usr/share/fonts/**/NotoSansCJK*", recursive=True)
for _f in _CJK_CANDIDATES:
    try:
        font_manager.fontManager.addfont(_f)
        plt.rcParams["font.sans-serif"] = [font_manager.FontProperties(fname=_f).get_name()]
        plt.rcParams["axes.unicode_minus"] = False
        break
    except Exception:
        continue

# ---- 深色背景下所有文字一律白色 ----
plt.rcParams.update({
    "text.color": "white",
    "axes.labelcolor": "white",
    "axes.titlecolor": "white",
    "xtick.color": "white",
    "ytick.color": "white",
})
GRIDLABEL_STYLE = {"color": "white"}

# ---- 格點地理資訊 (O-A0059-001 固定規格) ----
GRID_META = dict(lon0=115.0, lat0=18.0, res=0.0125, nx=921, ny=881)
LONS = GRID_META["lon0"] + np.arange(GRID_META["nx"]) * GRID_META["res"]
LATS = GRID_META["lat0"] + np.arange(GRID_META["ny"]) * GRID_META["res"]
EXTENT = [LONS[0], LONS[-1], LATS[0], LATS[-1]]
# 視野: 涵蓋台灣周邊雷達範圍 (含中國沿海、巴士海峽、與那國島), 與 CWA 合成回波圖相近
# [西經, 東經, 南緯, 北緯]
VIEW = [117.3, 124.8, 20.0, 26.8]

# 各區域視野 (放大到該區域並含周邊海域)
REGIONS = {
    "全台": VIEW,
    "北部": [120.4, 122.5, 24.2, 25.6],   # 北北基桃竹宜北段
    "中部": [119.7, 121.8, 23.2, 24.9],   # 苗中彰投雲
    "南部": [119.5, 121.8, 21.6, 23.6],   # 嘉南高屏
    "東部": [120.8, 123.2, 22.0, 25.3],   # 宜花東
}
REGION_ORDER = ["全台", "北部", "中部", "南部", "東部"]

# ---- CWA 標準 dBZ 色階 ----
DBZ_BOUNDS = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70]
DBZ_COLORS = [
    "#00FFFF", "#00ECFF", "#00A0FF", "#0000FF", "#00FF00",
    "#00C800", "#009000", "#FFFF00", "#FFC800", "#FF9000",
    "#FF0000", "#D60000", "#C00000", "#FF00FF",
]


def make_cmap():
    cmap = ListedColormap(DBZ_COLORS)
    cmap.set_under((0, 0, 0, 0))            # <0 dBZ 透明
    norm = BoundaryNorm(DBZ_BOUNDS, cmap.N)
    return cmap, norm


def parse_grid_only(path):
    xml = open(path, encoding="utf-8").read()
    dt = re.search(r"<DateTime>(.*?)</DateTime>", xml, re.S).group(1).strip()
    content = re.search(r"<content>(.*?)</content>", xml, re.S).group(1).strip()
    vals = np.fromstring(content, sep=",", dtype=np.float32)
    grid = vals.reshape(GRID_META["ny"], GRID_META["nx"])
    grid = np.where(grid <= -90, np.nan, grid)
    return grid, dt


def parse_product(path):
    grid, dt = parse_grid_only(path)
    return dict(grid=grid, lons=LONS, lats=LATS, dt=dt,
                nx=GRID_META["nx"], ny=GRID_META["ny"])


def render_frame(ax, grid, dt, cmap, norm, title="整合雷達回波圖  O-A0059-001"):
    """在 cartopy GeoAxes 上畫一張 A 版回波圖。回傳 imshow 物件。"""
    ax.set_extent(VIEW, crs=ccrs.PlateCarree())
    ax.set_facecolor("#0a1a33")
    # 海陸底色 + 海岸線 + 縣市界
    ax.add_feature(cfeature.OCEAN.with_scale("10m"), facecolor="#0a1a33")
    ax.add_feature(cfeature.LAND.with_scale("10m"), facecolor="#2b2b2b")
    ax.add_feature(cfeature.COASTLINE.with_scale("10m"), edgecolor="white", linewidth=0.7)
    ax.add_feature(cfeature.STATES.with_scale("10m"), edgecolor="white",
                   linewidth=0.3, alpha=0.5)
    im = ax.imshow(grid, origin="lower", extent=EXTENT, transform=ccrs.PlateCarree(),
                   cmap=cmap, norm=norm, interpolation="nearest", zorder=5)
    # 經緯網格
    gl = ax.gridlines(draw_labels=True, color="white", alpha=0.2, linewidth=0.4)
    gl.top_labels = gl.right_labels = False
    gl.xlabel_style = gl.ylabel_style = GRIDLABEL_STYLE
    # 時間標記
    ax.set_title(title, fontsize=13, pad=8)
    ax.text(0.015, 0.97, dt.replace("T", " ")[:16], transform=ax.transAxes,
            fontsize=13, color="white", va="top", ha="left", zorder=10,
            bbox=dict(boxstyle="round,pad=0.3", fc="#1565C0", ec="none", alpha=0.9))
    return im
