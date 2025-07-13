# coding: utf-8
import logging
from yamap_auto import yamap_auto_domo

def handler(event, context):
    """
    Google Cloud Functionsから呼び出されるエントリーポイント関数。

    Args:
        event (dict): イベントデータ。Pub/Subトリガーの場合、メッセージが含まれます。
        context (google.cloud.functions.Context): イベントのメタデータ。

    Returns:
        None
    """
    try:
        logging.info("Cloud Functionの処理を開始します。")

        # yamap_auto_domo.py の main 関数を呼び出して、自動操作を実行
        yamap_auto_domo.main()

        logging.info("Cloud Functionの処理が正常に完了しました。")
        return 'OK'

    except Exception as e:
        # 予期せぬエラーが発生した場合、ログに詳細を記録
        logging.critical("Cloud Functionの実行中に致命的なエラーが発生しました。", exc_info=True)
        # エラーを再送出するか、あるいは特定の値を返すかは要件による
        # ここではエラーログを記録した上で、エラーがあったことを示す文字列を返す
        return f'Error: {e}'

# --- ローカルでのテスト用 ---
# Cloud Functions環境外で直接このファイルを実行した際の動作確認用。
# (例: `python main.py`)
if __name__ == '__main__':
    print("ローカルテストとしてhandlerを実行します...")
    # テスト用のダミー引数でhandlerを呼び出し
    handler(None, None)
    print("ローカルテスト完了。詳細はログを確認してください。")
