# タスク管理

最終更新日時: 2025/07/11

---

## 🛠 仕掛中タスク
*   （現在、仕掛中のタスクはありません）

---

## 🚧 問題・課題
*   **Google Cloud Functionsでの定期実行:**
    *   現状のスクリプトはローカル実行を前提としていますが、これをGoogle Cloud Functionsにデプロイし、Cloud Schedulerを用いて定期的に自動実行できるように構成する必要があります。
    *   **検討事項:**
        *   **エントリーポイント:** Cloud Functions用のエントリーポイント関数（例: `main.py` の `handler` 関数）を定義する。
        *   **依存関係:** `requirements.txt` をCloud Functionsのランタイムに合わせて整備する。
        *   **環境変数:** `YAMAP_LOGIN_ID` などの認証情報を、Cloud Functionsの環境変数機能を使って安全に設定する。
        *   **実行環境:**
            *   Selenium (Headless Chrome) をCloud Functions上で動作させるための環境構築（カスタムコンテナの使用など）。
            *   メモリやタイムアウト時間などのリソース設定。
        *   **ログ出力:** Stackdriver Logging (Cloud Logging) でログを効果的にモニタリングできるように、ログの出力形式を調整する。

---

## 💡 メモ / 改善案
*   （ここにメモや改善案を記述）

---

## 🚀 新機能提案
*   （ここに新機能提案を記述）

---

## ✅ 完了タスク
*   （過去の完了タスクはクリアされました）

---
