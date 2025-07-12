import logging
import os
from yamap_auto import yamap_auto_domo

# ロガー設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import threading
from flask import Flask, jsonify

# ロガー設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- グローバル変数 ---
# 処理の状態を管理するための変数
# simple: 'idle', 'running', 'completed', 'error'
# detailed: 'idle', 'initializing', 'logging_in', 'executing_tasks', 'completed', 'error'
processing_status = {"simple": "idle", "detailed": "idle", "error_message": None}
processing_thread = None

def run_automation_in_background():
    """
    yamap_auto_domo.main() をバックグラウンドで実行するためのラッパー関数。
    グローバルなステータス変数を更新します。
    """
    global processing_status
    try:
        logger.info("バックグラウンド処理を開始します...")
        processing_status["simple"] = "running"
        processing_status["detailed"] = "initializing"

        # yamap_auto_domo.main() を直接呼び出す
        yamap_auto_domo.main()

        logger.info("バックグラウンド処理が正常に完了しました。")
        processing_status["simple"] = "completed"
        processing_status["detailed"] = "completed"

    except Exception as e:
        logger.error(f"バックグラウンド処理中にエラーが発生しました: {e}", exc_info=True)
        processing_status["simple"] = "error"
        processing_status["detailed"] = "error"
        # エラーメッセージを保存（簡潔なもの）
        processing_status["error_message"] = str(e)


@app.route('/start', methods=['POST'])
def start_process():
    """
    自動化処理を開始するエンドポイント。
    既に処理が実行中の場合はエラーを返します。
    """
    global processing_thread, processing_status
    logger.info("/start エンドポイントが呼び出されました。")

    if processing_thread and processing_thread.is_alive():
        logger.warning("既に処理が実行中です。")
        return jsonify({"status": "error", "message": "処理は既に実行中です。", "details": processing_status}), 409 # 409 Conflict

    # ステータスをリセットして新しいスレッドを開始
    processing_status = {"simple": "idle", "detailed": "idle", "error_message": None}
    processing_thread = threading.Thread(target=run_automation_in_background)
    processing_thread.start()

    logger.info("新しいバックグラウンド処理を開始しました。")
    return jsonify({"status": "success", "message": "処理を開始しました。", "details": processing_status}), 202 # 202 Accepted

@app.route('/status', methods=['GET'])
def get_status():
    """
    現在の処理状況を返すエンドポイント。
    """
    logger.info("/status エンドポイントが呼び出されました。")
    return jsonify({"status": "ok", "processing_status": processing_status})


@app.route('/', methods=['GET'])
def health_check():
    """
    ヘルスチェック用のエンドポイント。
    Cloud Runがコンテナの起動を確認するために使用します。
    """
    logger.info("/ (ヘルスチェック) エンドポイントが呼び出されました。")
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    # Cloud Run環境では、PORT環境変数がGunicornによって使用されます。
    # この部分は主にローカルでのデバッグ実行用です。
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
