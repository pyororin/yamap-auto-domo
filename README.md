# YAMAP 自動操作スクリプト

## 概要

このスクリプトは、YAMAP ([https://yamap.com](https://yamap.com)) のウェブサイト上で、特定の条件に基づいてDOMOの付与やフォロー申請を自動的に行うPythonスクリプトです。
Selenium WebDriverを使用してブラウザを操作し、設定ファイル (`config.yaml`) によって動作を細かく制御できます。

主な機能:
- **DOMO関連処理**:
  - フォロー中のユーザーの最新投稿へDOMO
  - 自身の投稿にDOMOしてくれたユーザーの最新投稿へDOMO
  - トップページのおすすめ投稿へDOMO
- **フォロー関連処理**:
  - 自身をフォローしてくれたユーザーへのフォローバック
  - DOMOをくれ、特定のRatio条件を満たすユーザーへのフォロー申請
- **柔軟な設定**: `config.yaml` ファイルで、各機能のON/OFFや詳細なパラメータ（処理上限数、待機時間など）を調整可能。
- **ログ出力**: 実行状況やエラーはコンソールとログファイル (`yamap_auto.log`) に詳細に出力。

**注意**: このスクリプトはYAMAPの利用規約を遵守する範囲で使用してください。過度な自動操作はアカウントの制限等に繋がる可能性があります。自己責任においてご利用ください。

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
        -   このスクリプト (`yamap_auto.py`) と同じディレクトリ (`yamap_auto/`)。
        -   システムのPATH環境変数が通っているディレクトリ。

4.  **必要なPythonライブラリのインストール**:
    ターミナルまたはコマンドプロンプトを開き、以下のコマンドを実行して、スクリプトの実行に必要なライブラリをインストールします。
    ```bash
    pip install selenium PyYAML
    ```
    (もし `pip` コマンドが見つからない場合は `python -m pip install selenium PyYAML` を試してください。)

## 設定

スクリプトの動作は `yamap_auto/config.yaml` ファイルで設定します。
このファイルをテキストエディタで開き、各項目を編集してください。

1.  **認証情報 (必須)**:
    -   `email`: あなたのYAMAPログインメールアドレスを記述します。
    -   `password`: あなたのYAMAPログインパスワードを記述します。
    -   `user_id`: あなたのYAMAPユーザーID (数字) を記述します。
        (例: プロフィールページのURLが `https://yamap.com/users/1234567` の場合、`user_id` は `"1234567"`)

2.  **DOMO関連設定 (`domo_settings`)**:
    各DOMO機能の有効/無効 (`true`/`false`) や、処理対象の上限数、待機時間などを設定します。
    詳細は `config.yaml` 内のコメントを参照してください。

3.  **フォロー関連設定 (`follow_settings`)**:
    各フォロー機能の有効/無効 (`true`/`false`) や、処理対象の上限数、Ratio条件の閾値、待機時間などを設定します。
    詳細は `config.yaml` 内のコメントを参照してください。

**注意**: `config.yaml` はYAML形式です。インデント（字下げ）が重要な意味を持つため、構造を崩さないように編集してください。

## 動作方法

1.  上記の「初期準備」と「設定」を完了させます。
2.  ターミナルまたはコマンドプロンプトで、この `README.md` があるディレクトリ (プロジェクトのルートディレクトリ、例: `yamap-auto-domo/`) に移動します。
3.  以下のコマンドを実行してスクリプトを開始します。
    ```bash
    python yamap_auto/yamap_auto.py
    ```
4.  スクリプトが起動すると、設定に基づいてブラウザが自動的に操作されます。
5.  実行状況はコンソールに出力され、より詳細なログは `yamap_auto/yamap_auto.log` ファイルに記録されます。
6.  設定された処理が完了すると、スクリプトは自動的に終了します。

## トラブルシューティング

-   **`モジュールが見つかりません` (ModuleNotFoundError)**:
    `pip install selenium PyYAML` を正しく実行したか確認してください。
-   **`WebDriverException: 'chromedriver' executable needs to be in PATH`**:
    ChromeDriverが正しく配置されていないか、PATHが通っていません。「初期準備」の3番を確認してください。
-   **`設定ファイルの形式が正しくありません` (yaml.YAMLError)**:
    `config.yaml` の記述（特にインデント）が正しいYAML形式になっているか確認してください。オンラインのYAMLバリデーターでチェックするのも有効です。
-   **要素が見つからないエラー (NoSuchElementException, TimeoutException)**:
    YAMAPのサイト構造が変更された可能性があります。スクリプト内のCSSセレクタやXPathの修正が必要になる場合があります。ログファイル (`yamap_auto.log`) でどの要素が見つからなかったかを確認してください。
-   **その他**:
    問題が発生した場合は、コンソールのエラーメッセージと `yamap_auto.log` の内容を確認し、開発者に報告してください。

## 免責事項

このスクリプトの使用によって生じたいかなる損害についても、開発者は責任を負いません。自己責任において利用してください。YAMAPの利用規約を遵守し、節度ある利用を心がけてください。
