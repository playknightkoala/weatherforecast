# 天氣 Telegram 機器人

使用中央氣象署（CWA）開放資料的 Telegram 機器人：每日推播縣市天氣預報，並可隨選產生當天雷達回波動畫。

## 功能

| 指令 | 說明 |
|------|------|
| `/setcounty <縣市>` | 設定所在縣市（例 `/setcounty 臺北市`），設定後每天 **08:00** 自動推播當天預報 |
| `/weather` | 立即查詢所在縣市的當天預報 |
| `/radar` | 雷達回波動畫（最近 12 小時、每 10 分鐘一幀、fps 10、高畫質 MP4）。會跳出按鈕選 **全台／北部／中部／南部／東部**（各區放大），也可直接 `/radar 北部`。逐幀快取、同時段秒回 |
| `/mycounty` | 查看目前設定的縣市 |
| `/counties` | 列出 22 個可設定縣市 |
| `/unsubscribe` | 取消每日推播 |
| `/start`、`/help` | 顯示說明 |

## 設定

`.env`（與程式同目錄）需含：

```
authorization=<CWA API Token>
bot_token=<Telegram Bot Token>
chat_id=<預設聊天室 ID（目前未強制使用）>
```

## 安裝與執行

```bash
pip install -r requirements.txt
python3 weatherbot.py
```

機器人會持續執行（polling）。每日 08:00（Asia/Taipei）對所有已用 `/setcounty` 設定縣市的使用者推播當天預報。
建議用 `nohup`、`screen`、`tmux` 或 `launchd`/`systemd` 常駐。

## 資料來源

- 天氣預報：`F-C0032-001`（今明 36 小時各縣市天氣預報）
- 雷達回波：`O-A0059-001`（整合雷達回波，每 10 分鐘一筆）

## 檔案結構

| 檔案 | 用途 |
|------|------|
| `weatherbot.py` | 機器人主程式（指令 + 每日排程） |
| `cwa.py` | CWA API 存取、預報格式化、雷達 GIF 產生 |
| `radar_common.py` | 雷達格點解析、dBZ 配色、底圖渲染（cartopy） |
| `subscribers.json` | 訂閱者資料（chat_id → 縣市，自動產生） |

> 說明：因 macOS Python 對 CWA 伺服器憑證驗證過嚴，CWA 請求一律透過系統 `curl` 發出。
> cartopy 海岸線/縣市界圖資（Natural Earth 10m）已下載至 `~/.local/share/cartopy/`。

## 其他工具腳本（雷達資料探索用）

`plot_radar.py`、`download_radar.py`、`animate_radar.py` 為先前用來測試單張回波圖與離線動畫的腳本，與機器人功能獨立。
