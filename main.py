import logging
import os
from yamap_auto import yamap_auto_domo

# ロガー設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_yamap_auto_domo_function(event, context):
    """
    Cloud Functionsのエントリーポイント。
    HTTPリクエストやPub/Subメッセージなど、さまざまなトリガーで呼び出すことができます。
    Cloud Schedulerから呼び出されることを想定しています。
    """
    logger.info("Cloud Function 'run_yamap_auto_domo_function' がトリガーされました。")
    try:
        # yamap_auto_domo.main() を直接呼び出す
        # 必要に応じて、設定ファイルや環境変数をここで処理することもできます。
        # 例: config_path = os.environ.get("CONFIG_PATH", "yamap_auto/config.yaml")
        #     yamap_auto_domo.main(config_path=config_path)

        logger.info("yamap_auto_domo.main() の実行を開始します。")
        yamap_auto_domo.main()
        logger.info("yamap_auto_domo.main() の実行が完了しました。")
        return "Function execution completed successfully.", 200
    except Exception as e:
        logger.error(f"yamap_auto_domo.main() の実行中にエラーが発生しました: {e}", exc_info=True)
        return f"Error during function execution: {e}", 500

# 従来のFlaskアプリ部分はCloud Functionsでは不要なためコメントアウトまたは削除
# from flask import Flask, jsonify
# app = Flask(__name__)
#
# @app.route('/start', methods=['GET'])
# def start_process():
#     logger.info("/start エンドポイントが呼び出されました。")
#     # Cloud FunctionsではHTTPリクエストごとに独立して実行されるため、
#     # バックグラウンドスレッドは通常不要です。
#     # Schedulerが直接エントリーポイント関数を呼び出します。
#     run_yamap_auto_domo_function(None, None) # 直接実行する場合の例
#     return jsonify({"message": "処理を開始しました。"}), 200
#
# @app.route('/', methods=['GET'])
# def health_check():
#     logger.info("/ (ヘルスチェック) エンドポイントが呼び出されました。")
#     return jsonify({"status": "healthy"}), 200
#
# if __name__ == '__main__':
#     # Cloud Functions環境では、この部分は実行されません。
#     # ローカルでのテスト用に残すか、削除します。
#     # app.run(host='0.0.0.0', port=8080, debug=True)
#     pass
