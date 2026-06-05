#!/usr/bin/env python3
"""從索引 JSON 下載最近 N 筆 O-A0059-001 雷達資料，解析後存成壓縮 .npz。

用法:
    python3 download_radar.py [索引JSON] [筆數N] [輸出.npz]
預設: response_1780641647882.json, 36 (=最近6小時), frames.npz

每筆原始 XML ~9MB，只暫存到 /tmp 解析後即刪除；最終 .npz 只存格點(float16)+時間。
"""
import sys
import json
import subprocess
import tempfile
import os
import numpy as np
from radar_common import parse_grid_only, GRID_META


def download(url, dst):
    subprocess.run(["curl", "-sS", "-m", "120", "-L", url, "-o", dst],
                   check=True)


def main():
    idx = sys.argv[1] if len(sys.argv) > 1 else "response_1780641647882.json"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 36
    out = sys.argv[3] if len(sys.argv) > 3 else "frames.npz"

    times = json.load(open(idx))["dataset"]["resources"]["resource"]["data"]["time"]
    sel = times[-n:]
    print(f"準備下載最近 {len(sel)} 筆: {sel[0]['DateTime']} ~ {sel[-1]['DateTime']}")

    grids, dts = [], []
    tmp = os.path.join(tempfile.gettempdir(), "_radar_tmp.xml")
    for i, e in enumerate(sel, 1):
        try:
            download(e["ProductURL"], tmp)
            g, dt = parse_grid_only(tmp)
            grids.append(g.astype(np.float16))
            dts.append(dt)
            mx = np.nanmax(g)
            print(f"  [{i}/{len(sel)}] {dt}  最大 {mx:.1f} dBZ")
        except Exception as ex:
            print(f"  [{i}/{len(sel)}] {e['DateTime']} 失敗: {ex}")
    if os.path.exists(tmp):
        os.remove(tmp)

    np.savez_compressed(out, grids=np.stack(grids), dts=np.array(dts))
    sz = os.path.getsize(out) / 1e6
    print(f"已存 {out}  ({len(grids)} 幀, {sz:.1f} MB)")


if __name__ == "__main__":
    main()
