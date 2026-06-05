#!/usr/bin/env python3
"""把 frames.npz 組成雷達回波動畫 GIF (A 版樣式)。

用法:
    python3 animate_radar.py [frames.npz] [輸出.gif] [每幀毫秒]
預設: frames.npz, radar_anim.gif, 200ms
"""
import sys
import ssl
ssl._create_default_https_context = ssl._create_unverified_context
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from radar_common import (make_cmap, EXTENT, VIEW, DBZ_BOUNDS)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "frames.npz"
    out = sys.argv[2] if len(sys.argv) > 2 else "radar_anim.gif"
    interval = int(sys.argv[3]) if len(sys.argv) > 3 else 200

    z = np.load(src, allow_pickle=True)
    grids, dts = z["grids"].astype(np.float32), z["dts"]
    n = len(grids)
    cmap, norm = make_cmap()

    fig = plt.figure(figsize=(7.5, 8.6), dpi=110)
    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.set_extent(VIEW, crs=ccrs.PlateCarree())
    ax.set_facecolor("#0a1a33")
    # 靜態底圖只畫一次
    ax.add_feature(cfeature.OCEAN.with_scale("10m"), facecolor="#0a1a33")
    ax.add_feature(cfeature.LAND.with_scale("10m"), facecolor="#2b2b2b")
    ax.add_feature(cfeature.COASTLINE.with_scale("10m"), edgecolor="white", linewidth=0.7)
    ax.add_feature(cfeature.STATES.with_scale("10m"), edgecolor="white", linewidth=0.3, alpha=0.5)
    gl = ax.gridlines(draw_labels=True, color="white", alpha=0.2, linewidth=0.4)
    gl.top_labels = gl.right_labels = False
    ax.set_title("整合雷達回波圖  O-A0059-001", fontsize=13, pad=8)

    im = ax.imshow(grids[0], origin="lower", extent=EXTENT, transform=ccrs.PlateCarree(),
                   cmap=cmap, norm=norm, interpolation="nearest", zorder=5)
    cbar = fig.colorbar(im, ax=ax, ticks=DBZ_BOUNDS, shrink=0.8, pad=0.04)
    cbar.set_label("回波強度 (dBZ)")
    badge = ax.text(0.015, 0.97, "", transform=ax.transAxes, fontsize=13, color="white",
                    va="top", ha="left", zorder=10,
                    bbox=dict(boxstyle="round,pad=0.3", fc="#1565C0", ec="none", alpha=0.9))

    def update(i):
        im.set_data(grids[i])
        badge.set_text(str(dts[i]).replace("T", " ")[:16])
        return im, badge

    anim = animation.FuncAnimation(fig, update, frames=n, interval=interval, blit=False)
    anim.save(out, writer=animation.PillowWriter(fps=max(1, 1000 // interval)))
    print(f"已輸出動畫: {out}  ({n} 幀, {dts[0]} ~ {dts[-1]})")


if __name__ == "__main__":
    main()
