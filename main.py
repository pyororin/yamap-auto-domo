import threading
from flask import Flask, jsonify
import logging

# yamap_auto.yamap_auto_domo が存在するかどうかを確認し、存在すればインポート
# これは、yamap_auto が PYTHONPATH にあるか、同じディレクトリ構造内にあることを前提としています。
try:
    from yamap_auto import yamap_auto_domo
except ImportError as e:
    logging.error(f"yamap_auto.yamap_auto_domoのインポートに失敗しました: {e}")
    # インポートに失敗した場合、アプリケーションは起動するが /start エンドポイントは機能しない
    # 適切なエラーハンドリングや設定が必要
    yamap_auto_domo = None

app = Flask(__name__)

# ロガー設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# yamap_auto_domo.main() を実行するためのワーカー関数
def run_yamap_auto_domo():
    if yamap_auto_domo:
        try:
            logger.info("yamap_auto_domo.main() の実行を開始します。")
            yamap_auto_domo.main()
            logger.info("yamap_auto_domo.main() の実行が完了しました。")
        except Exception as e:
            logger.error(f"yamap_auto_domo.main() の実行中にエラーが発生しました: {e}", exc_info=True)
    else:
        logger.error("yamap_auto_domoモジュールがロードされていないため、処理を実行できません。")

@app.route('/start', methods=['GET'])
def start_process():
    logger.info("/start エンドポイントが呼び出されました。")

    # バックグラウンドスレッドで yamap_auto_domo.main を実行
    thread = threading.Thread(target=run_yamap_auto_domo)
    thread.daemon = True # アプリケーション終了時にスレッドも終了させる
    thread.start()

    logger.info("yamap_auto_domo.main() のバックグラウンド実行を開始しました。")
    return jsonify({"message": "処理をバックグラウンドで開始しました。"}), 200

@app.route('/', methods=['GET'])
def health_check():
    logger.info("/ (ヘルスチェック) エンドポイントが呼び出されました。")
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    #開発用サーバー。本番環境ではgunicornを使用します。
    app.run(host='0.0.0.0', port=8080, debug=True)
