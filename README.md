# YAMAP 自動操作スクリプト

## 概要

このリポジトリには、YAMAP ([https://yamap.com](https://yamap.com)) のウェブサイト上で、特定の条件に基づいてDOMOの付与やフォロー申請などを自動的に行うPythonスクリプトが含まれています。
Selenium WebDriverを使用してブラウザを操作し、設定ファイル (`yamap_auto/config.yaml`) と認証情報ファイル (`yamap_auto/credentials.yaml`) によって動作を細かく制御できます。

このリポジトリのメインスクリプト (`yamap_auto/yamap_auto_domo.py`) は、以下の主要な機能を持ちます。

*   **ログイン機能**: 最初にYAMAPへログインします。
*   **フォロワーとの交流機能**:
    *   **フォローバック**: 自分をフォローしてくれたユーザーを自動でフォローバックします。
    *   **タイムラインDOMO**: タイムライン上の活動記録へ自動でDOMOします。
*   **新規フォローの拡充機能**:
    *   **検索結果からのフォロー＆DOMO**: 活動記録の検索結果 (`https://yamap.com/search/activities`) を巡回し、条件（フォロワー数、フォロー/フォロワー比率など）に合うユーザーをフォローし、そのユーザーの最新の活動記録へDOMOします。
*   ログファイル: `yamap_auto_domo.log`

スクリプトは `config.yaml` 内の設定に基づいて動作します。

**注意**: これらのスクリプトはYAMAPの利用規約を遵守する範囲で使用してください。過度な自動操作はアカウントの制限等に繋がる可能性があります。自己責任においてご利用ください。

## 動作環境

- Python 3.7以上 (推奨)
- Google Chrome ブラウザ
- ChromeDriver (使用するChromeブラウザのバージョンに適合するもの)
- 必要なPythonライブラリ (Selenium, PyYAML)

## 初期準備

1.  **Pythonのインストール**:
    Pythonがインストールされていない場合は、[公式サイト](https://www.python.org/)からダウンロードしてインストールしてください。

2.  **Google Chromeのインストール**:
    最新版のGoogle Chromeブラウザをインストールしてください。

3.  **ChromeDriverのダウンロードと配置**:
    -   お使いのGoogle Chromeのバージョンを確認します (Chromeの設定 > Chromeについて)。
    -   [ChromeDriverの公式サイト](https://chromedriver.chromium.org/downloads) から、Chromeのバージョンに対応するChromeDriverをダウンロードします。
    -   ダウンロードした `chromedriver.exe` (Windowsの場合) または `chromedriver` (macOS/Linuxの場合) を、以下のいずれかの場所に配置します:
        -   メインスクリプト (`yamap_auto_domo.py`) と同じディレクトリ (`yamap_auto/`)。
        -   システムのPATH環境変数が通っているディレクトリ。

4.  **必要なPythonライブラリのインストール**:
    ターミナルまたはコマンドプロンプトを開き、以下のコマンドを実行して、スクリプトの実行に必要なライブラリをインストールします。
    ```bash
    pip install selenium PyYAML
    ```
    (もし `pip` コマンドが見つからない場合は `python -m pip install selenium PyYAML` を試してください。)

## 設定

スクリプトの動作は主に以下の2つのYAMLファイルで設定します。これらのファイルは `yamap_auto/` ディレクトリ内に配置または作成してください。

1.  **認証情報ファイル (必須): `yamap_auto/credentials.yaml`**
    このファイルにご自身のYAMAPログイン情報を記述します。**このファイルはGit管理に含めないように `.gitignore` で指定されていますが、ローカルでの作成と管理は自己責任でお願いします。**
    ファイルが存在しない場合は、以下の内容で新規作成してください。

    ```yaml
    # yamap_auto/credentials.yaml の内容例
    email: "your_email@example.com"
    password: "your_password"
    user_id: "1234567" # あなたのYAMAPユーザーID (プロフィールページのURL末尾の数字)
    ```
    -   `email`: あなたのYAMAPログインメールアドレス。
    -   `password`: あなたのYAMAPログインパスワード。
    -   `user_id`: あなたのYAMAPユーザーID (数字)。例: プロフィールURLが `https://yamap.com/users/1234567` の場合、`1234567` を指定します。

2.  **設定ファイル: `yamap_auto/config.yaml`**
    このファイルでスクリプトの機能のON/OFFや詳細な動作パラメータ（処理上限数、待機時間など）を設定します。
    ファイル内のコメントを参照しながら、必要に応じて値を編集してください。

    主な設定項目およびセクション:
    *   `headless_mode`: ブラウザを非表示で実行するか (true/false) - トップレベル設定
    *   `implicit_wait_sec`: 要素が見つかるまでの暗黙的な待機時間 (秒) - トップレベル設定
    *   `action_delays`: DOMOやフォロー後の待機時間など、アクション間の遅延に関する設定。
        *   `after_domo_sec`: DOMO操作後の共通待機時間 (秒)
        *   `after_follow_action_sec`: フォロー操作後の共通待機時間 (秒)
        *   その他、詳細は `config.yaml` を参照。
    *   `follow_back_settings`: フォローバック機能に関する設定。
        *   `enable_follow_back`: 機能の有効/無効 (true/false)
        *   `max_users_to_follow_back`: 一度にフォローバックする最大ユーザー数
    *   `timeline_domo_settings`: タイムライン上の活動記録へのDOMO機能に関する設定。
        *   `enable_timeline_domo`: 機能の有効/無効 (true/false)
        *   `max_activities_to_domo_on_timeline`: DOMOする最大の活動記録数
    *   `search_and_follow_settings`: 検索結果からのフォロー＆DOMO機能に関する設定。
        *   `enable_search_and_follow`: 機能の有効/無効 (true/false)
        *   `search_activities_url`: 活動記録検索ページのURL
        *   `max_pages_to_process_search`: 処理する検索結果の最大ページ数
        *   `max_users_to_process_per_page`: 1ページあたりで処理する最大ユーザー数
        *   `min_followers_for_search_follow`: フォロー対象とするユーザーの最低フォロワー数
        *   `follow_ratio_threshold_for_search`: フォロー対象とするユーザーのフォロー数/フォロワー数比率の閾値
        *   `domo_latest_activity_after_follow`: フォロー後にそのユーザーの最新活動記録へDOMOするかのフラグ (true/false)
        *   その他、詳細は `config.yaml` を参照。
    *   `parallel_processing_settings`: 並列処理に関する設定。
        *   `enable_parallel_processing`: 並列処理を有効にするか (true/false)
        *   `max_workers`: 最大ワーカー数
        *   その他、詳細は `config.yaml` を参照。

    上記は主要な設定項目です。全ての詳細設定は `yamap_auto/config.yaml` ファイル内のコメントを確認してください。

**注意**: `credentials.yaml` と `config.yaml` はYAML形式です。インデント（字下げ）が重要な意味を持つため、構造を崩さないように編集してください。

## 動作方法

1.  上記の「初期準備」と「設定」を完了させます。
2.  ターミナルまたはコマンドプロンプトで、この `README.md` があるディレクトリ (プロジェクトのルートディレクトリ) に移動します。
3.  以下のコマンドを実行します。

    ```bash
    python yamap_auto/yamap_auto_domo.py
    ```
    ログは `yamap_auto/yamap_auto_domo.log` に出力されます。

4.  スクリプトが起動すると、設定に基づいてブラウザが自動的に操作されます。
5.  実行状況はコンソールに出力され、より詳細なログは `yamap_auto_domo.log` ファイルに記録されます。
6.  設定された処理が完了すると、スクリプトは自動的に終了します。

## トラブルシューティング

-   **`モジュールが見つかりません` (ModuleNotFoundError)**:
    `pip install selenium PyYAML` を正しく実行したか確認してください。
-   **`WebDriverException: 'chromedriver' executable needs to be in PATH`**:
    ChromeDriverが正しく配置されていないか、PATHが通っていません。「初期準備」の3番を確認してください。
-   **`設定ファイルの形式が正しくありません` (yaml.YAMLError)**:
    `config.yaml` の記述（特にインデント）が正しいYAML形式になっているか確認してください。オンラインのYAMLバリデーターでチェックするのも有効です。
-   **要素が見つからないエラー (NoSuchElementException, TimeoutException)**:
    YAMAPのサイト構造が変更された可能性があります。スクリプト内のCSSセレクタやXPathの修正が必要になる場合があります。ログファイル (`yamap_auto_domo.log`) でどの要素が見つからなかったかを確認してください。
-   **その他**:
    問題が発生した場合は、コンソールのエラーメッセージと `yamap_auto_domo.log` の内容を確認し、開発者に報告してください。

## 免責事項

このスクリプトの使用によって生じたいかなる損害についても、開発者は責任を負いません。自己責任において利用してください。YAMAPの利用規約を遵守し、節度ある利用を心がけてください。
