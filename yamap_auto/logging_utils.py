# coding: utf-8
import logging
import os

LOG_FILE_NAME = "yamap_auto_domo.log"  # ログファイル名（メインスクリプトと同じ場所に出力想定）

def setup_logger():
    """
    スクリプト全体で使用するロガーを設定します。
    ルートロガーを取得し、コンソールとファイルへのハンドラを設定します。
    既にハンドラが設定されている場合は、新たな設定を行いません。
    """
    logger = logging.getLogger()  # ルートロガーを取得
    if not logger.handlers:  # ハンドラがまだ設定されていない場合のみ設定（多重設定防止）
        logger.setLevel(logging.DEBUG)  # ロガー自体のレベルはDEBUGに設定 (ハンドラ側でフィルタリング)

        # StreamHandler (コンソールへのログ出力設定)
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)  # コンソールにはINFOレベル以上のログを出力
        stream_formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        stream_handler.setFormatter(stream_formatter)
        logger.addHandler(stream_handler)

        # FileHandler (ログファイルへの出力設定)
        try:
            # ログファイルはカレントディレクトリ（通常はリポジトリルート）に出力
            log_file_path = LOG_FILE_NAME
            file_handler = logging.FileHandler(log_file_path, encoding='utf-8', mode='a')  # 'a'モードで追記
            file_handler.setLevel(logging.DEBUG)  # ファイルにはDEBUGレベル以上のログを全て記録
            file_formatter = logging.Formatter(
                "[%(asctime)s] [%(levelname)s] [%(module)s.%(funcName)s:%(lineno)d] - %(message)s", # モジュール名も記録
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
            logger.info(f"ロガー設定完了。ログはコンソールおよび {os.path.abspath(log_file_path)} に出力されます。")
        except Exception as e:
            # ここでのlogger.errorはまだハンドラが完全に設定されていない可能性があるのでprintも使う
            print(f"ログファイルハンドラ ({LOG_FILE_NAME}) の設定に失敗しました: {e}")
            # logger.error(f"ログファイルハンドラの設定に失敗しました: {e}") # この時点ではloggerが期待通りに動かない可能性
    else:
        # 既にハンドラが設定されている場合、既存のロガーを使用することを通知
        # logger.info("ロガーは既に設定されています。") # setup_loggerが呼ばれるたびに出るのは冗長なのでコメントアウト
        pass

    return logging.getLogger(__name__) # このモジュール用のロガーを返す (呼び出し元で使うことは少ない想定)

if __name__ == '__main__':
    # logging_utils.py を直接実行した場合のテスト用
    setup_logger()
    test_logger = logging.getLogger("test_logging_utils")
    test_logger.debug("これはデバッグメッセージです (logging_utils)")
    test_logger.info("これは情報メッセージです (logging_utils)")
    test_logger.warning("これは警告メッセージです (logging_utils)")
    test_logger.error("これはエラーメッセージです (logging_utils)")
    test_logger.critical("これは重大なエラーメッセージです (logging_utils)")

    # ルートロガー経由での出力テスト
    logging.debug("ルートロガー経由のデバッグメッセージ")
    logging.info("ルートロガー経由の情報メッセージ")

    print(f"ログファイル: {os.path.abspath(LOG_FILE_NAME)}")
