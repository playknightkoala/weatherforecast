# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Telegram bot that uses Taiwan's Central Weather Administration (CWA) open data to push daily county weather forecasts and generate on-demand radar echo animations. The bot runs as a long-lived polling process. All UI text and comments are in Traditional Chinese.

## Commands

```bash
pip install -r requirements.txt
python3 weatherbot.py              # run the bot (polling, runs forever)

# Test data layers directly without Telegram (cwa.py __main__):
python3 cwa.py 臺北市               # print a county's formatted forecast
python3 cwa.py radar radarcache    # build today's radar video, print output path

# Docker (polling, no exposed ports; subscribers.json persisted to /data volume):
docker compose up -d --build
```

There is no test suite, linter, or build step. `.env` (same dir as code) must contain `authorization` (CWA token), `bot_token` (Telegram), and `chat_id`. See `.env.example`.

## Architecture

Three layers, each importing the one below:

- **`weatherbot.py`** — Telegram layer. Command handlers (`/setcounty` `/weather` `/radar` `/mycounty` `/unsubscribe` `/start`), the daily 08:00 (Asia/Taipei) push job, and a periodic cleanup job. Knows nothing about CWA internals — delegates all data/rendering to `cwa.py`.
- **`cwa.py`** — Data layer. CWA API access, forecast text formatting, and radar video assembly (orchestrates download → render → encode). Defines county list/normalization and region definitions.
- **`radar_common.py`** — Rendering primitives. XML grid parsing, the CWA dBZ color scale, fixed grid geo-metadata (`GRID_META`, `EXTENT`), per-region viewports (`REGIONS`), and cartopy frame rendering. No network or Telegram code.

### Things that will bite you

- **All CWA HTTP goes through system `curl`** (`cwa._curl`), not Python's `requests`/`urllib`. This is deliberate: macOS Python rejects the CWA server's certificate. Do not "fix" this by switching to a Python HTTP client.
- **Forecast vs. radar use different CWA API hosts.** Forecast (`F-C0032-001`) hits `opendata.cwa.gov.tw/api/v1/rest/datastore/`; radar metadata (`O-A0059-001`) hits `opendata.cwa.gov.tw/historyapi/v1/getMetadata/`. The radar product XMLs themselves are downloaded from per-frame `ProductURL`s in the metadata.
- **Radar caching is two-tiered** (`build_today_radar` + `_load_or_download`): per-frame grids cached as `rframe_<ts>.npz` (small, region-independent, reused across regions), and finished videos cached as `rvideo_<slug>_<latest-ts>_<nframes>.<ext>`. Same time window + same region → instant cache hit, no download/re-render. Cross-day cache is auto-pruned (`_prune_other_days`); `weatherbot.cleanup_job` sweeps stale files on a timer.
- **ffmpeg is optional.** With ffmpeg → H.264 MP4; without → falls back to GIF. The chosen extension flows through the video cache key.
- **County names use 臺 not 台** to match `F-C0032-001`. `normalize_county` converts user input and tolerates omitting 縣/市.
- **Access control** (`restricted` decorator + `ALLOWED_CHAT_IDS`): unlisted chat_ids are rejected before any API call. Fails *open* if the whitelist is empty (logs a warning) — don't assume the bot is locked down by default.
- **CJK fonts** are resolved at import in `radar_common.py` (macOS Arial Unicode → Linux Noto CJK). The Dockerfile installs `fonts-noto-cjk` and pre-downloads cartopy's Natural Earth 10m shapefiles to avoid runtime fetches.
- **Subscriptions** live in `subscribers.json` (`chat_id → county`), auto-created. `DATA_DIR` env var relocates it (and the radar cache) to a mounted volume in containers.

### Standalone scripts (not part of the bot)

`plot_radar.py`, `download_radar.py`, `animate_radar.py` are earlier exploration scripts for single-frame plots and offline animations. They're independent of the bot and safe to ignore for bot work.
