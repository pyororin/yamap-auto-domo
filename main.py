import logging
import os
from yamap_auto import yamap_auto_domo

# ロガー設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_yamap_auto_domo_function(request): # 引数を request に変更
    """
    Cloud Functionsのエントリーポイント (HTTPトリガー用)。
    Cloud Schedulerから呼び出されることを想定しています。
    """
    # request オブジェクトから情報を取得する場合の例 (今回は特に使用しない想定)
    # request_json = request.get_json(silent=True)
    # request_args = request.args
    logger.info(f"Cloud Function 'run_yamap_auto_domo_function' triggered. Request method: {request.method}, Headers: {request.headers}")

    try:
        # yamap_auto_domo.main() を直接呼び出す
        # 必要に応じて、設定ファイルや環境変数をここで処理することもできます。
        # 例: config_path = os.environ.get("CONFIG_PATH", "yamap_auto/config.yaml")
        #     yamap_auto_domo.main(config_path=config_path)

        logger.info("yamap_auto_domo.main() の実行を開始します。")
        yamap_auto_domo.main()
        logger.info("yamap_auto_domo.main() の実行が完了しました。")
        # HTTPレスポンスとして文字列とステータスコードを返す
        return "Function execution completed successfully.", 200
    except Exception as e:
        logger.error(f"yamap_auto_domo.main() の実行中にエラーが発生しました: {e}", exc_info=True)
        return f"Error during function execution: {e}", 500
