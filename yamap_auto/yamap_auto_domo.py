# coding: utf-8
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys
import time
import json
import os
import re
import logging
import yaml

# --- Loggerの設定 ---
LOG_FILE_NAME = "yamap_auto_domo.log" # ログファイル名を変更
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
# StreamHandler (コンソール出力)
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO) # コンソールにはINFO以上
stream_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
stream_handler.setFormatter(stream_formatter)
if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers): # ハンドラが重複して追加されるのを防ぐ
    logger.addHandler(stream_handler)
# FileHandler (ファイル出力)
try:
    file_handler = logging.FileHandler(LOG_FILE_NAME, encoding='utf-8', mode='a') # mode='a'で追記
    file_handler.setLevel(logging.DEBUG) # ファイルにはDEBUG以上
    file_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(funcName)s:%(lineno)d] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(file_formatter)
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == os.path.abspath(LOG_FILE_NAME) for h in logger.handlers):
        logger.addHandler(file_handler)
except Exception as e:
    logger.error(f"ログファイルハンドラの設定に失敗しました: {e}")
# --- Logger設定完了 ---

# 設定ファイルのパス
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.yaml")
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.yaml") # 認証情報ファイル

# --- 設定ファイルの読み込み ---
# (この部分は後で新しい機能の設定も読み込めるように調整するが、まずは既存の構造を維持)
try:
    # まず credentials.yaml を読み込む
    try:
        with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
            credentials_config = yaml.safe_load(f)
        if not credentials_config:
            raise ValueError("認証ファイルが空か、内容を読み取れませんでした。")
        YAMAP_EMAIL = credentials_config.get("email")
        YAMAP_PASSWORD = credentials_config.get("password")
        MY_USER_ID = str(credentials_config.get("user_id", ""))

        if not all([YAMAP_EMAIL, YAMAP_PASSWORD, MY_USER_ID]):
             logger.critical(f"認証ファイル ({CREDENTIALS_FILE}) に email, password, user_id のいずれかが正しく設定されていません。")
             logger.info(f"例:\nemail: your_email@example.com\npassword: your_password\nuser_id: '1234567'")
             exit()
    except FileNotFoundError:
        logger.critical(f"認証ファイル ({CREDENTIALS_FILE}) が見つかりません。作成して認証情報を記述してください。")
        logger.info(f"ファイルパス: {os.path.abspath(CREDENTIALS_FILE)}")
        logger.info(f"例:\nemail: your_email@example.com\npassword: your_password\nuser_id: '1234567'")
        exit()
    except (yaml.YAMLError, ValueError) as e_cred:
        logger.critical(f"認証ファイル ({CREDENTIALS_FILE}) の形式が正しくないか、内容に問題があります。エラー: {e_cred}")
        exit()

    # 次に config.yaml を読み込む
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        main_config = yaml.safe_load(f)
        if not main_config:
             raise ValueError("メインの設定ファイル (config.yaml) が空か、内容を読み取れませんでした。")
    # 各設定セクションの読み込み
    # 既存の yamap_auto.py と共存するため、domo_settings と follow_settings も読み込むが、
    # yamap_auto_domo.py では主に新しい設定セットを使用する。
    DOMO_SETTINGS = main_config.get("domo_settings", {})
    FOLLOW_SETTINGS = main_config.get("follow_settings", {})

    # 新しい機能のための設定セクション
    FOLLOW_BACK_SETTINGS = main_config.get("follow_back_settings", {})
    TIMELINE_DOMO_SETTINGS = main_config.get("timeline_domo_settings", {})
    SEARCH_AND_FOLLOW_SETTINGS = main_config.get("search_and_follow_settings", {})

    # 新しい設定が空の場合のフォールバックや必須チェックは、各機能の実装時に行うか、
    # ここで基本的な構造だけ確認することもできる。
    if not all([FOLLOW_BACK_SETTINGS, TIMELINE_DOMO_SETTINGS, SEARCH_AND_FOLLOW_SETTINGS]):
        logger.warning(
            "config.yamlに新しい機能（follow_back_settings, timeline_domo_settings, search_and_follow_settings）の"
            "一部または全ての設定セクションが見つからないか空です。デフォルト値で動作しようとしますが、"
            "意図した動作をしない可能性があります。config.yamlを確認してください。"
        )
        # 必須なキーがなければここで exit() する選択肢もあるが、今回は警告に留める。

except FileNotFoundError as e_fnf:
    logger.critical(f"設定ファイル ({e_fnf.filename}) が見つかりません。スクリプトを終了します。")
    exit()
except (yaml.YAMLError, ValueError) as e_yaml_val:
    logger.critical(f"設定ファイル ({CONFIG_FILE} または {CREDENTIALS_FILE}) の形式が正しくないか、内容に問題があります。エラー: {e_yaml_val}")
    exit()
except Exception as e:
    logger.critical(f"設定ファイルの読み込み中に予期せぬエラーが発生しました: {e}", exc_info=True)
    exit()
# --- 設定ファイルの読み込み完了 ---

BASE_URL = "https://yamap.com"
LOGIN_URL = f"{BASE_URL}/login"
TIMELINE_URL = f"{BASE_URL}/timeline" # 新機能で使う可能性のあるURL
SEARCH_ACTIVITIES_URL_DEFAULT = f"{BASE_URL}/search/activities" # 新機能で使う可能性のあるURL

def get_driver_options():
    options = webdriver.ChromeOptions()
    # headless_mode は config.yaml のトップレベルから読むように変更
    if main_config.get("headless_mode", False):
        logger.info("ヘッドレスモードで起動します。")
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
    return options

def login(driver, email, password):
    logger.info(f"ログインページ ({LOGIN_URL}) にアクセスします...")
    driver.get(LOGIN_URL)
    try:
        email_field = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "email")))
        email_field.send_keys(email)
        password_field = driver.find_element(By.NAME, "password")
        password_field.send_keys(password)
        login_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        login_button.click()
        WebDriverWait(driver, 15).until_not(EC.url_contains("login"))
        # ログイン成功の判定: 提供された情報に基づき、特定の要素が表示されるかで判断
        # 例: <div class="css-16byi0r"><span class="css-1jdcqgw">ユーザー名</span><div class="css-18ctnpz">マイページを表示</div></div>
        # この構造から、例えば "マイページを表示" というテキストを持つ要素を探す
        # --- ここから yamap_auto.py の login 関数のロジックをそのまま移植 ---
        WebDriverWait(driver, 15).until_not(EC.url_contains("login"))
        current_url_lower = driver.current_url.lower()
        page_title_lower = driver.title.lower()

        # MY_USER_ID は yamap_auto_domo.py のスコープで定義されているものを参照
        # (credentials.yaml から読み込まれているはず)
        if not MY_USER_ID:
             logger.warning("MY_USER_IDが設定されていません。ログイン成功判定の一部が機能しません。")

        # yamap_auto.py と同じ判定ロジック
        if "login" not in current_url_lower and \
           ("yamap" in current_url_lower or \
            (MY_USER_ID and MY_USER_ID in current_url_lower) or \
            "timeline" in current_url_lower or \
            "home" in current_url_lower or \
            "discover" in current_url_lower):
            logger.info("ログインに成功しました。(yamap_auto.py互換ロジック1)")
            return True
        elif "ようこそ" in page_title_lower or "welcome" in page_title_lower:
             logger.info("ログインに成功しました。(yamap_auto.py互換ロジック2: タイトル確認)")
             return True
        else:
            logger.error("ログインに失敗したか、予期せぬページに遷移しました。(yamap_auto.py互換ロジック)")
            logger.error(f"現在のURL: {driver.current_url}, タイトル: {driver.title}")
            try:
                error_message_element = driver.find_element(By.CSS_SELECTOR, "div[class*='ErrorText'], p[class*='error-message'], div[class*='FormError']")
                if error_message_element and error_message_element.is_displayed():
                    logger.error(f"ページ上のエラーメッセージ: {error_message_element.text.strip()}")
            except NoSuchElementException:
                logger.debug("ページ上にログインエラーメッセージ要素は見つかりませんでした。")
            return False
        # --- ここまで yamap_auto.py の login 関数のロジック移植 ---

    except Exception as e:
        logger.error(f"ログイン処理中に予期せぬエラーが発生しました。", exc_info=True) # この部分は共通
        return False

# --- DOMO関連補助関数 (yamap_auto.pyから移植・調整) ---
# def domo_activity(driver, activity_url): pass
# def get_latest_activity_url(driver, user_profile_url): pass
# def find_follow_button_on_profile_page(driver): pass
# def click_follow_button_and_verify(driver, button, name): pass
# def get_user_follow_counts(driver, profile_url): pass

# --- フォロー関連補助関数 (yamap_auto.pyから移植・調整) ---
def find_follow_button_in_list_item(user_list_item_element):
    """
    ユーザーリストアイテム要素内から「フォローする」ボタンを探す。
    既にフォロー中、またはボタンがない場合はNoneを返す。
    """
    try:
        # 「フォロー中」ボタンの判定 (提供されたHTMLを参考)
        # <button type="button" aria-pressed="true" class="bj9bow7 tfao701 syljt1l" ...><span class="c1hbtdj4">フォロー中</span></button>
        try:
            following_button = user_list_item_element.find_element(By.CSS_SELECTOR, "button[aria-pressed='true']")
            # さらにクラス名やテキストで絞り込んでも良いが、aria-pressed='true' が強い指標と仮定
            if following_button and following_button.is_displayed():
                # テキストが「フォロー中」であることも確認 (より確実性のため)
                try:
                    # ボタン自身のテキスト、または内部のspan要素のテキストを確認
                    button_text = following_button.text.strip()
                    span_text = ""
                    try:
                        span_elements = following_button.find_elements(By.CSS_SELECTOR, "span")
                        if span_elements: # 複数のspanがありうるので、主要なものを探すか、連結するか
                            span_text = " ".join(s.text.strip() for s in span_elements if s.text.strip())
                    except: pass # span がなくてもボタンテキストで判定試行

                    if "フォロー中" in button_text or "フォロー中" in span_text:
                        logger.debug("「フォロー中」ボタン (aria-pressed='true' およびテキスト確認) を発見。既にフォロー済みと判断。")
                        return None
                    else:
                        logger.debug(f"aria-pressed='true' ボタン発見もテキスト不一致。Button text: '{button_text}', Span text: '{span_text}'")
                        # テキストが不一致でもaria-pressed='true'ならフォロー済みとみなすか、ここではNoneを返さないでおくか。
                        # 現状はNoneを返して「フォロー済み」と判断させている。
                        return None # aria-pressed='true'を優先
                except Exception as e_text_check:
                     logger.debug(f"aria-pressed='true' ボタンのテキスト確認中にエラー: {e_text_check}")
                     return None # エラー時もフォロー済み扱い（安全策）
        except NoSuchElementException:
            logger.debug("aria-pressed='true' の「フォロー中」ボタンは見つかりませんでした。フォロー可能かもしれません。")

        # 「フォローする」ボタンの判定
        # data-testid検索はコメントアウト
        # try:
        #     follow_button_testid = user_list_item_element.find_element(By.CSS_SELECTOR, "button[data-testid='FollowButton']")
        #     if follow_button_testid and follow_button_testid.is_displayed() and follow_button_testid.is_enabled():
        #          logger.debug("リストアイテム内で「フォローする」ボタン (data-testid) を発見。")
        #          return follow_button_testid
        # except NoSuchElementException:
        #     logger.debug("リストアイテム内で data-testid='FollowButton' のボタンは見つかりませんでした。")

        # aria-pressed="false" のボタンを探し、テキストを確認 (こちらを優先)
        try:
            potential_follow_buttons = user_list_item_element.find_elements(By.CSS_SELECTOR, "button[aria-pressed='false']")
            if not potential_follow_buttons:
                logger.debug("リストアイテム内で aria-pressed='false' のボタン候補は見つかりませんでした。")
            else:
                for button_candidate in potential_follow_buttons:
                    if button_candidate and button_candidate.is_displayed() and button_candidate.is_enabled():
                        button_text = button_candidate.text.strip()
                        span_text = ""
                        try:
                            span_elements = button_candidate.find_elements(By.CSS_SELECTOR, "span")
                            if span_elements:
                                span_text = " ".join(s.text.strip() for s in span_elements if s.text.strip())
                        except: pass

                        if "フォローする" in button_text or "フォローする" in span_text:
                            logger.debug("リストアイテム内で「フォローする」ボタン (aria-pressed='false' かつテキスト確認) を発見。")
                            return button_candidate
                logger.debug("リストアイテム内の aria-pressed='false' ボタン群に「フォローする」テキストを持つものなし。")
        except NoSuchElementException: # find_elements なので実際にはここは通らないはずだが念のため
            logger.debug("リストアイテム内で aria-pressed='false' のボタン探索でエラー（通常発生しない）。")


        # XPathによるテキストでのフォールバック
        try:
            follow_button_xpath = ".//button[normalize-space(.)='フォローする']"
            button_by_text = user_list_item_element.find_element(By.XPATH, follow_button_xpath)
            if button_by_text and button_by_text.is_displayed() and button_by_text.is_enabled():
                logger.debug(f"リストアイテム内で「フォローする」ボタンをテキストで発見 (XPath: {follow_button_xpath})")
                return button_by_text
        except NoSuchElementException:
            logger.debug(f"リストアイテム内でテキスト「フォローする」でのボタン発見試行失敗 (XPath: {follow_button_xpath})。")

        # aria-label によるフォールバック
        try:
            follow_button_aria_label = user_list_item_element.find_element(By.CSS_SELECTOR, "button[aria-label*='フォローする']")
            if follow_button_aria_label and follow_button_aria_label.is_displayed() and follow_button_aria_label.is_enabled():
                 logger.debug(f"リストアイテム内で「フォローする」ボタン (aria-label) を発見。")
                 return follow_button_aria_label
        except NoSuchElementException:
            logger.debug("リストアイテム内で aria-label*='フォローする' のボタンは見つかりませんでした。")

        logger.debug("ユーザーリストアイテム内にクリック可能な「フォローする」ボタンが見つかりませんでした。")
        return None
    except Exception as e:
        logger.error(f"ユーザーリストアイテム内のフォローボタン検索で予期せぬエラー: {e}", exc_info=True)
        return None

def click_follow_button_and_verify(driver, follow_button_element, user_name_for_log=""):
    """
    指定されたフォローボタンをクリックし、フォロー状態に変わったことを確認する。
    """
    try:
        button_text_before = follow_button_element.text
        button_aria_label_before = follow_button_element.get_attribute('aria-label')
        logger.info(f"ユーザー「{user_name_for_log}」のフォローボタンをクリックします...")

        # スクロールしてクリック、その後状態変化を待つ
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", follow_button_element)
        time.sleep(0.3) # スクロール後の描画待ち (0.5秒から0.3秒に短縮)
        follow_button_element.click()

        # 状態変化の確認: ボタンのdata-testid, aria-label, またはテキストが変わることを期待
        # フォロー後は "FollowingButton" や "フォロー中" になることを想定
        # WebDriverWait を使って、要素の状態が変わるまで待機
        # action_delays から読むように変更 (変更済みだが、キー名を再確認)
        action_delays = main_config.get("action_delays", {}) # この行は既に存在
        delay_after_action = action_delays.get("after_follow_action_sec", 2.0) # 変更なし

        WebDriverWait(driver, 10).until(
            lambda d: (
                (follow_button_element.get_attribute("data-testid") == "FollowingButton") or
                ("フォロー中" in (follow_button_element.get_attribute("aria-label") or "")) or
                ("フォロー中" in follow_button_element.text) or
                # ボタン自体が消えるか、別の要素に置き換わる場合も考慮 (より複雑な判定が必要になる可能性)
                # ここでは、ボタンの属性/テキスト変化を主眼とする
                (not follow_button_element.is_displayed()) # ボタンが非表示になった場合も成功とみなすケース
            )
        )

        # 確認後の状態ログ
        final_testid = follow_button_element.get_attribute("data-testid")
        final_aria_label = follow_button_element.get_attribute("aria-label")
        final_text = ""
        try:
            final_text = follow_button_element.text # 要素が消えているとエラーになるのでtry-except
        except:
            pass

        if final_testid == "FollowingButton" or \
           (final_aria_label and "フォロー中" in final_aria_label) or \
           (final_text and "フォロー中" in final_text) or \
           (not follow_button_element.is_displayed()): # 非表示も成功とみなす
            logger.info(f"ユーザー「{user_name_for_log}」をフォローしました。状態: testid='{final_testid}', label='{final_aria_label}', text='{final_text}', displayed={follow_button_element.is_displayed()}")
            time.sleep(delay_after_action)
            return True
        else:
            logger.warning(f"フォローボタンクリック後、状態変化が期待通りではありません (ユーザー「{user_name_for_log}」)。状態: testid='{final_testid}', label='{final_aria_label}', text='{final_text}'")
            return False
    except TimeoutException:
        logger.warning(f"フォロー後の状態変化待機中にタイムアウト (ユーザー: {user_name_for_log})。")
        # タイムアウトした場合でも、実際にはフォロー成功しているがUIの反映が遅いだけの可能性もある。
        # より堅牢にするなら、ページをリフレッシュして再確認するロジックも考えられるが、一旦ここまで。
        return False # タイムアウト時は失敗扱い
    except Exception as e:
        logger.error(f"フォローボタンクリックまたは確認中にエラー (ユーザー: {user_name_for_log})", exc_info=True)
    return False

# --- DOMO関連補助関数 (yamap_auto.pyから移植・調整) ---
def domo_activity(driver, activity_url):
    """
    指定された活動日記URLのページを開き、DOMOボタンを探してクリックする。
    既にDOMO済みの場合は実行しない。
    """
    logger.info(f"活動日記 ({activity_url.split('/')[-1]}) へDOMOを試みます。")
    try:
        current_page_url = driver.current_url
        if current_page_url != activity_url:
            logger.debug(f"対象の活動日記ページ ({activity_url}) に遷移します。")
            driver.get(activity_url)
            WebDriverWait(driver, 15).until(EC.url_contains(activity_url.split('/')[-1])) # URL遷移確認
        else:
            logger.debug(f"既に活動日記ページ ({activity_url}) にいます。")

        # DOMOボタンのセレクタ候補 (YAMAPのHTML構造に依存)
        # プライマリ: data-testid属性を持つもの
        # フォールバック: class名など (変更されやすいので注意)
        # さらにフォールバック: aria-labelなど
        primary_domo_button_selector = "button[data-testid='ActivityDomoButton']"
        # 以前のyamap_auto.pyで使われていたIDセレクタも候補に入れる
        id_domo_button_selector = "button#DomoActionButton"

        # 補足的なセレクタ (クラス名は変わりやすいため優先度低)
        # 例: "button.domo-button-class"
        # 例: "button[aria-label*='Domoする'], button[aria-label*='DOMOする']"

        domo_button = None
        current_selector_used = ""
        found_button_details = ""

        # セレクタを優先順位で試行
        for idx, selector in enumerate([primary_domo_button_selector, id_domo_button_selector]):
            try:
                logger.debug(f"DOMOボタン探索試行 (セレクタ: {selector})")
                # DOMOボタンが表示され、クリック可能になるまで待つ (タイムアウト値を調整: プライマリ5秒, セカンダリ2秒)
                wait_time = 5 if idx == 0 else 2
                domo_button = WebDriverWait(driver, wait_time).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                current_selector_used = selector
                found_button_details = f"selector='{selector}'"
                if domo_button:
                    logger.debug(f"DOMOボタンを発見 ({found_button_details})")
                    break
            except TimeoutException:
                logger.debug(f"DOMOボタンがセレクタ '{selector}' で見つからず、またはタイムアウトしました。")
                continue

        if not domo_button:
            logger.warning(f"DOMOボタンが見つかりませんでした: {activity_url.split('/')[-1]}")
            return False

        # DOMO済みかどうかの判定 (aria-label やアイコンの状態で判断)
        # YAMAPのDOMO済みボタンは aria-label="Domo済み" や、内部のアイコンに is-active クラスが付くなど
        aria_label_before = domo_button.get_attribute("aria-label")
        is_domoed = False

        if aria_label_before and ("Domo済み" in aria_label_before or "domoed" in aria_label_before.lower() or "ドモ済み" in aria_label_before):
            is_domoed = True
            logger.info(f"既にDOMO済みです (aria-label='{aria_label_before}'): {activity_url.split('/')[-1]}")
        else:
            # is-activeクラスを持つspan要素で再確認 (より確実な場合がある)
            try:
                icon_span = domo_button.find_element(By.CSS_SELECTOR, "span[class*='DomoActionContainer__DomoIcon'], span.RidgeIcon") # 複数の可能性
                if "is-active" in icon_span.get_attribute("class"):
                    is_domoed = True
                    logger.info(f"既にDOMO済みです (アイコンis-active確認): {activity_url.split('/')[-1]}")
            except NoSuchElementException:
                logger.debug("DOMOボタン内のis-activeアイコンspanが見つかりませんでした。aria-labelに依存します。")

        if not is_domoed:
            logger.info(f"DOMOを実行します: {activity_url.split('/')[-1]} (使用ボタン: {found_button_details})")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", domo_button)
            time.sleep(0.3) # スクロール安定待ち (0.5秒から0.3秒に短縮)
            domo_button.click()

            # DOMO後の状態変化を待つ (aria-labelが "Domo済み" になるか、アイコンがis-activeになる)
            # action_delays から読むように変更
            action_delays = main_config.get("action_delays", {})
            delay_after_action = action_delays.get("after_domo_sec", 1.5)

            try:
                # DOMO後の状態確認のタイムアウトを5秒に短縮
                WebDriverWait(driver, 5).until(
                    lambda d: ("Domo済み" in (d.find_element(By.CSS_SELECTOR, current_selector_used).get_attribute("aria-label") or "")) or \
                              ("is-active" in (d.find_element(By.CSS_SELECTOR, f"{current_selector_used} span[class*='DomoActionContainer__DomoIcon'], {current_selector_used} span.RidgeIcon").get_attribute("class") or ""))
                )
                aria_label_after = driver.find_element(By.CSS_SELECTOR, current_selector_used).get_attribute("aria-label")
                logger.info(f"DOMOしました: {activity_url.split('/')[-1]} (aria-label: {aria_label_after})")
                time.sleep(delay_after_action)
                return True
            except TimeoutException:
                logger.warning(f"DOMO実行後、状態変化の確認でタイムアウト: {activity_url.split('/')[-1]}")
                # タイムアウトしても実際にはDOMO成功している可能性もある
                time.sleep(delay_after_action) # 一応待機
                return False # 失敗扱いとする
        else:
            # 既にDOMO済みの場合
            return False # DOMOアクションは実行していないのでFalse

    except TimeoutException:
        logger.warning(f"DOMO処理中にタイムアウト ({activity_url.split('/')[-1]})。ページ要素が見つからないか、読み込みが遅い可能性があります。")
    except NoSuchElementException:
        logger.warning(f"DOMOボタンまたはその構成要素が見つかりません ({activity_url.split('/')[-1]})。セレクタが古い可能性があります。")
    except Exception as e:
        logger.error(f"DOMO実行中に予期せぬエラー ({activity_url.split('/')[-1]}):", exc_info=True)
    return False

# --- タイムラインDOMO機能 ---
def domo_timeline_activities(driver):
    """
    タイムライン上の活動記録にDOMOする機能。
    config.yaml の timeline_domo_settings に従って動作する。
    """
    if not TIMELINE_DOMO_SETTINGS.get("enable_timeline_domo", False):
        logger.info("タイムラインDOMO機能は設定で無効になっています。")
        return

    logger.info(">>> タイムラインDOMO機能を開始します...")
    # タイムラインURLは固定か、configから取得できるようにしても良い
    timeline_page_url = TIMELINE_URL
    logger.info(f"タイムラインページへアクセス: {timeline_page_url}")
    driver.get(timeline_page_url)
    # --- デバッグ用HTML出力コードは削除されました ---

    max_activities_to_domo = TIMELINE_DOMO_SETTINGS.get("max_activities_to_domo_on_timeline", 10)
    domoed_count = 0
    processed_activity_urls = set()

    try:
        # タイムラインの各フィードアイテム（活動日記またはモーメント）を特定するセレクタ
        feed_item_selector = "li.TimelineList__Feed"
        # フィードアイテムが活動日記であることを示す内部のセレクタ
        activity_item_indicator_selector = "div.TimelineActivityItem"
        # 活動日記アイテム内の、実際の活動記録ページへのリンク
        activity_link_in_item_selector = "a.TimelineActivityItem__BodyLink[href^='/activities/']"

        logger.info(f"タイムラインのフィードアイテム ({feed_item_selector}) の出現を待ちます...")
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, feed_item_selector))
        )
        logger.info("タイムラインのフィードアイテム群を発見。")
        time.sleep(1.5) # スクロールや追加読み込みを考慮した描画安定待ち (2.5秒から短縮)

        feed_items = driver.find_elements(By.CSS_SELECTOR, feed_item_selector)
        logger.info(f"タイムラインから {len(feed_items)} 件のフィードアイテム候補を検出しました。")

        if not feed_items:
            logger.info("タイムラインにフィードアイテムが見つかりませんでした。")
            return

        initial_feed_item_count = len(feed_items) # 初期のアイテム数を保存
        logger.info(f"処理対象の初期フィードアイテム数: {initial_feed_item_count}")

        for idx in range(initial_feed_item_count):
            if domoed_count >= max_activities_to_domo:
                logger.info(f"タイムラインDOMOの上限 ({max_activities_to_domo}件) に達しました。")
                break

            activity_url = None
            # 各反復処理の開始時に、現在のページからフィードアイテム要素を再取得する
            # StaleElementReferenceException を避けるため
            try:
                feed_items_on_page = driver.find_elements(By.CSS_SELECTOR, feed_item_selector)
                if idx >= len(feed_items_on_page):
                    logger.warning(f"フィードアイテムインデックス {idx} が現在のアイテム数 {len(feed_items_on_page)} を超えています。DOMが大きく変更された可能性があります。このアイテムの処理をスキップします。")
                    continue
                feed_item_element = feed_items_on_page[idx]

                # このフィードアイテムが活動日記であるかを確認
                # 活動日記特有の要素 (activity_item_indicator_selector) を探す
                activity_indicator_elements = feed_item_element.find_elements(By.CSS_SELECTOR, activity_item_indicator_selector)

                if not activity_indicator_elements:
                    logger.debug(f"フィードアイテム {idx+1}/{initial_feed_item_count} は活動日記ではありません (indicator: '{activity_item_indicator_selector}' 見つからず)。スキップします。")
                    continue

                # 活動日記であれば、その中のリンクを取得
                # activity_indicator_elements[0] をコンテキストとして使用
                link_element = activity_indicator_elements[0].find_element(By.CSS_SELECTOR, activity_link_in_item_selector)
                activity_url = link_element.get_attribute("href")

                if activity_url:
                    if activity_url.startswith("/"):
                        activity_url = BASE_URL + activity_url

                    if not activity_url.startswith(f"{BASE_URL}/activities/"):
                        logger.warning(f"無効な活動記録URL形式です: {activity_url}。スキップします。")
                        activity_url = None # 無効化

                if not activity_url:
                    logger.warning(f"活動記録カード {idx+1}/{initial_feed_item_count} から有効な活動記録URLを取得できませんでした。スキップします。")
                    continue

                if activity_url in processed_activity_urls:
                    logger.info(f"活動記録 ({activity_url.split('/')[-1]}) は既に処理試行済みです。スキップします。")
                    continue
                processed_activity_urls.add(activity_url)

                # ログ出力の母数を initial_feed_item_count に変更
                logger.info(f"タイムライン活動記録 {idx+1}/{initial_feed_item_count} (URL: {activity_url.split('/')[-1]}) のDOMOを試みます。")

                # 現在のページURLを保存
                current_main_page_url = driver.current_url

                if domo_activity(driver, activity_url): # domo_activity内でページ遷移が発生する
                    domoed_count += 1

                # DOMO処理後、元のタイムラインページに戻る (必要がある場合)
                # domo_activity が別ページに遷移するため、戻る処理を入れる
                if driver.current_url != current_main_page_url:
                    logger.debug(f"DOMO処理後、元のページ ({current_main_page_url}) に戻ります。")
                    driver.get(current_main_page_url)
                    # 戻った後、要素が再認識されるように少し待つ (セレクタを feed_item_selector に修正)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, feed_item_selector)))
                    time.sleep(0.5) # 追加の安定待ち (1秒から短縮)

                # 次の活動記録処理までの待機時間は domo_activity 内で考慮されているので、ここでは不要

            except NoSuchElementException:
                logger.warning(f"活動記録カード {idx+1}/{initial_feed_item_count} 内で活動記録リンクが見つかりません。スキップします。")
            except Exception as e_card_proc: # StaleElementReferenceException もここでキャッチされる可能性あり
                logger.error(f"活動記録カード {idx+1}/{initial_feed_item_count} (URL: {activity_url.split('/')[-1] if activity_url else 'N/A'}) の処理中にエラー: {e_card_proc}", exc_info=True)

            # ループの最後に短いグローバルな待機を入れても良い (サーバー負荷軽減のため)
            # time.sleep(TIMELINE_DOMO_SETTINGS.get("delay_between_timeline_domo_sec", 2.0)) # これはdomo_activity内で実行されるので不要

    except TimeoutException:
        logger.warning("タイムライン活動記録の読み込みでタイムアウトしました。")
    except Exception as e:
        logger.error(f"タイムラインDOMO処理中に予期せぬエラーが発生しました。", exc_info=True)

    logger.info(f"<<< タイムラインDOMO機能完了。合計 {domoed_count} 件の活動記録にDOMOしました。")

# --- ユーザープロフィール操作関連の補助関数 (yamap_auto.pyから移植・調整) ---
def get_latest_activity_url(driver, user_profile_url):
    """
    指定されたユーザープロフィールURLから最新の活動日記のURLを取得する。
    """
    user_id_log = user_profile_url.split('/')[-1].split('?')[0] # user_id部分のみ取得
    logger.info(f"プロフィール ({user_id_log}) の最新活動日記URLを取得します。")

    current_page_url = driver.current_url
    if user_profile_url not in current_page_url : # 部分一致でも可とするか、厳密にするか
        logger.debug(f"対象のユーザープロフィールページ ({user_profile_url}) に遷移します。")
        driver.get(user_profile_url)
        # プロフィールページ内の特定の要素が表示されるまで待つ (例: ユーザー名や活動記録タブなど)
        try:
            WebDriverWait(driver, 10).until(
                EC.any_of(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[data-testid='profile-tab-activities']")), # 活動記録タブ
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h1[class*='UserProfileScreen_userName']")) # ユーザー名
                )
            )
        except TimeoutException:
            logger.warning(f"ユーザー ({user_id_log}) のプロフィールページ主要要素の読み込みタイムアウト。")
            # ページ遷移が不完全な可能性があるため、ここでリターンも検討
    else:
        logger.debug(f"既にユーザープロフィールページ ({user_profile_url}) 付近にいます。")

    latest_activity_url = None
    try:
        # 活動日記一覧のタブが選択されていることを確認、またはクリックする (必要な場合)
        # YAMAPではデフォルトで活動日記タブが開いていることが多いので、一旦省略

        # 最新の活動日記へのリンクを探すセレクタ (YAMAPのHTML構造に依存)
        # 例: <article data-testid="activity-entry"><a href="/activities/..." ...>
        # 優先順位をつけて試行
        activity_link_selectors = [
            "article[data-testid='activity-entry'] a[href^='/activities/']", # 推奨される構造
            "a[data-testid='activity-card-link']", # 以前の構造・フォールバック
            ".ActivityCard_card__link__XXXXX a[href^='/activities/']" # 特定のクラス名 (変わりやすい)
        ]

        # ページが完全に読み込まれるのを待つために少し待機 -> WebDriverWaitに置き換える
        # time.sleep(DOMO_SETTINGS.get("short_wait_sec", 2)) # short_wait_secはdomo_settingsにある想定

        for selector in activity_link_selectors:
            try:
                # ページが動的に読み込まれる場合、要素が見つかるまで待つ (ここでしっかり待つ)
                # action_delays から読むように変更
                action_delays = main_config.get("action_delays", {})
                wait_time_for_activity_link = action_delays.get("wait_for_activity_link_sec", 7)
                WebDriverWait(driver, wait_time_for_activity_link).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                activity_link_element = driver.find_element(By.CSS_SELECTOR, selector) # 最初の一つが最新と仮定
                href = activity_link_element.get_attribute('href')
                if href:
                    if href.startswith("/"):
                        latest_activity_url = BASE_URL + href
                    elif href.startswith(BASE_URL):
                        latest_activity_url = href

                    if latest_activity_url and "/activities/" in latest_activity_url:
                        logger.info(f"ユーザー ({user_id_log}) の最新活動日記URL: {latest_activity_url.split('/')[-1]} (selector: {selector})")
                        return latest_activity_url
                    else:
                        latest_activity_url = None # 無効なURLならリセット
            except (NoSuchElementException, TimeoutException):
                logger.debug(f"セレクタ '{selector}' で最新活動日記リンクが見つかりませんでした。")
                continue

        if not latest_activity_url:
            logger.info(f"ユーザー ({user_id_log}) の最新の活動日記が見つかりませんでした。")

    except TimeoutException:
        logger.warning(f"ユーザー ({user_id_log}) の活動日記リスト読み込みでタイムアウトしました。")
    except Exception as e:
        logger.error(f"ユーザー ({user_id_log}) の最新活動日記取得中にエラー。", exc_info=True)
    return latest_activity_url

def get_user_follow_counts(driver, user_profile_url):
    """
    ユーザープロフィールページからフォロー数とフォロワー数を取得する。
    取得できなかった場合は (-1, -1) を返す。
    """
    user_id_log = user_profile_url.split('/')[-1].split('?')[0]
    logger.info(f"ユーザー ({user_id_log}) のフォロー数/フォロワー数を取得します。")

    current_page_url = driver.current_url
    if user_profile_url not in current_page_url:
        logger.debug(f"対象のユーザープロフィールページ ({user_profile_url}) に遷移します。")
        driver.get(user_profile_url)
        # ページ遷移確認
        try:
            WebDriverWait(driver, 10).until(EC.url_contains(user_id_log))
        except TimeoutException:
            logger.warning(f"ユーザー({user_id_log})のプロフィールページへの遷移確認タイムアウト")
            # return -1, -1 # 遷移失敗の可能性
    else:
        logger.debug(f"既にユーザープロフィールページ ({user_profile_url}) 付近にいます。")

    follows_count = -1
    followers_count = -1

    try:
        # フォロー数/フォロワー数を含むタブコンテナが表示されるまで待つ
        tabs_container_selector = "div#tabs.css-1kw20l6" # または ul.css-7te929
        try:
            tabs_container_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, tabs_container_selector))
            )
            logger.debug(f"タブコンテナ ({tabs_container_selector}) を発見。")
        except TimeoutException:
            logger.warning(f"フォロー数/フォロワー数タブコンテナ ({tabs_container_selector}) の読み込みタイムアウト ({user_id_log})。")
            # --- デバッグ用：タイムアウト時のページソース一部出力 (コメントアウトに戻す) ---
            # try:
            #     logger.debug(f"Page source on get_user_follow_counts timeout (tabs container, approx 2000 chars):\n{driver.page_source[:2000]}")
            # except Exception as e_debug:
            #     logger.error(f"ページソース取得中のデバッグエラー: {e_debug}")
            # --- デバッグここまで ---
            return follows_count, followers_count # コンテナが見つからなければ早期リターン

        follow_link_selector = "a[href*='tab=follows']"  # 末尾一致から部分一致に変更
        follower_link_selector = "a[href*='tab=followers']" # 末尾一致から部分一致に変更
        found_follows = False # 取得成功フラグ
        found_followers = False # 取得成功フラグ

        # フォロー中の数
        try:
            # tabs_container_element を起点に検索
            follow_link_element = tabs_container_element.find_element(By.CSS_SELECTOR, follow_link_selector)
            full_text = follow_link_element.text.strip()
            num_str = "".join(filter(str.isdigit, full_text))
            if num_str:
                follows_count = int(num_str)
                found_follows = True
            else:
                logger.warning(f"フォロー数のテキスト「{full_text}」から数値を抽出できませんでした ({user_id_log})。")
        except NoSuchElementException:
            logger.warning(f"フォロー中の数を特定するリンク要素 ({follow_link_selector}) がタブコンテナ内に見つかりませんでした ({user_id_log})。")
            # リンクが見つからない場合、タブコンテナのHTMLとページソースを出力 (コメントアウトに戻す)
            # try:
            #     if 'tabs_container_element' in locals() and tabs_container_element: # tabs_container_elementが定義されているか確認
            #         logger.debug(f"Tabs container HTML (follow link not found for {user_id_log}):\n{tabs_container_element.get_attribute('innerHTML')[:1000]}...")
            #     logger.debug(f"Page source (follow link not found for {user_id_log}, approx 2000 chars):\n{driver.page_source[:2000]}")
            # except Exception as e_debug_nf:
            #     logger.error(f"フォローリンク未発見時のデバッグHTML取得エラー ({user_id_log}): {e_debug_nf}")
        except Exception as e_follow_count:
            logger.error(f"フォロー数取得処理中に予期せぬエラー ({user_id_log}): {e_follow_count}", exc_info=True)

        # フォロワーの数
        try:
            # tabs_container_element を起点に検索
            follower_link_element = tabs_container_element.find_element(By.CSS_SELECTOR, follower_link_selector)
            full_text = follower_link_element.text.strip()
            num_str = "".join(filter(str.isdigit, full_text))
            if num_str:
                followers_count = int(num_str)
                found_followers = True
            else:
                logger.warning(f"フォロワー数のテキスト「{full_text}」から数値を抽出できませんでした ({user_id_log})。")
        except NoSuchElementException:
            logger.warning(f"フォロワーの数を特定するリンク要素 ({follower_link_selector}) がタブコンテナ内に見つかりませんでした ({user_id_log})。")
            # リンクが見つからない場合、タブコンテナのHTMLとページソースを出力 (コメントアウトに戻す)
            # try:
            #     if 'tabs_container_element' in locals() and tabs_container_element: # tabs_container_elementが定義されているか確認
            #         logger.debug(f"Tabs container HTML (follow link not found for {user_id_log}):\n{tabs_container_element.get_attribute('innerHTML')[:1000]}...")
            #     logger.debug(f"Page source (follow link not found for {user_id_log}, approx 2000 chars):\n{driver.page_source[:2000]}")
            # except Exception as e_debug_nf:
            #     logger.error(f"フォローリンク未発見時のデバッグHTML取得エラー ({user_id_log}): {e_debug_nf}")
        except Exception as e_follower_count:
            logger.error(f"フォロワー数取得処理中に予期せぬエラー ({user_id_log}): {e_follower_count}", exc_info=True)

        logger.info(f"ユーザー ({user_id_log}): フォロー中={follows_count}, フォロワー={followers_count}")

    except TimeoutException: # これは tabs_container_element の取得に関する TimeoutException をキャッチするものではなくなった
        # このブロックは、tabs_container_element の取得が成功した後の、予期せぬタイムアウトを指す。
        # 通常は tabs_container_element.find_element で NoSuchElementException になるはず。
        logger.warning(f"get_user_follow_countsのメインtryブロックで予期せぬTimeoutExceptionが発生 ({user_id_log})。")
        # --- デバッグ用：タイムアウト時のページソース一部出力 (通常はコメントアウト) ---
        # try:
        #     # プロフィール情報が含まれると期待される上位のコンテナ要素のセレクタ（例）
        #     # body_element = driver.find_element(By.CSS_SELECTOR, "body")
        #     # profile_header_area = driver.find_element(By.CSS_SELECTOR, "div.css-10rsfrr") # プロフィールヘッダー付近
        #     # stats_area = driver.find_element(By.CSS_SELECTOR, "div.css-6ej1p9") # タブリストの親
        #     # logger.debug(f"Page source (stats_area) on timeout:\n{stats_area.get_attribute('outerHTML')}")
        #     logger.debug(f"Page source on get_user_follow_counts timeout (approx 2000 chars):\n{driver.page_source[:2000]}")
        # except Exception as e_debug:
        #     logger.error(f"ページソース取得中のデバッグエラー: {e_debug}")
        # --- デバッグここまで ---
    except Exception as e:
        logger.error(f"フォロー数/フォロワー数取得中にエラー ({user_id_log})。", exc_info=True)

    return follows_count, followers_count

def find_follow_button_on_profile_page(driver):
    """
    ユーザープロフィールページ上で「フォローする」ボタンを探す。
    既にフォロー中、またはボタンがない場合はNoneを返す。
    """
    logger.info(f"find_follow_button_on_profile_page: Executing. URL: {driver.current_url}, Title: {driver.title}")
    try:
        # 呼び出し元でページの読み込み完了を待っているため、ここでのユーザー名H1の待機はコメントアウト
        # username_h1_selector = "h1.css-jctfiw"
        # try:
        #     WebDriverWait(driver, 10).until(
        #         EC.visibility_of_element_located((By.CSS_SELECTOR, username_h1_selector))
        #     )
        #     logger.debug(f"ユーザー名 ({username_h1_selector}) の表示を確認。")
        # except TimeoutException:
        #     logger.warning(f"プロフィールページのユーザー名 ({username_h1_selector}) が10秒以内に表示されませんでした。")
        #     try:
        #         logger.debug(f"Timeout context (H1 not found): URL={driver.current_url}, Title={driver.title}")
        #         logger.debug(f"Page source on username H1 timeout (approx 2000 chars):\n{driver.page_source[:2000]}")
        #     except Exception as e_debug:
        #         logger.error(f"ユーザー名H1タイムアウト時のデバッグ情報取得エラー: {e_debug}")
        #     return None

        # 主要要素の存在確認ログ (ユーザー名確認後)
        debug_elements_found = {
            "div.css-1fsc5gw (フォローボタンコンテナ)": len(driver.find_elements(By.CSS_SELECTOR, "div.css-1fsc5gw")),
            # "button[data-testid='FollowButton']": len(driver.find_elements(By.CSS_SELECTOR, "button[data-testid='FollowButton']")), # コメントアウト
            # "button[data-testid='FollowingButton']": len(driver.find_elements(By.CSS_SELECTOR, "button[data-testid='FollowingButton']")), # コメントアウト
            "button[aria-pressed='true'] (フォロー中候補)": len(driver.find_elements(By.CSS_SELECTOR, "button[aria-pressed='true']")),
            "button[aria-pressed='false'] (フォローする候補)": len(driver.find_elements(By.CSS_SELECTOR, "button[aria-pressed='false']")),
        }
        logger.debug(f"プロフィールページのフォロー関連要素検出状況: {debug_elements_found}")

        # 1. 「フォロー中」ボタンの確認
        # data-testid検索はコメントアウト
        # try:
        #     # data-testid検索前のHTMLデバッグログ
        #     try:
        #         debug_button_container = driver.find_element(By.CSS_SELECTOR, "div.css-1fsc5gw")
        #         if debug_button_container:
        #             logger.debug(f"Debug HTML for FollowingButton (div.css-1fsc5gw):\n{debug_button_container.get_attribute('outerHTML')[:500]}...")
        #     except NoSuchElementException:
        #         logger.debug("Debug HTML: div.css-1fsc5gw not found before searching FollowingButton.")
        #     except Exception as e_debug:
        #         logger.error(f"Debug HTML (FollowingButton) logging error: {e_debug}")
        #
        #     following_button_testid = driver.find_element(By.CSS_SELECTOR, "button[data-testid='FollowingButton']")
        #     if following_button_testid and following_button_testid.is_displayed():
        #         logger.info("プロフィールページで「フォロー中」ボタン (data-testid) を発見。既にフォロー済みと判断。")
        #         return None
        # except NoSuchElementException:
        #     logger.debug("data-testid='FollowingButton' の「フォロー中」ボタンは見つかりませんでした。")

        # aria-pressed='true' とテキストで確認
        try:
            # ボタンを直接囲む可能性のあるコンテナから探索を試みる
            button_container_candidates = driver.find_elements(By.CSS_SELECTOR, "div.css-1fsc5gw, div.css-194f6e2")
            for container in button_container_candidates:
                try:
                    following_buttons_aria = container.find_elements(By.CSS_SELECTOR, "button[aria-pressed='true']")
                    for btn in following_buttons_aria:
                        if btn and btn.is_displayed():
                            # span.c1hbtdj4 に依存せず、ボタン自身のテキストも確認する
                            if "フォロー中" in btn.text or ("フォロー中" in btn.find_element(By.CSS_SELECTOR, "span").text if btn.find_elements(By.CSS_SELECTOR, "span") else False):
                                logger.info(f"プロフィールページで「フォロー中」ボタン (aria-pressed='true' + text in container) を発見。")
                                return None
                except NoSuchElementException:
                    continue # コンテナ内の探索で失敗しても次のコンテナ候補へ

            # コンテナ指定なしでのグローバルな探索 (フォールバック)
            following_buttons_aria_global = driver.find_elements(By.CSS_SELECTOR, "button[aria-pressed='true']")
            for btn in following_buttons_aria_global:
                if btn and btn.is_displayed():
                    if "フォロー中" in btn.text or ("フォロー中" in btn.find_element(By.CSS_SELECTOR, "span").text if btn.find_elements(By.CSS_SELECTOR, "span") else False):
                        logger.info("プロフィールページで「フォロー中」ボタン (aria-pressed='true' + text, global) を発見。")
                        return None

            # XPathによるテキスト一致 (最終フォールバック)
            if driver.find_elements(By.XPATH, ".//button[normalize-space(.)='フォロー中']"):
                 logger.info("プロフィールページで「フォロー中」ボタン (XPath text, グローバル) を発見。既にフォロー済みと判断。")
                 return None
        except Exception as e_following_check:
            logger.warning(f"「フォロー中」ボタンの aria-pressed/XPath 確認中にエラー: {e_following_check}", exc_info=True)


        # 2. 「フォローする」ボタンの探索
        # data-testid検索はコメントアウト
        # try:
        #     # data-testid検索前のHTMLデバッグログ
        #     try:
        #         debug_button_container = driver.find_element(By.CSS_SELECTOR, "div.css-1fsc5gw")
        #         if debug_button_container:
        #             logger.debug(f"Debug HTML for FollowButton (div.css-1fsc5gw):\n{debug_button_container.get_attribute('outerHTML')[:500]}...")
        #     except NoSuchElementException:
        #         logger.debug("Debug HTML: div.css-1fsc5gw not found before searching FollowButton.")
        #     except Exception as e_debug:
        #         logger.error(f"Debug HTML (FollowButton) logging error: {e_debug}")
        #
        #     follow_button_testid = driver.find_element(By.CSS_SELECTOR, "button[data-testid='FollowButton']")
        #     if follow_button_testid and follow_button_testid.is_displayed() and follow_button_testid.is_enabled():
        #         logger.info("プロフィールページで「フォローする」ボタン (data-testid) を発見。")
        #         return follow_button_testid
        # except NoSuchElementException:
        #     logger.debug("data-testid='FollowButton' の「フォローする」ボタンは見つかりませんでした。")

        # aria-pressed='false' とテキストで確認
        try:
            button_container_candidates = driver.find_elements(By.CSS_SELECTOR, "div.css-1fsc5gw, div.css-194f6e2")
            for container in button_container_candidates:
                try:
                    follow_buttons_aria = container.find_elements(By.CSS_SELECTOR, "button[aria-pressed='false']")
                    for btn in follow_buttons_aria:
                        if btn and btn.is_displayed() and btn.is_enabled():
                            if "フォローする" in btn.text or ("フォローする" in btn.find_element(By.CSS_SELECTOR, "span").text if btn.find_elements(By.CSS_SELECTOR, "span") else False):
                                logger.info(f"プロフィールページで「フォローする」ボタン (aria-pressed='false' + text in container) を発見。")
                                return btn
                except NoSuchElementException:
                    continue

            follow_buttons_aria_global = driver.find_elements(By.CSS_SELECTOR, "button[aria-pressed='false']")
            for btn in follow_buttons_aria_global:
                 if btn and btn.is_displayed() and btn.is_enabled():
                    if "フォローする" in btn.text or ("フォローする" in btn.find_element(By.CSS_SELECTOR, "span").text if btn.find_elements(By.CSS_SELECTOR, "span") else False):
                        logger.info("プロフィールページで「フォローする」ボタン (aria-pressed='false' + text, global) を発見。")
                        return btn

            # XPathによるテキスト一致 (最終フォールバック)
            button_xpath = driver.find_element(By.XPATH, ".//button[normalize-space(.)='フォローする']")
            if button_xpath and button_xpath.is_displayed() and button_xpath.is_enabled():
                logger.info("プロフィールページで「フォローする」ボタン (XPath text, グローバル) を発見。")
                return button_xpath
        except NoSuchElementException: # XPathで見つからなかった場合の NoSuchElementException はここでキャッチ
             logger.debug("XPath .//button[normalize-space(.)='フォローする'] (グローバル) で「フォローする」ボタンが見つかりませんでした。")
        except Exception as e_follow_check:
            logger.warning(f"「フォローする」ボタンの aria-pressed/XPath 確認中にエラー: {e_follow_check}", exc_info=True)

        # aria-label によるフォールバック (グローバル検索)
        try:
            follow_button_aria_label = driver.find_element(By.CSS_SELECTOR, "button[aria-label*='フォローする']")
            if follow_button_aria_label and follow_button_aria_label.is_displayed() and follow_button_aria_label.is_enabled():
                logger.info("プロフィールページで「フォローする」ボタン (aria-label, グローバル) を発見。")
                return follow_button_aria_label
        except NoSuchElementException:
            logger.debug("CSSセレクタ button[aria-label*='フォローする'] (グローバル) で「フォローする」ボタンが見つかりませんでした。")


        logger.info("プロフィールページでクリック可能な「フォローする」ボタンが見つかりませんでした。")
        # デバッグ情報として関連エリアのHTMLを出力
        try:
            debug_html_output = ""
            for sel in ["div.css-1fsc5gw", "div.css-126zbgb", "div.css-kooiip"]: # 狭い範囲から試す
                try:
                    debug_element = driver.find_element(By.CSS_SELECTOR, sel)
                    if debug_element:
                        debug_html_output = debug_element.get_attribute('outerHTML')
                        logger.debug(f"ボタンが見つからなかった関連エリアのHTML ({sel}):\n{debug_html_output[:1000]}...") # 長すぎる場合に省略
                        break # 最初に見つかったものを出力
                except NoSuchElementException:
                    pass
            if not debug_html_output:
                logger.debug("ボタン検索失敗時のデバッグHTML取得試行で、主要なコンテナ候補が見つかりませんでした。")
            # else: # HTMLが見つかった場合は既に出力されている
            #    pass
            # さらに広範囲のHTMLを出力（最終手段）
            try:
                body_html = driver.find_element(By.CSS_SELECTOR, "body").get_attribute("outerHTML")
                logger.debug(f"Body HTML (first 3000 chars) on button not found:\n{body_html[:3000]}...")
            except Exception as e_body_debug:
                logger.error(f"Body HTML取得中のデバッグエラー: {e_body_debug}")
        except Exception as e_debug_html:
            logger.debug(f"ボタン検索失敗時のデバッグHTML取得中にエラー: {e_debug_html}")
        return None
    except TimeoutException:
        logger.warning("プロフィールページの主要コンテナまたはフォローボタン群の読み込みタイムアウト。") # ここは username_h1_selector のタイムアウトを指すことになる
        # タイムアウト時にもページソースの情報を少し出す (これは username_h1_selector のタイムアウト時に既に出力される)
        # try:
        #     logger.debug(f"Page source on WebDriverWait timeout (approx 2000 chars):\n{driver.page_source[:2000]}")
        # except Exception as e_timeout_debug:
        #     logger.error(f"タイムアウト時のページソース取得デバッグエラー: {e_timeout_debug}")
    except Exception as e:
        logger.error("プロフィールページのフォローボタン検索でエラー。", exc_info=True)
    return None

# --- 検索からのフォロー＆DOMO機能 ---
def search_follow_and_domo_users(driver, current_user_id):
    """
    活動記録検索ページを巡回し、条件に合うユーザーをフォローし、
    そのユーザーの最新活動記録にDOMOする。
    config.yaml の search_and_follow_settings に従って動作する。
    """
    if not SEARCH_AND_FOLLOW_SETTINGS.get("enable_search_and_follow", False):
        logger.info("検索からのフォロー＆DOMO機能は設定で無効になっています。")
        return

    logger.info(">>> 検索からのフォロー＆DOMO機能を開始します...")

    start_url = SEARCH_AND_FOLLOW_SETTINGS.get("search_activities_url", SEARCH_ACTIVITIES_URL_DEFAULT)
    max_pages = SEARCH_AND_FOLLOW_SETTINGS.get("max_pages_to_process_search", 1)
    max_users_per_page = SEARCH_AND_FOLLOW_SETTINGS.get("max_users_to_process_per_page", 5)
    min_followers = SEARCH_AND_FOLLOW_SETTINGS.get("min_followers_for_search_follow", 20)
    ratio_threshold = SEARCH_AND_FOLLOW_SETTINGS.get("follow_ratio_threshold_for_search", 0.9)
    domo_after_follow = SEARCH_AND_FOLLOW_SETTINGS.get("domo_latest_activity_after_follow", True)
    delay_user_processing = SEARCH_AND_FOLLOW_SETTINGS.get("delay_between_user_processing_in_search_sec", 5.0)
    delay_pagination = SEARCH_AND_FOLLOW_SETTINGS.get("delay_after_pagination_sec", 3.0)

    processed_users_on_current_page = 0
    total_followed_count = 0
    total_domoed_count = 0

    # 活動記録検索結果ページからユーザープロフィールへの典型的なパスを想定
    activity_card_selector = "article[data-testid='activity-entry']" # タイムラインと同様のカードを想定 (要確認)
    # ユーザー提供HTMLに基づく修正: <div class="css-1vh31zw"><a class="css-k2fvpp" href="/users/3122085">...</a></div>
    user_profile_link_in_card_selector = "div.css-1vh31zw > a.css-k2fvpp[href^='/users/']"

    processed_profile_urls = set() # セッション内で同じユーザーを何度も処理しないため

    for page_num in range(1, max_pages + 1):
        if page_num > 1: # 2ページ目以降はページネーションが必要
            logger.info(f"{page_num-1}ページ目の処理完了。次のページへ遷移します。")
            # TODO: ページネーション処理の実装
            # YAMAPの検索結果ページで「次へ」やページ番号のボタンを見つけてクリックする
            # 例: next_button_selector = "a[data-testid='pagination-next-button'], a.pagination-next"
            # try:
            #     next_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, next_button_selector)))
            #     driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
            #     next_button.click()
            #     logger.info(f"{page_num}ページ目へ遷移しました。")
            #     time.sleep(delay_pagination)
            #     WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector))) # 新しいページのカード読み込み待ち
            # except (TimeoutException, NoSuchElementException):
            #     logger.info("次のページへのボタンが見つからないか、クリックできませんでした。処理を終了します。")
            #     break
            logger.warning("ページネーション処理は未実装です。複数ページ処理は現在スキップされます。")
            break # 現状は1ページのみ対応

        current_url_to_load = start_url if page_num == 1 else driver.current_url # 1ページ目はstart_url, 以降は現在のURLのまま(ページネーション後)
        if driver.current_url != current_url_to_load and page_num == 1 : # 1ページ目のみ明示的にget
             logger.info(f"{page_num}ページ目の活動記録検索結果 ({current_url_to_load}) にアクセスします。")
             driver.get(current_url_to_load)

        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, activity_card_selector))
            )
            time.sleep(0.5) # 描画安定待ち (2秒から0.5秒に短縮)
        except TimeoutException:
            logger.warning(f"活動記録検索結果ページ ({current_url_to_load}) で活動記録カードの読み込みタイムアウト。このページの処理をスキップします。")
            continue

        initial_activity_cards_on_page = driver.find_elements(By.CSS_SELECTOR, activity_card_selector)
        num_cards_to_process = len(initial_activity_cards_on_page)
        logger.info(f"{page_num}ページ目: {num_cards_to_process} 件の活動記録候補を検出。")

        if not initial_activity_cards_on_page:
            logger.info("このページには活動記録が見つかりませんでした。")
            continue

        processed_users_on_current_page = 0
        # activity_cards_on_page はループ内で再取得するので、ここではインデックスの範囲だけを使用
        for card_idx in range(num_cards_to_process):
            if processed_users_on_current_page >= max_users_per_page:
                logger.info(f"このページでの処理上限 ({max_users_per_page}ユーザー) に達しました。")
                break

            user_profile_url = None
            user_name_for_log = f"活動記録{card_idx+1}のユーザー" # ログ用のインデックスは0始まりを1始まりに

            try:
                # ループの各反復でカード要素を再取得
                # 元の検索ページに戻った後、要素が確実に存在するようにWebDriverWaitを挟む
                # (既存のWebDriverWaitはページ全体のカード読み込みなので、ここでは個別のカード再取得)
                current_activity_cards = driver.find_elements(By.CSS_SELECTOR, activity_card_selector)
                if card_idx >= len(current_activity_cards):
                    logger.warning(f"カードインデックス {card_idx} が現在のカード数 {len(current_activity_cards)} を超えています。DOM構造が変更された可能性があります。このカードの処理をスキップします。")
                    continue
                card_element = current_activity_cards[card_idx]

                # カードからユーザープロフィールURLを取得
                # StaleElementReferenceException がここで発生していた
                profile_link_el = WebDriverWait(card_element, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, user_profile_link_in_card_selector))
                )
                # profile_link_el = card_element.find_element(By.CSS_SELECTOR, user_profile_link_in_card_selector) # 元のコード
                href = profile_link_el.get_attribute("href")
                if href:
                    if href.startswith("/"): user_profile_url = BASE_URL + href
                    elif href.startswith(BASE_URL): user_profile_url = href

                if not user_profile_url or f"/users/{current_user_id}" in user_profile_url: # 自分自身は除外
                    logger.debug(f"無効なプロフィールURLか自分自身 ({user_profile_url}) のためスキップ。")
                    continue

                if user_profile_url in processed_profile_urls:
                    logger.info(f"ユーザー ({user_profile_url.split('/')[-1]}) は既に処理済みのためスキップ。")
                    continue

                # ユーザー名の取得 (ログ用、取得できなくても処理は続行)
                try:
                    name_el = profile_link_el.find_element(By.CSS_SELECTOR, "span, img[alt]") # span内やimgのalt属性など
                    if name_el.tag_name == "img": user_name_for_log = name_el.get_attribute("alt")
                    else: user_name_for_log = name_el.text.strip()
                    if not user_name_for_log: user_name_for_log = user_profile_url.split('/')[-1]
                except: pass # ユーザー名取得失敗は許容

                logger.info(f"--- ユーザー「{user_name_for_log}」(URL: {user_profile_url.split('/')[-1]}) の処理開始 ---")
                processed_profile_urls.add(user_profile_url) # ここで処理対象としてマーク

                # 1. プロフィールページでフォローボタンがあるか確認 (なければ既にフォロー済みか対象外)
                #    get_user_follow_counts の中でページ遷移するので、その前にURLを保持
                search_page_url_before_profile_visit = driver.current_url

                follow_button = find_follow_button_on_profile_page(driver) # この中で user_profile_url へ遷移する想定だったが...
                                                                       # find_follow_button_on_profile_page は driver.get を内部で行わないので修正が必要
                                                                       # 先に遷移する
                driver.get(user_profile_url)
                try:
                    # ページ遷移と主要コンテンツの読み込みをより確実に待つ
                    WebDriverWait(driver, 20).until( # タイムアウトを20秒に設定
                        EC.all_of(
                            EC.url_contains(user_profile_url.split('/')[-1]),
                            EC.visibility_of_element_located((By.CSS_SELECTOR, "h1.css-jctfiw")), # ユーザー名
                            lambda d: d.execute_script("return document.readyState") == "complete",
                            EC.presence_of_element_located((By.CSS_SELECTOR, "footer.css-1yg0z07")) # フッター要素
                        )
                    )
                    logger.debug(f"ユーザープロフィールページ ({user_profile_url}) の主要コンテンツ読み込み完了を確認。")
                except TimeoutException:
                    logger.warning(f"ユーザープロフィールページ ({user_profile_url}) の読み込みタイムアウト（複合条件）。このユーザーの処理をスキップします。")
                    logger.debug(f"Timeout context: URL={driver.current_url}, Title={driver.title}")
                    # 元の検索ページに戻る処理をここにも入れる（エラーリカバリのため）
                    driver.get(search_page_url_before_profile_visit)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    continue # 次のカードへ

                # find_follow_button_on_profile_page を呼び出す直前にURLを再確認 (念のため維持)
                if user_profile_url not in driver.current_url:
                    logger.error(f"URL不一致（待機後）: プロフィールページ ({user_profile_url}) にいるはずが、現在のURLは {driver.current_url} です。スキップします。")
                    # driver.get(search_page_url_before_profile_visit) # 必要に応じて戻る処理
                    # WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    continue

                follow_button_on_profile = find_follow_button_on_profile_page(driver)

                if not follow_button_on_profile:
                    logger.info(f"ユーザー「{user_name_for_log}」は既にフォロー済みか、プロフィールにフォローボタンがありません。スキップ。")
                    driver.get(search_page_url_before_profile_visit) # 元の検索ページに戻る
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector))) # 安定待ちをWebDriverWaitに
                    continue

                # 2. フォロー数/フォロワー数を取得して条件判定
                follows, followers = get_user_follow_counts(driver, user_profile_url) # driverは既にプロフィールページにいる想定

                if follows == -1 or followers == -1:
                    logger.warning(f"ユーザー「{user_name_for_log}」のフォロー数/フォロワー数が取得できませんでした。スキップ。")
                    driver.get(search_page_url_before_profile_visit)
                    time.sleep(1)
                    continue

                if followers < min_followers:
                    logger.info(f"ユーザー「{user_name_for_log}」のフォロワー数 ({followers}) が閾値 ({min_followers}) 未満。スキップ。")
                    driver.get(search_page_url_before_profile_visit)
                    time.sleep(1)
                    continue

                current_ratio = (follows / followers) if followers > 0 else float('inf') # ゼロ除算回避
                logger.info(f"ユーザー「{user_name_for_log}」: F中={follows}, Fワー={followers}, Ratio={current_ratio:.2f} (閾値: >= {ratio_threshold})")

                # 条件: フォロー数がフォロワー数より多く、かつ、比率が閾値以上
                if not (follows > followers and current_ratio >= ratio_threshold):
                    logger.info(f"「F中 > Fワー」かつ「Ratio >= {ratio_threshold}」の条件を満たしません。スキップ。")
                    driver.get(search_page_url_before_profile_visit)
                    time.sleep(1) # 元のページに戻った後の安定待機（これは後続のWebDriverWaitで代替可能か別途検討）
                    continue

                # 3. 条件を満たせばフォロー実行
                logger.info(f"フォロー条件を満たしました。ユーザー「{user_name_for_log}」をフォローします。")
                if click_follow_button_and_verify(driver, follow_button_on_profile, user_name_for_log):
                    total_followed_count += 1

                    # 4. フォロー後、DOMOが有効なら最新活動記録にDOMO
                    if domo_after_follow:
                        logger.info(f"ユーザー「{user_name_for_log}」の最新活動記録にDOMOを試みます。")
                        # get_latest_activity_url は内部で user_profile_url に遷移する
                        latest_act_url = get_latest_activity_url(driver, user_profile_url)
                        if latest_act_url:
                            if domo_activity(driver, latest_act_url): # domo_activity は内部で遷移
                                total_domoed_count += 1
                        else:
                            logger.info(f"ユーザー「{user_name_for_log}」の最新活動記録が見つからず、DOMOできませんでした。")

                processed_users_on_current_page += 1
                logger.info(f"--- ユーザー「{user_name_for_log}」の処理終了 ---")

                # 元の検索結果ページに戻る
                logger.debug(f"ユーザー処理後、検索結果ページ ({search_page_url_before_profile_visit}) に戻ります。")
                driver.get(search_page_url_before_profile_visit)
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector))) # 戻り確認
                time.sleep(delay_user_processing) # 次のユーザー処理までの待機

            except NoSuchElementException:
                logger.warning(f"活動記録カード {card_idx+1} からユーザー情報取得に必要な要素が見つかりません。スキップ。")
            except Exception as e_user_proc:
                logger.error(f"ユーザー「{user_name_for_log}」の処理中にエラー: {e_user_proc}", exc_info=True)
                # エラーが発生したら、元の検索ページに戻ることを試みる
                try:
                    current_search_url = start_url # page_numに応じて変更が必要だが、一旦start_url
                    if driver.current_url != current_search_url:
                         driver.get(current_search_url)
                         WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                except Exception as e_recover:
                     logger.error(f"エラー後の検索ページ復帰試行中にもエラー: {e_recover}")


        logger.info(f"{page_num}ページ目の処理が完了しました。")
        if page_num < max_pages and len(activity_cards_on_page) > 0 : # 次のページがある場合のみ
             # ページネーション処理が実装されたら、ここで break しない
             pass
        # else:
        #      logger.info("最大ページ数に達したか、これ以上活動記録がありません。")
        #      break # ループ終了

    logger.info(f"<<< 検索からのフォロー＆DOMO機能完了。合計フォロー: {total_followed_count}人, 合計DOMO: {total_domoed_count}件。")


# --- フォローバック機能 ---
def follow_back_users_new(driver, current_user_id):
    """
    自分をフォローしてくれたユーザーをフォローバックする機能。
    config.yaml の follow_back_settings に従って動作する。
    """
    if not FOLLOW_BACK_SETTINGS.get("enable_follow_back", False):
        logger.info("フォローバック機能は設定で無効になっています。")
        return

    logger.info(">>> フォローバック機能を開始します...")
    # 正しいフォロワー一覧ページのURL形式に修正
    followers_url = f"{BASE_URL}/users/{current_user_id}?tab=followers#tabs"
    logger.info(f"フォロワー一覧ページへアクセス: {followers_url}")
    driver.get(followers_url)

    # --- フォローバック機能のデバッグコードは削除 ---
    # (このコメント自体も、実際のコードでは time.sleep やファイル書き込み処理があった場所を示す)

    max_to_follow_back = FOLLOW_BACK_SETTINGS.get("max_users_to_follow_back", 10)
    delay_between_actions = FOLLOW_BACK_SETTINGS.get("delay_after_follow_back_action_sec", 3.0) # ユーザー間の待機にも流用

    followed_count = 0

    # --- セレクタ定義 ---
    followers_list_container_selector = "ul.css-18aka15" # フォロワーリスト全体を囲むulタグ (HTMLから特定)
    user_card_selector = "div[data-testid='user']"       # 各フォロワーカードのルートdiv (HTMLから特定)
    user_link_in_card_selector = "a.css-e5vv35[href^='/users/']" # カード内のユーザープロフへのリンクaタグ (HTMLから特定)
    name_element_css_selector_in_link = "h2.css-o7x4kv"      # 上記aタグ内のユーザー名h2タグ (HTMLから特定)

    try:
        logger.info(f"フォロワーリストのコンテナ ({followers_list_container_selector}) の出現を待ちます...")
        WebDriverWait(driver, 20).until( # 少し長めに待つ
            EC.presence_of_element_located((By.CSS_SELECTOR, followers_list_container_selector))
        )
        logger.info("フォロワーリストのコンテナを発見。")

        # コンテナが見つかった後、改めてユーザーカードを取得
        user_cards_all = driver.find_elements(By.CSS_SELECTOR, user_card_selector)
        logger.info(f"フォロワー一覧ページから {len(user_cards_all)} 件のユーザーカード候補を検出しました。")

        if len(user_cards_all) > 3:
            user_cards = user_cards_all[3:] # 最初の3件（レコメンドと仮定）を除外
            logger.info(f"レコメンドを除いた {len(user_cards)} 件のフォロワー候補を処理対象とします。")
        else:
            user_cards = [] # 除外したら候補がいなくなる、または元々3件以下だった場合
            logger.info("フォロワー一覧のユーザー候補が3件以下（レコメンドのみか、実際のフォロワーがいない可能性）。処理対象ユーザーがいません。")

        if not user_cards:
            logger.info("処理対象となるフォロワーが見つかりませんでした。")
            return

        for card_idx, user_card_element in enumerate(user_cards):
            if followed_count >= max_to_follow_back:
                logger.info(f"フォローバック上限 ({max_to_follow_back}人) に達しました。")
                break

            user_name = f"ユーザー{card_idx+1}" # デフォルト名
            profile_url = ""

            try:
                # ユーザー名とプロフィールURLの取得
                user_link_element = user_card_element.find_element(By.CSS_SELECTOR, user_link_in_card_selector)
                profile_url = user_link_element.get_attribute("href")

                name_element_selectors = [
                    "span[class*='UserListItem_name__']", # 名前が含まれる可能性のあるspan
                    "h2", "h3" # ヘッダータグ
                ]
                for sel in name_element_selectors:
                    try:
                        name_el = user_link_element.find_element(By.CSS_SELECTOR, sel)
                        if name_el.text.strip():
                            user_name = name_el.text.strip()
                            break
                    except NoSuchElementException:
                        continue
                if not profile_url: # URLが取れなければスキップ
                    logger.warning(f"ユーザーカード {card_idx+1} からプロフィールURLを取得できませんでした。スキップします。")
                    continue

                # URLが相対パスなら絶対パスに変換
                if profile_url.startswith("/"):
                    profile_url = BASE_URL + profile_url

                # 自分自身や無効なURLはスキップ
                if f"/users/{current_user_id}" in profile_url or not profile_url.startswith(f"{BASE_URL}/users/"):
                    logger.debug(f"スキップ: 自分自身または無効なフォロワーURL ({profile_url})")
                    continue

            except NoSuchElementException:
                logger.warning(f"ユーザーカード {card_idx+1} の名前またはURL特定に必要な要素が見つかりません。スキップします。")
                continue
            except Exception as e_card_parse:
                logger.warning(f"ユーザーカード {card_idx+1} の情報解析中にエラー: {e_card_parse}。スキップします。")
                continue

            logger.info(f"フォロワー「{user_name}」(URL: {profile_url.split('/')[-1]}) のフォロー状態を確認中...")

            # user_card_element をコンテキストとしてフォローボタンを探す
            follow_button = find_follow_button_in_list_item(user_card_element)

            if follow_button:
                logger.info(f"ユーザー「{user_name}」はまだフォローしていません。フォローバックを試みます。")
                if click_follow_button_and_verify(driver, follow_button, user_name):
                    followed_count += 1
                # 次のユーザー処理までの待機 (フォロー成否に関わらず)
                time.sleep(delay_between_actions)
            else:
                logger.info(f"ユーザー「{user_name}」は既にフォロー済みか、フォローボタンが見つかりません。スキップします。")
                time.sleep(0.5) # 短い待機

    except TimeoutException:
        logger.warning("フォロワー一覧の読み込みでタイムアウトしました。")
    except Exception as e:
        logger.error(f"フォローバック処理中に予期せぬエラーが発生しました。", exc_info=True)

    logger.info(f"<<< フォローバック機能完了。合計 {followed_count} 人をフォローバックしました。")


# --- mainブロック (テスト用) ---
if __name__ == "__main__":
    logger.info(f"=========== {os.path.basename(__file__)} スクリプト開始 ===========")
    driver = None
    try:
        # DOMO_SETTINGS は config.yaml の domo_settings セクションに依存するため、
        # この時点では headless_mode のみ参照される get_driver_options の呼び出しはOK
        driver_options = get_driver_options()
        driver = webdriver.Chrome(options=driver_options)

        # implicit_wait_sec は config.yaml のトップレベルから読むように変更
        implicit_wait = main_config.get("implicit_wait_sec", 7)
        driver.implicitly_wait(implicit_wait)

        logger.info(f"認証情報: email={YAMAP_EMAIL}, user_id={MY_USER_ID}") # パスワードはログ出力しない

        if login(driver, YAMAP_EMAIL, YAMAP_PASSWORD):
            logger.info(f"ログイン成功。現在のURL: {driver.current_url}")

            # --- 各機能の呼び出し ---
            # MY_USER_ID はログイン処理前に設定ファイルから読み込まれている想定
            if MY_USER_ID:
                # フォローバック機能
                if FOLLOW_BACK_SETTINGS.get("enable_follow_back", False):
                    follow_back_users_new(driver, MY_USER_ID)
                else:
                    logger.info("フォローバック機能は設定で無効です。")

                # タイムラインDOMO機能
                if TIMELINE_DOMO_SETTINGS.get("enable_timeline_domo", False):
                    domo_timeline_activities(driver)
                else:
                    logger.info("タイムラインDOMO機能は設定で無効です。")

                # 検索結果からのフォロー＆DOMO機能
                if SEARCH_AND_FOLLOW_SETTINGS.get("enable_search_and_follow", False):
                    search_follow_and_domo_users(driver, MY_USER_ID)
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
