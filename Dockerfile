FROM python:3.10-slim

# 必要な依存パッケージのインストール
RUN apt-get update && apt-get install -y \
    unzip curl gnupg ca-certificates fonts-liberation \
    libnss3 libgconf-2-4 libxi6 libxcursor1 libxcomposite1 libasound2 \
    libxrandr2 libxdamage1 libxtst6 libatk-bridge2.0-0 libgtk-3-0 \
    chromium chromium-driver xvfb && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 環境変数設定（Selenium用）
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_BIN=/usr/lib/chromium/chromedriver
ENV PATH="$PATH:/usr/lib/chromium/"

# 作業ディレクトリの設定
WORKDIR /app
COPY . /app

# Pythonパッケージのインストール
RUN pip install --no-cache-dir -r requirements.txt

# ポート指定（Cloud Runのデフォルト）
EXPOSE 8080

# アプリケーション起動コマンド
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "main:app"]
