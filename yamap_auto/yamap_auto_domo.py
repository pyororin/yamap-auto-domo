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
import datetime # datetime をインポート

# user_profile_utils から必要なものをインポート
from .user_profile_utils import (
    get_latest_activity_url,
    get_user_follow_counts,
    find_follow_button_on_profile_page,
    get_last_activity_date, # 追加
    get_my_following_users_profiles, # 追加
    is_user_following_me, # 追加
    get_my_followers_profiles # is_user_following_me のために追加 (my_followers_list を事前に取得する場合)
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
    unfollow_user, # 追加
    # search_follow_and_domo_users, # search_utils へ移動
    # follow_back_users_new, # follow_back_utils へ移動
)
# search_utils から必要なものをインポート
from .search_utils import search_follow_and_domo_users
# follow_back_utils から必要なものをインポート
from .follow_back_utils import follow_back_users_new
# my_post_interaction_utils から必要なものをインポート
from .my_post_interaction_utils import (
    # interact_with_domo_users_on_my_posts, # Removed
    domo_back_to_past_domo_users # 新機能の関数をインポート
)


import logging # logging_utils.setup_logger() の後で、getLogger を使うために必要

# --- Loggerの設定 ---
# logging_utils を使ってロガーを初期設定
# この呼び出しでルートロガーが設定される
setup_logger()
# このモジュール固有のロガーを取得 (推奨プラクティス)
# ルートロガーが設定されていれば、getLogger(__name__) で取得されるロガーもその設定を引き継ぐ
logger = logging.getLogger(__name__)
# --- Logger設定完了 ---

import shutil # ディレクトリ操作のために追加

# --- ログディレクトリのクリーンアップ ---
# スクリプトの実行ディレクトリの 'logs' サブディレクトリを対象とする
# __file__ はこのスクリプトのフルパス
# os.path.dirname(__file__) はこのスクリプトがあるディレクトリ (yamap_auto)
# その親ディレクトリがリポジトリルートになる
_SCRIPT_DIR = os.path.dirname(__file__)
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR) # リポジトリルートを想定
LOGS_DIR_TO_CLEAR = os.path.join(_REPO_ROOT, "logs")

if os.path.exists(LOGS_DIR_TO_CLEAR):
    logger.info(f"既存のログディレクトリ '{LOGS_DIR_TO_CLEAR}' の中身をクリアします...")
    for item_name in os.listdir(LOGS_DIR_TO_CLEAR):
        item_path = os.path.join(LOGS_DIR_TO_CLEAR, item_name)
        try:
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.unlink(item_path)
                logger.debug(f"  削除: {item_path} (ファイル/リンク)")
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
                logger.debug(f"  削除: {item_path} (ディレクトリ)")
        except Exception as e_clear:
            logger.warning(f"  ログディレクトリ内のアイテム '{item_path}' の削除に失敗しました: {e_clear}")
    logger.info(f"ログディレクトリ '{LOGS_DIR_TO_CLEAR}' のクリーンアップ完了。")
else:
    logger.info(f"ログディレクトリ '{LOGS_DIR_TO_CLEAR}' は存在しないため、クリーンアップはスキップします。")
# --- ログディレクトリのクリーンアップ完了 ---


# --- 設定情報の読み込み (driver_utils経由) ---
try:
    # main_config の取得前にロガーが利用可能であることを確認
    logger.debug("メイン設定情報の読み込み開始 (driver_utils経由)")
    main_config = get_main_config()
    # credentials = get_credentials() # 環境変数から読み込むためコメントアウト
    # YAMAP_EMAIL = credentials.get("email") # 環境変数から読み込む
    # YAMAP_PASSWORD = credentials.get("password") # 環境変数から読み込む
    # MY_USER_ID = credentials.get("user_id") # credentials.yaml から引き続き読み込む

    YAMAP_EMAIL = os.environ.get("YAMAP_LOGIN_ID")
    YAMAP_PASSWORD = os.environ.get("YAMAP_LOGIN_PASSWORD")

    # MY_USER_ID は引き続き credentials.yaml から読み込む想定
    # credentials.yaml の読み込み処理は get_credentials() に残っている前提
    # ただし、YAMAP_EMAIL と YAMAP_PASSWORD が環境変数から取得できなかった場合のフォールバックは考慮しない
    credentials_data_for_userid = get_credentials()
    MY_USER_ID = credentials_data_for_userid.get("user_id")


    if not all([YAMAP_EMAIL, YAMAP_PASSWORD, MY_USER_ID, main_config]):
        missing_items = []
        if not YAMAP_EMAIL: missing_items.append("YAMAP_LOGIN_ID (環境変数)")
        if not YAMAP_PASSWORD: missing_items.append("YAMAP_LOGIN_PASSWORD (環境変数)")
        if not MY_USER_ID: missing_items.append("user_id (credentials.yaml)")
        if not main_config: missing_items.append("main_config (config.yaml)")
        logger.critical(f"必須の設定情報が不足しています: {', '.join(missing_items)}。処理を中止します。")
        exit()
    else:
        logger.info("環境変数と設定ファイルから情報を正常に読み込みました。")
        logger.info(f"  YAMAP_LOGIN_ID (from env): {'設定済み' if YAMAP_EMAIL else '未設定'}")
        # パスワード自体はログに出力しない
        logger.info(f"  YAMAP_LOGIN_PASSWORD (from env): {'設定済み' if YAMAP_PASSWORD else '未設定'}")
        logger.info(f"  user_id (from credentials.yaml): {MY_USER_ID if MY_USER_ID else '未設定'}")


    # 各機能ごとの設定セクションを読み込み (存在しない場合は空の辞書として扱う)
    DOMO_SETTINGS = main_config.get("domo_settings", {})
    FOLLOW_SETTINGS = main_config.get("follow_settings", {})
    FOLLOW_BACK_SETTINGS = main_config.get("follow_back_settings", {})
    TIMELINE_DOMO_SETTINGS = main_config.get("timeline_domo_settings", {})
    SEARCH_AND_FOLLOW_SETTINGS = main_config.get("search_and_follow_settings", {})
    PARALLEL_PROCESSING_SETTINGS = main_config.get("parallel_processing_settings", {})
    # MY_POST_INTERACTION_SETTINGS = main_config.get("new_feature_my_post_interaction", {}) # Removed
    UNFOLLOW_INACTIVE_SETTINGS = main_config.get("unfollow_inactive_users_settings", {}) # 新機能の設定読み込み

    # 主要な設定セクションの存在確認 (UNFOLLOW_INACTIVE_SETTINGS も対象に追加)
    essential_settings = [
        FOLLOW_BACK_SETTINGS,
        TIMELINE_DOMO_SETTINGS,
        SEARCH_AND_FOLLOW_SETTINGS,
        PARALLEL_PROCESSING_SETTINGS,
        # MY_POST_INTERACTION_SETTINGS, # Removed
        UNFOLLOW_INACTIVE_SETTINGS
    ]
    essential_setting_names = [
        "follow_back_settings",
        "timeline_domo_settings",
        "search_and_follow_settings",
        "parallel_processing_settings",
        # "new_feature_my_post_interaction", # Removed
        "unfollow_inactive_users_settings"
    ]

    missing_settings = [name for setting, name in zip(essential_settings, essential_setting_names) if not setting]

    if missing_settings:
        logger.warning(
            f"config.yamlに主要な機能の設定セクションの一部が見つからないか空です: {', '.join(missing_settings)}。"
            "デフォルト値で動作しようとしますが、意図した動作をしない可能性があります。config.yamlを確認してください。"
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
        # 'my_post_followed_back': 0, # Removed
        # 'my_post_domoed_to_user': 0, # Removed
        'domo_back_to_past_users': 0,
        'unfollowed_inactive': 0
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

    # 自分自身の投稿へのDOMOユーザーインタラクション機能は削除されました。
    # new_feature_domo_back_to_past_domo_users がその役割を包含します。

    # 非アクティブユーザーのアンフォロー機能
    if UNFOLLOW_INACTIVE_SETTINGS.get("enable_unfollow_inactive", False):
        start_time = time.time()
        logger.info("非アクティブユーザーのアンフォロー機能を呼び出します。")
        unfollowed_count = unfollow_inactive_not_following_back_users(driver, user_id, shared_cookies)
        summary_counts['unfollowed_inactive'] = unfollowed_count if isinstance(unfollowed_count, int) else 0
        end_time = time.time()
        logger.info(f"非アクティブユーザーのアンフォロー機能の処理時間: {end_time - start_time:.2f}秒。アンフォロー数: {summary_counts['unfollowed_inactive']}")
    else:
        logger.info("非アクティブユーザーのアンフォロー機能は設定で無効です。")

    # === 過去記事DOMOユーザーへのDOMO返し機能 ===
    # この設定は my_post_interaction_utils 内部で config から読み込まれるが、
    # ここでは main_config を使って有効無効を判定し、呼び出しを制御する。
    # new_feature_domo_back_to_past_domo_users セクションを main_config から取得
    domo_back_settings = main_config.get("new_feature_domo_back_to_past_domo_users", {})
    if domo_back_settings.get("enable_domo_back_to_past_users", False):
        start_time = time.time()
        logger.info("過去記事DOMOユーザーへのDOMO返し機能を呼び出します。")
        domo_back_count = domo_back_to_past_domo_users(driver, user_id, shared_cookies)
        summary_counts['domo_back_to_past_users'] = domo_back_count
        end_time = time.time()
        logger.info(f"過去記事DOMOユーザーへのDOMO返し機能の処理時間: {end_time - start_time:.2f}秒。DOMO返し成功数: {domo_back_count}")
    else:
        logger.info("過去記事DOMOユーザーへのDOMO返し機能は設定で無効です。")

    return summary_counts


# --- Worker Task for fetching last activity date ---
def _fetch_user_last_activity_task(user_profile_url, shared_cookies_for_task, current_user_id_for_login_check):
    """
    Worker task to fetch the last activity date for a single user.
    Creates its own WebDriver instance.
    """
    task_driver = None
    user_id_log = user_profile_url.split('/')[-1].split('?')[0]
    log_prefix_task = f"[ActivityDateTask][UID:{user_id_log}] "
    logger.info(f"{log_prefix_task}Fetching last activity date for {user_profile_url}")

    try:
        task_driver = create_driver_with_cookies(shared_cookies_for_task, current_user_id_for_login_check)
        if not task_driver:
            logger.error(f"{log_prefix_task}Failed to create WebDriver or verify login for task. Cannot fetch activity date.")
            return {'url': user_profile_url, 'last_activity_date': None, 'error': 'WebDriver/Login failure in task'}

        last_activity = get_last_activity_date(task_driver, user_profile_url)

        if last_activity:
            logger.info(f"{log_prefix_task}Successfully fetched last activity date: {last_activity}")
            return {'url': user_profile_url, 'last_activity_date': last_activity, 'error': None}
        else:
            logger.warning(f"{log_prefix_task}Could not fetch last activity date.")
            return {'url': user_profile_url, 'last_activity_date': None, 'error': 'Date not found'}

    except Exception as e_task:
        logger.error(f"{log_prefix_task}Exception in fetching activity date: {e_task}", exc_info=True)
        return {'url': user_profile_url, 'last_activity_date': None, 'error': str(e_task)}
    finally:
        if task_driver:
            try:
                task_driver.quit()
                logger.debug(f"{log_prefix_task}Task WebDriver quit successfully.")
            except Exception as e_quit:
                logger.error(f"{log_prefix_task}Error quitting task WebDriver: {e_quit}", exc_info=True)

# --- Worker Task for unfollowing a user ---
def _unfollow_user_task(user_profile_url_to_unfollow, user_name_for_log, shared_cookies_for_task, current_user_id_for_login_check, unfollow_settings_for_task):
    """
    Worker task to unfollow a single user.
    Creates its own WebDriver instance.
    """
    task_driver = None
    user_id_log = user_profile_url_to_unfollow.split('/')[-1].split('?')[0]
    log_prefix_task = f"[UnfollowTask][UID:{user_id_log}] "
    logger.info(f"{log_prefix_task}Attempting to unfollow user: {user_name_for_log} ({user_profile_url_to_unfollow})")
    unfollowed_successfully = False

    try:
        task_driver = create_driver_with_cookies(shared_cookies_for_task, current_user_id_for_login_check)
        if not task_driver:
            logger.error(f"{log_prefix_task}Failed to create WebDriver or verify login for unfollow task.")
            return {'url': user_profile_url_to_unfollow, 'unfollowed': False, 'error': 'WebDriver/Login failure in task'}

        # Navigate to the user's profile page (unfollow_user from follow_utils might expect to be on the page)
        # However, `follow_utils.unfollow_user` itself handles navigation. So, direct call is fine.

        delay_before_action = unfollow_settings_for_task.get("delay_before_unfollow_action_sec", 2.0)
        logger.debug(f"{log_prefix_task}Waiting {delay_before_action}s before unfollow action.")
        time.sleep(delay_before_action)

        if unfollow_user(task_driver, user_profile_url_to_unfollow): # This is from follow_utils
            logger.info(f"{log_prefix_task}Successfully unfollowed user: {user_name_for_log}")
            unfollowed_successfully = True
        else:
            logger.warning(f"{log_prefix_task}Failed to unfollow user: {user_name_for_log}")
            # Optional: Add a small delay on failure if not handled by unfollow_user
            time.sleep(unfollow_settings_for_task.get("delay_after_action_error_sec", 1.0))


        delay_after_action = unfollow_settings_for_task.get("delay_per_worker_unfollow_sec", 2.0)
        logger.debug(f"{log_prefix_task}Waiting {delay_after_action}s after unfollow action.")
        time.sleep(delay_after_action)

        return {'url': user_profile_url_to_unfollow, 'unfollowed': unfollowed_successfully, 'error': None}

    except Exception as e_task:
        logger.error(f"{log_prefix_task}Exception during unfollow task for {user_name_for_log}: {e_task}", exc_info=True)
        return {'url': user_profile_url_to_unfollow, 'unfollowed': False, 'error': str(e_task)}
    finally:
        if task_driver:
            try:
                task_driver.quit()
                logger.debug(f"{log_prefix_task}Unfollow Task WebDriver quit successfully.")
            except Exception as e_quit:
                logger.error(f"{log_prefix_task}Error quitting Unfollow Task WebDriver: {e_quit}", exc_info=True)


def unfollow_inactive_not_following_back_users(driver, my_user_id, shared_cookies=None):
    """
    フォローしているユーザーの中で、指定された条件に基づいてユーザーをアンフォローします。
    条件：
    1. 自分をフォローバックしていない。
    2. 最終活動記録が指定日数以上前である (個別プロフィールページから並列取得)。
    3. アンフォローアクション自体も設定に応じて並列実行可能。
    """
    logger.info("非アクティブかつフォローバックしていないユーザーのアンフォロー処理を開始します。")
    settings = UNFOLLOW_INACTIVE_SETTINGS # This should be loaded from main_config at the start of the script
    if not settings.get("enable_unfollow_inactive", False):
        logger.info("設定で無効化されているため、アンフォロー処理をスキップします。")
        return 0

    inactive_threshold_days = settings.get("inactive_threshold_days", 90)
    max_to_unfollow_total = settings.get("max_users_to_unfollow_per_run", 5)
    max_pages_to_check_following = settings.get("max_pages_for_my_following_list", 10) # This might need its own config

    activity_date_workers = settings.get("parallel_profile_page_workers", 3) # Default to 3 if not set

    # Settings for parallel unfollow actions
    enable_parallel_unfollow_action = settings.get("enable_parallel_unfollow_action", False)
    unfollow_action_workers = settings.get("max_workers_unfollow_action", 3) # Default to 3

    unfollowed_this_run_count = 0

    logger.info(f"自分がフォローしているユーザーのリストとフォローバック状況を取得します (最大 {max_pages_to_check_following} ページ)。")
    my_following_user_details = get_my_following_users_profiles(driver, my_user_id, max_pages_to_check=max_pages_to_check_following)

    if not my_following_user_details:
        logger.info("フォロー中のユーザーが見つからないか、リストの取得に失敗しました。")
        return 0
    logger.info(f"{len(my_following_user_details)} 件のフォロー中ユーザー情報を取得しました。")

    non_followers_back = [
        ud for ud in my_following_user_details if not ud['is_followed_back']
    ]
    logger.info(f"{len(my_following_user_details) - len(non_followers_back)} 件は相互フォローのため対象外。")


    if not non_followers_back:
        logger.info("フォローバックしていないユーザーが見つかりませんでした。処理を終了します。")
        return 0

    logger.info(f"{len(non_followers_back)} 件のフォローバックしていないユーザーについて、最終活動日を並列で確認します (最大ワーカー数: {activity_date_workers})。")
    users_with_activity_dates = {}
    activity_futures = []
    if not shared_cookies: # Ensure shared_cookies for tasks
        logger.warning("共有Cookieが利用できません。並列タスクでのログイン状態が不安定になる可能性があります。")

    with ThreadPoolExecutor(max_workers=activity_date_workers, thread_name_prefix='ActivityDateFetch') as executor:
        for user_data in non_followers_back:
            future = executor.submit(_fetch_user_last_activity_task, user_data['url'], shared_cookies, my_user_id)
            activity_futures.append(future)

        for future in as_completed(activity_futures):
            try:
                result = future.result()
                if result and result.get('url'):
                    users_with_activity_dates[result['url']] = result.get('last_activity_date')
                    if result.get('error'):
                         logger.warning(f"ユーザー ({result['url'].split('/')[-1]}) の最終活動日取得タスクでエラー: {result['error']}")
            except Exception as e_future:
                logger.error(f"最終活動日取得の並列タスク実行中に例外: {e_future}", exc_info=True)

    logger.info(f"{len(users_with_activity_dates)}/{len(non_followers_back)} 件のフォローバックしていないユーザーの最終活動日情報を収集完了。")

    # Filter for inactive users
    inactive_unfollowed_candidates = []
    for user_data in non_followers_back:
        user_profile_url = user_data['url']
        last_activity_date = users_with_activity_dates.get(user_profile_url)
        if last_activity_date:
            days_since_last_activity = (datetime.date.today() - last_activity_date).days
            if days_since_last_activity >= inactive_threshold_days:
                inactive_unfollowed_candidates.append(user_data) # user_data includes name and url
            else:
                 logger.info(f"ユーザー {user_data['name']} ({user_profile_url.split('/')[-1]}) は活動閾値内 ({days_since_last_activity}日前)。アンフォロー対象外。")
        else:
            logger.warning(f"ユーザー {user_data['name']} ({user_profile_url.split('/')[-1]}) の最終活動日不明。アンフォロー対象外。")

    if not inactive_unfollowed_candidates:
        logger.info("非アクティブと判定されたフォローバックしていないユーザーが見つかりませんでした。")
        return 0

    logger.info(f"{len(inactive_unfollowed_candidates)} 件の非アクティブかつ未フォローバックユーザーをアンフォロー対象候補とします。")

    # Perform unfollow actions (sequentially or in parallel)
    users_to_actually_unfollow = inactive_unfollowed_candidates[:max_to_unfollow_total]
    logger.info(f"最大アンフォロー数 ({max_to_unfollow_total}) に基づき、{len(users_to_actually_unfollow)} 件を処理します。")

    if enable_parallel_unfollow_action:
        logger.info(f"アンフォローアクションを並列で実行します (最大ワーカー数: {unfollow_action_workers})。")
        unfollow_futures = []
        with ThreadPoolExecutor(max_workers=unfollow_action_workers, thread_name_prefix='UnfollowAction') as executor:
            for user_to_unfollow_data in users_to_actually_unfollow:
                if unfollowed_this_run_count >= max_to_unfollow_total: break # Redundant check, but safe

                # Pass the whole settings dict for the task to pick necessary delays
                future = executor.submit(_unfollow_user_task,
                                         user_to_unfollow_data['url'],
                                         user_to_unfollow_data['name'],
                                         shared_cookies,
                                         my_user_id,
                                         settings) # Pass the full settings dict
                unfollow_futures.append(future)

            for future in as_completed(unfollow_futures):
                try:
                    result = future.result()
                    if result and result.get('unfollowed'):
                        unfollowed_this_run_count += 1
                    if result and result.get('error'):
                        logger.error(f"並列アンフォロータスクでエラー (URL: {result.get('url', 'N/A')}): {result['error']}")
                except Exception as e_future_unfollow:
                    logger.error(f"並列アンフォロータスクの結果取得中に例外: {e_future_unfollow}", exc_info=True)
    else:
        logger.info("アンフォローアクションを逐次実行します。")
        for user_data_to_unfollow_seq in users_to_actually_unfollow:
            if unfollowed_this_run_count >= max_to_unfollow_total:
                logger.info(f"アンフォロー上限 ({max_to_unfollow_total}人) に達しました (逐次処理中)。")
                break

            user_profile_url_seq = user_data_to_unfollow_seq['url']
            user_name_seq = user_data_to_unfollow_seq['name']
            user_id_log_seq = user_profile_url_seq.split('/')[-1].split('?')[0]

            logger.info(f"--- 逐次アンフォロー試行: {user_name_seq} ({user_id_log_seq}) ---")
            delay_before_unfollow_seq = settings.get("delay_before_unfollow_action_sec", 2.0)
            logger.debug(f"    アンフォロー実行前に {delay_before_unfollow_seq} 秒待機します。")
            time.sleep(delay_before_unfollow_seq)

            # Use the main driver for sequential unfollow
            if unfollow_user(driver, user_profile_url_seq):
                logger.info(f"    ユーザー {user_name_seq} ({user_id_log_seq}) のアンフォローに成功しました。")
                unfollowed_this_run_count += 1
            else:
                logger.warning(f"    ユーザー {user_name_seq} ({user_id_log_seq}) のアンフォローに失敗しました。")
                time.sleep(settings.get("delay_after_action_error_sec", 3.0)) # Delay on error

            if unfollowed_this_run_count < max_to_unfollow_total:
                 time.sleep(settings.get("delay_per_worker_unfollow_sec", 2.0)) # Use this as delay between sequential actions too
            logger.info(f"--- 逐次アンフォロー試行完了: {user_name_seq} ({user_id_log_seq}) ---")


    logger.info(f"非アクティブユーザーのアンフォロー処理完了。この実行で合計 {unfollowed_this_run_count} 人をアンフォローしました。")
    return unfollowed_this_run_count


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
                # logger.info(f"  自分の投稿へのインタラクション - フォローバック数: {summary.get('my_post_followed_back', 0)} 件") # Removed
                # logger.info(f"  自分の投稿へのインタラクション - DOMOユーザーへのDOMO数: {summary.get('my_post_domoed_to_user', 0)} 件") # Removed
                logger.info(f"  過去記事DOMOユーザーへのDOMO返し数: {summary.get('domo_back_to_past_users', 0)} 件")
                logger.info(f"  非アクティブユーザーのアンフォロー数: {summary.get('unfollowed_inactive', 0)} 件")
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
