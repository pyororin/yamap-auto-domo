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
    gnupg \
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
    && rm -rf /usr/local/bin/chromedriver-linux64

# 作業ディレクトリの設定
WORKDIR /app

# 依存関係ファイルのコピーとインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードのコピー
COPY . .

# Gunicorn を使用してアプリケーションを起動します。
# Cloud Run は PORT 環境変数でリッスンするポートを指定します。
# Gunicorn はワーカーを1つ、スレッドを8つ持つように設定し、タイムアウトを延長します。
# ログは標準出力に直接出すように設定します。
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers=1", "--threads=8", "--timeout=300", "main:app", "--log-level=info", "--log-file=-"]

# 環境変数 (オプション、必要に応じて設定)
# 例: ENV GOOGLE_APPLICATION_CREDENTIALS /app/credentials.json
ENV PYTHONUNBUFFERED TRUE
