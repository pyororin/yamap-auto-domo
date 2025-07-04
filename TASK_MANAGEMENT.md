# タスク管理

最終更新日時: 2025/07/03

---

## 🛠 仕掛中タスク

(ここにタスクを記述)

---

## 🚧 問題・課題

(ここに問題・課題を記述)

---

## 💡 メモ / 改善案

(ここにメモや改善案を記述)

---

## 🚀 新機能提案

### yamap_auto_domo.py の新規作成

**概要:** 既存の `yamap_auto.py` を参考に、YAMAPの自動操作を行う新機能を追加する。主な機能はフォロワーとの交流支援と新規フォローの拡充。

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
        *   ユーザーのフォロー数がフォロワー数よりも少ない場合（または指定のRatioを満たす場合）に「フォロー」する。
        *   フォローしたユーザーの最新の活動記録へDOMOする。
        *   `config.yaml` でON/OFF、処理ページ数、フォロー条件のRatio、1ページあたりの処理ユーザー数を設定可能にする。

4.  **設定管理:**
    *   `yamap_auto/config.yaml` に上記機能のON/OFFやしきい値、設定値を追加・管理する。
        *   既存の設定項目との整合性を考慮する。
        *   新しい機能のためのセクションを追加する（例: `timeline_domo_settings`, `new_follow_expansion_settings`）。

**タスクブレークダウン (yamap_auto_domo.py 作成と config.yaml 更新):**

*   [ ] `yamap_auto_domo.py` の基本構造作成 (既存の `yamap_auto.py` を参考に、ロガー設定、WebDriver設定、ログイン機能流用)
*   [ ] `config.yaml` に新機能用の設定項目を追加定義
*   [ ] **フォローバック機能の実装:**
    *   [ ] 自分のフォロワー一覧を取得する処理
    *   [ ] 各フォロワーが既にフォローバック済みか確認する処理
    *   [ ] フォローバックを実行する処理
    *   [ ] `config.yaml` から設定値を読み込み、動作を制御
*   [ ] **タイムラインDOMO機能の実装:**
    *   [ ] タイムラインページにアクセスし、活動記録要素を取得する処理
    *   [ ] 各活動記録へDOMOする処理（既存DOMO処理を参考に、重複DOMOを避ける）
    *   [ ] `config.yaml` から設定値を読み込み、動作を制御
*   [ ] **検索結果からのフォロー＆DOMO機能の実装:**
    *   [ ] `https://yamap.com/search/activities` にアクセスする処理
    *   [ ] ページネーションを処理し、次のページへ進むロジック
    *   [ ] 各活動記録からユーザーページURLを取得する処理
    *   [ ] ユーザーページでフォロー数・フォロワー数を取得する処理 (既存処理を参考に拡張)
    *   [ ] フォロー条件（フォロー数 < フォロワー数 or Ratio）を判定する処理
    *   [ ] ユーザーをフォローする処理 (既存処理を参考に拡張)
    *   [ ] フォローしたユーザーの最新活動記録を取得しDOMOする処理 (既存処理を参考に拡張)
    *   [ ] `config.yaml` から設定値を読み込み、動作を制御
*   [ ] エラーハンドリング、ログ出力の強化
*   [ ] main関数での各機能の呼び出し制御
*   [ ] README.md の更新 (新機能の追加、config.yaml の説明更新など)
*   [ ] 動作確認・デバッグ

**その他:**

*   既存の `yamap_auto.py` との機能重複や依存関係を考慮し、共通化できる部分は関数として切り出すことも検討。ただし、今回はまず `yamap_auto_domo.py` として独立して作成する。
*   セレクタの変更に強い実装を心がける (可能な範囲で `data-testid` などを優先)。

(ここに新機能提案を記述)

---

## ✅ 完了タスク

(ここに完了したタスクをチェックボックス付きで記述)
<!-- - [x] 完了したタスク1 (コミットハッシュ or Issue番号) -->

---

## ❗手動確認依頼

(ここに手動確認が必要な事項を記述)
