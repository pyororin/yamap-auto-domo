# タスク管理

最終更新日時: 2025/07/08

---

## 🛠 仕掛中タスク
*   [ ] **新機能:** 自分自身の1週間以内の記事投稿について、DOMOをくれた未フォローユーザーをフォローバックし、そのユーザーの最新投稿1つへDOMOする機能 (コミット: `[THIS_COMMIT_HASH]`)
    *   `my_post_interaction_utils.py` に主要ロジックを実装。
    *   `yamap_auto_domo.py` から呼び出し、`config.yaml` に設定項目追加。
    *   **要ユーザー確認・調整:**
        *   DOMOユーザー一覧取得部分のCSSセレクタ (`get_domo_users_from_activity` 内) は仮のものが多く、実際のYAMAPのUIに合わせて調整が必須。
        *   フォローバック条件は現在簡略化（ボタンがあればフォロー）。必要なら既存のフォローバック条件（フォロワー数レシオ等）を詳細に適用する改修を検討。
        *   全体的な動作確認と、エラーハンドリングの強化。
*   [ ] 並列処理時のログイン問題を調査・修正
    *   ワーカースレッド作成時のCookieによるログイン確認処理を強化 (`driver_utils.create_driver_with_cookies` でマイページアクセス検証追加、各タスク処理の冒頭でもヘッダーアバター確認)。ログイン失敗時にはスクリーンショットを保存するように改善。 ([PREVIOUS_COMMIT_HASH])
    *   `driver_utils.create_driver_with_cookies` のログイン検証ロジックを強化（アバターalt属性確認、URL正規化比較、失敗時HTML保存）。`follow_back_utils._follow_back_task` はこの強化された関数を利用するようにし、同タスク内のログ出力を改善。([THIS_COMMIT_HASH])
    *   **要ユーザー確認:** 上記修正を適用した上で並列処理を実行し、ログイン問題が改善されるか、依然として発生する場合はログ（特に `create_driver_with_cookies` 内の検証ステップログ、`_follow_back_task` 内のデバッグログ）とスクリーンショット、HTMLソースを分析して原因を特定する必要あり。`ConnectionResetError` が頻発する場合は、`config.yaml` の並列処理設定（ワーカー数、遅延時間）の大幅な緩和を試すこと。
*   [ ] 検索＆フォロー機能の並列処理におけるパフォーマンス改善と安定性向上 ([THIS_COMMIT_HASH])
    *   [x] `search_utils.py` のログ出力強化（ワーカースレッドの処理詳細、メインループの状況等）
    *   [x] `search_utils.py` に並列処理のパフォーマンス計測機能追加（総処理時間、処理ユーザー数、スループット等）
    *   [x] `config.yaml` の検索＆フォロー並列処理関連パラメータに詳細なコメントを追記
*   [ ] エラーハンドリング、ログ出力の強化 - 継続的に改善要
*   [ ] 動作確認・デバッグ - 継続的に必要 (特に並列処理の安定性とパフォーマンス)
    *   検索結果からのフォロー＆DOMO機能において、「次へ」ボタンのページネーションが機能しない問題を修正。`search_utils.py` のセレクタ更新、ログ強化、関連処理調整を実施。([THIS_COMMIT_HASH])

---

## 🚧 問題・課題
*   並列処理でワーカースレッドが正しくログインできていない可能性。
    *   上記「仕掛中タスク」にてログイン検証ロジックの強化とログ改善を実施。ユーザーによる動作確認とフィードバック待ち。([THIS_COMMIT_HASH])
*   検索結果からのフォロー＆DOMO機能で、ページネーションの「次へ」ボタンが機能していなかった。
    *   `search_utils.py` の関連セレクタを更新し、ログを強化する修正を実施。ユーザーによる動作確認待ち。([THIS_COMMIT_HASH])
(ここに問題・課題を記述)

---

## 💡 メモ / 改善案

*   [x] フォローバックについて、「次へ」のページ遷移も行い全ページの確認を実施します (`max_pages_for_follow_back` 設定追加)
*   [x] タイムラインDOMO機能について、個別の記事に飛ばずに一覧上でDOMOする
*   [ ] 並列処理のワーカー数や遅延時間について、最適な値をユーザー環境ごとに調整する必要があるため、README等に指針を記載検討。（`config.yaml` 内のコメントで一部対応済み [THIS_COMMIT_HASH]）
(ここにメモや改善案を記述)

---

## 🚀 新機能提案

### yamap_auto_domo.py の機能改善・完成

**概要:** 既存の `yamap_auto_domo.py` の機能を改善・完成させ、YAMAPの自動操作（フォロワー交流、新規フォロー）を実現する。

**機能詳細:**

1.  **ログイン機能:**
    *   最初にYAMAPへログインする。

2.  **フォロワーとの交流機能:**
    *   **機能1: フォローバック**
        *   自分をフォローしてくれたユーザーを自動でフォローバックする。
        *   `config.yaml` でON/OFF、最大フォローバック数を設定可能にする。
    *   **機能2: タイムラインDOMO**
        *   タイムライン上の活動記録へ自動でDOMOする。
        *   `config.yaml` でON/OFF、DOMOする投稿数を設定可能にする。

3.  **新規フォローの拡充機能:**
    *   **機能1: 検索結果からのフォロー＆DOMO**
        *   `https://yamap.com/search/activities` の一覧をページングしながら進む。
        *   各活動記録のユーザーページを開く。
        *   ユーザーのフォロー数がフォロワー数よりも多い場合（かつ指定のRatioを満たす場合）に「フォロー」する。
        *   フォローしたユーザーの最新の活動記録へDOMOする。
        *   `config.yaml` でON/OFF、処理ページ数、フォロー条件のRatio、1ページあたりの処理ユーザー数を設定可能にする。

4.  **設定管理:**
    *   `yamap_auto/config.yaml` に上記機能のON/OFFやしきい値、設定値を追加・管理する。
        *   既存の設定項目との整合性を考慮する。
        *   新しい機能のためのセクションを追加する（例: `timeline_domo_settings`, `new_follow_expansion_settings`）。

**タスクブレークダウン (yamap_auto_domo.py 改善と関連ファイル更新):**

*   [x] `yamap_auto_domo.py` の基本構造作成 (ロガー設定、WebDriver設定、ログイン機能流用) - 実装済み
*   [x] `config.yaml` に新機能用の設定項目を追加定義 - 実装済み
*   [x] **フォローバック機能の実装:** - 実装済み
    *   [x] 自分のフォロワー一覧を取得する処理 - 実装済み
    *   [x] 各フォロワーが既にフォローバック済みか確認する処理 - 実装済み
    *   [x] フォローバックを実行する処理 - 実装済み
    *   [x] `config.yaml` から設定値を読み込み、動作を制御 - 実装済み
*   [x] **タイムラインDOMO機能の実装:** - 実装済み
    *   [x] タイムラインページにアクセスし、活動記録要素を取得する処理 - 実装済み
    *   [x] 各活動記録へDOMOする処理（既存DOMO処理を参考に、重複DOMOを避ける） - 実装済み
    *   [x] `config.yaml` から設定値を読み込み、動作を制御 - 実装済み
*   [x] **検索結果からのフォロー＆DOMO機能の実装:** - 実装済み
    *   [x] `https://yamap.com/search/activities` にアクセスする処理 - 実装済み
    *   [x] ページネーションを処理し、次のページへ進むロジック - 実装済み
    *   [x] 各活動記録からユーザーページURLを取得する処理 - 実装済み
    *   [x] ユーザーページでフォロー数・フォロワー数を取得する処理 (既存処理を参考に拡張) - 実装済み
    *   [x] フォロー条件（フォロー数 > フォロワー数 AND Ratio）を判定する処理 - 実装済み
    *   [x] ユーザーをフォローする処理 (既存処理を参考に拡張) - 実装済み
    *   [x] フォローしたユーザーの最新活動記録を取得しDOMOする処理 (既存処理を参考に拡張) - 実装済み
    *   [x] `config.yaml` から設定値を読み込み、動作を制御 - 実装済み
*   [ ] エラーハンドリング、ログ出力の強化 - 継続的に改善要
*   [x] main関数での各機能の呼び出し制御 - 実装済み
*   [x] README.md の更新 (新機能の追加、config.yaml の説明更新、旧スクリプト記述削除) - 今回対応済 (コミットハッシュ: `[NEEDS_ACTUAL_COMMIT_HASH_AFTER_MERGE]`)
*   [ ] 動作確認・デバッグ - 継続的に必要

**その他:**

*   既存の `yamap_auto_domo.py` との機能重複や依存関係を考慮し、共通化できる部分は関数として切り出すことも検討。
*   セレクタの変更に強い実装を心がける (可能な範囲で `data-testid` などを優先)。

(ここに新機能提案を記述)
*   [ ] 自分自身の1週間以内の記事投稿について
    *   [ ] 未フォローの場合、フォローバックする（フォロバの条件は他同様）
    *   [ ] DOMOをくれたユーザーの最新投稿1つへDOMOする
    *   上記は今回「🛠 仕掛中タスク」として実装・追加。

---

## ✅ 完了タスク

*   [x] スクリプト実行結果のサマリー情報（フォロー数、DOMO数など）を最後にまとめてログ出力する ([THIS_COMMIT_HASH])
*   [x] タイムラインDOMO機能について、個別の記事に飛ばずに一覧上でDOMOするよう改修 ([PREVIOUS_DIRECT_DOMO_COMMIT_HASH]) (意図しないページ遷移発生時の復帰処理追加 [THIS_FIX_COMMIT_HASH])
*   [x] `domo_utils.py` の `domo_activity` 関数のエラーハンドリングとログ出力を強化 `[THIS_COMMIT_HASH]`
*   [x] `yamap_auto_domo.py` 内のフォローバック処理 (`follow_back_users_new`) を `follow_back_utils.py` 等に分割 (現状 `follow_utils.py` に存在、これから `follow_back_utils.py` へ移動、実際には既に `follow_back_utils.py` に存在することを確認) `[THIS_COMMIT_HASH]`
*   [x] `yamap_auto_domo.py` 内の検索結果処理 (`search_follow_and_domo_users`) を `search_utils.py` 等に分割 (現状 `follow_utils.py` に存在、これから `search_utils.py` へ移動、実際には既に `search_utils.py` に存在することを確認) `[THIS_COMMIT_HASH]`
*   [x] `yamap_auto_domo.py` 内のタイムライン処理 (`domo_timeline_activities`, `domo_timeline_activities_parallel`) を `timeline_utils.py` 等に分割 (実質 `domo_utils.py` へ分割済) `[THIS_COMMIT_HASH]`
*   [x] `yamap_auto_domo.py` の基本構造作成 (ロガー設定、WebDriver設定、ログイン機能流用)
*   [x] `config.yaml` に新機能用の設定項目を追加定義
*   [x] **フォローバック機能の実装:**
    *   [x] 自分のフォロワー一覧を取得する処理
    *   [x] 各フォロワーが既にフォローバック済みか確認する処理
    *   [x] フォローバックを実行する処理
    *   [x] `config.yaml` から設定値を読み込み、動作を制御
*   [x] **タイムラインDOMO機能の実装:**
    *   [x] タイムラインページにアクセスし、活動記録要素を取得する処理
    *   [x] 各活動記録へDOMOする処理（既存DOMO処理を参考に、重複DOMOを避ける）
    *   [x] `config.yaml` から設定値を読み込み、動作を制御
*   [x] **検索結果からのフォロー＆DOMO機能の実装:**
    *   [x] `https://yamap.com/search/activities` にアクセスする処理
    *   [x] ページネーションを処理し、次のページへ進むロジック
    *   [x] 各活動記録からユーザーページURLを取得する処理
    *   [x] ユーザーページでフォロー数・フォロワー数を取得する処理 (既存処理を参考に拡張)
    *   [x] フォロー条件（フォロー数 > フォロワー数 AND Ratio）を判定する処理
    *   [x] ユーザーをフォローする処理 (既存処理を参考に拡張)
    *   [x] フォローしたユーザーの最新活動記録を取得しDOMOする処理 (既存処理を参考に拡張)
    *   [x] `config.yaml` から設定値を読み込み、動作を制御
*   [x] main関数での各機能の呼び出し制御
*   [x] README.md の更新 (新機能の追加、config.yaml の説明更新、旧スクリプト記述削除) (コミットハッシュ: `[NEEDS_ACTUAL_COMMIT_HASH_AFTER_MERGE]`)
*   [x] 各主要機能の処理時間計測機能を追加 (コミットハッシュ: `[NEEDS_ACTUAL_COMMIT_HASH_AFTER_MERGE]`)
*   [x] フォロー条件の変更（レシオのみの判定） (コミットハッシュ: `[THIS_COMMIT_HASH]`)
*   [x] スクリプトとconfigへのコメント付与するリファクタリング (コミットハッシュ: `[THIS_COMMIT_HASH]`)
*   [x] 検索＆フォロー機能の待機時間見直しによる効率化 (コミットハッシュ: `[THIS_COMMIT_HASH]`)
*   [x] `yamap_auto_domo.py` のリファクタリング - 機能分割 (ログイン関連処理を `driver_utils.py` に分割完了) `[PREVIOUS_COMMIT_HASH_PLACEHOLDER]`
*   [x] `yamap_auto_domo.py` のリファクタリング - 機能分割 (ユーザープロフィール関連処理を `user_profile_utils.py` に分割完了: `get_latest_activity_url`, `get_user_follow_counts`, `find_follow_button_on_profile_page`) `[PREVIOUS_COMMIT_HASH_PLACEHOLDER]`
*   [x] `yamap_auto_domo.py` のリファクタリング - 機能分割 (DOMO関連処理を `domo_utils.py` に、リストアイテムからのフォロー関連処理を `follow_utils.py` に分割) `[THIS_COMMIT_HASH]`
*   [x] `follow_utils.py` のログ出力強化（詳細なセレクタ情報、ボタン状態の記録） `[PREVIOUS_COMMIT_HASH]`
*   [x] **フォローバック機能の高速化（並列処理化）** `[THIS_COMMIT_HASH]`
    *   `follow_back_utils.py` に `ThreadPoolExecutor` を用いた並列処理ロジックを実装。
    *   ワーカースレッドは独立したWebDriverインスタンスと共有Cookieで動作。
    *   StaleElement対策として、ワーカースレッド内で対象ユーザー要素を再探索。
    *   `config.yaml` に並列処理関連の設定項目 (`enable_parallel_follow_back`, `max_workers_follow_back`, `delay_per_worker_action_sec`) を追加。
*   [x] **検索＆フォロー機能の高速化（ユーザー処理の並列化）** `[THIS_COMMIT_HASH]`
    *   `search_utils.py` に `ThreadPoolExecutor` を用いた並列処理ロジックを実装。
    *   メインスレッドが検索結果ページからユーザー情報を収集し、ワーカースレッドが個々のユーザー処理（プロフィール確認、フォロー、DOMO）を担当。
    *   ワーカースレッドは独立したWebDriverインスタンスと共有Cookieで動作。
    *   `config.yaml` に並列処理関連の設定項目 (`enable_parallel_search_follow`, `max_workers_search_follow`, `delay_per_worker_user_processing_sec`) を追加。
*   [x] スクリプトの管理容易性向上のためのリファクタリング（ロガー設定の共通化とメイン処理の構造化） `[THIS_COMMIT_HASH]`
<!-- - [x] 完了したタスク1 (コミットハッシュ or Issue番号) -->

---

## ❗手動確認依頼

*   **ユーザープロフィール関連関数のリファクタリング影響確認 (`user_profile_utils.py` 分割関連)** `[PREVIOUS_COMMIT_HASH]`
    *   `yamap_auto_domo.py` を実行し、特に「検索からのフォロー＆DOMO機能 (`search_follow_and_domo_users`)」が正常に動作することを確認してください。
        *   ユーザーのプロフィールページへのアクセス
        *   フォロー数・フォロワー数の取得
        *   フォローボタンの検出
        *   最新活動日記URLの取得
        *   上記に基づくフォローおよびDOMOの実行
    *   スクリプト実行時にエラーログが出力されていないか確認してください。
    *   意図しない挙動（例：対象ユーザーの誤判定、操作の失敗など）がないか確認してください。
*   **フォローバック機能および検索＆フォロー機能の並列処理動作確認** `[THIS_COMMIT_HASH]`
    *   `config.yaml` で各機能の並列処理を有効 (`enable_parallel_...: true`) にし、ワーカー数を調整して実行してください。
    *   処理が正常に完了すること、エラーログが出力されないことを確認してください。
    *   特に、複数のブラウザウィンドウ（ヘッドレスの場合あり）が起動し、並行して処理が進む様子をログで確認してください。
    *   フォロー/DOMOのアクションがYAMAP上で正しく行われているか（可能な範囲で）確認してください。
    *   処理件数の上限設定 (`max_users_to_follow_back`, `max_users_to_process_per_page` など) が並列処理時も意図通り機能することを確認してください。
    *   並列処理を無効にした場合と比較して、処理時間が短縮されるか確認してください。
(ここに手動確認が必要な事項を記述)
