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
import yaml # YAMLをインポート

# --- Loggerの設定 ---
LOG_FILE_NAME = "yamap_auto.log"
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
# StreamHandler (コンソール出力)
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO) # コンソールにはINFO以上
stream_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
stream_handler.setFormatter(stream_formatter)
if not logger.handlers: # ハンドラが重複して追加されるのを防ぐ
    logger.addHandler(stream_handler)
# FileHandler (ファイル出力)
try:
    file_handler = logging.FileHandler(LOG_FILE_NAME, encoding='utf-8', mode='a') # mode='a'で追記
    file_handler.setLevel(logging.DEBUG) # ファイルにはDEBUG以上
    file_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(funcName)s:%(lineno)d] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
except Exception as e:
    logger.error(f"ログファイルハンドラの設定に失敗しました: {e}") # このエラーはコンソールにも出るようにする
# --- Logger設定完了 ---

# 設定ファイルのパス
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.yaml")
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.yaml") # 認証情報ファイル

# --- 設定ファイルの読み込み ---
try:
    # まず credentials.yaml を読み込む
    try:
        with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
            credentials_config = yaml.safe_load(f)
        if not credentials_config: # ファイルが空の場合など
            raise ValueError("認証ファイルが空か、内容を読み取れませんでした。")
        YAMAP_EMAIL = credentials_config.get("email")
        YAMAP_PASSWORD = credentials_config.get("password")
        MY_USER_ID = str(credentials_config.get("user_id", "")) # user_id は文字列として扱う

        if not all([YAMAP_EMAIL, YAMAP_PASSWORD, MY_USER_ID]):
             logger.critical(f"認証ファイル ({CREDENTIALS_FILE}) に email, password, user_id のいずれかが正しく設定されていません。")
             logger.info(f"例:\nemail: your_email@example.com\npassword: your_password\nuser_id: '1234567'")
             exit()
    except FileNotFoundError:
        logger.critical(f"認証ファイル ({CREDENTIALS_FILE}) が見つかりません。作成して認証情報を記述してください。")
        logger.info(f"ファイルパス: {os.path.abspath(CREDENTIALS_FILE)}")
        logger.info(f"例:\nemail: your_email@example.com\npassword: your_password\nuser_id: '1234567'")
        exit()
    except (yaml.YAMLError, ValueError) as e_cred: # ValueErrorもキャッチ
        logger.critical(f"認証ファイル ({CREDENTIALS_FILE}) の形式が正しくないか、内容に問題があります。エラー: {e_cred}")
        exit()

    # 次に config.yaml を読み込む
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        main_config = yaml.safe_load(f)
        if not main_config: # ファイルが空の場合など
             raise ValueError("メインの設定ファイル (config.yaml) が空か、内容を読み取れませんでした。")
    DOMO_SETTINGS = main_config.get("domo_settings", {})
    FOLLOW_SETTINGS = main_config.get("follow_settings", {})

except FileNotFoundError: # config.yaml が見つからない場合
    logger.critical(f"メインの設定ファイル ({CONFIG_FILE}) が見つかりません。スクリプトを終了します。")
    exit()
except (yaml.YAMLError, ValueError) as e_main: # config.yaml のパースエラーや空ファイル
    logger.critical(f"メインの設定ファイル ({CONFIG_FILE}) の形式が正しくないか、内容に問題があります。エラー: {e_main}")
    exit()
except Exception as e:
    logger.critical(f"設定ファイルの読み込み中に予期せぬエラーが発生しました: {e}", exc_info=True)
    exit()
# --- 設定ファイルの読み込み完了 ---

BASE_URL = "https://yamap.com"
LOGIN_URL = f"{BASE_URL}/login"

def get_driver_options():
    options = webdriver.ChromeOptions()
    if DOMO_SETTINGS.get("headless_mode", False):
        logger.info("ヘッドレスモードで起動します。")
        options.add_argument('--headless')
        options.add_argument('--disable-gpu') # ヘッドレスモードではGPUアクセラレーションを無効にするのが一般的
        options.add_argument('--window-size=1920,1080') # ヘッドレスでも描画エリアのサイズを指定
        # 以下のオプションは主にLinuxコンテナ環境での安定性向上のためのもので、
        # 通常のWindowsデスクトップ環境では不要なことが多いです。
        # 必要に応じてコメントを解除してください。
        # options.add_argument('--no-sandbox')
        # options.add_argument('--disable-dev-shm-usage')

    # User-Agentのカスタマイズ (必要な場合のみ設定ファイルに項目を追加して利用)
    # custom_user_agent = DOMO_SETTINGS.get("custom_user_agent")
    # if custom_user_agent:
    #     logger.info(f"カスタムUser-Agentを使用します: {custom_user_agent}")
    #     options.add_argument(f"user-agent={custom_user_agent}")

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
        current_url_lower = driver.current_url.lower()
        page_title_lower = driver.title.lower()
        if "login" not in current_url_lower and ("yamap" in current_url_lower or MY_USER_ID in current_url_lower or "timeline" in current_url_lower or "home" in current_url_lower or "discover" in current_url_lower): # discoverも追加
            logger.info("ログインに成功しました。")
            return True
        elif "ようこそ" in page_title_lower or "welcome" in page_title_lower:
             logger.info("ログインに成功しました。(タイトル確認)")
             return True
        else:
            logger.error("ログインに失敗したか、予期せぬページに遷移しました。")
            logger.error(f"現在のURL: {driver.current_url}, タイトル: {driver.title}")
            try:
                error_message_element = driver.find_element(By.CSS_SELECTOR, "div[class*='ErrorText'], p[class*='error-message'], div[class*='FormError']")
                if error_message_element and error_message_element.is_displayed():
                    logger.error(f"ページ上のエラーメッセージ: {error_message_element.text}")
            except NoSuchElementException:
                logger.debug("ページ上にログインエラーメッセージ要素は見つかりませんでした。")
            return False
    except Exception as e:
        logger.error(f"ログイン処理中にエラーが発生しました。", exc_info=True)
        return False

def get_latest_activity_url(driver, user_profile_url):
    logger.info(f"プロフィール ({user_profile_url.split('/')[-1]}) の最新活動日記を取得します。")
    driver.get(user_profile_url)
    latest_activity_url = None
    try:
        # Updated selectors based on user-provided HTML: <article data-testid="activity-entry"><a href="/activities/..." class="css-192jaxu">
        primary_activity_selector = "article[data-testid='activity-entry'] a[href^='/activities/']"
        secondary_activity_selector = "a.css-192jaxu[href^='/activities/']" # More specific class from snippet
        fallback_activity_selector = "a[data-testid='activity-card-link']" # Keep old one as fallback

        # Wait for the primary container of activities or a specific activity link
        WebDriverWait(driver, 10).until(
            EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, "article[data-testid='activity-entry']")),
                EC.presence_of_element_located((By.CSS_SELECTOR, primary_activity_selector)),
                EC.presence_of_element_located((By.CSS_SELECTOR, fallback_activity_selector))
            )
        )
        time.sleep(DOMO_SETTINGS.get("short_wait_sec", 1)) # Allow some time for rendering after presence

        # Try selectors in order of expected reliability/specificity
        for selector in [primary_activity_selector, secondary_activity_selector, fallback_activity_selector]:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                # Assuming the first one is the latest, which is typical for activity feeds
                href = elements[0].get_attribute('href')
                if href:
                    full_href = href if href.startswith(BASE_URL) else (BASE_URL + href if href.startswith('/') else None)
                    if full_href and "/activities/" in full_href:
                        latest_activity_url = full_href
                        logger.debug(f"最新の活動日記URL候補: {latest_activity_url} (selector: {selector})")
                        return latest_activity_url

        if not latest_activity_url:
            logger.info(f"ユーザー ({user_profile_url.split('/')[-1]}) の最新の活動日記が見つかりませんでした。試行したセレクタ: {[primary_activity_selector, secondary_activity_selector, fallback_activity_selector]}")
    except TimeoutException:
        logger.warning(f"ユーザー ({user_profile_url.split('/')[-1]}) の活動日記読み込みでタイムアウトしました。")
    except Exception as e:
        logger.error(f"ユーザー ({user_profile_url.split('/')[-1]}) の活動日記取得中にエラー。", exc_info=True)
    return latest_activity_url

def domo_activity(driver, activity_url):
    logger.info(f"活動日記 ({activity_url.split('/')[-1]}) へDOMOを試みます。")
    driver.get(activity_url)
    try:
        # Updated selector based on user-provided HTML: <button id="DomoActionButton" ...>
        # Fallback to the old data-testid if the ID is not found or doesn't work.
        primary_domo_button_selector = "button#DomoActionButton"
        fallback_domo_button_selector = "button[data-testid='ActivityDomoButton']"

        domo_button = None
        current_selector_used = ""

        try:
            logger.debug(f"DOMOボタン探索中 (プライマリセレクタ: {primary_domo_button_selector})")
            domo_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, primary_domo_button_selector)))
            current_selector_used = primary_domo_button_selector
            logger.debug(f"DOMOボタンをプライマリセレクタで発見: {primary_domo_button_selector}")
        except TimeoutException:
            logger.debug(f"DOMOボタンがプライマリセレクタで見つからず。フォールバックセレクタ試行: {fallback_domo_button_selector}")
            try:
                domo_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, fallback_domo_button_selector)))
                current_selector_used = fallback_domo_button_selector
                logger.debug(f"DOMOボタンをフォールバックセレクタで発見: {fallback_domo_button_selector}")
            except TimeoutException:
                logger.warning(f"DOMOボタンが見つからないかタイムアウト (試行セレクタ: {primary_domo_button_selector}, {fallback_domo_button_selector}): {activity_url.split('/')[-1]}")
                return False

        aria_label_before = domo_button.get_attribute("aria-label"); is_domoed = False
        # Check for 'is-active' class on the span as another indicator, if aria-label is unreliable
        # The provided HTML shows: <span class="RidgeIcon DomoActionContainer__DomoIcon is-active">
        # This 'is-active' might mean it's already domoed.
        try:
            icon_span = domo_button.find_element(By.CSS_SELECTOR, "span.RidgeIcon")
            if "is-active" in icon_span.get_attribute("class"):
                logger.info(f"DOMOボタンのアイコンが既にアクティブ状態です (class='is-active'): {activity_url.split('/')[-1]}")
                # This could mean already DOMOed. Rely on aria-label if present, otherwise this is a strong hint.
                if not aria_label_before : # If aria-label is empty, this might be the only indicator
                     is_domoed = True
        except NoSuchElementException:
            logger.debug("DOMOボタン内のRidgeIcon spanが見つかりませんでした。")


        if aria_label_before and ("Domo済み" in aria_label_before or "domoed" in aria_label_before.lower() or "ドモ済み" in aria_label_before):
            is_domoed = True
            logger.info(f"既にDOMO済みです (aria-label確認): {activity_url.split('/')[-1]} (aria-label: {aria_label_before})")

        if not is_domoed:
            logger.info(f"DOMOを実行します: {activity_url.split('/')[-1]}")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", domo_button); time.sleep(0.5)
            domo_button.click()

            # Wait for aria-label change or for the icon to become active
            WebDriverWait(driver, 10).until(
                lambda d: (d.find_element(By.CSS_SELECTOR, current_selector_used).get_attribute("aria-label") != aria_label_before and \
                           ("Domo済み" in d.find_element(By.CSS_SELECTOR, current_selector_used).get_attribute("aria-label") or \
                            "domoed" in d.find_element(By.CSS_SELECTOR, current_selector_used).get_attribute("aria-label").lower() or \
                            "ドモ済み" in d.find_element(By.CSS_SELECTOR, current_selector_used).get_attribute("aria-label"))) or \
                          ("is-active" in d.find_element(By.CSS_SELECTOR, f"{current_selector_used} span.RidgeIcon").get_attribute("class"))
            )

            aria_label_after = driver.find_element(By.CSS_SELECTOR, current_selector_used).get_attribute("aria-label")
            icon_is_active_after = "is-active" in driver.find_element(By.CSS_SELECTOR, f"{current_selector_used} span.RidgeIcon").get_attribute("class")

            if ("Domo済み" in aria_label_after or "domoed" in aria_label_after.lower() or "ドモ済み" in aria_label_after) or icon_is_active_after:
                logger.info(f"DOMOしました: {activity_url.split('/')[-1]} (aria-label: {aria_label_after}, icon active: {icon_is_active_after})")
            else:
                logger.warning(f"DOMO実行しましたが状態変化が期待通りではありません: {activity_url.split('/')[-1]} (aria-label: {aria_label_after}, icon active: {icon_is_active_after})")
            time.sleep(DOMO_SETTINGS.get("delay_after_domo_action_sec", 1.5)); return True
        else:
            # If it was already domoed (either by aria-label or initial icon state)
            logger.info(f"既にDOMO済みと判断されました: {activity_url.split('/')[-1]} (aria-label: {aria_label_before})"); return False

    except TimeoutException: # This timeout is for the initial button find or the lambda wait
        logger.warning(f"DOMO処理中にタイムアウトが発生: {activity_url.split('/')[-1]}")
    except NoSuchElementException:
        logger.warning(f"DOMOボタンの構成要素が見つかりません: {activity_url.split('/')[-1]}")
    except Exception as e:
        logger.error(f"DOMO実行中に予期せぬエラー: {activity_url.split('/')[-1]}", exc_info=True)
    return False

def get_my_activity_urls(driver, user_id, max_activities_to_check):
    my_activities_url = f"{BASE_URL}/users/{user_id}/activities"; logger.info(f"自分の活動日記一覧 ({my_activities_url}) を取得します。")
    driver.get(my_activities_url); activity_urls = []
    try:
        # Updated selectors based on user-provided HTML: <article data-testid="activity-entry"><a href="/activities/..." class="css-192jaxu">
        primary_activity_selector = "article[data-testid='activity-entry'] a[href^='/activities/']"
        secondary_activity_selector = "a.css-192jaxu[href^='/activities/']" # More specific class from snippet

        # Wait for the primary container of activities or a specific activity link
        WebDriverWait(driver, 15).until(
            EC.any_of(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "article[data-testid='activity-entry']")), # Wait for any activity entry
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, primary_activity_selector))
            )
        )
        time.sleep(DOMO_SETTINGS.get("short_wait_sec", 1.5)) # Allow some time for rendering after presence

        candidate_elements = []
        # Collect elements from both selectors if they exist
        candidate_elements.extend(driver.find_elements(By.CSS_SELECTOR, primary_activity_selector))
        # To avoid duplicates if primary and secondary selectors match same elements, ensure unique hrefs later
        # For now, let's assume primary_activity_selector is the main one based on data-testid

        raw_urls = []
        for el in candidate_elements:
            href = el.get_attribute('href')
            if href:
                if href.startswith("/activities/"): raw_urls.append(BASE_URL + href)
                elif href.startswith(f"{BASE_URL}/activities/"): raw_urls.append(href)
        unique_urls = []; [unique_urls.append(u) for u in raw_urls if u not in unique_urls]
        activity_urls = unique_urls[:max_activities_to_check]; logger.info(f"チェック対象の自分の活動日記 {len(activity_urls)} 件を取得しました。")
    except TimeoutException: logger.warning("自分の活動日記一覧の読み込みでタイムアウトしました。")
    except Exception as e: logger.error(f"自分の活動日記一覧取得中にエラー。", exc_info=True)
    return activity_urls

def get_users_who_domoed_activity(driver, activity_url):
    logger.info(f"活動日記 ({activity_url.split('/')[-1]}) のDOMOユーザーを確認します。")
    driver.get(activity_url); domo_user_profiles = []
    try:
        domo_list_open_button_selectors = ["button[data-testid='DomoListModalOpenButton']", "//button[.//span[contains(text(),'DOMO') and contains(text(),'人')]]", "div[class*='ActivityInfo_stats'] a[href$='/domos']", "button[aria-label*='DOMOしたユーザー']", "button[aria-label*='domoしたユーザー']"]
        open_button = None
        for selector in domo_list_open_button_selectors:
            try:
                wait_time = 5 if "testid" in selector else 2
                if selector.startswith("//"): open_button = WebDriverWait(driver, wait_time).until(EC.element_to_be_clickable((By.XPATH, selector)))
                else: open_button = WebDriverWait(driver, wait_time).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                if open_button: logger.debug(f"DOMO一覧を開くボタンを特定 ({selector})"); break
            except: continue
        if not open_button: logger.info(f"DOMOユーザー一覧を開くボタンが見つかりませんでした: {activity_url.split('/')[-1]}"); return []
        logger.debug(f"DOMOユーザー一覧を開きます..."); driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", open_button); time.sleep(0.5); open_button.click()
        modal_selector = "div[role='dialog']"; modal_user_list_item_selector = f"{modal_selector} div[class*='UserListItem_root']"
        WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.CSS_SELECTOR, modal_user_list_item_selector))); time.sleep(1)
        modal_user_links_elements = driver.find_elements(By.CSS_SELECTOR, f"{modal_user_list_item_selector} a[href^='/users/']")
        for link_el in modal_user_links_elements:
            href = link_el.get_attribute('href')
            if href:
                if href.startswith("/"): href = BASE_URL + href
                if href.startswith(f"{BASE_URL}/users/") and href.split(f"{BASE_URL}/users/")[1].split("/")[0].isdigit() and f"/users/{MY_USER_ID}" not in href: domo_user_profiles.append(href)
        domo_user_profiles = sorted(list(set(domo_user_profiles))); logger.info(f"日記 ({activity_url.split('/')[-1]}) にDOMOしたユーザー {len(domo_user_profiles)} 人 (自分を除く) を見つけました。")
        try:
            close_button_candidates = [f"{modal_selector} button[data-testid='ModalCloseButton']", f"{modal_selector} button[aria-label='閉じる']", f"{modal_selector} button[aria-label*='Close']", f"{modal_selector} header button"]
            closed = False
            for sel in close_button_candidates:
                try:
                    close_btn = WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                    driver.execute_script("arguments[0].click();", close_btn); WebDriverWait(driver, 5).until_not(EC.visibility_of_element_located((By.CSS_SELECTOR, modal_selector)))
                    closed = True; logger.debug("DOMOユーザー一覧モーダルを閉じました (JSクリック)。"); break
                except:
                    try: close_btn.click(); WebDriverWait(driver, 5).until_not(EC.visibility_of_element_located((By.CSS_SELECTOR, modal_selector))); closed = True; logger.debug("DOMOユーザー一覧モーダルを閉じました。"); break
                    except: continue
            if not closed: driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE); WebDriverWait(driver, 5).until_not(EC.visibility_of_element_located((By.CSS_SELECTOR, modal_selector))); logger.debug("DOMOユーザー一覧モーダルをEscapeキーで閉じました。")
        except Exception as e_close: logger.warning(f"DOMOユーザー一覧モーダルを閉じる際にエラー、または既に閉じています。", exc_info=True)
    except TimeoutException: logger.warning(f"DOMOユーザー一覧の読み込み/操作でタイムアウト: {activity_url.split('/')[-1]}")
    except Exception as e: logger.error(f"DOMOユーザー一覧取得中にエラー: {activity_url.split('/')[-1]}", exc_info=True)
    return domo_user_profiles

def domo_users_who_domoed_my_posts(driver, my_user_id):
    if not DOMO_SETTINGS.get("domo_users_who_domoed_my_posts"): logger.info("「自身の投稿にDOMOしてくれたユーザーへDOMO」はスキップされました。"); return
    logger.info(">>> 自身の投稿にDOMOしてくれたユーザーへのDOMOを開始します...")
    # (以降、loggerを使用するように修正)
    max_activities = DOMO_SETTINGS.get("max_my_activities_to_check_domo", 3); my_activity_urls = get_my_activity_urls(driver, my_user_id, max_activities)
    if not my_activity_urls: logger.info("チェック対象の自身の活動日記がありません。"); return
    processed_domo_givers = set(); total_domo_made_count = 0
    for activity_url in my_activity_urls:
        domo_user_profiles = get_users_who_domoed_activity(driver, activity_url)
        if not domo_user_profiles: time.sleep(DOMO_SETTINGS.get("delay_between_domo_check_sec", 2)); continue
        for profile_url in domo_user_profiles:
            if profile_url in processed_domo_givers: continue
            logger.info(f"DOMOをくれたユーザー ({profile_url.split('/')[-1]}) の活動を確認します。")
            latest_activity_of_domo_giver = get_latest_activity_url(driver, profile_url)
            if latest_activity_of_domo_giver:
                time.sleep(0.5)
                if domo_activity(driver, latest_activity_of_domo_giver):
                    total_domo_made_count +=1
            processed_domo_givers.add(profile_url); time.sleep(DOMO_SETTINGS.get("delay_between_users_sec", 3))
        time.sleep(DOMO_SETTINGS.get("delay_between_domo_check_sec", 2))
    logger.info(f"<<< 自身の投稿へDOMOしてくれたユーザーへのDOMO処理完了。合計 {total_domo_made_count} 件 DOMOしました。")

def get_recommended_activity_urls(driver, max_posts_to_get):
    logger.info(f"トップページ ({BASE_URL}/) でおすすめの活動日記を探します...")
    driver.get(BASE_URL + "/"); activity_urls = []
    try:
        # Keep existing section selectors, as no new HTML was provided for the section itself
        recommended_section_selectors = ["section[aria-labelledby*='おすすめの活動日記']", "section[data-testid*='recommend-activities']", "//section[.//h2[contains(text(),'おすすめの活動日記') or contains(text(),'Recommended Activities')]]", "div[class*='HomeFeedSection_root'][.//h2[contains(text(),'おすすめ')]]"]

        # Update activity link selectors within the section to match new structure
        # Using XPath for .// to search within the context of recommend_section_element
        recommended_activity_card_link_selectors = [
            ".//article[@data-testid='activity-entry']//a[starts-with(@href,'/activities/')]", # Preferred new structure
            ".//a[@class='css-192jaxu' and starts-with(@href,'/activities/')]",             # Alternative new structure
            ".//a[@data-testid='activity-card-link']",                                      # Old fallback
            ".//a[starts-with(@href,'/activities/')]"                                       # Generic fallback
        ]

        recommend_section_element = None; logger.debug("おすすめセクションを探索中...")
        for sel_idx, sel in enumerate(recommended_section_selectors):
            try:
                wait_time = 10 # Increased wait time slightly
                logger.debug(f"おすすめセクション探索試行 {sel_idx+1}/{len(recommended_section_selectors)}: {sel}")
                if sel.startswith("//"):
                    WebDriverWait(driver, wait_time).until(EC.presence_of_element_located((By.XPATH, sel)))
                    recommend_section_element = driver.find_element(By.XPATH, sel)
                else:
                    WebDriverWait(driver, wait_time).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                    recommend_section_element = driver.find_element(By.CSS_SELECTOR, sel)

                if recommend_section_element:
                    logger.info(f"おすすめ活動日記セクションを特定 ({sel})")
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", recommend_section_element)
                    time.sleep(DOMO_SETTINGS.get("short_wait_sec", 2)) # Wait for potential dynamic content loading within section
                    break
            except TimeoutException:
                logger.debug(f"おすすめセクションセレクタ '{sel}' でタイムアウト。")
            except Exception as e_sel:
                 logger.debug(f"おすすめセクションセレクタ '{sel}' でエラー: {e_sel}")
            continue

        if not recommend_section_element:
            logger.info("おすすめの活動日記セクションが見つかりませんでした。")
            return []

        candidate_elements = []; logger.debug("セクション内のおすすめ活動日記リンクを探索中...")
        # Ensure recommend_section_element is not None before proceeding
        if recommend_section_element:
            for link_sel_idx, link_sel in enumerate(recommended_activity_card_link_selectors):
                try:
                    logger.debug(f"セクション内リンク探索試行 {link_sel_idx+1}/{len(recommended_activity_card_link_selectors)}: {link_sel}")
                    elements = []
                    if link_sel.startswith(".//"): # Indicates XPath
                        elements = recommend_section_element.find_elements(By.XPATH, link_sel)
                    else: # Assumes CSS selector if not starting with .// (though these are all XPath now)
                        elements = recommend_section_element.find_elements(By.CSS_SELECTOR, link_sel)

                    if elements:
                        logger.debug(f"リンク候補を {len(elements)} 件発見 (selector: {link_sel})")
                        candidate_elements.extend(elements)
                    # Optimization: if we have enough posts from preferred selectors, maybe stop early
                    # This might be too aggressive if later selectors are more accurate for some items
                    # if len(set(el.get_attribute('href') for el in candidate_elements)) >= max_posts_to_get and link_sel_idx < 0: # Disabled for now
                    #     break
                except Exception as e_link_sel:
                    logger.debug(f"セクション内リンクセレクタ '{link_sel}' でエラー: {e_link_sel}")
                continue

        raw_urls = []
        for el in candidate_elements:
            href = el.get_attribute('href')
            if href:
                if href.startswith("/activities/"): raw_urls.append(BASE_URL + href)
                elif href.startswith(f"{BASE_URL}/activities/"): raw_urls.append(href)
        unique_urls = []; [unique_urls.append(u) for u in raw_urls if u not in unique_urls]
        activity_urls = unique_urls[:max_posts_to_get]; logger.info(f"おすすめの活動日記 {len(activity_urls)} 件を取得しました。")
    except TimeoutException: logger.warning("トップページのおすすめ活動日記の読み込みでタイムアウトしました。")
    except Exception as e: logger.error(f"トップページのおすすめ活動日記取得中にエラー。", exc_info=True)
    return activity_urls

def domo_recommended_posts(driver):
    if not DOMO_SETTINGS.get("domo_recommended_posts"): logger.info("「トップページのおすすめ投稿へDOMO」はスキップされました。"); return
    logger.info(">>> トップページのおすすめ投稿へのDOMOを開始します...")
    # (以降、loggerを使用するように修正)
    max_posts = DOMO_SETTINGS.get("max_recommended_posts_to_domo", 3); recommended_activity_urls = get_recommended_activity_urls(driver, max_posts)
    if not recommended_activity_urls: logger.info("DOMO対象のおすすめ活動日記がありません。"); return
    domo_count = 0
    for activity_url in recommended_activity_urls:
        logger.info(f"おすすめの活動日記 ({activity_url.split('/')[-1]}) を確認します。")
        time.sleep(0.5)
        if domo_activity(driver, activity_url): domo_count += 1
        time.sleep(DOMO_SETTINGS.get("delay_between_recommended_domo_sec", 2))
    logger.info(f"<<< トップページのおすすめ投稿へのDOMO処理完了。合計 {domo_count} 件 DOMOしました。")

# --- フォロー関連関数 (loggerを使用するように修正) ---
def find_follow_button_for_user(user_card_element): # フォロワー一覧ページ用
    try:
        follow_button_selectors = ["button[data-testid='FollowButton']", "button[aria-label*='フォローする']", ".//button[normalize-space(.)='フォローする']"]
        following_button_selectors = ["button[data-testid='FollowingButton']", "button[aria-label*='フォロー中']", ".//button[normalize-space(.)='フォロー中']"]
        for sel in following_button_selectors:
            try:
                if sel.startswith(".//"):
                    if user_card_element.find_element(By.XPATH, sel).is_displayed(): return None
                else:
                    if user_card_element.find_element(By.CSS_SELECTOR, sel).is_displayed(): return None
            except NoSuchElementException: continue
        for sel in follow_button_selectors:
            try:
                button = None
                if sel.startswith(".//"): button = user_card_element.find_element(By.XPATH, sel)
                else: button = user_card_element.find_element(By.CSS_SELECTOR, sel)
                if button and button.is_displayed() and button.is_enabled(): return button
            except NoSuchElementException: continue
        return None
    except Exception as e:
        logger.debug(f"ユーザーカード内のフォローボタン検索でエラー", exc_info=True)
        return None

def click_follow_button_and_verify(driver, follow_button_element, user_name_for_log=""):
    try:
        button_text_before = follow_button_element.text; button_aria_label_before = follow_button_element.get_attribute('aria-label')
        logger.info(f"ユーザー「{user_name_for_log}」のフォローボタンをクリックします...")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", follow_button_element); time.sleep(0.3)
        follow_button_element.click()
        WebDriverWait(driver, 10).until(lambda d: (follow_button_element.get_attribute("data-testid") == "FollowingButton") or (follow_button_element.get_attribute("aria-label") and "フォロー中" in follow_button_element.get_attribute("aria-label")) or (follow_button_element.text and "フォロー中" in follow_button_element.text))
        button_text_after = follow_button_element.text; button_aria_label_after = follow_button_element.get_attribute('aria-label'); button_testid_after = follow_button_element.get_attribute('data-testid')
        if "FollowingButton" == button_testid_after or (button_aria_label_after and "フォロー中" in button_aria_label_after) or (button_text_after and "フォロー中" in button_text_after):
            logger.info(f"ユーザー「{user_name_for_log}」をフォローしました。状態: testid='{button_testid_after}', label='{button_aria_label_after}', text='{button_text_after}'")
            time.sleep(FOLLOW_SETTINGS.get("delay_after_follow_action_sec", 1.5)); return True
        else:
            logger.warning(f"フォローボタンクリック後、状態変化が期待通りではありません (ユーザー「{user_name_for_log}」)。状態: testid='{button_testid_after}', label='{button_aria_label_after}', text='{button_text_after}'")
            return False
    except TimeoutException:
        logger.warning(f"フォロー後の状態変化待機中にタイムアウト (ユーザー: {user_name_for_log})。")
    except Exception as e:
        logger.error(f"フォローボタンクリックまたは確認中にエラー (ユーザー: {user_name_for_log})", exc_info=True)
    return False

def follow_back_users(driver, my_user_id):
    if not FOLLOW_SETTINGS.get("follow_users_who_followed_me"):
        logger.info("「フォローしてくれたユーザーへのフォローバック」はスキップされました。"); return
    logger.info(">>> フォローしてくれたユーザーへのフォローバックを開始します...")
    followers_url = f"{BASE_URL}/users/{my_user_id}?tab=followers#tabs"; logger.info(f"フォロワー一覧ページへアクセス: {followers_url}"); driver.get(followers_url)
    max_to_follow_back = FOLLOW_SETTINGS.get("max_followers_to_follow_back", 10); followed_count = 0
    try:
        user_link_selector = "a.css-e5vv35[href^='/users/']"
        WebDriverWait(driver, 15).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, user_link_selector))); time.sleep(2)

        user_elements = driver.find_elements(By.CSS_SELECTOR, user_link_selector)
        logger.info(f"フォロワー一覧から {len(user_elements)} 件のユーザー要素を検出しました。")
        if not user_elements: logger.info("フォロワーが見つかりませんでした。"); return

        for card_idx, user_link_el in enumerate(user_elements):
            if followed_count >= max_to_follow_back: logger.info(f"フォローバック上限 ({max_to_follow_back}人) に達しました。"); break

            user_name = ""; profile_url = ""
            try:
                # The link element itself is the main container for user info
                profile_url = user_link_el.get_attribute("href")
                if profile_url.startswith("/"): profile_url = BASE_URL + profile_url

                # Try to find name within the link element
                name_el = user_link_el.find_element(By.CSS_SELECTOR, "h2.css-o7x4kv") # Based on provided HTML: <h2 class="css-o7x4kv">とし</h2>
                user_name = name_el.text.strip() if name_el else f"ユーザー{card_idx+1}"
            except NoSuchElementException:
                user_name = f"ユーザー{card_idx+1} (名前特定不可)"
                logger.debug(f"ユーザーカード {card_idx+1} の名前取得で要素見つからず (h2.css-o7x4kv)。")
            except Exception as e_card_parse:
                user_name = f"ユーザー{card_idx+1}"
                logger.debug(f"ユーザーカード {card_idx+1} の名前/URL取得で軽微なエラー: {e_card_parse}")

            # Ensure it's a valid user profile URL and not the current user
            match = re.match(f"^{BASE_URL}/users/(\\d+)$", profile_url)
            if not match or (match and match.group(1) == MY_USER_ID):
                logger.debug(f"スキップ: 自分自身または無効なフォロワーURL ({profile_url})")
                continue

            logger.info(f"フォロワー「{user_name}」(URL: {profile_url.split('/')[-1] if profile_url else 'N/A'}) のフォロー状態を確認中...")
            # Pass the user_link_el (the <a> tag) as the context for finding the follow button
            follow_button = find_follow_button_for_user(user_link_el)
            if follow_button:
                if click_follow_button_and_verify(driver, follow_button, user_name): followed_count += 1
                time.sleep(FOLLOW_SETTINGS.get("delay_between_follow_back_sec", 3))
            else:
                logger.info(f"ユーザー「{user_name}」は既にフォロー済みか、フォローボタンが見つかりません。")
                time.sleep(0.5)
    except TimeoutException: logger.warning("フォロワー一覧の読み込みでタイムアウトしました。")
    except Exception as e: logger.error(f"フォローバック処理中にエラー。", exc_info=True)
    logger.info(f"<<< フォローバック処理完了。合計 {followed_count} 人をフォローバックしました。")

def get_user_follow_counts(driver, user_profile_url):
    user_id_log = user_profile_url.split('/')[-1]
    logger.info(f"ユーザー ({user_id_log}) のフォロー数を取得中...")
    # driver.get(user_profile_url) # 呼び出し側で遷移済みを期待
    follows_count = -1; followers_count = -1
    try:
        stats_section_selector = "div[class*='UserProfileScreen_profileStats'], section[class*='UserProfileStats_root']"
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, stats_section_selector)))
        try:
            el = driver.find_element(By.CSS_SELECTOR, f"{stats_section_selector} a[href$='/follows'] span[class*='Count_count'], {stats_section_selector} a[data-testid='profile-tab-follows'] span")
            count_text = el.text.strip().replace(",", "")
            num_str = "".join(filter(str.isdigit, count_text))
            if num_str: follows_count = int(num_str)
        except NoSuchElementException: logger.debug(f"フォロー中の数を特定する要素が見つかりませんでした ({user_id_log})。")
        try:
            el = driver.find_element(By.CSS_SELECTOR, f"{stats_section_selector} a[href$='/followers'] span[class*='Count_count'], {stats_section_selector} a[data-testid='profile-tab-followers'] span")
            count_text = el.text.strip().replace(",", "")
            num_str = "".join(filter(str.isdigit, count_text))
            if num_str: followers_count = int(num_str)
        except NoSuchElementException: logger.debug(f"フォロワーの数を特定する要素が見つかりませんでした ({user_id_log})。")
        logger.info(f"ユーザー ({user_id_log}): フォロー中: {follows_count}, フォロワー: {followers_count}")
    except TimeoutException: logger.warning(f"フォロー数/フォロワー数セクションの読み込みタイムアウト ({user_id_log})")
    except Exception as e: logger.error(f"フォロー数/フォロワー数取得中にエラー ({user_id_log})", exc_info=True)
    return follows_count, followers_count

def find_follow_button_on_profile_page(driver): # プロフィールページ用
    try:
        follow_button_selectors = ["button[data-testid='FollowButton']", "button[aria-label*='フォローする']", ".//button[normalize-space(.)='フォローする']" ]
        following_button_selectors = ["button[data-testid='FollowingButton']", "button[aria-label*='フォロー中']", ".//button[normalize-space(.)='フォロー中']"]
        WebDriverWait(driver, 7).until(EC.any_of( # 少し長めに待つ
            EC.presence_of_element_located((By.CSS_SELECTOR, follow_button_selectors[0])),
            EC.presence_of_element_located((By.CSS_SELECTOR, following_button_selectors[0])),
            EC.presence_of_element_located((By.XPATH, follow_button_selectors[2])),
            EC.presence_of_element_located((By.XPATH, following_button_selectors[2]))
        ))
        for sel in following_button_selectors:
            try:
                if sel.startswith(".//"):
                    if driver.find_element(By.XPATH, sel).is_displayed(): return None
                else:
                    if driver.find_element(By.CSS_SELECTOR, sel).is_displayed(): return None
            except NoSuchElementException: continue
        for sel in follow_button_selectors:
            try:
                button = None
                if sel.startswith(".//"): button = driver.find_element(By.XPATH, sel)
                else: button = driver.find_element(By.CSS_SELECTOR, sel)
                if button and button.is_displayed() and button.is_enabled():
                    logger.debug(f"プロフィールページで「フォローする」ボタンを発見 (selector: {sel})")
                    return button
            except NoSuchElementException: continue
        logger.info(f"プロフィールページでフォロー可能なボタンが見つかりませんでした。"); return None
    except TimeoutException: logger.warning(f"プロフィールページのフォローボタン群の読み込みタイムアウト。")
    except Exception as e: logger.error(f"プロフィールページのフォローボタン検索でエラー。", exc_info=True); return None

def follow_domo_givers_with_ratio(driver, my_user_id):
    if not FOLLOW_SETTINGS.get("follow_users_who_domoed_and_high_follow_ratio"):
        logger.info("「DOMOをくれたRatio指定ユーザーへのフォロー」はスキップされました。"); return
    logger.info(">>> DOMOをくれたRatio指定ユーザーへのフォローを開始します...")
    # (以降、loggerを使用するように修正)
    max_my_acts = FOLLOW_SETTINGS.get("max_domo_activities_for_ratio_follow", 3)
    my_activity_urls = get_my_activity_urls(driver, my_user_id, max_my_acts)
    if not my_activity_urls: logger.info("フォロー対象者を探すための自身の活動日記がありません。"); return

    all_domo_givers_profiles = set()
    for activity_url in my_activity_urls:
        domo_user_profiles_on_activity = get_users_who_domoed_activity(driver, activity_url)
        all_domo_givers_profiles.update(domo_user_profiles_on_activity)
        time.sleep(DOMO_SETTINGS.get("delay_between_domo_check_sec", 2))
    if not all_domo_givers_profiles: logger.info("DOMOをくれたユーザーが見つかりませんでした。"); return
    logger.info(f"合計 {len(all_domo_givers_profiles)} 人のユニークなDOMO提供者をチェック対象とします。")

    followed_this_session_count = 0
    min_followers_threshold = FOLLOW_SETTINGS.get("min_followers_for_ratio_follow", 50)
    ratio_threshold = FOLLOW_SETTINGS.get("follow_to_follower_ratio_threshold", 0.8)

    for profile_url in list(all_domo_givers_profiles):
        if profile_url == f"{BASE_URL}/users/{my_user_id}": continue
        user_name_log = profile_url.split('/')[-1]
        logger.info(f"DOMO提供者「{user_name_log}」のフォロー状況とRatioを確認します...")
        driver.get(profile_url); time.sleep(FOLLOW_SETTINGS.get("short_wait_sec", 1.5))

        follow_button_on_profile = find_follow_button_on_profile_page(driver)
        if not follow_button_on_profile:
            logger.info(f"ユーザー「{user_name_log}」は既にフォロー済みか、フォローボタンがありません。スキップします。")
            time.sleep(FOLLOW_SETTINGS.get("delay_between_ratio_follow_sec", 3) / 2); continue

        follows, followers = get_user_follow_counts(driver, profile_url)
        if follows == -1 or followers == -1:
            logger.warning(f"ユーザー「{user_name_log}」のフォロー数/フォロワー数が取得できませんでした。スキップします。"); continue
        if followers == 0:
            logger.info(f"ユーザー「{user_name_log}」のフォロワーが0です。Ratio計算不可のためスキップ。"); continue
        if followers < min_followers_threshold:
            logger.info(f"ユーザー「{user_name_log}」のフォロワー数 ({followers}) が閾値 ({min_followers_threshold}) 未満です。スキップ。"); continue

        current_ratio = follows / followers
        logger.info(f"ユーザー「{user_name_log}」: フォロー中={follows}, フォロワー={followers}, 現在Ratio(フォロー中/フォロワー)={current_ratio:.2f} (閾値: <{ratio_threshold})")

        if follows < followers and current_ratio < ratio_threshold :
            logger.info(f"Ratio条件およびフォロー中<フォロワー条件を満たしました。フォローを試みます。")
            if click_follow_button_and_verify(driver, follow_button_on_profile, user_name_log):
                followed_this_session_count += 1
            time.sleep(FOLLOW_SETTINGS.get("delay_between_ratio_follow_sec", 5))
        else:
            if not (follows < followers) : logger.info(f"条件「フォロー中 < フォロワー」を満たしませんでした ({follows} < {followers} is False)。")
            if not (current_ratio < ratio_threshold) : logger.info(f"条件「Ratio < 閾値」を満たしませんでした ({current_ratio:.2f} < {ratio_threshold} is False)。")
            logger.info(f"スキップします。")
            time.sleep(FOLLOW_SETTINGS.get("delay_between_ratio_follow_sec", 3) / 2)

    logger.info(f"<<< DOMOをくれたRatio指定ユーザーへのフォロー処理完了。合計 {followed_this_session_count} 人をフォローしました。")

# --- mainブロック ---
if __name__ == "__main__":
    logger.info("=========== スクリプト開始 ===========")
    driver = None # driverを初期化
    try:
        driver = webdriver.Chrome(options=get_driver_options())
        driver.implicitly_wait(DOMO_SETTINGS.get("implicit_wait_sec", 7))
        logger.info(f"設定ファイル {CONFIG_FILE} から認証情報を読み込みました。")

        if login(driver, YAMAP_EMAIL, YAMAP_PASSWORD):
            logger.info(f"ログイン後のページURL: {driver.current_url}")
            current_config_display = {"domo_settings": DOMO_SETTINGS, "follow_settings": FOLLOW_SETTINGS}
            logger.info(f"現在の設定:\n{json.dumps(current_config_display, indent=2, ensure_ascii=False)}")
            logger.info(f"自分のユーザーID: {MY_USER_ID}"); time.sleep(2)

            if DOMO_SETTINGS.get("domo_users_who_domoed_my_posts"): domo_users_who_domoed_my_posts(driver, MY_USER_ID)
            else: logger.info("「自身の投稿にDOMOしてくれたユーザーへDOMO」機能は設定で無効になっています。")
            if DOMO_SETTINGS.get("domo_recommended_posts"): domo_recommended_posts(driver)
            else: logger.info("「トップページのおすすめ投稿へDOMO」機能は設定で無効になっています。")

            if FOLLOW_SETTINGS.get("follow_users_who_followed_me"): follow_back_users(driver, MY_USER_ID)
            else: logger.info("「フォローしてくれたユーザーへのフォローバック」機能は設定で無効になっています。")
            if FOLLOW_SETTINGS.get("follow_users_who_domoed_and_high_follow_ratio"): follow_domo_givers_with_ratio(driver, MY_USER_ID)
            else: logger.info("「DOMOをくれたRatio指定ユーザーへのフォロー」機能は設定で無効になっています。")

            logger.info("全ての有効な処理が完了しました。")
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
        logger.info("=========== スクリプト終了 ===========")
