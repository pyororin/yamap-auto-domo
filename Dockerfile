# ベースイメージとして、Google Cloud Functions の Python ランタイムに合わせるか、
# 公式の Python イメージを使用します。ここでは公式 Python イメージを使い、必要なものを追加します。
FROM python:3.10-slim

# Google Chrome と ChromeDriver のインストールに必要なパッケージ
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    xvfb \
    libxi6 \
    libgconf-2-4 \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    fonts-liberation \
    # ChromeDriverのバージョンに合わせたChromeのバージョンをインストールすることが重要
    # 最新版のChromeをインストールする例:
    && curl -sSL https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# ChromeDriver のインストール
# ChromeDriver のバージョンは、インストールされた Chrome のバージョンに合わせて調整してください。
# https://googlechromelabs.github.io/chrome-for-testing/ でバージョン確認可能
ARG CHROME_DRIVER_VERSION=120.0.6099.109 # 例。実際のChromeバージョンに合わせてください
RUN curl -sSLo /tmp/chromedriver_linux64.zip https://storage.googleapis.com/chrome-for-testing-public/${CHROME_DRIVER_VERSION}/linux64/chromedriver-linux64.zip \
    && unzip /tmp/chromedriver_linux64.zip -d /usr/local/bin/ \
    && rm /tmp/chromedriver_linux64.zip \
    && mv /usr/local/bin/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver \
    && chmod +x /usr/local/bin/chromedriver \
    && rmdir /usr/local/bin/chromedriver-linux64

# 作業ディレクトリの設定
WORKDIR /app

# 依存関係ファイルのコピーとインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードのコピー
COPY . .

# Cloud Functions の場合、CMD や EXPOSE は通常不要です。
# Google Cloud Functions は、デプロイ時に指定されたエントリーポイント（例: main.run_yamap_auto_domo_function）を
# 直接呼び出します。
# EXPOSE 8080
# CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers=1", "main:app"]

# 環境変数 (オプション、必要に応じて設定)
# 例: ENV GOOGLE_APPLICATION_CREDENTIALS /app/credentials.json
ENV PYTHONUNBUFFERED TRUE

# main.py 内の関数が呼び出されることを想定
# Cloud Functionsのデプロイ時にエントリーポイントとして `run_yamap_auto_domo_function` を指定
