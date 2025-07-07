# coding: utf-8
# ==============================================================================
# YAMAP 自動操作スクリプト (yamap_auto_domo.py)
#
# 概要:
#   このスクリプトは、Seleniumを使用してYAMAPウェブサイト上での一部の操作を自動化します。
#   主な機能として、ログイン、フォローバック、タイムラインへのDOMO、
#   活動記録検索結果からのユーザーフォローおよびDOMOなどが含まれます。
#   並列処理によるタイムラインDOMOもサポートしています（実験的）。
#
# 依存ファイル:
#   - yamap_auto/config.yaml: スクリプトの動作設定を記述する設定ファイル。
#   - yamap_auto/credentials.yaml: YAMAPへのログイン認証情報（メールアドレス、パスワード、ユーザーID）を記述するファイル。
#
# 注意事項:
#   - このスクリプトの使用は、YAMAPの利用規約に従って自己責任で行ってください。
#     自動化ツールの使用が規約に抵触する場合があり、アカウントに影響が出る可能性があります。
#   - セレクタはYAMAPのウェブサイト構造に依存しているため、サイトのアップデートにより動作しなくなることがあります。
#     定期的なメンテナンスやセレクタの更新が必要になる場合があります。
#   - 過度な連続アクセスはサーバーに負荷をかける可能性があるため、設定ファイル内の遅延時間を適切に設定してください。
# ==============================================================================

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys # 現状直接は使われていないが、将来的な拡張のために残す
import time
import json # 現状直接は使われていないが、将来的な拡張のために残す (Cookie保存/読込など)
import os
import re # 現状直接は使われていないが、将来的な拡張のために残す (URLやテキストのパターンマッチなど)
import logging
# import yaml # driver_utils に移動
from concurrent.futures import ThreadPoolExecutor, as_completed

# driver_utils から必要なものをインポート
from .driver_utils import (
    get_driver_options,
    login as util_login, # login関数名がローカルにも存在しうるため別名でインポート
    create_driver_with_cookies,
    get_main_config,
    get_credentials,
    # BASE_URL as UTIL_BASE_URL, # driver_utils側のBASE_URLは内部利用とし、こちらは維持
    # LOGIN_URL as UTIL_LOGIN_URL # 同上
)
# user_profile_utils から必要なものをインポート
from .user_profile_utils import (
    get_latest_activity_url,
    get_user_follow_counts,
    find_follow_button_on_profile_page
)
# domo_utils から必要なものをインポート
from .domo_utils import (
    domo_activity,
    domo_timeline_activities,
    domo_timeline_activities_parallel,
    # domo_activity_task は domo_utils 内部でのみ使用されるため、ここではインポート不要
)
# follow_utils から必要なものをインポート
from .follow_utils import (
    find_follow_button_in_list_item,
    click_follow_button_and_verify,
    # search_follow_and_domo_users, # search_utils へ移動
    # follow_back_users_new, # follow_back_utils へ移動
)
# search_utils から必要なものをインポート
from .search_utils import search_follow_and_domo_users
# follow_back_utils から必要なものをインポート
from .follow_back_utils import follow_back_users_new


# --- Loggerの設定 ---
# スクリプトの動作状況やエラー情報をログとして記録するための設定。
# コンソールとファイルの両方に出力します。
# この設定は driver_utils を含む他のモジュールにも影響します。
LOG_FILE_NAME = "yamap_auto_domo.log" # ログファイル名
logger = logging.getLogger() # ルートロガーを取得または生成
if not logger.handlers: # ハンドラがまだ設定されていない場合のみ設定（多重設定防止）
    logger.setLevel(logging.DEBUG) # ロガー自体のレベルはDEBUGに設定 (ハンドラ側でフィルタリング)

    # StreamHandler (コンソールへのログ出力設定)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO) # コンソールにはINFOレベル以上のログを出力
    stream_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    stream_handler.setFormatter(stream_formatter)
    logger.addHandler(stream_handler)

    # FileHandler (ログファイルへの出力設定)
    try:
        file_handler = logging.FileHandler(LOG_FILE_NAME, encoding='utf-8', mode='a') # 'a'モードで追記
        file_handler.setLevel(logging.DEBUG) # ファイルにはDEBUGレベル以上のログを全て記録
        file_formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(funcName)s:%(lineno)d] - %(message)s", # 関数名と行番号も記録
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        # ここでのlogger.errorはまだハンドラが完全に設定されていない可能性があるのでprintも使う
        print(f"ログファイルハンドラ ({LOG_FILE_NAME}) の設定に失敗しました: {e}")
        logger.error(f"ログファイルハンドラの設定に失敗しました: {e}")
else:
    logger = logging.getLogger(__name__) # 既に設定済みの場合は、このモジュール用のロガーを取得
# --- Logger設定完了 ---


# --- 設定情報の読み込み (driver_utils経由) ---
try:
    main_config = get_main_config()
    credentials = get_credentials()
    YAMAP_EMAIL = credentials.get("email")
    YAMAP_PASSWORD = credentials.get("password")
    MY_USER_ID = credentials.get("user_id")

    if not all([YAMAP_EMAIL, YAMAP_PASSWORD, MY_USER_ID, main_config]):
        logger.critical("設定情報 (main_config または credentials) の取得に失敗しました。driver_utilsからの読み込みを確認してください。")
        exit()

    # 各機能ごとの設定セクションを読み込み (存在しない場合は空の辞書として扱う)
    DOMO_SETTINGS = main_config.get("domo_settings", {})
    FOLLOW_SETTINGS = main_config.get("follow_settings", {})
    FOLLOW_BACK_SETTINGS = main_config.get("follow_back_settings", {})
    TIMELINE_DOMO_SETTINGS = main_config.get("timeline_domo_settings", {})
    SEARCH_AND_FOLLOW_SETTINGS = main_config.get("search_and_follow_settings", {})
    PARALLEL_PROCESSING_SETTINGS = main_config.get("parallel_processing_settings", {})

    if not all([FOLLOW_BACK_SETTINGS, TIMELINE_DOMO_SETTINGS, SEARCH_AND_FOLLOW_SETTINGS, PARALLEL_PROCESSING_SETTINGS]):
        logger.warning(
            "config.yamlに新しい機能（follow_back_settings, timeline_domo_settings, search_and_follow_settings, parallel_processing_settings）の"
            "一部または全ての設定セクションが見つからないか空です。デフォルト値で動作しようとしますが、"
            "意図した動作をしない可能性があります。config.yamlを確認してください。"
        )

except Exception as e: # 設定読み込み中の予期せぬエラー
    logger.critical(f"設定情報の読み込み中に致命的なエラーが発生しました (driver_utils経由): {e}", exc_info=True)
    exit()
# --- 設定情報の読み込み完了 ---


# --- グローバル定数 ---
# YAMAPウェブサイトの基本的なURLなどを定義します。
# driver_utils 側にも BASE_URL はあるが、こちらはメインスクリプト側のグローバル定数として維持
BASE_URL = "https://yamap.com"
# LOGIN_URL は driver_utils 側で定義・使用されるため、ここでは不要 (または driver_utils からインポート)
# LOGIN_URL = f"{BASE_URL}/login" # 不要になった
TIMELINE_URL = f"{BASE_URL}/timeline"
SEARCH_ACTIVITIES_URL_DEFAULT = f"{BASE_URL}/search/activities"

# --- WebDriver関連の関数は driver_utils に移動したため、ここでは削除 ---
# def get_driver_options(): ...
# def login(driver, email, password): ...
# def create_driver_with_cookies(cookies, base_url_to_visit_first="https://yamap.com/"): ...


# --- DOMO関連補助関数 (yamap_auto.pyから移植・調整) ---
# (get_latest_activity_url, find_follow_button_on_profile_page, get_user_follow_counts はユーザープロフィール操作関連として後述)

# --- フォロー関連補助関数は follow_utils.py に移動 ---
# def find_follow_button_in_list_item(user_list_item_element): ... (削除)
# def click_follow_button_and_verify(driver, follow_button_element, user_name_for_log=""): ... (削除)


# --- DOMO関連補助関数は domo_utils.py に移動 ---
# def domo_activity(driver, activity_url): ... (削除)
# --- タイムラインDOMO機能群は domo_utils.py に移動 ---
# def domo_timeline_activities(driver): ... (削除)
# def domo_activity_task(activity_url, shared_cookies, task_delay_sec): ... (削除)
# def domo_timeline_activities_parallel(driver, shared_cookies): ... (削除)
# --- 検索からのフォロー＆DOMO機能とフォローバック機能は follow_utils.py に移動 ---
# def search_follow_and_domo_users(driver, current_user_id): ... (削除)
# def follow_back_users_new(driver, current_user_id): ... (削除)

# --- mainブロック (テスト用) ---
if __name__ == "__main__":
    logger.info(f"=========== {os.path.basename(__file__)} スクリプト開始 ===========")
    driver = None
    try:
        # driver_utilsからWebDriverオプションを取得
        driver_options = get_driver_options() # これは driver_utils.get_driver_options() を指す
        driver = webdriver.Chrome(options=driver_options)

        # implicit_wait_sec は main_config (driver_utils経由で取得済み) から読む
        implicit_wait = main_config.get("implicit_wait_sec", 7)
        driver.implicitly_wait(implicit_wait)

        logger.info(f"認証情報: email={YAMAP_EMAIL}, user_id={MY_USER_ID}") # パスワードはログ出力しない

        # driver_utils の login (util_loginとしてインポート) を使用
        if util_login(driver, YAMAP_EMAIL, YAMAP_PASSWORD, MY_USER_ID): # MY_USER_ID を引数に追加
            logger.info(f"ログイン成功。現在のURL: {driver.current_url}")
            shared_cookies = None
            if PARALLEL_PROCESSING_SETTINGS.get("enable_parallel_processing", False) and \
               PARALLEL_PROCESSING_SETTINGS.get("use_cookie_sharing", True):
                try:
                    shared_cookies = driver.get_cookies()
                    logger.info(f"ログイン後のCookieを {len(shared_cookies)} 個取得しました。並列処理で利用します。")
                except Exception as e_cookie_get:
                    logger.error(f"ログイン後のCookie取得に失敗しました: {e_cookie_get}", exc_info=True)
                    shared_cookies = None

            # --- 各機能の呼び出し ---
            if MY_USER_ID: # MY_USER_ID は driver_utils 経由で取得済み
                # フォローバック機能
                if FOLLOW_BACK_SETTINGS.get("enable_follow_back", False):
                    start_time = time.time()
                    # shared_cookies が取得できていればそれを渡し、並列処理を試みる
                    # follow_back_users_new 内部で並列設定が無効、またはCookieがない場合は逐次処理にフォールバックされる
                    logger.info("フォローバック機能呼び出し。並列処理は設定とCookieの有無に依存。")
                    follow_back_users_new(driver, MY_USER_ID, shared_cookies_from_main=shared_cookies)
                    end_time = time.time()
                    logger.info(f"フォローバック機能の処理時間: {end_time - start_time:.2f}秒")
                else:
                    logger.info("フォローバック機能は設定で無効です。")

                # タイムラインDOMO機能
                if TIMELINE_DOMO_SETTINGS.get("enable_timeline_domo", False):
                    start_time = time.time()
                    if PARALLEL_PROCESSING_SETTINGS.get("enable_parallel_processing", False) and shared_cookies:
                        domo_timeline_activities_parallel(driver, shared_cookies, MY_USER_ID) # MY_USER_ID を追加
                    else:
                        if PARALLEL_PROCESSING_SETTINGS.get("enable_parallel_processing", False) and not shared_cookies:
                            logger.warning("並列処理が有効ですがCookie共有ができなかったため、タイムラインDOMOは逐次実行されます。")
                        domo_timeline_activities(driver) # 従来の逐次実行
                    end_time = time.time()
                    logger.info(f"タイムラインDOMO機能の処理時間: {end_time - start_time:.2f}秒")
                else:
                    logger.info("タイムラインDOMO機能は設定で無効です。")

                # 検索結果からのフォロー＆DOMO機能
                if SEARCH_AND_FOLLOW_SETTINGS.get("enable_search_and_follow", False):
                    start_time = time.time()
                    logger.info("検索結果からのフォロー＆DOMO機能呼び出し。並列処理は設定とCookieの有無に依存。")
                    search_follow_and_domo_users(driver, MY_USER_ID, shared_cookies_from_main=shared_cookies)
                    end_time = time.time()
                    logger.info(f"検索結果からのフォロー＆DOMO機能の処理時間: {end_time - start_time:.2f}秒")
                else:
                    logger.info("検索結果からのフォロー＆DOMO機能は設定で無効です。")

            else:
                logger.error("MY_USER_IDが不明なため、ユーザーIDが必要な機能は実行できません。")

            logger.info("全ての有効な処理が完了しました。")
            time.sleep(3) # 処理完了後の状態を少し確認できるように
        else:
            logger.critical("ログインに失敗したため、処理を中止します。")

    except Exception as main_e:
        logger.critical("スクリプト実行中に予期せぬ致命的なエラーが発生しました。", exc_info=True)
    finally:
        if driver:
            logger.info("ブラウザを閉じるまで5秒待機します...")
            time.sleep(5)
            driver.quit()
            logger.info("ブラウザを終了しました。")
        logger.info(f"=========== {os.path.basename(__file__)} スクリプト終了 ===========")
