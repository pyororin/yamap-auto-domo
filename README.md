# YAMAP 自動操作スクリプト

## 概要

このリポジトリは、YAMAP ([https://yamap.com](https://yamap.com)) のウェブサイト上で特定の操作を自動化するPythonスクリプト群です。
Selenium WebDriver (Headless Chrome) を使用し、設定ファイル (`yamap_auto/config.yaml`) と環境変数を通じて、柔軟な自動操作を実現します。

### 主な機能

*   **ログイン**: スクリプト実行時にYAMAPへ自動ログインします。
*   **フォローバック**: 自分をフォローしてくれたユーザーを自動でフォローバックします。
*   **タイムラインDOMO**: タイムライン上の活動記録へ自動でDOMO（いいね）します。
*   **検索＆フォロー**: 活動記録の検索結果を巡回し、特定の条件に合うユーザーを自動でフォロー＆DOMOします。
*   **DOMO返し**: 自分の過去の投稿にDOMOをくれたユーザーの最新投稿にDOMOを返します。条件に応じてフォローも可能です。
*   **非アクティブユーザー整理**: 長期間活動がなく、かつ自分をフォローしていないユーザーのフォローを解除します。

**⚠️ 注意事項**
*   **自己責任での利用**: 自動操作はYAMAPの利用規約を遵守する範囲で使用してください。このスクリプトの使用によって生じたいかなる損害についても、開発者は責任を負いません。
*   **アカウント制限のリスク**: 過度な頻度での実行や、並列処理数の設定によっては、YAMAPサーバーへの負荷増大や、アカウントの一時的な利用制限に繋がる可能性があります。設定は慎重に行ってください。

---

## 実行環境

### 1. ローカル環境での実行

#### 必要なもの
*   Python 3.8以上
*   Google Chrome
*   ChromeDriver (使用するChromeのバージョンに合ったもの)

#### セットアップ
1.  **ChromeDriverの準備**:
    お使いのGoogle Chromeのバージョンを確認し、対応する[ChromeDriver](https://chromedriver.chromium.org/downloads)をダウンロードしてください。ダウンロードした`chromedriver` (または`chromedriver.exe`)を、このプロジェクトのルートディレクトリに配置するか、システムのPATHが通ったディレクトリに配置してください。

2.  **依存ライブラリのインストール**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **認証情報の設定**:
    YAMAPへのログインに必要な以下の情報を、環境変数として設定します。
    - `YAMAP_LOGIN_ID`: YAMAPのログインに使用するメールアドレス
    - `YAMAP_LOGIN_PASSWORD`: YAMAPのログインに使用するパスワード
    - `USER_ID`: あなたのYAMAPユーザーID（プロフィールページのURL末尾の数字など）

    **設定例 (.bashrc, .zshrc など):**
    ```bash
    export YAMAP_LOGIN_ID="your_email@example.com"
    export YAMAP_LOGIN_PASSWORD="your_password"
    export USER_ID="1234567"
    ```
    設定後は、ターミナルを再起動するか `source ~/.bashrc` などを実行して環境変数を読み込んでください。

4.  **設定ファイルの編集**:
    `yamap_auto/config.yaml` を開き、各機能の有効/無効や動作条件を好みに合わせて編集します。詳細は後述の「設定ファイル (`config.yaml`)」セクションを参照してください。

5.  **スクリプトの実行**:
    ```bash
    python yamap_auto/yamap_auto_domo.py
    ```

### 2. Docker環境での実行 (推奨)

Dockerを使用することで、ローカル環境のOSやライブラリバージョンに依存せず、安定した実行環境を構築できます。

(Dockerfileやdocker-compose.ymlの準備が必要です。現状は未提供ですが、将来的にサポート予定です。)

---

## 設定ファイル (`config.yaml`)

スクリプトの全機能は `yamap_auto/config.yaml` ファイルで制御します。主要な設定項目は以下の通りです。

### 機能の有効化/無効化
ファイルの先頭にある `enable_...` 系のフラグ (`true`/`false`) で、各機能を個別にON/OFFできます。
- `enable_follow_back`: フォローバック機能
- `enable_timeline_domo`: タイムラインDOMO機能
- `enable_search_and_follow`: 検索＆フォロー機能
- `enable_domo_back_to_past_users`: DOMO返し機能
- `enable_unfollow_inactive`: 非アクティブユーザー整理機能
- `enable_parallel_processing`: 一部の機能（タイムラインDOMOなど）での並列処理

### WebDriver設定
- `headless_mode`: `true`にするとブラウザ非表示で実行します。デバッグ時は`false`が便利です。
- `webdriver_settings`: `execution_environment` を `local` または `docker_container` に設定します。

### 並列処理設定 (`parallel_processing_settings`)
- **`max_workers`**: 並列処理の最大スレッド数を指定します。**値を大きくしすぎるとアカウント制限のリスクが高まります。**最初は`2`や`3`で試すことを強く推奨します。
- 各機能（フォローバック、検索＆フォローなど）にも個別の並列処理設定 (`enable_parallel_...`, `max_workers_...`) があり、より詳細な制御が可能です。

### 各機能の詳細設定
- **`follow_back_settings`**: フォローバックする上限数や、確認するフォロワーリストのページ数を設定します。
- **`search_and_follow_settings`**: フォロー対象とするユーザーの条件（フォロワー数、フォロー/フォロワー比率）などを細かく設定できます。
- **`new_feature_domo_back_to_past_domo_users`**: DOMO返しを行う対象期間や、フォローを試みるかなどを設定します。
- **`unfollow_inactive_users_settings`**: 「非アクティブ」と見なす日数や、一度に整理する最大人数を設定します。

---

## 将来の展望

- **Google Cloud Functionsでの定期実行**:
  現在、このスクリプトをGoogle Cloud Functionsにデプロイし、Cloud Schedulerで定期実行する改修を計画しています。これにより、手動でスクリプトを起動する必要がなくなります。

---

## トラブルシューティング

- **`モジュールが見つかりません` (ModuleNotFoundError)**:
  `pip install -r requirements.txt` を正しく実行したか確認してください。
- **`WebDriverException: 'chromedriver' executable needs to be in PATH`**:
  ChromeDriverが正しく配置されていないか、PATHが通っていません。「セットアップ」の項目を確認してください。
- **要素が見つからないエラー (NoSuchElementException, TimeoutException)**:
  YAMAPのサイト構造が変更された可能性があります。スクリプト内のCSSセレクタやXPathの修正が必要になる場合があります。

---

## 免責事項

このスクリプトの使用によって生じたいかなる損害についても、開発者は責任を負いません。自己責任において利用してください。YAMAPの利用規約を遵守し、節度ある利用を心がけてください。
