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

# --- グローバル変数 (設定情報キャッシュ) ---
# 設定ファイルの内容をキャッシュして、不要なファイル読み込みを防ぎます。
_main_config_cache = None

# --- 定数 ---
BASE_URL = "https://yamap.com" # create_driver_with_cookies で使用
LOGIN_URL = f"{BASE_URL}/login"

def get_main_config():
    """
    メインの設定ファイルを読み込み、その内容を返します。
    環境変数 YAMAP_CONFIG_FILE が設定されていればそのパスを、
    そうでなければデフォルトの 'yamap_auto/config.yaml' を使用します。
    """
    global _main_config_cache

    # 環境変数から設定ファイルのパスを取得、未設定ならデフォルト値を使用
    default_config_path = "yamap_auto/config.yaml"
    config_path = os.environ.get("YAMAP_CONFIG_FILE", default_config_path)

    # キャッシュが存在し、要求された設定ファイルがキャッシュされたものと同じであればキャッシュを返す
    if _main_config_cache is not None and _main_config_cache.get('_source_path') == config_path:
        logger.debug(f"メイン設定のキャッシュを使用します ('{config_path}')。")
        return _main_config_cache

    logger.info(f"メイン設定ファイル '{config_path}' を読み込みます...")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            if config:
                config['_source_path'] = config_path  # キャッシュ識別のためにソースパスを格納
                _main_config_cache = config  # 成功した場合にキャッシュに保存
                logger.info(f"メイン設定ファイル '{config_path}' の読み込みに成功しました。")
            else:
                logger.warning(f"設定ファイル '{config_path}' は空または無効なYAMLです。")
                _main_config_cache = None # 不正な場合はキャッシュをクリア
                return None
            return config
    except FileNotFoundError:
        logger.error(f"設定ファイル '{config_path}' が見つかりません。")
        _main_config_cache = None
        return None
    except yaml.YAMLError as e:
        logger.error(f"設定ファイル '{config_path}' の解析中にエラーが発生しました: {e}", exc_info=True)
        _main_config_cache = None
        return None
    except Exception as e:
        logger.error(f"設定ファイル '{config_path}' の読み込み中に予期せぬエラーが発生しました: {e}", exc_info=True)
        _main_config_cache = None
        return None

def get_credentials():
    """環境変数から認証情報を取得して返します。"""
    # load_settings() は config.yaml のために呼び出される可能性があるが、
    # credentials.yaml の読み込みはスキップされるように load_settings が変更されている。
    # ここでは環境変数から直接取得する。
    email = os.environ.get("YAMAP_LOGIN_ID")
    password = os.environ.get("YAMAP_LOGIN_PASSWORD")
    user_id = os.environ.get("USER_ID")

    if not all([email, password, user_id]):
        missing = []
        if not email: missing.append("YAMAP_LOGIN_ID")
        if not password: missing.append("YAMAP_LOGIN_PASSWORD")
        if not user_id: missing.append("USER_ID")
        logger.warning(f"環境変数から次の認証情報が取得できませんでした: {', '.join(missing)}。")
        # 呼び出し元でNoneチェックをしてもらうため、ここではエラーを発生させずに返す。
        # あるいは、ここで例外を発生させる設計も可能。

    return {
        "email": email,
        "password": password,
        "user_id": user_id
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
    webdriver_settings_conf = main_conf.get("webdriver_settings", {})
    execution_env = webdriver_settings_conf.get("execution_environment", "local")

    options = webdriver.ChromeOptions()

    # ヘッドレスモード設定 (config.yaml のルートレベルから取得)
    if main_conf.get("headless_mode", True): # デフォルトTrueに変更
        logger.info("ヘッドレスモードで起動します。")
        options.add_argument('--headless')
        options.add_argument('--disable-gpu') # GPUハードウェアアクセラレーションなし
        options.add_argument('--window-size=1280x800') # ウィンドウサイズ指定

    # Dockerコンテナ環境向けの共通オプション
    if execution_env == "docker_container":
        logger.info("Dockerコンテナ環境向けのWebDriverオプションを設定します。")
        options.add_argument('--no-sandbox') # サンドボックスなし (コンテナ実行にしばしば必要)
        options.add_argument('--disable-dev-shm-usage') # /dev/shmパーティションの使用を無効化 (リソース制限のある環境向け)
        options.add_argument('--remote-debugging-port=9222') # デバッグポート（オプション）

        # DockerfileでChrome/Chromiumのパスが固定されていることを期待
        # chrome_binary_location はDockerfile側でENV等で設定されるか、標準パスにあることを想定
        # config.yaml の chrome_binary_location は主にローカルでの特殊ケース用
        # Dockerfile内のChromeのパスに合わせて調整が必要な場合がある
        # 例: options.binary_location = "/usr/bin/google-chrome-stable" または "/usr/bin/chromium"
        # ここではDockerfileで適切にインストールされPATHが通っていると仮定し、明示的には設定しない。
        # もし問題があれば、下記のようにconfigから読むか、固定値を設定する。
        container_chrome_binary = webdriver_settings_conf.get("chrome_binary_location")
        if container_chrome_binary:
            logger.info(f"Dockerコンテナ内のChromeバイナリとして {container_chrome_binary} を使用します。")
            options.binary_location = container_chrome_binary
        else:
            # 一般的なパスを試す (Dockerfileのインストール先に依存)
            possible_paths = ["/usr/bin/google-chrome-stable", "/usr/bin/chromium"]
            found_path = None
            for path in possible_paths:
                if os.path.exists(path):
                    found_path = path
                    break
            if found_path:
                logger.info(f"Dockerコンテナ内でChromeバイナリとして {found_path} を自動検出して使用します。")
                options.binary_location = found_path
            else:
                logger.warning(f"Dockerコンテナ環境でChromeバイナリのパスを自動検出できませんでした。標準のPATHに期待します。")


    # User-Agent (webdriver_settings から取得)
    user_agent_string = webdriver_settings_conf.get("user_agent")
    if user_agent_string:
        logger.info(f"指定されたUser-Agentを使用します: {user_agent_string}")
        options.add_argument(f"user-agent={user_agent_string}")
    else:
        logger.info("User-Agentは指定されていません。WebDriverのデフォルトを使用します。")

    return options

def create_webdriver():
    """
    config.yamlの設定に基づいて適切なWebDriver (Chrome) インスタンスを作成します。
    - execution_environment: "local" または "docker_container"
    - headless_mode: true/false
    - chromedriver_path: ローカル実行時のChromeDriverパス
    """
    main_conf = get_main_config()
    webdriver_settings_conf = main_conf.get("webdriver_settings", {})
    execution_env = webdriver_settings_conf.get("execution_environment", "local")
    options = get_driver_options() # 上で定義したオプション取得関数を呼び出す

    driver = None
    logger.info(f"WebDriverを {execution_env} 環境向けに初期化します。")

    try:
        if execution_env == "local":
            chromedriver_path = webdriver_settings_conf.get("chromedriver_path", "")
            if chromedriver_path and os.path.exists(chromedriver_path):
                logger.info(f"指定されたChromeDriverパスを使用します: {chromedriver_path}")
                service = webdriver.chrome.service.Service(executable_path=chromedriver_path)
                driver = webdriver.Chrome(service=service, options=options)
            else:
                if chromedriver_path:
                    logger.warning(f"指定されたChromeDriverパス '{chromedriver_path}' が見つかりません。システムPATHから探します。")
                else:
                    logger.info("ChromeDriverパスは指定されていません。システムPATHから探します。")
                driver = webdriver.Chrome(options=options) # PATHから探す
        elif execution_env == "docker_container":
            # Dockerコンテナ内では、ChromeDriverはPATHに通っているか、
            # /usr/local/bin/chromedriver のような標準的な場所にあることを期待します。
            # Dockerfileで適切に配置されている前提。
            # Serviceオブジェクトを使わずに直接 options のみで初期化。
            # もし特定のパスを指定する必要があれば、Serviceオブジェクトを使う。
            # (例: service = webdriver.chrome.service.Service(executable_path="/usr/local/bin/chromedriver"))
            logger.info("Dockerコンテナ環境のため、システムPATH上のChromeDriverを使用します。")
            driver = webdriver.Chrome(options=options)
        else:
            raise ValueError(f"未対応の execution_environment: {execution_env}")

        logger.info("WebDriverの初期化に成功しました。")
        # implicit_wait_sec はルートレベルから取得 (メインのドライバー用)
        implicit_wait = main_conf.get("implicit_wait_sec", 7)
        driver.implicitly_wait(implicit_wait)
        logger.info(f"WebDriverの暗黙的待機時間を {implicit_wait} 秒に設定しました。")
        return driver

    except Exception as e:
        logger.error(f"WebDriverの初期化中にエラーが発生しました ({execution_env}環境): {e}", exc_info=True)
        if execution_env == "docker_container":
            logger.error("Dockerコンテナ環境でのエラーの場合、DockerfileでのChrome/ChromeDriverのインストールやパス設定を確認してください。")
        elif webdriver_settings_conf.get("chromedriver_path"):
            logger.error(f"ローカル環境でChromeDriverパス({webdriver_settings_conf.get('chromedriver_path')})が指定されている場合、そのパスが正しいか、実行権限があるか確認してください。")
        else:
            logger.error("ローカル環境でChromeDriverがシステムPATHに正しく設定されているか確認してください。")
        # エラー発生時はNoneを返す
        return None


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
    # ログ出力用に元のCookie情報をディープコピー（add_cookie処理中に変更される可能性があるため）
    original_cookies_for_log = [c.copy() for c in cookies]

    try:
        # create_webdriver() を使用して、設定に基づいたWebDriverインスタンスを取得
        driver = create_webdriver()
        if not driver:
            logger.error("create_webdriver() でWebDriverの作成に失敗したため、Cookie付きドライバーの作成を中止します。")
            return None

        # create_webdriver 内で implicit_wait は設定済みのはずだが、
        # webdriver_settings の implicit_wait_sec を優先するならここで再設定。
        # 今回は create_webdriver の設定に任せる。
        # webdriver_settings = main_conf.get("webdriver_settings", {})
        # implicit_wait_cookie_driver = webdriver_settings.get("implicit_wait_sec", 7)
        # driver.implicitly_wait(implicit_wait_cookie_driver)
        # logger.info(f"Cookieドライバーの暗黙的待機時間を {implicit_wait_cookie_driver} 秒に設定しました。")


        logger.debug(f"Cookie設定のため、初期ページ ({initial_page_for_cookie_setting}) にアクセスします。")
        driver.get(initial_page_for_cookie_setting)
        time.sleep(0.5) # ページロード待機

        logger.debug(f"受け取ったCookie (計{len(cookies)}個) を設定します。")
        for idx, cookie in enumerate(cookies):
            # cookie_info_for_log = {k: v for k, v in cookie.items() if k != 'value'}
            # logger.debug(f"Cookie {idx+1}/{len(cookies)}: {cookie_info_for_log}")
            cookie_original_domain = cookie.get('domain')
            try:
                # ドメインが設定されていて、かつ現在のページのドメインと一致しない場合、
                # または .yamap.com で終わっていない場合、より慎重に扱う
                if cookie_original_domain and \
                   not initial_page_for_cookie_setting.endswith(cookie_original_domain.lstrip('.')) and \
                   not cookie_original_domain.endswith(".yamap.com"):

                    logger.warning(
                        f"Cookie {idx+1} (名: {cookie.get('name', 'N/A')}) のドメイン '{cookie_original_domain}' が "
                        f"初期ページドメイン '{initial_page_for_cookie_setting}' やYAMAP関連ドメインと一致しません。ドメイン情報を削除して試行します。"
                    )
                    cookie_copy_for_add = cookie.copy()
                    del cookie_copy_for_add['domain']
                    driver.add_cookie(cookie_copy_for_add)
                else:
                    if cookie_original_domain and not initial_page_for_cookie_setting.endswith(cookie_original_domain.lstrip('.')):
                        logger.info(f"Cookie {idx+1} (名: {cookie.get('name', 'N/A')}) のドメイン '{cookie_original_domain}' は初期ページと異なりますが、YAMAP関連ドメインのため保持して設定します。")
                    driver.add_cookie(cookie)

            except Exception as e_cookie_add_initial:
                logger.warning(f"Cookie {idx+1} (名: {cookie.get('name', 'N/A')}, ドメイン: {cookie_original_domain}) の初期追加試行中にエラー: {e_cookie_add_initial}。ドメイン情報を削除して再試行します。")
                try:
                    cookie_copy_for_retry = cookie.copy()
                    if 'domain' in cookie_copy_for_retry:
                        del cookie_copy_for_retry['domain']
                    driver.add_cookie(cookie_copy_for_retry)
                    logger.info(f"Cookie {idx+1} (名: {cookie.get('name', 'N/A')}) はドメイン情報削除後に設定成功。")
                except Exception as e_cookie_add_retry:
                    logger.error(f"Cookie {idx+1} (名: {cookie.get('name', 'N/A')}) はドメイン情報削除後も追加中にエラー: {e_cookie_add_retry}", exc_info=False)

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
        verification_details = [] # 検証ステップごとの詳細を記録

        # --- ヘルパー関数: URL正規化 ---
        def _normalize_url(url_string):
            if not url_string:
                return ""
            url_string = url_string.strip().lower()
            if url_string.endswith('/'):
                url_string = url_string[:-1]
            # クエリパラメータやハッシュを除去することも検討 (今回はシンプルに末尾スラッシュのみ)
            return url_string

        normalized_expected_my_page_url = _normalize_url(my_page_url)
        normalized_current_url = _normalize_url(driver.current_url)

        # --- 確認ステップ1: URLが期待通りマイページか ---
        if normalized_current_url == normalized_expected_my_page_url:
            logger.info(f"マイページURL ({my_page_url}) に正しく遷移済みであることを確認。")
            verification_details.append("URL_MATCH_OK")
        else:
            logger.warning(f"マイページURL ({my_page_url}) への遷移を期待しましたが、現在のURL ({driver.current_url}) が異なります。")
            verification_details.append(f"URL_MISMATCH (Expected: {my_page_url}, Actual: {driver.current_url})")
            # URLが異なる場合は即時失敗とはせず、他の要素でログイン状態を確認する

        # --- 確認ステップ2: 主要なログインインジケータ (ユーザーメニューボタン) ---
        user_menu_button_selector = "button[aria-label='ユーザーメニューを開く']"
        # ヘッダーアバター画像セレクタ (alt属性確認用) - より具体的なセレクタに変更が必要な場合あり
        header_avatar_selector = "header button[aria-label='ユーザーメニューを開く'] img, header a[href*='/users/'] img" # 複数候補

        try:
            user_menu_element = WebDriverWait(driver, 15).until( # 少し短縮
                EC.presence_of_element_located((By.CSS_SELECTOR, user_menu_button_selector))
            )
            logger.info(f"主要ログイン確認要素 ({user_menu_button_selector}) の存在を確認。")
            verification_details.append("USER_MENU_BTN_OK")

            # --- 確認ステップ2a: アバター画像のalt属性確認 (ユーザーメニューボタンが見つかった場合) ---
            try:
                avatar_verified = False
                avatar_elements = driver.find_elements(By.CSS_SELECTOR, header_avatar_selector)
                if avatar_elements:
                    for avatar_img in avatar_elements:
                        if avatar_img.is_displayed(): # 表示されているもののみ対象
                            alt_text = avatar_img.get_attribute("alt")
                            if alt_text:
                                # ユーザーIDが含まれているか、またはユーザー名（取得できれば）が含まれているか
                                # ここでは current_user_id (数値ID) の一部が含まれているかで簡易的に確認
                                if current_user_id in alt_text: # 完全一致または部分一致
                                    logger.info(f"ヘッダーアバター画像のalt属性 ({alt_text}) にユーザーID ({current_user_id}) を確認。")
                                    avatar_verified = True
                                    verification_details.append(f"AVATAR_ALT_OK (alt: {alt_text})")
                                    break
                                else:
                                    logger.debug(f"アバターalt属性 ({alt_text}) にユーザーID ({current_user_id}) が見つからず。")
                            else:
                                logger.debug("アバター画像のalt属性が空または取得できませんでした。")
                        else:
                            logger.debug("非表示のアバター画像をスキップ。")
                else:
                    logger.warning(f"ヘッダーアバター画像要素 ({header_avatar_selector}) が見つかりませんでした。")

                if avatar_verified:
                    my_page_login_ok = True # ユーザーメニューとアバターaltでOK
                else:
                    logger.warning(f"ユーザーメニューボタンは存在しましたが、アバターalt属性でのユーザーID確認に失敗。")
                    # この時点ではまだ失敗とせず、他の要素で補完する

            except Exception as e_avatar:
                logger.warning(f"アバターalt属性確認中にエラー: {e_avatar}", exc_info=True)
                verification_details.append("AVATAR_ALT_CHECK_ERROR")

            if my_page_login_ok: # アバター確認もOKならここで確定
                 logger.info(f"ユーザーメニューボタンおよびアバターalt属性によりログイン状態は良好と判断。")

        except TimeoutException:
            logger.warning(f"主要なログイン確認要素 ({user_menu_button_selector}) が15秒以内に見つかりませんでした。")
            verification_details.append("USER_MENU_BTN_TIMEOUT")
        except Exception as e_user_menu:
            logger.warning(f"ユーザーメニューボタン確認中に予期せぬエラー: {e_user_menu}", exc_info=True)
            verification_details.append("USER_MENU_BTN_ERROR")

        # --- 確認ステップ3: 補助的なログインインジケータ (プロフィール編集ボタン) ---
        # 主要な確認 (ユーザーメニュー＋アバター) でOKでなければ、こちらを試す
        if not my_page_login_ok:
            profile_edit_button_selector = "a[href$='/profile/edit'], button[data-testid='profile-edit-button']"
            logger.info(f"主要確認でNGだったため、セカンダリのログイン確認要素 ({profile_edit_button_selector}) の確認を試みます...")
            try:
                edit_element = WebDriverWait(driver, 7).until( # 短めのタイムアウト
                    EC.presence_of_element_located((By.CSS_SELECTOR, profile_edit_button_selector))
                )
                my_page_login_ok = True # プロフィール編集ボタンがあればOKとみなす
                logger.info(f"セカンダリのプロフィール編集関連要素 ({profile_edit_button_selector}) の存在を確認。ログイン状態は良好と判断。")
                verification_details.append("PROFILE_EDIT_BTN_OK")
            except TimeoutException:
                logger.warning(f"セカンダリのログイン確認要素 ({profile_edit_button_selector}) も7秒以内に見つかりませんでした。")
                verification_details.append("PROFILE_EDIT_BTN_TIMEOUT")
            except Exception as e_prof_edit:
                logger.warning(f"プロフィール編集ボタン確認中に予期せぬエラー: {e_prof_edit}", exc_info=True)
                verification_details.append("PROFILE_EDIT_BTN_ERROR")

        # --- 確認ステップ4: 最終手段としてのURL再確認 (他の要素が全滅した場合) ---
        if not my_page_login_ok:
            logger.info("主要およびセカンダリの要素確認でNG。最終手段としてURLの一致を再評価します。")
            if normalized_current_url == normalized_expected_my_page_url:
                my_page_login_ok = True
                logger.info(f"最終確認: 現在のURL ({driver.current_url}) が期待されるマイページURLと一致するため、ログイン状態とみなします。")
                verification_details.append("FINAL_URL_MATCH_RECONFIRMED_OK")
            else:
                logger.error(f"最終確認: 現在のURL ({driver.current_url}) も期待されるマイページURL ({my_page_url}) と不一致。")
                verification_details.append("FINAL_URL_MATCH_FAILED")


        # --- 総合判定と失敗時の処理 ---
        if not my_page_login_ok:
            logger.error(
                f"マイページ ({my_page_url}) でのログイン状態確認に失敗。Cookieによるセッションが正しく機能していません。検証詳細: {verification_details}"
            )
            # HTMLソースとスクリーンショットの保存
            if driver:
                try:
                    html_source = driver.page_source
                    # logs/debug_html ディレクトリは save_screenshot 内で screenshots と同様に作成されることを期待するか、ここで作る
                    debug_html_dir = os.path.join(os.path.dirname(_MODULE_DIR), "logs", "debug_html")
                    os.makedirs(debug_html_dir, exist_ok=True)
                    debug_source_filename = f"MyPageFail_UID_{current_user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                    debug_source_path = os.path.join(debug_html_dir, debug_source_filename)
                    with open(debug_source_path, "w", encoding="utf-8") as f:
                        f.write(html_source)
                    logger.info(f"ログイン失敗時のHTMLソースを保存しました: {debug_source_path}")
                except Exception as e_ps:
                    logger.error(f"ページソース取得/保存中にエラー: {e_ps}")
                save_screenshot(driver, "MyPageLoginCheckFail_CookieDriver", f"UID_{current_user_id}_Details_{'_'.join(verification_details)}")

            # 詳細なデバッグ情報をログに出力 (既存のものを流用・強化)
            current_url_on_fail = "N/A"
            current_title_on_fail = "N/A"
            try:
                current_url_on_fail = driver.current_url
                current_title_on_fail = driver.title
            except Exception as e_url_title:
                logger.warning(f"ログイン失敗時のURL/タイトル取得中にエラー: {e_url_title}")

            logger.error(f"ログイン失敗時のURL: {current_url_on_fail}, タイトル: {current_title_on_fail}")

            try:
                logger.debug("--- 設定試行したCookie情報 (ログイン失敗時) ---")
                if original_cookies_for_log:
                    for idx, cookie_param in enumerate(original_cookies_for_log):
                        log_cookie = {k: v for k, v in cookie_param.items() if k.lower() != 'value'} # valueを除外
                        logger.debug(f"Param Cookie {idx+1}: {log_cookie}")
                else:
                    logger.debug("設定試行するCookie情報がありませんでした（original_cookies_for_logが空）。")

                logger.debug("--- WebDriverが保持している実際のCookie情報 (ログイン失敗時) ---")
                actual_cookies_on_fail = driver.get_cookies()
                if actual_cookies_on_fail:
                    for idx, actual_cookie in enumerate(actual_cookies_on_fail):
                        log_actual_cookie = {k: v for k, v in actual_cookie.items() if k.lower() != 'value'} # valueを除外
                        logger.debug(f"Actual Cookie {idx+1}: {log_actual_cookie}")
                else:
                    logger.debug("WebDriverはログイン失敗時点でCookieを保持していませんでした。")
            except Exception as e_cookie_log:
                logger.error(f"ログイン失敗時のCookie情報ログ記録中にエラー: {e_cookie_log}")

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


def wait_for_page_transition(driver, timeout=10, expected_url_part=None, expected_element_selector=None, previous_url=None):
    """
    ページ遷移やコンテンツの読み込みを待機します。
    URLの変更、特定の要素の出現、またはその両方を待機条件とすることができます。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        timeout (int, optional): 最大待機時間 (秒)。デフォルトは10秒。
        expected_url_part (str, optional): 遷移後のURLに含まれることを期待する部分文字列。
                                           Noneの場合、URLのチェックは行われません。
        expected_element_selector (tuple, optional): (By, value) の形式で、出現を待つ要素のセレクタ。
                                                    例: (By.CSS_SELECTOR, "h1.title")
                                                    Noneの場合、要素のチェックは行われません。
        previous_url (str, optional): 遷移前のURL。指定された場合、URLが実際に変更されたかも確認します。
                                      主にページネーションなどで、同じURL構造だがコンテンツが変わる場合に利用。

    Returns:
        bool: 待機条件が満たされればTrue、タイムアウトした場合はFalse。
    """
    logger.debug(f"ページ遷移/読み込み待機開始 (timeout={timeout}s, url_part='{expected_url_part}', element='{expected_element_selector}', prev_url='{previous_url}')")
    original_url = driver.current_url # ログおよび比較用
    wait_succeeded = False

    try:
        # 1. 期待される要素があれば、まずその出現を待つ (最も確実な読み込み完了指標の一つ)
        if expected_element_selector:
            logger.debug(f"期待要素 '{expected_element_selector}' の出現を待機します...")
            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located(expected_element_selector)
            )
            logger.debug(f"期待要素 '{expected_element_selector}' の出現を確認。")
            wait_succeeded = True # 要素が見つかれば、主要な待機は成功とみなす

        # 2. previous_url があり、かつ現在のURLと異なる場合、URLの変更を待つ
        #    これは主にクリックなどによるページ遷移で使う
        if previous_url and original_url == previous_url and driver.current_url == previous_url:
            # driver.get() の直後などで original_url と previous_url が同じ場合、
            # current_url も同じはずなので、url_changes は期待できない。
            # この場合は要素待機が主になる。要素待機が成功していればOK。
            # もし要素待機がなく、URLも変わっていない場合は、url_contains に進む。
            if not wait_succeeded: # 要素待機がなかった、または失敗した場合
                 logger.debug(f"previous_url ('{previous_url}') が現在のURLと同じです。EC.url_changesの待機はスキップし、他の条件に進みます。")
        elif previous_url:
            logger.debug(f"URLが '{previous_url}' から変更されるのを待機します...")
            WebDriverWait(driver, timeout).until(EC.url_changes(previous_url))
            logger.debug(f"URLが '{previous_url}' から '{driver.current_url}' に変更されたのを確認。")
            wait_succeeded = True

        # 3. 期待されるURL部分文字列があれば、それを含むか確認
        #    これは driver.get() 直後や、URL変更後に追加で確認する場合に使う
        if expected_url_part:
            if not wait_succeeded and original_url == driver.current_url and not expected_element_selector:
                # 要素待機がなく、URLもまだ変わっていない場合、url_containsを主待機とする
                logger.debug(f"URLに '{expected_url_part}' が含まれるのを主待機します...")
                WebDriverWait(driver, timeout).until(EC.url_contains(expected_url_part))
                wait_succeeded = True
            elif expected_url_part not in driver.current_url:
                # すでに他の条件で待機成功しているが、念のためURL部分も確認
                logger.debug(f"URLに '{expected_url_part}' が含まれるのを追加待機します...")
                WebDriverWait(driver, timeout).until(EC.url_contains(expected_url_part))
            logger.debug(f"URL '{driver.current_url}' に期待部分 '{expected_url_part}' が含まれることを確認。")
            wait_succeeded = True # URL部分が含まれていればOK

        if not expected_element_selector and not previous_url and not expected_url_part:
            logger.warning("待機条件が何も指定されていません。即時Trueを返します。")
            return True

        if not wait_succeeded:
            # 全ての明示的な待機条件が設定されていなかったか、
            # 設定されていたが上記ロジックで wait_succeeded = True にならなかった場合
            # (例えば previous_url がなく、expected_url_part もなく、要素待機のみでそれが失敗した場合など)
            # このケースは通常、TimeoutExceptionでキャッチされるはずだが、念のため。
            logger.warning("有効な待機条件で成功しませんでした。遷移失敗とみなします。")
            save_screenshot(driver, "PageTransitionLogicFail", f"FinalURL_{driver.current_url}")
            return False

        logger.info(f"ページ遷移/読み込み完了。最終URL: {driver.current_url}")
        return True

    except TimeoutException:
        logger.warning(f"ページ遷移/読み込み待機中にタイムアウト ({timeout}秒)。")
        logger.warning(f"  遷移前URL: {original_url}")
        logger.warning(f"  タイムアウト時URL: {driver.current_url}")
        logger.warning(f"  期待したURL部分: '{expected_url_part}', 期待した要素: '{expected_element_selector}'")
        try:
            html_source_on_timeout = driver.page_source
            # logs/debug_html ディレクトリを _MODULE_DIR (yamap_auto) の親 (リポジトリルート) の logs サブディレクトリとして構築
            debug_html_dir = os.path.join(os.path.dirname(_MODULE_DIR), "logs", "debug_html")
            os.makedirs(debug_html_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # URLからファイル名に使えない文字を除去または置換 (簡易的)
            safe_url_part = driver.current_url.replace('/', '_').replace(':', '').replace('?', '_').replace('#', '_')
            filename = f"timeout_{timestamp}_url_{safe_url_part}.html"
            filepath = os.path.join(debug_html_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_source_on_timeout)
            logger.info(f"タイムアウト時のHTMLソースを保存しました: {filepath}")
        except Exception as e_html_save:
            logger.error(f"タイムアウト時のHTMLソース保存中にエラー: {e_html_save}")
        save_screenshot(driver, "PageTransitionTimeout", f"Timeout_{timeout}s_URLPart_{expected_url_part or 'None'}_Elem_{expected_element_selector or 'None'}")
        return False
    except Exception as e:
        logger.error(f"ページ遷移/読み込み待機中に予期せぬエラー: {e}", exc_info=True)
        save_screenshot(driver, "PageTransitionError", f"Error_URLPart_{expected_url_part or 'None'}_Elem_{expected_element_selector or 'None'}")
        return False


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
