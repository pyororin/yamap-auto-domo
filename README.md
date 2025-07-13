# YAMAP 自動操作スクリプト

## 概要

このリポジトリは、YAMAP ([https://yamap.com](https://yamap.com)) のウェブサイト上で特定の操作を自動化するPythonスクリプトです。
Selenium WebDriver (Headless Chrome) を使用し、設定ファイル (`yamap_auto/config.yaml`) と環境変数を通じて動作を制御します。

メインスクリプト (`yamap_auto/yamap_auto_domo.py`) は、以下の主要な機能を持ちます。

*   ログイン機能
*   フォロワーとの交流機能（フォローバック、タイムラインDOMO）
*   新規フォローの拡充機能（検索結果からのフォロー＆DOMO）

**注意**: 自動操作はYAMAPの利用規約を遵守する範囲で使用してください。

## ローカルでの実行

### 必要なもの

*   Python 3.8以上
*   Google Chrome
*   ChromeDriver (使用するChromeのバージョンに合ったもの)

### 初期準備

1.  **ChromeDriverの準備**
    お使いのGoogle Chromeのバージョンを確認し、対応する[ChromeDriver](https://chromedriver.chromium.org/downloads)をダウンロードしてください。
    ダウンロードした `chromedriver` (または `chromedriver.exe`) を、このプロジェクトのルートディレクトリに配置するか、システムのPATHが通ったディレクトリに配置してください。

2.  **依存ライブラリのインストール**
    ```bash
    pip install -r requirements.txt
    ```

### 認証情報の設定

YAMAPへのログインに必要な以下の情報を、環境変数として設定します。

-   `YAMAP_LOGIN_ID`: YAMAPのログインに使用するメールアドレス。
-   `YAMAP_LOGIN_PASSWORD`: YAMAPのログインに使用するパスワード。
-   `USER_ID`: あなたのYAMAPユーザーID。

**設定例 (.bashrc, .zshrc など):**
```bash
export YAMAP_LOGIN_ID="your_email@example.com"
export YAMAP_LOGIN_PASSWORD="your_password"
export USER_ID="your_user_id"
```
設定後は、ターミナルを再起動するか `source ~/.bashrc` などを実行して環境変数を読み込んでください。

### スクリプトの実行

以下のコマンドでスクリプトを実行します。

```bash
python yamap_auto/yamap_auto_domo.py
```

**設定ファイルの切り替え:**

デフォルトでは `yamap_auto/config.yaml` が使用されます。
逐次処理（並列なし）で実行したい場合は、環境変数 `YAMAP_CONFIG_FILE` を設定します。

```bash
export YAMAP_CONFIG_FILE="yamap_auto/config_sequential.yaml"
python yamap_auto/yamap_auto_domo.py
```

## トラブルシューティング

-   **`モジュールが見つかりません` (ModuleNotFoundError)**:
    `pip install -r requirements.txt` を正しく実行したか確認してください。
-   **`WebDriverException: 'chromedriver' executable needs to be in PATH`**:
    ChromeDriverが正しく配置されていないか、PATHが通っていません。「初期準備」の項目を確認してください。
-   **`設定ファイルの形式が正しくありません` (yaml.YAMLError)**:
    `config.yaml` の記述（特にインデント）が正しいYAML形式になっているか確認してください。
-   **要素が見つからないエラー (NoSuchElementException, TimeoutException)**:
    YAMAPのサイト構造が変更された可能性があります。スクリプト内のCSSセレクタやXPathの修正が必要になる場合があります。

## 免責事項

このスクリプトの使用によって生じたいかなる損害についても、開発者は責任を負いません。自己責任において利用してください。YAMAPの利用規約を遵守し、節度ある利用を心がけてください。
