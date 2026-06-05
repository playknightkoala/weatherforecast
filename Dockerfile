FROM python:3.12-slim

# 系統相依: curl(抓CWA/圖資)、geos/proj(cartopy)、Noto CJK 字型(中文)、ca憑證
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl unzip ca-certificates ffmpeg \
        build-essential g++ pkg-config \
        libgeos-dev libproj-dev proj-bin proj-data \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先裝相依 (利用快取)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 預先下載 cartopy 海岸線/縣市界圖資 (Natural Earth 10m)，避免執行期下載
ENV CARTOPY_DIR=/root/.local/share/cartopy
RUN set -e; \
    B="$CARTOPY_DIR/shapefiles/natural_earth"; \
    mkdir -p "$B/physical" "$B/cultural"; \
    for spec in \
        "physical:coastline:physical" \
        "physical:land:physical" \
        "physical:ocean:physical" \
        "cultural:admin_1_states_provinces_lines:cultural" \
        "cultural:admin_0_boundary_lines_land:cultural"; do \
        cat=$(echo $spec | cut -d: -f1); name=$(echo $spec | cut -d: -f2); sub=$(echo $spec | cut -d: -f3); \
        curl -sSL "https://naturalearth.s3.amazonaws.com/10m_${cat}/ne_10m_${name}.zip" -o /tmp/z.zip; \
        unzip -o -q /tmp/z.zip -d "$B/$sub"; \
    done; \
    rm -f /tmp/z.zip

# 應用程式碼
COPY radar_common.py cwa.py weatherbot.py ./

# 訂閱資料持久化目錄
ENV DATA_DIR=/data
RUN mkdir -p /data
VOLUME ["/data"]

CMD ["python", "weatherbot.py"]
