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

YAMAPへのログインに必要な以下の情報は、すべて環境変数を通じて設定されます。
これにより、`yamap_auto/credentials.yaml` ファイルは不要になりました。

-   **`YAMAP_LOGIN_ID`**: YAMAPのログインに使用するメールアドレス。
-   **`YAMAP_LOGIN_PASSWORD`**: YAMAPのログインに使用するパスワード。
-   **`USER_ID`**: あなたのYAMAPユーザーID。
-   **`YAMAP_CONFIG_FILE`**: (オプション) 使用する設定ファイルを指定します。デフォルトは `yamap_auto/config.yaml` です。`yamap_auto/config_sequential.yaml` を指定すると、並列処理を無効にした設定で実行できます。

これらの環境変数は、`jules.yml` で定義されており、Google Secret Managerに保存されたシークレットから読み込まれます。
ローカルで実行する場合は、これらの環境変数を手動で設定してください。

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

## ローカルでの開発・実行

ローカルでの開発とテストは、**Dockerコンテナを使用**して行います。これにより、GCP上の実行環境と完全に一致させることができ、環境差異による問題を未然に防ぎます。

### 動作環境 (ローカル)

-   Docker Desktop (または同等のDocker環境)

### 初期準備 (ローカル)

1.  Docker Desktopをインストールし、起動します。
2.  プロジェクトのルートディレクトリで、以下のコマンドを実行してDockerイメージをビルドします。
    ```bash
    docker build -t yamap-auto-domo-local .
    ```
    -   `Dockerfile` や `requirements.txt` を変更した場合は、このコマンドを再実行してイメージを更新してください。

### 動作方法 (ローカル)

以下のコマンドでDockerコンテナを起動し、スクリプトを実行します。

```bash
docker run --rm -it \
  -e YAMAP_LOGIN_ID="あなたのメールアドレス" \
  -e YAMAP_LOGIN_PASSWORD="あなたのパスワード" \
  -e USER_ID="あなたのユーザーID" \
  -e YAMAP_CONFIG_FILE="yamap_auto/config.yaml" \
  yamap-auto-domo-local
```

**コマンドの解説:**

-   `docker run`: コンテナを実行するコマンドです。
-   `--rm`: コンテナ終了時に自動でコンテナを削除します。
-   `-it`: コンテナのログを直接ターミナルに表示します。
-   `-e 環境変数名="値"`: コンテナ内で使用する環境変数を設定します。**YAMAPの認証情報はここで設定してください。**
-   `yamap-auto-domo-local`: ビルドしたDockerイメージの名前です。

**設定ファイルの切り替え:**

-   逐次処理（並列なし）でテストしたい場合は、`YAMAP_CONFIG_FILE`の値を変更します。
    ```bash
    -e YAMAP_CONFIG_FILE="yamap_auto/config_sequential.yaml" \
    ```

スクリプトのログは、コンテナの標準出力としてターミナルに直接表示されます。

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
