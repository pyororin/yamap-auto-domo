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
# import logging # logging_utils に集約
# import yaml # driver_utils に移動
from concurrent.futures import ThreadPoolExecutor, as_completed

# logging_utils からロガー設定関数をインポート
from .logging_utils import setup_logger

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
# my_post_interaction_utils から必要なものをインポート
from .my_post_interaction_utils import interact_with_domo_users_on_my_posts


import logging # logging_utils.setup_logger() の後で、getLogger を使うために必要

# --- Loggerの設定 ---
# logging_utils を使ってロガーを初期設定
# この呼び出しでルートロガーが設定される
setup_logger()
# このモジュール固有のロガーを取得 (推奨プラクティス)
# ルートロガーが設定されていれば、getLogger(__name__) で取得されるロガーもその設定を引き継ぐ
logger = logging.getLogger(__name__)
# --- Logger設定完了 ---


# --- 設定情報の読み込み (driver_utils経由) ---
try:
    # main_config の取得前にロガーが利用可能であることを確認
    logger.debug("メイン設定情報の読み込み開始 (driver_utils経由)")
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
    MY_POST_INTERACTION_SETTINGS = main_config.get("new_feature_my_post_interaction", {}) # 新機能の設定

    if not all([FOLLOW_BACK_SETTINGS, TIMELINE_DOMO_SETTINGS, SEARCH_AND_FOLLOW_SETTINGS, PARALLEL_PROCESSING_SETTINGS, MY_POST_INTERACTION_SETTINGS]):
        logger.warning(
            "config.yamlに主要な機能（follow_back, timeline_domo, search_and_follow, parallel_processing, new_feature_my_post_interaction）の" # MY_POST_INTERACTION_SETTINGS を警告対象に追加
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

# --- メイン処理の構造化のための関数群 ---

def initialize_driver():
    """WebDriverのオプション設定、インスタンス化、暗黙的待機設定を行います。"""
    logger.info("WebDriverを初期化します...")
    try:
        driver_options = get_driver_options()
        driver = webdriver.Chrome(options=driver_options)
        implicit_wait = main_config.get("implicit_wait_sec", 7)
        driver.implicitly_wait(implicit_wait)
        logger.info("WebDriverの初期化が完了しました。")
        return driver
    except Exception as e:
        logger.critical(f"WebDriverの初期化中にエラーが発生しました: {e}", exc_info=True)
        return None

def perform_login(driver, email, password, user_id):
    """ログイン処理を呼び出し、成功したか否かを返します。"""
    if not driver:
        logger.error("WebDriverが初期化されていないため、ログイン処理をスキップします。")
        return False

    logger.info(f"ログイン処理を開始します。email={email}, user_id={user_id}") # パスワードはログ出力しない
    try:
        if util_login(driver, email, password, user_id): # MY_USER_ID を引数に追加
            logger.info(f"ログイン成功。現在のURL: {driver.current_url}")
            return True
        else:
            logger.critical("ログインに失敗しました。")
            return False
    except Exception as e:
        logger.critical(f"ログイン処理中にエラーが発生しました: {e}", exc_info=True)
        return False

def get_shared_cookies(driver):
    """並列処理用の共有Cookieを取得します。"""
    if not driver:
        return None

    shared_cookies = None
    if PARALLEL_PROCESSING_SETTINGS.get("enable_parallel_processing", False) and \
       PARALLEL_PROCESSING_SETTINGS.get("use_cookie_sharing", True):
        try:
            shared_cookies = driver.get_cookies()
            logger.info(f"ログイン後のCookieを {len(shared_cookies)} 個取得しました。並列処理で利用します。")
        except Exception as e_cookie_get:
            logger.error(f"ログイン後のCookie取得に失敗しました: {e_cookie_get}", exc_info=True)
            shared_cookies = None
    return shared_cookies

def execute_main_tasks(driver, user_id, shared_cookies):
    """各機能（フォローバック、タイムラインDOMO、検索＆フォロー）の呼び出し制御を行い、実行結果数を返します。"""
    summary_counts = {
        'followed_back': 0,
        'timeline_domo': 0,
        'search_followed': 0,
        'search_domoed': 0,
        'my_post_followed_back': 0, # 新機能のサマリー用
        'my_post_domoed_to_user': 0  # 新機能のサマリー用
    }
    if not driver:
        logger.error("WebDriverが初期化されていないため、メインタスクの実行をスキップします。")
        return summary_counts
    if not user_id:
        logger.error("ユーザーIDが不明なため、メインタスクの実行をスキップします。")
        return summary_counts

    # フォローバック機能
    if FOLLOW_BACK_SETTINGS.get("enable_follow_back", False):
        start_time = time.time()
        logger.info("フォローバック機能呼び出し。並列処理は設定とCookieの有無に依存。")
        followed_back_count = follow_back_users_new(driver, user_id, shared_cookies_from_main=shared_cookies)
        summary_counts['followed_back'] = followed_back_count if isinstance(followed_back_count, int) else 0
        end_time = time.time()
        logger.info(f"フォローバック機能の処理時間: {end_time - start_time:.2f}秒。成功数: {summary_counts['followed_back']}")
    else:
        logger.info("フォローバック機能は設定で無効です。")

    # タイムラインDOMO機能
    if TIMELINE_DOMO_SETTINGS.get("enable_timeline_domo", False):
        start_time = time.time()
        timeline_domo_count = 0
        if PARALLEL_PROCESSING_SETTINGS.get("enable_parallel_processing", False) and shared_cookies:
            logger.info("タイムラインDOMO機能 (並列処理) を呼び出します。")
            timeline_domo_count = domo_timeline_activities_parallel(driver, shared_cookies, user_id)
        else:
            if PARALLEL_PROCESSING_SETTINGS.get("enable_parallel_processing", False) and not shared_cookies:
                logger.warning("並列処理が有効ですがCookie共有ができなかったため、タイムラインDOMOは逐次実行されます。")
            logger.info("タイムラインDOMO機能 (逐次処理) を呼び出します。")
            timeline_domo_count = domo_timeline_activities(driver)
        summary_counts['timeline_domo'] = timeline_domo_count if isinstance(timeline_domo_count, int) else 0
        end_time = time.time()
        logger.info(f"タイムラインDOMO機能の処理時間: {end_time - start_time:.2f}秒。成功数: {summary_counts['timeline_domo']}")
    else:
        logger.info("タイムラインDOMO機能は設定で無効です。")

    # 検索結果からのフォロー＆DOMO機能
    if SEARCH_AND_FOLLOW_SETTINGS.get("enable_search_and_follow", False):
        start_time = time.time()
        logger.info("検索結果からのフォロー＆DOMO機能呼び出し。並列処理は設定とCookieの有無に依存。")
        search_results = search_follow_and_domo_users(driver, user_id, shared_cookies_from_main=shared_cookies)
        if isinstance(search_results, dict):
            summary_counts['search_followed'] = search_results.get('followed', 0)
            summary_counts['search_domoed'] = search_results.get('domoed', 0)
        end_time = time.time()
        logger.info(f"検索結果からのフォロー＆DOMO機能の処理時間: {end_time - start_time:.2f}秒。フォロー数: {summary_counts['search_followed']}, DOMO数: {summary_counts['search_domoed']}")
    else:
        logger.info("検索結果からのフォロー＆DOMO機能は設定で無効です。")

    # 自分自身の投稿へのDOMOユーザーインタラクション機能
    # この機能は MY_POST_INTERACTION_SETTINGS を直接参照するため、ここで main_config から読み込む必要はない
    # my_post_interaction_utils 内部で _get_my_post_interaction_settings() を使って取得する
    if MY_POST_INTERACTION_SETTINGS.get("enable_my_post_interaction", False): # main_configから直接有効性を確認
        start_time = time.time()
        logger.info("自分の投稿へのDOMOユーザーインタラクション機能を呼び出します。")
        # interact_with_domo_users_on_my_posts は (followed_count, domoed_count) を返す
        mpi_followed_count, mpi_domoed_count = interact_with_domo_users_on_my_posts(driver, user_id, shared_cookies)
        summary_counts['my_post_followed_back'] = mpi_followed_count
        summary_counts['my_post_domoed_to_user'] = mpi_domoed_count
        end_time = time.time()
        logger.info(f"自分の投稿へのDOMOユーザーインタラクション機能の処理時間: {end_time - start_time:.2f}秒。")
        logger.info(f"  インタラクションによるフォローバック数: {mpi_followed_count}, DOMOユーザーへのDOMO数: {mpi_domoed_count}")
    else:
        logger.info("自分の投稿へのDOMOユーザーインタラクション機能は設定で無効です。")

    return summary_counts


def main():
    """スクリプト全体の処理フローを制御します。"""
    logger.info(f"=========== {os.path.basename(__file__)} スクリプト開始 ===========")
    driver = None
    try:
        driver = initialize_driver()
        if not driver:
            logger.critical("WebDriverの初期化に失敗したため、処理を中止します。")
            return

        if perform_login(driver, YAMAP_EMAIL, YAMAP_PASSWORD, MY_USER_ID):
            shared_cookies = get_shared_cookies(driver)
            summary = execute_main_tasks(driver, MY_USER_ID, shared_cookies)
            logger.info("全ての有効な処理が完了しました。")

            # サマリー情報の出力
            logger.info("--- 実行結果サマリー ---")
            if summary:
                logger.info(f"  フォローバック成功数: {summary.get('followed_back', 0)} 件")
                logger.info(f"  タイムラインDOMO数: {summary.get('timeline_domo', 0)} 件")
                logger.info(f"  検索からの新規フォロー数: {summary.get('search_followed', 0)} 件")
                logger.info(f"  検索からのDOMO数 (フォロー後): {summary.get('search_domoed', 0)} 件")
                logger.info(f"  自分の投稿へのインタラクション - フォローバック数: {summary.get('my_post_followed_back', 0)} 件")
                logger.info(f"  自分の投稿へのインタラクション - DOMOユーザーへのDOMO数: {summary.get('my_post_domoed_to_user', 0)} 件")
            else:
                logger.info("  サマリー情報の取得に失敗しました。")
            logger.info("----------------------")

            time.sleep(3) # 処理完了後の状態を少し確認できるように
        else:
            # perform_login 内で既にクリティカルログが出力されているはず
            logger.info("ログインに失敗したため、後続処理は実行されませんでした。")

    except Exception as main_e:
        logger.critical("スクリプト実行中に予期せぬ致命的なエラーが発生しました。", exc_info=True)
    finally:
        if driver:
            logger.info("ブラウザを閉じるまで5秒待機します...")
            time.sleep(5)
            driver.quit()
            logger.info("ブラウザを終了しました。")
        logger.info(f"=========== {os.path.basename(__file__)} スクリプト終了 ===========")

# --- mainブロック ---
if __name__ == "__main__":
    main()
