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
    # DOMO_SETTINGS はまだ新しい config を反映していないが、一旦既存のキーを参照する形でコピー
    if DOMO_SETTINGS.get("headless_mode", False): # headless_mode は domo_settings から読む想定
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
                    button_text_span = following_button.find_element(By.CSS_SELECTOR, "span.c1hbtdj4") # 提供されたHTMLのspanクラス
                    if "フォロー中" in button_text_span.text:
                        logger.debug("「フォロー中」ボタン (aria-pressed='true' およびテキスト確認) を発見。既にフォロー済みと判断。")
                        return None
                except NoSuchElementException: # spanが見つからなくてもaria-pressedだけで判断するケースも考慮
                     logger.debug("「フォロー中」ボタン (aria-pressed='true') を発見したが、内部テキスト確認できず。フォロー済みと判断。")
                     return None
        except NoSuchElementException:
            logger.debug("aria-pressed='true' の「フォロー中」ボタンは見つかりませんでした。フォロー可能かもしれません。")

        # 「フォローする」ボタンの判定
        # 未フォローの場合、ボタンは aria-pressed="false" か、または別の属性やテキストを持つと想定
        # または、フォロー中ボタンが存在しないことで判定する

        # まず、汎用的な「フォローする」テキストを持つボタンを探す (XPathが有効)
        try:
            follow_button_xpath = ".//button[normalize-space(.)='フォローする']"
            button_by_text = user_list_item_element.find_element(By.XPATH, follow_button_xpath)
            if button_by_text and button_by_text.is_displayed() and button_by_text.is_enabled():
                logger.debug(f"「フォローする」ボタンをテキストで発見 (XPath: {follow_button_xpath})")
                return button_by_text
        except NoSuchElementException:
            logger.debug(f"テキスト「フォローする」でのボタン発見試行失敗 (XPath: {follow_button_xpath})。")

        # 次に、aria-pressed="false" のボタンを探し、内部テキストが「フォローする」であることを確認
        try:
            # まず aria-pressed="false" のボタン候補を取得
            potential_follow_buttons = user_list_item_element.find_elements(By.CSS_SELECTOR, "button[aria-pressed='false']")
            if not potential_follow_buttons:
                logger.debug("aria-pressed='false' のボタン候補は見つかりませんでした。")
                raise NoSuchElementException # 次の探索ブロックへ

            for button_candidate in potential_follow_buttons:
                if button_candidate and button_candidate.is_displayed() and button_candidate.is_enabled():
                    # 内部のspan.c1hbtdj4 のテキストを確認
                    try:
                        text_span = button_candidate.find_element(By.CSS_SELECTOR, "span.c1hbtdj4")
                        if "フォローする" in text_span.text:
                            logger.debug("「フォローする」ボタン (aria-pressed='false' かつ内部テキスト確認) を発見。")
                            return button_candidate
                    except NoSuchElementException:
                        logger.debug(f"aria-pressed='false' ボタン内に期待するテキストspan (span.c1hbtdj4) が見つかりません。ボタン: {button_candidate.get_attribute('outerHTML')}")
                        continue # 次の候補へ
            logger.debug("aria-pressed='false' のボタン群の中に、テキスト「フォローする」を持つものは見つかりませんでした。")
        except NoSuchElementException:
            # この例外はキャッチして、次の探索ブロックに進むためにここでは何もしない
            pass # logger.debug は上記 raise の前で出力済み

        # data-testid や特有のクラス名での探索 (以前の候補も残す) - 優先度低
        # ただし、提供されたHTMLには FollowButton の data-testid は無かった
        legacy_follow_button_selectors = [
            "button[data-testid='FollowButton']",
            "button[aria-label*='フォローする']",
        ]
        for sel in legacy_follow_button_selectors:
            try:
                button = None
                if sel.startswith(".//"):
                    button = user_list_item_element.find_element(By.XPATH, sel)
                else:
                    button = user_list_item_element.find_element(By.CSS_SELECTOR, sel)

                if button and button.is_displayed() and button.is_enabled():
                    # ボタンのテキストやaria-labelをさらに確認して誤判定を防ぐ
                    button_text = button.text.strip()
                    aria_label = button.get_attribute('aria-label')
                    if "フォローする" in button_text or ("フォローする" in aria_label if aria_label else False):
                         logger.debug(f"フォローボタン発見 (selector: {sel}, text: '{button_text}', aria-label: '{aria_label}')")
                         return button
                    else:
                        logger.debug(f"ボタン発見だがテキスト/aria-labelが不一致 (selector: {sel}, text: '{button_text}', aria-label: '{aria_label}')")
            except NoSuchElementException:
                continue
        logger.debug("ユーザーリストアイテム内にクリック可能な「フォローする」ボタンが見つかりませんでした。")
        return None
    except Exception as e:
        logger.error(f"ユーザーリストアイテム内のフォローボタン検索で予期せぬエラー", exc_info=True)
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
        time.sleep(0.5) # スクロール後の描画待ち
        follow_button_element.click()

        # 状態変化の確認: ボタンのdata-testid, aria-label, またはテキストが変わることを期待
        # フォロー後は "FollowingButton" や "フォロー中" になることを想定
        # WebDriverWait を使って、要素の状態が変わるまで待機
        delay_after_action = FOLLOW_BACK_SETTINGS.get("delay_after_follow_back_action_sec", # 新しい設定を参照
                                               FOLLOW_SETTINGS.get("delay_after_follow_action_sec", 2.0))

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
                # DOMOボタンが表示され、クリック可能になるまで待つ
                domo_button = WebDriverWait(driver, 7 if idx == 0 else 3).until(
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
            time.sleep(0.5) # スクロール安定待ち
            domo_button.click()

            # DOMO後の状態変化を待つ (aria-labelが "Domo済み" になるか、アイコンがis-activeになる)
            # TIMELINE_DOMO_SETTINGS から delay を読むようにする (汎用DOMOなのでどちらでも良いが、新しい方を優先)
            delay_after_action = TIMELINE_DOMO_SETTINGS.get("delay_between_timeline_domo_sec",
                                                        DOMO_SETTINGS.get("delay_after_domo_action_sec", 1.5))
            try:
                WebDriverWait(driver, 10).until(
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
    # --- タイムラインDOMO機能のためのデバッグコード挿入 ---
    logger.info("タイムラインページ読み込みのため10秒間待機します...")
    time.sleep(10)
    debug_timeline_file_name = f"debug_timeline_page_source_{time.strftime('%Y%m%d%H%M%S')}.html"
    try:
        with open(debug_timeline_file_name, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        logger.info(f"タイムラインページのHTMLソースを '{debug_timeline_file_name}' に出力しました。")
    except Exception as e_dump_timeline:
        logger.error(f"タイムラインHTMLソースのファイル出力中にエラー: {e_dump_timeline}")
    # --- デバッグコード終了 ---

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
        time.sleep(2.5) # スクロールや追加読み込みを考慮した描画安定待ち

        feed_items = driver.find_elements(By.CSS_SELECTOR, feed_item_selector)
        logger.info(f"タイムラインから {len(feed_items)} 件のフィードアイテム候補を検出しました。")

        if not feed_items:
            logger.info("タイムラインにフィードアイテムが見つかりませんでした。")
            return

        for idx, feed_item_element in enumerate(feed_items):
            if domoed_count >= max_activities_to_domo:
                logger.info(f"タイムラインDOMOの上限 ({max_activities_to_domo}件) に達しました。")
                break

            activity_url = None
            try:
                # このフィードアイテムが活動日記であるかを確認
                # 活動日記特有の要素 (activity_item_indicator_selector) を探す
                activity_indicator_elements = feed_item_element.find_elements(By.CSS_SELECTOR, activity_item_indicator_selector)

                if not activity_indicator_elements:
                    logger.debug(f"フィードアイテム {idx+1} は活動日記ではありません (indicator: '{activity_item_indicator_selector}' 見つからず)。スキップします。")
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
                    logger.warning(f"活動記録カード {idx+1} から有効な活動記録URLを取得できませんでした。スキップします。")
                    continue

                if activity_url in processed_activity_urls:
                    logger.info(f"活動記録 ({activity_url.split('/')[-1]}) は既に処理試行済みです。スキップします。")
                    continue
                processed_activity_urls.add(activity_url)

                logger.info(f"タイムライン活動記録 {idx+1}/{len(feed_items)} (URL: {activity_url.split('/')[-1]}) のDOMOを試みます。")

                # 現在のページURLを保存
                current_main_page_url = driver.current_url

                if domo_activity(driver, activity_url): # domo_activity内でページ遷移が発生する
                    domoed_count += 1

                # DOMO処理後、元のタイムラインページに戻る (必要がある場合)
                # domo_activity が別ページに遷移するため、戻る処理を入れる
                if driver.current_url != current_main_page_url:
                    logger.debug(f"DOMO処理後、元のページ ({current_main_page_url}) に戻ります。")
                    driver.get(current_main_page_url)
                    # 戻った後、要素が再認識されるように少し待つ
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    time.sleep(1) # 追加の安定待ち

                # 次の活動記録処理までの待機時間は domo_activity 内で考慮されているので、ここでは不要

            except NoSuchElementException:
                logger.warning(f"活動記録カード {idx+1} 内で活動記録リンクが見つかりません。スキップします。")
            except Exception as e_card_proc:
                logger.error(f"活動記録カード {idx+1} (URL: {activity_url.split('/')[-1] if activity_url else 'N/A'}) の処理中にエラー: {e_card_proc}", exc_info=True)

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

        # ページが完全に読み込まれるのを待つために少し待機
        time.sleep(DOMO_SETTINGS.get("short_wait_sec", 2)) # short_wait_secはdomo_settingsにある想定

        for selector in activity_link_selectors:
            try:
                # ページが動的に読み込まれる場合、要素が見つかるまで少し待つ
                WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
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
        # フォロー数・フォロワー数が表示されているセクションを特定
        # セレクタ例: YAMAPのHTML構造による
        # <a href=".../follows" data-testid="profile-tab-follows"><span class="Count_count__XXXX">NUM</span>...</a>
        # <a href=".../followers" data-testid="profile-tab-followers"><span class="Count_count__XXXX">NUM</span>...</a>

        stats_container_selector = "div[class*='UserProfileScreen_profileStats']" # この親要素の中にフォロー・フォロワー数がある想定
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, stats_container_selector)))

        # フォロー中の数
        try:
            # data-testid を優先
            follow_el_selector_testid = f"{stats_container_selector} a[data-testid='profile-tab-follows'] span[class*='Count_count']"
            # href をフォールバック
            follow_el_selector_href = f"{stats_container_selector} a[href$='/follows'] span[class*='Count_count']"

            follow_el = None
            try:
                follow_el = driver.find_element(By.CSS_SELECTOR, follow_el_selector_testid)
            except NoSuchElementException:
                logger.debug(f"フォロー数要素(testid)が見つからず。hrefセレクタ試行: {follow_el_selector_href}")
                follow_el = driver.find_element(By.CSS_SELECTOR, follow_el_selector_href)

            count_text = follow_el.text.strip().replace(",", "")
            num_str = "".join(filter(str.isdigit, count_text))
            if num_str:
                follows_count = int(num_str)
        except NoSuchElementException:
            logger.warning(f"フォロー中の数を特定する要素が見つかりませんでした ({user_id_log})。")

        # フォロワーの数
        try:
            follower_el_selector_testid = f"{stats_container_selector} a[data-testid='profile-tab-followers'] span[class*='Count_count']"
            follower_el_selector_href = f"{stats_container_selector} a[href$='/followers'] span[class*='Count_count']"

            follower_el = None
            try:
                follower_el = driver.find_element(By.CSS_SELECTOR, follower_el_selector_testid)
            except NoSuchElementException:
                logger.debug(f"フォロワー数要素(testid)が見つからず。hrefセレクタ試行: {follower_el_selector_href}")
                follower_el = driver.find_element(By.CSS_SELECTOR, follower_el_selector_href)

            count_text = follower_el.text.strip().replace(",", "")
            num_str = "".join(filter(str.isdigit, count_text))
            if num_str:
                followers_count = int(num_str)
        except NoSuchElementException:
            logger.warning(f"フォロワーの数を特定する要素が見つかりませんでした ({user_id_log})。")

        logger.info(f"ユーザー ({user_id_log}): フォロー中={follows_count}, フォロワー={followers_count}")

    except TimeoutException:
        logger.warning(f"フォロー数/フォロワー数セクションの読み込みタイムアウト ({user_id_log})。")
    except Exception as e:
        logger.error(f"フォロー数/フォロワー数取得中にエラー ({user_id_log})。", exc_info=True)

    return follows_count, followers_count

def find_follow_button_on_profile_page(driver):
    """
    ユーザープロフィールページ上で「フォローする」ボタンを探す。
    既にフォロー中、またはボタンがない場合はNoneを返す。
    """
    try:
        # 「フォロー中」ボタンのセレクタ (これがあればフォローしない)
        following_button_selectors = [
            "button[data-testid='FollowingButton']",
            ".//button[normalize-space(.)='フォロー中']", # XPath
            "button[aria-label*='フォロー中']"
        ]
        # プロフィールページの主要部分が表示されるまで少し待つ
        WebDriverWait(driver, 7).until(
            EC.any_of( # どれか一つでもあれば良い
                EC.presence_of_element_located((By.CSS_SELECTOR, following_button_selectors[0])),
                EC.presence_of_element_located((By.XPATH, following_button_selectors[1])),
                EC.presence_of_element_located((By.CSS_SELECTOR, "button[data-testid='FollowButton']")) # フォローするボタンも候補に
            )
        )

        for sel in following_button_selectors:
            try:
                if sel.startswith(".//"):
                    if driver.find_elements(By.XPATH, sel): return None # 発見したら既にフォロー中
                else:
                    if driver.find_elements(By.CSS_SELECTOR, sel): return None # 発見したら既にフォロー中
            except NoSuchElementException:
                continue

        # 「フォローする」ボタンのセレクタ
        follow_button_selectors = [
            "button[data-testid='FollowButton']",
            ".//button[normalize-space(.)='フォローする']", # XPath
            "button[aria-label*='フォローする']",
            # プロフィールページ特有のフォローボタンのクラスなど (例)
            # "button.ProfileFollowButtonClass"
        ]
        for sel in follow_button_selectors:
            try:
                button = None
                if sel.startswith(".//"):
                    button = driver.find_element(By.XPATH, sel)
                else:
                    button = driver.find_element(By.CSS_SELECTOR, sel)

                if button and button.is_displayed() and button.is_enabled():
                    # ボタンのテキストやaria-labelをさらに確認
                    button_text = button.text.strip()
                    aria_label = button.get_attribute('aria-label')
                    if "フォローする" in button_text or ("フォローする" in aria_label if aria_label else False):
                        logger.debug(f"プロフィールページで「フォローする」ボタンを発見 (selector: {sel}, text: '{button_text}', aria-label: '{aria_label}')")
                        return button
                    else:
                         logger.debug(f"ボタン発見だがテキスト/aria-label不一致 (selector: {sel}, text: '{button_text}', aria-label: '{aria_label}')")
            except NoSuchElementException:
                continue

        logger.info("プロフィールページでフォロー可能な「フォローする」ボタンが見つかりませんでした。")
        return None
    except TimeoutException:
        logger.warning("プロフィールページのフォローボタン群の読み込みタイムアウト。")
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
            time.sleep(2) # 描画安定待ち
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
                WebDriverWait(driver,10).until(EC.url_contains(user_profile_url.split('/')[-1]))
                follow_button_on_profile = find_follow_button_on_profile_page(driver)


                if not follow_button_on_profile:
                    logger.info(f"ユーザー「{user_name_for_log}」は既にフォロー済みか、プロフィールにフォローボタンがありません。スキップ。")
                    driver.get(search_page_url_before_profile_visit) # 元の検索ページに戻る
                    time.sleep(1)
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
                logger.info(f"ユーザー「{user_name_for_log}」: F中={follows}, Fワー={followers}, Ratio={current_ratio:.2f} (閾値: <{ratio_threshold})")

                if not (follows < followers and current_ratio < ratio_threshold):
                    logger.info(f"Ratio条件または「F中 < Fワー」を満たしません。スキップ。")
                    driver.get(search_page_url_before_profile_visit)
                    time.sleep(1)
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

        # implicit_wait_sec も DOMO_SETTINGS から読む想定だが、デフォルト値を設定するか、
        # config.yaml の domo_settings に存在することを期待する。
        # ここでは、後で config 更新時に domo_settings が必ず存在するようにするため、一旦そのまま。
        implicit_wait = DOMO_SETTINGS.get("implicit_wait_sec", 7) # DOMO_SETTINGSが空ならデフォルト7秒
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
