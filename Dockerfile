FROM python:3.10-slim

# Chrome & ChromeDriverのインストール
RUN apt-get update && apt-get install -y \
    unzip curl gnupg libnss3 libgconf-2-4 libxi6 libxcursor1 libxcomposite1 libasound2 libxrandr2 libxdamage1 libxtst6 \
    fonts-liberation libappindicator1 libatk-bridge2.0-0 libgtk-3-0 \
    chromium chromium-driver && \
    rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/chromium
ENV PATH="$PATH:/usr/lib/chromium/"

# 作業ディレクトリ
WORKDIR /app
COPY . /app

# 依存パッケージ
RUN pip install --no-cache-dir selenium PyYAML

CMD ["python", "-m", "yamap_auto.yamap_auto_domo"]
