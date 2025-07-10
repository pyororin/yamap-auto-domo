# YAMAP 自動操作スクリプト

# YAMAP 自動操作スクリプト for Google Cloud Run

## 概要

このリポジトリは、YAMAP ([https://yamap.com](https://yamap.com)) のウェブサイト上で特定の操作を自動化するPythonスクリプトを、**Google Cloud Run** 上で定期実行するための構成です。
Selenium WebDriver (Headless Chrome) を使用し、設定ファイル (`yamap_auto/config.yaml`) と環境変数を通じて動作を制御します。

メインスクリプト (`yamap_auto/yamap_auto_domo.py`) は、以下の主要な機能を持ちます（詳細は既存の機能説明を参照）。

*   ログイン機能
*   フォロワーとの交流機能（フォローバック、タイムラインDOMO）
*   新規フォローの拡充機能（検索結果からのフォロー＆DOMO）

**注意**: 自動操作はYAMAPの利用規約を遵守する範囲で使用してください。

## Google Cloud Run での実行

このプロジェクトは、Jules (Google Cloud 開発支援ツール) を用いて、Git push時に自動でDockerイメージのビルドとCloud Runへのデプロイが行われるように構成されています。

### 必要なファイル

ルートディレクトリに以下のファイルが配置されます。

*   **`Dockerfile`**: Cloud Runで実行するDockerイメージをビルドするための定義ファイルです。Python 3.10をベースに、ChromeとChromeDriver、必要なPythonライブラリをインストールします。
*   **`requirements.txt`**: Pythonの依存ライブラリをリストしたファイルです。主に `selenium` が含まれます。
*   **`jules.yml`**: JulesがCloud Runサービスをデプロイするための設定ファイルです。サービス名、リージョン、環境変数（Secret Managerからの参照を含む）などを定義します。
*   **`README.md`**: このファイルです。

### 認証情報の設定

YAMAPへのログインに使用するメールアドレスとパスワードは、`jules.yml` で定義された環境変数 `YAMAP_LOGIN_ID` と `YAMAP_LOGIN_PASSWORD` を通じて、Google Secret Managerに保存されたシークレットから読み込まれます。

`yamap_auto/credentials.yaml` ファイルは、`user_id` のみを読み込むために引き続き使用されます。**Cloud Run環境に `credentials.yaml` を含める場合は、`user_id` 以外の認証情報を削除またはコメントアウトしてください。**

```yaml
# yamap_auto/credentials.yaml のCloud Run用設定例
# email: "your_email@example.com"  # 環境変数 YAMAP_LOGIN_ID を使用
# password: "your_password"        # 環境変数 YAMAP_LOGIN_PASSWORD を使用
user_id: "1234567"                 # 【必須】あなたのYAMAPユーザーID
```

### 定期実行 (Cloud Scheduler)

Cloud Runサービスは、Cloud Schedulerを使用して定期的にトリガーできます。以下は、毎週月曜日の午前10時に実行する例です。

```bash
gcloud scheduler jobs create http selenium-batch-run \
  --schedule="0 10 * * 1" \
  --uri="https://<your-service-name>-<project-hash>-<region>.a.run.app" \
  --http-method=GET \
  --oidc-service-account-email=<your-service-account>@<project-id>.iam.gserviceaccount.com
```
`<your-service-name>`、`<project-hash>`、`<region>`、`<your-service-account>`、`<project-id>` は実際の値に置き換えてください。Cloud RunサービスのURLはデプロイ後に確認できます。

## ローカルでの開発・実行（従来通り）

ローカル環境でスクリプトを実行する場合のセットアップや実行方法は基本的に従来通りです。

### 動作環境 (ローカル)

- Python 3.7以上 (Cloud Run環境はPython 3.10)
- Google Chrome ブラウザ
- ChromeDriver (ローカルのChromeバージョンに適合するもの)
- 必要なPythonライブラリ (Selenium, PyYAMLなど)

### 初期準備 (ローカル)

1.  Python、Google Chrome、ChromeDriverをインストールします。
2.  必要なPythonライブラリをインストールします。
    ```bash
    pip install -r requirements.txt  # requirements.txt を使用
    pip install PyYAML # config.yaml の読み込みに必要
    ```

### 設定 (ローカル)

ローカル実行時は、`yamap_auto/credentials.yaml` にメールアドレス、パスワード、ユーザーIDを直接記述します。
`yamap_auto/config.yaml` の設定はCloud Run実行時と共通です。

```yaml
# yamap_auto/credentials.yaml のローカル実行用設定例
email: "your_yamap_email@example.com"
password: "your_yamap_password"
user_id: "1234567"
```

### 動作方法 (ローカル)

プロジェクトのルートディレクトリから以下のコマンドで実行します。
```bash
python -m yamap_auto.yamap_auto_domo
```
ログは `logs/yamap_auto_domo.log` に出力されます (ログディレクトリはスクリプト実行時にクリアされます)。

## トラブルシューティング

(従来と同様のトラブルシューティング情報)

-   **`モジュールが見つかりません` (ModuleNotFoundError)**:
    `pip install -r requirements.txt` および `pip install PyYAML` を正しく実行したか確認してください。
-   **`WebDriverException: 'chromedriver' executable needs to be in PATH`** (ローカル実行時):
    ChromeDriverが正しく配置されていないか、PATHが通っていません。
-   **`設定ファイルの形式が正しくありません` (yaml.YAMLError)**:
    `config.yaml` の記述（特にインデント）が正しいYAML形式になっているか確認してください。
-   **要素が見つからないエラー (NoSuchElementException, TimeoutException)**:
    YAMAPのサイト構造が変更された可能性があります。スクリプト内のCSSセレクタやXPathの修正が必要になる場合があります。

## 免責事項

このスクリプトの使用によって生じたいかなる損害についても、開発者は責任を負いません。自己責任において利用してください。YAMAPの利用規約を遵守し、節度ある利用を心がけてください。
