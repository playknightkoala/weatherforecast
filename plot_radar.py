#!/usr/bin/env python3
"""
繪製 CWA 整合雷達回波圖 (資料代碼 O-A0059-001 / 雷達合成回波)。

用法:
    python3 plot_radar.py <product.xml> [輸出.png]

輸入檔為單一時刻的雷達產品 XML (從 response_*.json 裡的 ProductURL 下載而得)。
"""
import sys
import re
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm


def parse_product(path):
    xml = open(path, encoding="utf-8").read()

    def grab(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
        return m.group(1).strip() if m else None

    lon0 = float(grab("StartPointLongitude"))
    lat0 = float(grab("StartPointLatitude"))
    res = float(grab("GridResolution"))
    nx = int(grab("GridDimensionX"))
    ny = int(grab("GridDimensionY"))
    dt = grab("DateTime")

    content = grab("content")
    vals = np.fromstring(content, sep=",", dtype=np.float32)
    grid = vals.reshape(ny, nx)  # 先由西向東(x)、再由南往北(y) -> row=y

    # 無效值 -99、範圍外 -999 設為 NaN
    grid = np.where(grid <= -90, np.nan, grid)

    lons = lon0 + np.arange(nx) * res
    lats = lat0 + np.arange(ny) * res
    return dict(grid=grid, lons=lons, lats=lats, dt=dt, nx=nx, ny=ny)


# CWA 標準 dBZ 色階 (0~65 dBZ)
DBZ_BOUNDS = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70]
DBZ_COLORS = [
    "#00FFFF", "#00ECFF", "#00A0FF", "#0000FF", "#00FF00",
    "#00C800", "#009000", "#FFFF00", "#FFC800", "#FF9000",
    "#FF0000", "#D60000", "#C00000", "#FF00FF",
]


def plot(d, out):
    cmap = ListedColormap(DBZ_COLORS)
    cmap.set_under((0, 0, 0, 0))  # 0 dBZ 以下透明
    norm = BoundaryNorm(DBZ_BOUNDS, cmap.N)

    fig, ax = plt.subplots(figsize=(10, 9.6), dpi=120)
    ax.set_facecolor("#0a1a33")
    extent = [d["lons"][0], d["lons"][-1], d["lats"][0], d["lats"][-1]]
    im = ax.imshow(d["grid"], origin="lower", extent=extent,
                   cmap=cmap, norm=norm, interpolation="nearest")

    ax.set_xlabel("經度 Longitude (°E)")
    ax.set_ylabel("緯度 Latitude (°N)")
    ax.set_title(f"整合雷達回波圖  O-A0059-001\n{d['dt']}", fontsize=12)
    ax.grid(True, color="white", alpha=0.15, linewidth=0.5)

    cbar = fig.colorbar(im, ax=ax, ticks=DBZ_BOUNDS, shrink=0.85, pad=0.02)
    cbar.set_label("回波強度 Reflectivity (dBZ)")

    fig.tight_layout()
    fig.savefig(out, dpi=120, facecolor="#0a1a33")
    print(f"已輸出: {out}  (grid {d['nx']}x{d['ny']}, 時間 {d['dt']})")
    valid = np.isfinite(d["grid"])
    print(f"有效格點: {valid.sum():,} / {d['grid'].size:,}  "
          f"最大回波 {np.nanmax(d['grid']):.1f} dBZ")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/product.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "radar_echo.png"
    plot(parse_product(src), out)
