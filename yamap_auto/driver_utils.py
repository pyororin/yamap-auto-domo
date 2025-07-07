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
from datetime import datetime # datetime をインポート

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

def create_driver_with_cookies(cookies, current_user_id, initial_page_for_cookie_setting=BASE_URL):
    """
    指定されたCookieを設定済みの新しいWebDriverインスタンスを作成し、ログイン状態をより詳細に確認します。
    Cookieを設定する前に、一度そのドメインのページ (initial_page_for_cookie_setting) にアクセスします。
    ログイン確認は主にユーザー自身のマイページで行います。

    Args:
        cookies (list[dict]): 設定するCookieのリスト。
        current_user_id (str): ログイン確認に使用する現在のユーザーID。
        initial_page_for_cookie_setting (str, optional): Cookie設定前にアクセスする初期URL。
                                                       デフォルトは BASE_URL (https://yamap.com/)。

    Returns:
        webdriver.Chrome or None: Cookie設定およびログイン確認済みのWebDriverインスタンス。失敗時はNone。
    """
    logger.debug("新しいWebDriverインスタンスを作成し、Cookieとログイン状態を確認します...")
    main_conf = get_main_config() # 設定を確実にロード
    driver = None
    try:
        options = get_driver_options()
        driver = webdriver.Chrome(options=options)
        implicit_wait = main_conf.get("implicit_wait_sec", 7)
        driver.implicitly_wait(implicit_wait)

        logger.debug(f"Cookie設定のため、初期ページ ({initial_page_for_cookie_setting}) にアクセスします。")
        driver.get(initial_page_for_cookie_setting)
        time.sleep(0.5) # ページロード待機

        logger.debug(f"受け取ったCookie (計{len(cookies)}個) を設定します。")
        for idx, cookie in enumerate(cookies):
            # cookie_info_for_log = {k: v for k, v in cookie.items() if k != 'value'}
            # logger.debug(f"Cookie {idx+1}/{len(cookies)}: {cookie_info_for_log}")
            if 'domain' in cookie and cookie['domain'] and not initial_page_for_cookie_setting.endswith(cookie['domain'].lstrip('.')):
                original_domain = cookie['domain']
                if not original_domain.endswith(".yamap.com"):
                    del cookie['domain']
                    logger.warning(
                        f"Cookie {idx+1} のドメイン '{original_domain}' が予期されるドメインと異なり、初期ページのドメイン '{initial_page_for_cookie_setting}' "
                        f"とも一致しないため、ドメイン情報を削除して試みます。Cookie名: {cookie.get('name', 'N/A')}"
                    )
                else:
                     logger.info(f"Cookie {idx+1} のドメイン '{original_domain}' は初期ページのドメインと異なりますが、YAMAP関連ドメインのため保持します。")
            try:
                driver.add_cookie(cookie)
            except Exception as e_cookie_add:
                logger.error(f"Cookie {idx+1} ({cookie.get('name', 'N/A')}) の追加中にエラー: {e_cookie_add}", exc_info=False)

        logger.info(f"{len(cookies)}個のCookieを新しいWebDriverインスタンスに設定試行完了。")

        # --- Primary Login Verification: My Page Check ---
        if not current_user_id:
            logger.error("current_user_id が提供されていないため、マイページでの詳細なログイン確認を実行できません。タスク失敗とします。")
            save_screenshot(driver, "MyPageLoginCheckFail_NoUID", "NoUserID_CookieDriver")
            driver.quit()
            return None

        my_page_url = f"{BASE_URL}/users/{current_user_id}"
        logger.info(f"Cookie設定後、ユーザー自身のマイページ ({my_page_url}) にアクセスしてログイン状態を詳細に確認します。")
        driver.get(my_page_url)

        try:
            WebDriverWait(driver, 15).until(EC.url_to_be(my_page_url))
            logger.info(f"マイページ ({my_page_url}) への遷移を確認。")
        except TimeoutException:
            logger.warning(f"マイページ ({my_page_url}) へのURL遷移が15秒以内に確認できませんでした。現在のURL: {driver.current_url}, タイトル: {driver.title}")
            save_screenshot(driver, "MyPageNavFail_CookieDriver", f"UID_{current_user_id}")
            driver.quit()
            return None

        time.sleep(0.5) # JS等によるコンテンツ描画の時間を少し待つ

        my_page_login_ok = False
        profile_edit_button_selector = "a[href$='/profile/edit'], button[data-testid='profile-edit-button']"
        try:
            # Increased timeout from 10 to 20 seconds
            edit_element = WebDriverWait(driver, 20).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, profile_edit_button_selector))
            )
            if edit_element.is_displayed():
                my_page_login_ok = True
                logger.info(f"マイページ ({my_page_url}) でプロフィール編集関連要素 ({profile_edit_button_selector}) を確認。ログイン状態は良好と判断。")
            else:
                logger.warning(f"マイページ ({my_page_url}) でプロフィール編集関連要素は存在しますが非表示です。")
        except TimeoutException:
            logger.warning(f"マイページ ({my_page_url}) の特有要素 ({profile_edit_button_selector}) の表示が20秒以内にタイムアウトしました。")
            # HTMLソースを取得してデバッグ情報を追加
            if driver:
                try:
                    html_source = driver.page_source
                    debug_source_filename = f"MyPageFail_UID_{current_user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                    debug_source_path = os.path.join(os.path.dirname(_MODULE_DIR), "logs", "debug_html", debug_source_filename)
                    os.makedirs(os.path.dirname(debug_source_path), exist_ok=True)
                    with open(debug_source_path, "w", encoding="utf-8") as f:
                        f.write(html_source)
                    logger.info(f"タイムアウト時のHTMLソースを保存しました: {debug_source_path}")
                    # ログには一部を出力（長すぎる可能性があるため）
                    logger.debug(f"タイムアウト時のHTMLソース先頭1000文字:\n{html_source[:1000]}")
                except Exception as e_ps:
                    logger.error(f"ページソース取得/保存中にエラー: {e_ps}")
        except Exception as e_mypage_check:
            logger.warning(f"マイページ ({my_page_url}) 確認中に予期せぬエラー: {e_mypage_check}", exc_info=True)

        if not my_page_login_ok:
            logger.error(
                f"マイページ ({my_page_url}) でのログイン状態確認に失敗。Cookieによるセッションが正しく機能していません。"
                f"現在のURL: {driver.current_url}, タイトル: {driver.title}"
            )
            # スクリーンショットは既にこのエラー発生時に撮られる想定 (save_screenshot呼び出しがここにある)
            save_screenshot(driver, "MyPageLoginCheckFail_CookieDriver", f"UID_{current_user_id}")
            driver.quit()
            return None

        logger.info("CookieベースのWebDriver作成とマイページでのログイン確認成功。ドライバーを返します (現在マイページにいます)。")
        return driver

    except Exception as e:
        logger.error(f"Cookie付きWebDriver作成中に致命的なエラー: {e}", exc_info=True)
        if driver:
            driver.quit()
        return None

def save_screenshot(driver, error_type="error", context_info=""):
    """
    現在のブラウザのスクリーンショットを指定されたディレクトリに保存します。
    ファイル名にはタイムスタンプ、エラータイプ、コンテキスト情報が含まれます。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        error_type (str, optional): エラーの種類 (例: "Timeout", "NoSuchElement")。
                                    ファイル名の一部として使用されます。デフォルトは "error"。
        context_info (str, optional): エラー発生時のコンテキスト情報 (例: activity_id)。
                                     ファイル名の一部として使用されます。デフォルトは空文字列。
    """
    try:
        # スクリーンショット保存ディレクトリの準備
        # _MODULE_DIR は driver_utils.py があるディレクトリ (yamap_auto) を指す
        # その親ディレクトリ (リポジトリルート) の下に logs/screenshots を作成
        screenshots_dir = os.path.join(os.path.dirname(_MODULE_DIR), "logs", "screenshots")
        if not os.path.exists(screenshots_dir):
            os.makedirs(screenshots_dir)
            logger.info(f"スクリーンショット保存ディレクトリを作成しました: {screenshots_dir}")

        # ファイル名の生成
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_parts = [timestamp, error_type]
        if context_info:
            filename_parts.append(str(context_info).replace("/", "_")) # context_info をサニタイズ

        filename = "_".join(filename_parts) + ".png"
        filepath = os.path.join(screenshots_dir, filename)

        # スクリーンショットの保存
        if driver.save_screenshot(filepath):
            logger.info(f"スクリーンショットを保存しました: {filepath}")
        else:
            logger.error(f"スクリーンショットの保存に失敗しました: {filepath}")
            # driver.get_screenshot_as_png() を試すこともできるが、
            # save_screenshotがFalseを返す場合はより根本的な問題の可能性あり

    except Exception as e:
        logger.error(f"スクリーンショット保存処理中にエラーが発生しました: {e}", exc_info=True)

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
