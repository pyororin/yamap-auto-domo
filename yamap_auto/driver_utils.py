# coding: utf-8
# ==============================================================================
# WebDriver関連ユーティリティ (driver_utils.py)
#
# 概要:
#   Selenium WebDriverの初期化、ログイン処理、Cookie関連処理など、
#   WebDriver操作の基本的な機能を提供するモジュール。
# ==============================================================================

import logging
import os
import time
import yaml

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# --- Loggerの設定 ---
# このモジュール用のロガーを取得します。
# ロガーの基本的な設定（レベル、ハンドラ、フォーマッタ）は、
# メインスクリプト (例: yamap_auto_domo.py) で行われることを想定しています。
logger = logging.getLogger(__name__)

# --- 設定ファイルのパス定義 ---
# このモジュールが yamap_auto ディレクトリ内にあることを前提としてパスを構築します。
# __file__ はこのファイル (driver_utils.py) のパスを指します。
_MODULE_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(_MODULE_DIR, "config.yaml")
CREDENTIALS_FILE = os.path.join(_MODULE_DIR, "credentials.yaml")

# --- グローバル変数 (設定情報) ---
# これらの変数は、初回アクセス時に `load_settings()` によってロードされます。
# モジュール外からは `get_main_config()` や `get_credentials()` でアクセスすることを推奨。
_main_config = None
_credentials_config = None
_YAMAP_EMAIL = None
_YAMAP_PASSWORD = None
_MY_USER_ID = None

# --- 定数 ---
BASE_URL = "https://yamap.com" # create_driver_with_cookies で使用
LOGIN_URL = f"{BASE_URL}/login"

def load_settings(force_reload=False):
    """
    設定ファイル (config.yaml, credentials.yaml) を読み込み、グローバル変数に格納します。
    既に読み込み済みの場合は、force_reload=True でない限り再読み込みしません。

    Args:
        force_reload (bool): Trueの場合、既に設定が読み込まれていても強制的に再読み込みします。

    Raises:
        FileNotFoundError: 設定ファイルが見つからない場合。
        yaml.YAMLError: YAMLファイルの解析に失敗した場合。
        ValueError: 設定ファイルの内容が不正な場合。
    """
    global _main_config, _credentials_config, _YAMAP_EMAIL, _YAMAP_PASSWORD, _MY_USER_ID

    if _main_config and _credentials_config and not force_reload:
        logger.debug("設定は既に読み込み済みです。")
        return

    logger.info(f"設定ファイル ({CONFIG_FILE}, {CREDENTIALS_FILE}) を読み込みます...")
    try:
        # 1. `credentials.yaml` (認証情報ファイル) の読み込み
        try:
            with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
                loaded_credentials = yaml.safe_load(f)
            if not loaded_credentials:
                raise ValueError("認証ファイルが空か、内容を読み取れませんでした。")

            email = loaded_credentials.get("email")
            password = loaded_credentials.get("password")
            user_id = str(loaded_credentials.get("user_id", ""))

            if not all([email, password, user_id]):
                err_msg = f"認証ファイル ({CREDENTIALS_FILE}) に email, password, user_id のいずれかが正しく設定されていません。"
                logger.critical(err_msg)
                raise ValueError(err_msg)

            _credentials_config = loaded_credentials
            _YAMAP_EMAIL = email
            _YAMAP_PASSWORD = password
            _MY_USER_ID = user_id
            logger.info("認証情報を正常に読み込みました。")

        except FileNotFoundError:
            err_msg = f"認証ファイル ({CREDENTIALS_FILE}) が見つかりません。"
            logger.critical(err_msg)
            raise
        except (yaml.YAMLError, ValueError) as e_cred:
            err_msg = f"認証ファイル ({CREDENTIALS_FILE}) の形式が不正か、内容に問題があります。エラー: {e_cred}"
            logger.critical(err_msg)
            raise

        # 2. `config.yaml` (メイン設定ファイル) の読み込み
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded_main_config = yaml.safe_load(f)
            if not loaded_main_config:
                raise ValueError("メインの設定ファイル (config.yaml) が空か、内容を読み取れませんでした。")
            _main_config = loaded_main_config
            logger.info("メイン設定ファイルを正常に読み込みました。")

        except FileNotFoundError:
            err_msg = f"メイン設定ファイル ({CONFIG_FILE}) が見つかりません。"
            logger.critical(err_msg)
            raise
        except (yaml.YAMLError, ValueError) as e_main_conf:
            err_msg = f"メイン設定ファイル ({CONFIG_FILE}) の形式が不正か、内容に問題があります。エラー: {e_main_conf}"
            logger.critical(err_msg)
            raise

        logger.info("全ての設定ファイルの読み込みが完了しました。")

    except Exception as e:
        logger.critical(f"設定ファイルの読み込み中に予期せぬエラーが発生しました: {e}", exc_info=True)
        # モジュールレベル変数をリセットして、不正な状態を防ぐ
        _main_config = None
        _credentials_config = None
        _YAMAP_EMAIL = None
        _YAMAP_PASSWORD = None
        _MY_USER_ID = None
        raise # エラーを再送出して呼び出し元に通知

def get_main_config():
    """メイン設定 (config.yaml) を返します。未ロードの場合はロード試行します。"""
    if not _main_config:
        load_settings()
    return _main_config

def get_credentials():
    """認証情報 (credentials.yaml) を返します。未ロードの場合はロード試行します。"""
    if not _credentials_config:
        load_settings()
    return {
        "email": _YAMAP_EMAIL,
        "password": _YAMAP_PASSWORD,
        "user_id": _MY_USER_ID
    }

# --- WebDriver関連 ---

def get_driver_options():
    """
    Selenium WebDriver (Chrome) のオプションを設定します。
    `config.yaml` の `headless_mode` 設定に基づいて、ヘッドレスモードの有効/無効を切り替えます。

    Returns:
        webdriver.ChromeOptions: 設定済みのChromeオプションオブジェクト。
    """
    main_conf = get_main_config() # 設定を確実にロード
    options = webdriver.ChromeOptions()
    if main_conf.get("headless_mode", False):
        logger.info("ヘッドレスモードで起動します。")
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
    return options

def login(driver, email, password, user_id_for_check):
    """
    指定されたメールアドレスとパスワードを使用してYAMAPにログインします。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        email (str): YAMAPのログインに使用するメールアドレス。
        password (str): YAMAPのログインに使用するパスワード。
        user_id_for_check (str): ログイン成功判定に使用するユーザーID。

    Returns:
        bool: ログインに成功した場合はTrue、失敗した場合はFalse。
    """
    logger.info(f"ログインページ ({LOGIN_URL}) にアクセスします...")
    driver.get(LOGIN_URL)
    try:
        email_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "email"))
        )
        email_field.send_keys(email)

        password_field = driver.find_element(By.NAME, "password")
        password_field.send_keys(password)

        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()

        WebDriverWait(driver, 15).until_not(EC.url_contains("login"))

        current_url_lower = driver.current_url.lower()
        page_title_lower = driver.title.lower()

        if not user_id_for_check:
             logger.warning("user_id_for_checkが設定されていません。ログイン成功判定の一部が機能しません。")

        if "login" not in current_url_lower and \
           ("yamap" in current_url_lower or \
            (user_id_for_check and user_id_for_check in current_url_lower) or \
            "timeline" in current_url_lower or \
            "home" in current_url_lower or \
            "discover" in current_url_lower):
            logger.info("ログインに成功しました。(URLベース判定)")
            return True
        elif "ようこそ" in page_title_lower or "welcome" in page_title_lower:
             logger.info("ログインに成功しました。(ページタイトル判定)")
             return True
        else:
            logger.error("ログインに失敗したか、予期せぬページに遷移しました。")
            logger.error(f"現在のURL: {driver.current_url}, タイトル: {driver.title}")
            try:
                error_message_element = driver.find_element(By.CSS_SELECTOR, "div[class*='ErrorText'], p[class*='error-message'], div[class*='FormError']")
                if error_message_element and error_message_element.is_displayed():
                    logger.error(f"ページ上のエラーメッセージ: {error_message_element.text.strip()}")
            except NoSuchElementException:
                logger.debug("ページ上にログインエラーメッセージ要素は見つかりませんでした。")
            return False

    except Exception as e:
        logger.error(f"ログイン処理中に予期せぬエラーが発生しました。", exc_info=True)
        return False

def create_driver_with_cookies(cookies, base_url_to_visit_first=BASE_URL):
    """
    指定されたCookieを設定済みの新しいWebDriverインスタンスを作成します。
    Cookieを設定する前に、一度そのドメインのページにアクセスする必要があります。

    Args:
        cookies (list[dict]): 設定するCookieのリスト。
        base_url_to_visit_first (str, optional): Cookie設定前にアクセスするURL。

    Returns:
        webdriver.Chrome or None: Cookie設定済みのWebDriverインスタンス。失敗時はNone。
    """
    logger.debug("新しいWebDriverインスタンスを作成し、Cookieを設定します...")
    main_conf = get_main_config() # 設定を確実にロード
    driver = None
    try:
        options = get_driver_options()
        driver = webdriver.Chrome(options=options)
        implicit_wait = main_conf.get("implicit_wait_sec", 7)
        driver.implicitly_wait(implicit_wait)

        logger.debug(f"Cookie設定のため、ベースURL ({base_url_to_visit_first}) にアクセスします。")
        driver.get(base_url_to_visit_first)
        time.sleep(0.5)

        for cookie in cookies:
            if 'domain' in cookie and not base_url_to_visit_first.endswith(cookie['domain'].lstrip('.')):
                logger.warning(f"Cookieのドメイン '{cookie['domain']}' とアクセス先ドメインが一致しないため、このCookieのドメイン情報を削除して試みます: {cookie}")
                del cookie['domain']
            try:
                driver.add_cookie(cookie)
            except Exception as e_cookie_add:
                logger.error(f"Cookie追加中にエラーが発生しました: {cookie}, エラー: {e_cookie_add}")

        logger.debug(f"{len(cookies)}個のCookieを新しいWebDriverインスタンスに設定しました。")
        driver.get(base_url_to_visit_first) # 再度アクセスしてセッション確認
        time.sleep(0.5)
        return driver
    except Exception as e:
        logger.error(f"Cookie付きWebDriver作成中にエラー: {e}", exc_info=True)
        if driver:
            driver.quit()
        return None

# モジュールロード時に設定を読み込む (オプション)
# load_settings()
# アプリケーションの起動時に明示的に呼び出す方が制御しやすい場合もある。
# 今回は、各get関数内で必要に応じてロードする形を採用。

if __name__ == '__main__':
    # このモジュールが直接実行された場合のテストコードなど (任意)
    # 例: ロガーの基本設定をして、設定読み込みを試す
    logging.basicConfig(level=logging.DEBUG, format="[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] - %(message)s")
    logger.info("driver_utils.py を直接実行テスト")
    try:
        load_settings(force_reload=True)
        main_cfg = get_main_config()
        creds = get_credentials()
        logger.info(f"メイン設定の headless_mode: {main_cfg.get('headless_mode')}")
        logger.info(f"認証情報の email: {creds.get('email')}")
        logger.info(f"認証情報の user_id: {creds.get('user_id')}")

        # 簡単なWebDriver起動テスト (ヘッドレスモード推奨)
        if main_cfg.get("headless_mode"):
            logger.info("ヘッドレスモードで簡単なWebDriver起動テストを開始...")
            test_options = get_driver_options()
            test_driver = None
            try:
                test_driver = webdriver.Chrome(options=test_options)
                logger.info(f"テスト用WebDriver ({'ヘッドレス' if test_options.headless else '通常'}) 起動成功。")
                test_driver.get(BASE_URL)
                logger.info(f"YAMAPトップページ ({BASE_URL}) アクセス成功。タイトル: {test_driver.title}")
                time.sleep(1)
            except Exception as e_wd_test:
                logger.error(f"WebDriver起動テスト中にエラー: {e_wd_test}", exc_info=True)
            finally:
                if test_driver:
                    test_driver.quit()
                logger.info("テスト用WebDriver終了。")
        else:
            logger.info("ヘッドレスモードが無効なため、WebDriver起動テストはスキップします。")

    except Exception as e_test:
        logger.error(f"driver_utils.py のテスト実行中にエラー: {e_test}", exc_info=True)
