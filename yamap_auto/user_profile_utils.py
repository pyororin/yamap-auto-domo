# coding: utf-8
# ==============================================================================
# ユーザープロフィール関連ユーティリティ (user_profile_utils.py)
#
# 概要:
#   YAMAPのユーザープロフィールページに関連する操作（最新活動日記の取得、
#   フォロー数・フォロワー数の取得、フォローボタンの検索など）を提供するモジュール。
# ==============================================================================

import logging
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from datetime import datetime, timezone # datetime をインポート

# driver_utilsから必要なものをインポート
from .driver_utils import get_main_config, BASE_URL, wait_for_page_transition, save_screenshot

# New imports
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Ensure datetime is imported from datetime (though not used in this specific function anymore)
# from datetime import datetime # Not strictly needed here anymore

# ... (logger definition) ...

# Helper function to parse a single user item using BeautifulSoup
def _parse_user_item_bs(item_html_content):
    """
    Parses a single user list item's HTML (obtained via BeautifulSoup)
    to extract profile URL, name, and follow-back status.
    """
    item_soup = BeautifulSoup(item_html_content, 'html.parser')

    profile_url = "N/A"
    user_name = "N/A"
    is_followed_back = False
    # last_activity_date_on_list = None # REMOVED - No longer extracted here

    # Selectors (relative to the item_soup)
    user_profile_link_selector_bs = "a.css-e5vv35"
    user_name_selector_within_link_bs = "h2.css-o7x4kv"
    followed_back_status_selector_bs = "div.css-b8hsdn"
    # REMOVED: last_activity_date_selector_bs as it's no longer used here

    try:
        profile_link_element = item_soup.select_one(user_profile_link_selector_bs)
        if profile_link_element:
            href = profile_link_element.get('href')
            if href and "/users/" in href:
                profile_url = href if href.startswith(BASE_URL) else BASE_URL + href

            name_element = profile_link_element.select_one(user_name_selector_within_link_bs)
            if name_element:
                user_name = name_element.get_text(strip=True)

        followed_back_element = item_soup.select_one(followed_back_status_selector_bs)
        if followed_back_element and "フォローされています" in followed_back_element.get_text(strip=True):
            is_followed_back = True

        # REMOVED: Logic to extract last activity date from list item

    except Exception as e_bs_parse:
        logger.error(f"BS parsing error for item: {e_bs_parse}. HTML snippet: {item_html_content[:200]}", exc_info=True)

    return {
        'url': profile_url,
        'name': user_name,
        'is_followed_back': is_followed_back
        # REMOVED: 'last_activity_date_on_list': last_activity_date_on_list
    }

# ... (rest of user_profile_utils.py, including get_my_following_users_profiles) ...

def get_latest_activity_url(driver, user_profile_url):
    """
    指定されたユーザープロフィールURLから最新の活動日記のURLを取得する。
    プロフィールページにアクセスし、活動日記リストの先頭にある活動日記のURLを返します。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        user_profile_url (str): 対象ユーザーのプロフィールページの完全なURL。

    Returns:
        str or None: 最新の活動日記の完全なURL。見つからない場合はNone。
    """
    main_conf = get_main_config() # 設定をロード
    user_id_log = user_profile_url.split('/')[-1].split('?')[0] # ログ用にユーザーID部分を抽出
    logger.info(f"プロフィール ({user_id_log}) の最新活動日記URLを取得します。")

    # 1. 対象のユーザープロフィールページへ遷移 (既にそのページにいなければ)
    current_page_url = driver.current_url
    if user_profile_url not in current_page_url :
        logger.debug(f"対象のユーザープロフィールページ ({user_profile_url}) に遷移します。")
        driver.get(user_profile_url)
        # ページ遷移後、主要な要素（活動記録タブやユーザー名など）が表示されるまで待機
        try:
            WebDriverWait(driver, 10).until(
                EC.any_of( # いずれかの要素が見つかればOK
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[data-testid='profile-tab-activities']")), # 活動記録タブ
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h1[class*='UserProfileScreen_userName']"))    # ユーザー名表示
                )
            )
        except TimeoutException:
            logger.warning(f"ユーザー ({user_id_log}) のプロフィールページ主要要素の読み込みタイムアウト。最新活動日記取得失敗の可能性。")
            # ページ遷移が不完全な場合、ここでリターンすることも検討
    else:
        logger.debug(f"既にユーザープロフィールページ ({user_profile_url}) 付近にいます。")

    latest_activity_url = None
    try:
        # 2. 最新の活動日記へのリンクを探す
        #    YAMAPのUI変更に対応するため、複数のセレクタ候補を試行します。
        #    通常、プロフィールページの活動日記リストの最初のアイテムが最新です。
        activity_link_selectors = [
            "article[data-testid='activity-entry'] a[href^='/activities/']", # 推奨される構造
            "a[data-testid='activity-card-link']",                           # 以前の構造・フォールバック
            ".ActivityCard_card__link__XXXXX a[href^='/activities/']"        # 特定のクラス名 (変わりやすいので注意)
        ]

        # configから活動日記リンクの待機時間を読み込み
        action_delays = main_conf.get("action_delays", {})
        wait_time_for_activity_link = action_delays.get("wait_for_activity_link_sec", 7)

        for selector in activity_link_selectors:
            try:
                # 活動日記リンクが表示されるまで待機
                WebDriverWait(driver, wait_time_for_activity_link).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                activity_link_element = driver.find_element(By.CSS_SELECTOR, selector) # 最初に見つかったものが最新と仮定
                href = activity_link_element.get_attribute('href')
                if href:
                    # URLの整形
                    if href.startswith("/"): latest_activity_url = BASE_URL + href
                    elif href.startswith(BASE_URL): latest_activity_url = href

                    # 有効な活動日記URLか確認
                    if latest_activity_url and "/activities/" in latest_activity_url:
                        logger.info(f"ユーザー ({user_id_log}) の最新活動日記URL: {latest_activity_url.split('/')[-1]} (selector: {selector})")
                        return latest_activity_url # 発見、処理終了
                    else:
                        latest_activity_url = None # 無効なURLならリセットして次のセレクタへ
            except (NoSuchElementException, TimeoutException):
                logger.debug(f"セレクタ '{selector}' で最新活動日記リンクが見つかりませんでした。")
                continue # 次のセレクタ候補へ

        if not latest_activity_url: # 全てのセレクタで見つからなかった場合
            logger.info(f"ユーザー ({user_id_log}) の最新の活動日記が見つかりませんでした。")

    except TimeoutException: # 活動日記リスト全体の読み込みタイムアウト
        logger.warning(f"ユーザー ({user_id_log}) の活動日記リスト読み込みでタイムアウトしました。")
    except Exception as e: # その他の予期せぬエラー
        logger.error(f"ユーザー ({user_id_log}) の最新活動日記取得中にエラー。", exc_info=True)
    return latest_activity_url

def get_user_follow_counts(driver, user_profile_url):
    """
    ユーザープロフィールページからフォロー数とフォロワー数を取得する。
    YAMAPのUIでは、これらの数値は通常タブ形式で表示されています（例：「フォロー中 XX」「フォロワー YY」）。
    数値が取得できなかった場合は (-1, -1) を返します。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        user_profile_url (str): 対象ユーザーのプロフィールページの完全なURL。

    Returns:
        tuple[int, int]: (フォロー数, フォロワー数)。取得失敗時は (-1, -1)。
    """
    user_id_log = user_profile_url.split('/')[-1].split('?')[0] # ログ用ユーザーID
    logger.info(f"ユーザー ({user_id_log}) のフォロー数/フォロワー数を取得します。")

    # 1. 対象のユーザープロフィールページへ遷移 (既にそのページにいなければ)
    current_page_url = driver.current_url
    if user_profile_url not in current_page_url:
        logger.debug(f"対象のユーザープロフィールページ ({user_profile_url}) に遷移します。")
        driver.get(user_profile_url)
        try: # ページ遷移確認 (URLにユーザーIDが含まれるかで判断)
            WebDriverWait(driver, 10).until(EC.url_contains(user_id_log))
        except TimeoutException:
            logger.warning(f"ユーザー({user_id_log})のプロフィールページへの遷移確認タイムアウト。数値取得失敗の可能性。")
    else:
        logger.debug(f"既にユーザープロフィールページ ({user_profile_url}) 付近にいます。")

    follows_count = -1    # フォロー数 (初期値 -1)
    followers_count = -1  # フォロワー数 (初期値 -1)

    try:
        # 2. フォロー数/フォロワー数が表示されているタブコンテナ要素を特定
        #    セレクタはYAMAPのUIに依存 (例: "div#tabs.css-1kw20l6", "ul.css-7te929")
        tabs_container_selector = "div#tabs.css-1kw20l6" # 現在のYAMAPのUIに基づくセレクタ例
        try:
            tabs_container_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, tabs_container_selector))
            )
            logger.debug(f"フォロー数/フォロワー数タブコンテナ ({tabs_container_selector}) を発見。")
        except TimeoutException:
            logger.warning(f"フォロー数/フォロワー数タブコンテナ ({tabs_container_selector}) の読み込みタイムアウト ({user_id_log})。")
            return follows_count, followers_count # コンテナが見つからなければ早期リターン

        # 3. タブコンテナ内からフォロー数とフォロワー数のリンク/テキストを抽出
        #    リンクのhref属性やテキスト内容から数値を抽出します。
        follow_link_selector = "a[href*='tab=follows']"    # 「フォロー中」タブへのリンク (部分一致)
        follower_link_selector = "a[href*='tab=followers']" # 「フォロワー」タブへのリンク (部分一致)

        # フォロー中の数を取得
        try:
            follow_link_element = tabs_container_element.find_element(By.CSS_SELECTOR, follow_link_selector)
            full_text = follow_link_element.text.strip() # 例: "フォロー中 123"
            num_str = "".join(filter(str.isdigit, full_text)) # テキストから数字のみを抽出
            if num_str:
                follows_count = int(num_str)
            else:
                logger.warning(f"フォロー数のテキスト「{full_text}」から数値を抽出できませんでした ({user_id_log})。")
        except NoSuchElementException:
            logger.warning(f"フォロー中の数を特定するリンク要素 ({follow_link_selector}) が見つかりませんでした ({user_id_log})。")
        except Exception as e_follow_count:
            logger.error(f"フォロー数取得処理中に予期せぬエラー ({user_id_log}): {e_follow_count}", exc_info=True)

        # フォロワーの数を取得
        try:
            follower_link_element = tabs_container_element.find_element(By.CSS_SELECTOR, follower_link_selector)
            full_text = follower_link_element.text.strip() # 例: "フォロワー 456"
            num_str = "".join(filter(str.isdigit, full_text)) # テキストから数字のみを抽出
            if num_str:
                followers_count = int(num_str)
            else:
                logger.warning(f"フォロワー数のテキスト「{full_text}」から数値を抽出できませんでした ({user_id_log})。")
        except NoSuchElementException:
            logger.warning(f"フォロワーの数を特定するリンク要素 ({follower_link_selector}) が見つかりませんでした ({user_id_log})。")
        except Exception as e_follower_count:
            logger.error(f"フォロワー数取得処理中に予期せぬエラー ({user_id_log}): {e_follower_count}", exc_info=True)

        logger.info(f"ユーザー ({user_id_log}): フォロー中={follows_count}, フォロワー={followers_count}")

    except TimeoutException: # タブコンテナ取得後の予期せぬタイムアウト (通常は発生しにくい)
        logger.warning(f"get_user_follow_countsのメインtryブロックで予期せぬTimeoutExceptionが発生 ({user_id_log})。")
    except Exception as e: # その他の予期せぬエラー
        logger.error(f"フォロー数/フォロワー数取得中にエラー ({user_id_log})。", exc_info=True)

    return follows_count, followers_count

def find_follow_button_on_profile_page(driver):
    """
    ユーザープロフィールページ上で「フォローする」ボタンを探す。
    既にフォロー中である場合や、クリック可能な「フォローする」ボタンがない場合はNoneを返します。
    この関数は、呼び出し元で対象ユーザーのプロフィールページに既に遷移していることを前提とします。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。

    Returns:
        WebElement or None: 「フォローする」ボタンのWebElement。見つからない場合はNone。
    """
    # 現在のURLとタイトルをログに出力 (デバッグ用)
    logger.info(f"プロフィールページ上のフォローボタン探索開始。URL: {driver.current_url}, Title: {driver.title}")
    try:
        # --- 呼び出し元でページ読み込み完了を待つため、ここでの追加待機は原則不要 ---
        # (以前あったユーザー名H1要素の待機はコメントアウト済み)

        # デバッグ用に、フォロー関連ボタンの候補となりそうな要素の検出状況をログに出力
        debug_elements_found = {
            "div.css-1fsc5gw (フォローボタンコンテナ候補1)": len(driver.find_elements(By.CSS_SELECTOR, "div.css-1fsc5gw")),
            "button[aria-pressed='true'] (「フォロー中」ボタン候補)": len(driver.find_elements(By.CSS_SELECTOR, "button[aria-pressed='true']")),
            "button[aria-pressed='false'] (「フォローする」ボタン候補)": len(driver.find_elements(By.CSS_SELECTOR, "button[aria-pressed='false']")),
        }
        logger.debug(f"プロフィールページのフォロー関連要素検出状況: {debug_elements_found}")

        # 1. 「フォロー中」ボタンの確認 (既にフォロー済みかの判定)
        #    - 主に `button[aria-pressed='true']` とそのテキストで判定。
        #    - YAMAPのUI構造に依存するため、複数のセレクタやコンテナ候補を試行。
        try:
            # ボタンを直接囲む可能性のあるコンテナ要素から探索
            button_container_candidates_css = "div.css-1fsc5gw, div.css-194f6e2" # 例: プロフィールヘッダー内のボタンエリア
            button_containers = driver.find_elements(By.CSS_SELECTOR, button_container_candidates_css)
            for container in button_containers:
                try:
                    # コンテナ内で `aria-pressed='true'` のボタンを探す
                    following_buttons_in_container = container.find_elements(By.CSS_SELECTOR, "button[aria-pressed='true']")
                    for btn in following_buttons_in_container:
                        if btn and btn.is_displayed():
                            # ボタンテキストまたは内部spanのテキストに「フォロー中」が含まれるか確認
                            if "フォロー中" in btn.text or \
                               ("フォロー中" in btn.find_element(By.CSS_SELECTOR, "span").text if btn.find_elements(By.CSS_SELECTOR, "span") else False):
                                logger.info(f"プロフィールページで「フォロー中」ボタン (aria-pressed='true' + テキスト, コンテナ内) を発見。既にフォロー済みと判断。")
                                return None # フォロー中なので対象外
                except NoSuchElementException: continue # コンテナ内に該当ボタンなし

            # コンテナ指定なしでのグローバルな探索 (フォールバック)
            following_buttons_global = driver.find_elements(By.CSS_SELECTOR, "button[aria-pressed='true']")
            for btn in following_buttons_global:
                if btn and btn.is_displayed():
                    if "フォロー中" in btn.text or \
                       ("フォロー中" in btn.find_element(By.CSS_SELECTOR, "span").text if btn.find_elements(By.CSS_SELECTOR, "span") else False):
                        logger.info("プロフィールページで「フォロー中」ボタン (aria-pressed='true' + テキスト, グローバル) を発見。既にフォロー済みと判断。")
                        return None

            # XPathによるテキスト一致での最終フォールバック (「フォロー中」)
            if driver.find_elements(By.XPATH, ".//button[normalize-space(.)='フォロー中']"):
                 logger.info("プロフィールページで「フォロー中」ボタン (XPathテキスト, グローバル) を発見。既にフォロー済みと判断。")
                 return None
        except Exception as e_following_check: # 「フォロー中」ボタン確認中のエラー
            logger.warning(f"「フォロー中」ボタンの確認中にエラー: {e_following_check}", exc_info=True)


        # 2. 「フォローする」ボタンの探索
        #    - 主に `button[aria-pressed='false']` とそのテキストで判定。
        #    - data-testid は現在コメントアウト。XPathやaria-labelもフォールバックとして使用。
        try:
            # ボタンを直接囲む可能性のあるコンテナ要素から探索 (上記と同様のコンテナ候補)
            button_container_candidates_css = "div.css-1fsc5gw, div.css-194f6e2"
            button_containers = driver.find_elements(By.CSS_SELECTOR, button_container_candidates_css)
            for container in button_containers:
                try:
                    # コンテナ内で `aria-pressed='false'` のボタンを探す
                    follow_buttons_in_container = container.find_elements(By.CSS_SELECTOR, "button[aria-pressed='false']")
                    for btn in follow_buttons_in_container:
                        if btn and btn.is_displayed() and btn.is_enabled(): # 表示されていてクリック可能なもの
                            if "フォローする" in btn.text or \
                               ("フォローする" in btn.find_element(By.CSS_SELECTOR, "span").text if btn.find_elements(By.CSS_SELECTOR, "span") else False):
                                logger.info(f"プロフィールページで「フォローする」ボタン (aria-pressed='false' + テキスト, コンテナ内) を発見。")
                                return btn # 発見
                except NoSuchElementException: continue

            # コンテナ指定なしでのグローバルな探索 (フォールバック)
            follow_buttons_global = driver.find_elements(By.CSS_SELECTOR, "button[aria-pressed='false']")
            for btn in follow_buttons_global:
                 if btn and btn.is_displayed() and btn.is_enabled():
                    if "フォローする" in btn.text or \
                       ("フォローする" in btn.find_element(By.CSS_SELECTOR, "span").text if btn.find_elements(By.CSS_SELECTOR, "span") else False):
                        logger.info("プロフィールページで「フォローする」ボタン (aria-pressed='false' + テキスト, グローバル) を発見。")
                        return btn

            # XPathによるテキスト一致でのフォールバック (「フォローする」)
            button_by_xpath = driver.find_element(By.XPATH, ".//button[normalize-space(.)='フォローする']")
            if button_by_xpath and button_by_xpath.is_displayed() and button_by_xpath.is_enabled():
                logger.info("プロフィールページで「フォローする」ボタン (XPathテキスト, グローバル) を発見。")
                return button_by_xpath
        except NoSuchElementException: # XPathで見つからなかった場合
             logger.debug("XPath .//button[normalize-space(.)='フォローする'] (グローバル) で「フォローする」ボタンが見つかりませんでした。")
        except Exception as e_follow_check: # 「フォローする」ボタン確認中のエラー
            logger.warning(f"「フォローする」ボタンの確認中にエラー: {e_follow_check}", exc_info=True)

        # aria-label によるフォールバック検索 (グローバル)
        try:
            follow_button_aria = driver.find_element(By.CSS_SELECTOR, "button[aria-label*='フォローする']")
            if follow_button_aria and follow_button_aria.is_displayed() and follow_button_aria.is_enabled():
                logger.info("プロフィールページで「フォローする」ボタン (aria-label, グローバル) を発見。")
                return follow_button_aria
        except NoSuchElementException:
            logger.debug("CSSセレクタ button[aria-label*='フォローする'] (グローバル) で「フォローする」ボタンが見つかりませんでした。")


        logger.info("プロフィールページでクリック可能な「フォローする」ボタンが見つかりませんでした。")
        # ボタンが見つからなかった場合に、関連エリアのHTMLをデバッグ出力 (UI変更調査のため)
        try:
            debug_html_output = ""
            # フォローボタンが含まれそうなコンテナのセレクタ候補
            relevant_container_selectors = ["div.css-1fsc5gw", "div.css-126zbgb", "div.css-kooiip"]
            for sel in relevant_container_selectors:
                try:
                    debug_element = driver.find_element(By.CSS_SELECTOR, sel)
                    if debug_element:
                        debug_html_output = debug_element.get_attribute('outerHTML')
                        logger.debug(f"ボタンが見つからなかった関連エリアのHTML ({sel}):\n{debug_html_output[:1000]}...") # 長すぎる場合は省略
                        break # 最初に見つかったものを出力して終了
                except NoSuchElementException: pass
            if not debug_html_output: # 候補コンテナが見つからなかった場合
                logger.debug("ボタン検索失敗時のデバッグHTML取得試行で、主要なコンテナ候補が見つかりませんでした。")
        except Exception as e_debug_html:
            logger.debug(f"ボタン検索失敗時のデバッグHTML取得中にエラー: {e_debug_html}")
        return None # 全ての探索で見つからなかった場合
    except TimeoutException: # この関数内での明示的なWebDriverWaitはないが、将来的な追加を考慮
        logger.warning("プロフィールページのフォローボタン探索中に予期せぬタイムアウト。")
    except Exception as e: # この関数全体の予期せぬエラー
        logger.error("プロフィールページのフォローボタン検索で予期せぬエラー。", exc_info=True)
    return None


def get_last_activity_date(driver, user_profile_url):
    """
    指定されたユーザープロフィールURLから最新の活動の日付を取得する。
    プロフィールページにアクセスし、活動日記リストの最初のアイテムの日付を解析します。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        user_profile_url (str): 対象ユーザーのプロフィールページの完全なURL。

    Returns:
        datetime.date or None: 最新の活動記録の日付。見つからない場合や解析できない場合はNone。
    """
    main_conf = get_main_config()
    user_id_log = user_profile_url.split('/')[-1].split('?')[0]
    user_id_log = user_profile_url.split('/')[-1].split('?')[0]
    logger.info(f"プロフィール ({user_id_log}) の最新活動日時を取得します。")

    config = get_main_config()
    unfollow_settings = config.get("unfollow_inactive_users_settings", {})
    # Use a general timeout for profile page elements, can be overridden by specific date element timeout
    profile_element_timeout = unfollow_settings.get("profile_load_timeout_sec", 20)
    # Specific timeout for the date element itself, falls back to profile_element_timeout
    date_element_timeout = unfollow_settings.get("date_element_timeout_sec", profile_element_timeout)

    current_page_url = driver.current_url
    normalized_current_url = current_page_url.split('?')[0].rstrip('/')
    normalized_target_url = user_profile_url.split('?')[0].rstrip('/')

    if normalized_current_url != normalized_target_url:
        logger.debug(f"対象のユーザープロフィールページ ({user_profile_url}) に遷移します。")
        driver.get(user_profile_url)
        try:
            WebDriverWait(driver, profile_element_timeout).until( # Use configured timeout - CORRECTED VARIABLE
                EC.any_of(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[data-testid='profile-tab-activities']")),
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h1[class*='UserProfileScreen_userName']")),
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h1.css-jctfiw")) # Profile name as a fallback
                )
            )
        except TimeoutException:
            logger.warning(f"ユーザー ({user_id_log}) のプロフィールページ主要要素の読み込みタイムアウト ({profile_element_timeout}秒)。最新活動日時取得失敗の可能性。")
            save_screenshot(driver, "ProfileLoadTimeout_GetDate", f"UID_{user_id_log}")
            return None
    else:
        logger.debug(f"既にユーザープロフィールページ ({user_profile_url}) 付近にいます。")

    try:
        # 活動記録の日時情報が含まれる可能性のある要素のセレクタ
        date_selectors = [
            "article[data-testid='activity-entry'] time[datetime]",
            "a[data-testid='activity-card-link'] time[datetime]",
            "time.css-1vh94j7",
            "div[class*='ActivityEntry_meta'] time",
            "ul[class*='ActivityListScreen_list__'] li:first-child time[datetime]", # List view first item
            "ul.css-qksbms li:first-child time[datetime]", # Another list view variant
            "p.ActivityItem__Meta span.ActivityItem__Date" # New selector based on provided HTML
        ]
        # action_delays = main_conf.get("action_delays", {}) # main_conf already loaded as config
        # wait_time_for_activity_date = action_delays.get("wait_for_activity_link_sec", 7)
        # Use profile_element_timeout for waiting for date elements as well, or a new config value
        wait_time_for_date_element = unfollow_settings.get("date_element_timeout_sec", profile_element_timeout)


        for selector in date_selectors:
            try:
                WebDriverWait(driver, wait_time_for_date_element).until( # Use configured/profile_element_timeout
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                time_element = driver.find_element(By.CSS_SELECTOR, selector)
                datetime_str = time_element.get_attribute("datetime")
                date_text_content = time_element.text.strip()

                if datetime_str:
                    # ISO 8601形式 (YYYY-MM-DDTHH:MM:SSZ や YYYY-MM-DDTHH:M M:SS+09:00) を想定
                    try:
                        # タイムゾーン情報を考慮してdatetimeオブジェクトに変換
                        # ZはUTCを示す
                        if datetime_str.endswith('Z'):
                            dt_object = datetime.strptime(datetime_str[:-1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                        else:
                            # Python 3.7+ では fromisoformat が使える
                            dt_object = datetime.fromisoformat(datetime_str)

                        activity_date = dt_object.date()
                        logger.info(f"ユーザー ({user_id_log}) の最新活動日時: {activity_date} (selector: {selector}, from datetime attr: {datetime_str})")
                        return activity_date
                    except ValueError as ve:
                        logger.debug(f"datetime属性値 '{datetime_str}' (selector: {selector}) のパースに失敗: {ve}。テキストコンテントを試行します。")
                        # Fall through to text content parsing

                # datetime属性がない、またはパースに失敗した場合、テキストコンテントから抽出を試みる
                if date_text_content:
                    try:
                        # "YYYY.MM.DD(曜日)" 形式の対応
                        if "." in date_text_content and "(" in date_text_content and ")" in date_text_content:
                            date_part = date_text_content.split("(")[0].strip()
                            dt_object = datetime.strptime(date_part, "%Y.%m.%d")
                            activity_date = dt_object.date()
                            logger.info(f"ユーザー ({user_id_log}) の最新活動日時 (テキストパース YYYY.MM.DD): {activity_date} (selector: {selector}, text: {date_text_content})")
                            return activity_date
                        # "YYYY年MM月DD日" 形式の対応
                        elif "年" in date_text_content and "月" in date_text_content and "日" in date_text_content:
                            dt_object = datetime.strptime(date_text_content, "%Y年%m月%d日")
                            activity_date = dt_object.date()
                            logger.info(f"ユーザー ({user_id_log}) の最新活動日時 (テキストパース YYYY年MM月DD日): {activity_date} (selector: {selector}, text: {date_text_content})")
                            return activity_date
                        # 単純な "YYYY-MM-DD" 形式 (datetime属性がなくてもテキストがこの形式の場合)
                        elif "-" in date_text_content and len(date_text_content.split('-')) == 3:
                             try:
                                dt_object = datetime.strptime(date_text_content.split('T')[0], "%Y-%m-%d") # 時刻情報があれば除去
                                activity_date = dt_object.date()
                                logger.info(f"ユーザー ({user_id_log}) の最新活動日時 (テキストパース YYYY-MM-DD): {activity_date} (selector: {selector}, text: {date_text_content})")
                                return activity_date
                             except ValueError:
                                 logger.debug(f"テキスト '{date_text_content}' (selector: {selector}) の YYYY-MM-DD パースに失敗。")
                                 continue # 次のセレクタへ
                        # 他のテキスト形式のパースロジックをここに追加可能
                        else:
                            logger.debug(f"日時テキスト '{date_text_content}' (selector: {selector}) が既知の形式と一致しません。")
                            continue # 次のセレクタへ
                    except ValueError as e_text_parse:
                        logger.debug(f"日時テキスト '{date_text_content}' (selector: {selector}) のパース中にエラー: {e_text_parse}")
                        continue # 次のセレクタへ
                else:
                    logger.debug(f"セレクタ '{selector}' で要素は取得できましたが、datetime属性もテキストコンテントも空です。")
                    continue # 次のセレクタへ

            except (NoSuchElementException, TimeoutException):
                logger.debug(f"セレクタ '{selector}' で活動日時要素が見つかりませんでした。")
                continue

        logger.info(f"ユーザー ({user_id_log}) の最新の活動日時が見つかりませんでした（全セレクタ試行後）。")
        return None

    except Exception as e:
        logger.error(f"ユーザー ({user_id_log}) の最新活動日時取得中にエラー。", exc_info=True)
        return None


def get_my_following_users_profiles(driver, my_user_id, max_users_to_fetch=None, max_pages_to_check=None):
    """
    自分の「フォロー中」リストページから、フォローしているユーザーのプロフィール情報
    (URL、名前、自分をフォローバックしているか) のリストを取得します。
    ページネーションに対応し、指定された最大ユーザー数または最大ページ数まで取得します。
    各ページ内のユーザーアイテム解析はBeautifulSoupとThreadPoolExecutorを使用します。
    """
    if not my_user_id:
        logger.error("自分のユーザーIDが指定されていないため、フォロー中ユーザーリストを取得できません。")
        return []

    following_list_url = f"{BASE_URL}/users/{my_user_id}?tab=follows#tabs"
    logger.info(f"自分のフォロー中ユーザーリスト ({following_list_url}) からプロフィール情報を取得します（BS+ThreadPool最適化）。")
    main_conf = get_main_config() # For thread pool settings
    parallel_settings = main_conf.get("parallel_processing_settings", {})
    # Use a specific worker count for this BS parsing, or fallback to general workers
    bs_workers = parallel_settings.get("bs_parsing_workers", parallel_settings.get("max_workers_generic", 4))


    user_list_container_selector_selenium = "main.css-1ed9ptx ul.css-18aka15"
    user_list_item_selector_bs = "li.css-1qsnhpb" # For BeautifulSoup

    next_page_button_selector_candidates = [
        "nav.css-t3h2hz button:not([disabled])[aria-label='次のページに移動する']",
        "button.btn-next"
    ]

    current_url_before_get = driver.current_url
    # Ensure we always explicitly navigate to the first page for a fresh start
    logger.info(f"Navigating to initial following list URL: {following_list_url}")
    driver.get(following_list_url) # Explicitly go to page 1

    try:
        # Wait for the main list container to be present
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, user_list_container_selector_selenium))
        )
        # Add a more specific wait for at least one list item to ensure content has started loading
        WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, f"{user_list_container_selector_selenium} > {user_list_item_selector_bs}"))
        )
        logger.info(f"フォロー中ユーザーリストコンテナと最初のアイテムの表示を確認しました。 ({driver.current_url})")
    except TimeoutException:
        logger.error(f"フォロー中ユーザーリストコンテナまたは最初のアイテムの読み込みタイムアウト。URL: {driver.current_url}")
        save_screenshot(driver, "FollowingListContainerOrItemTimeout_BS", f"UID_{my_user_id}")
        return []

    all_users_data = []
    processed_pages = 0
    # Max workers for parsing items on a single page
    # Should be modest as it's CPU-bound on potentially shared HTML string
    max_item_parsers = bs_workers

    while True:
        if max_pages_to_check is not None and processed_pages >= max_pages_to_check:
            logger.info(f"最大確認ページ数 ({max_pages_to_check}) に達したため、処理を終了します。")
            break
        if max_users_to_fetch is not None and len(all_users_data) >= max_users_to_fetch:
            logger.info(f"最大取得ユーザー数 ({max_users_to_fetch}) に達したため、処理を終了します。")
            break

        page_start_time = time.time()
        logger.info(f"フォロー中リストの {processed_pages + 1} ページ目を処理中...")

        try:
            # Get the list container element via Selenium
            list_container_element = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, user_list_container_selector_selenium))
            )
            # Get its HTML content
            list_container_html = list_container_element.get_attribute('outerHTML')
            if not list_container_html:
                logger.warning(f"{processed_pages + 1} ページ目のリストコンテナHTMLが取得できませんでした。スキップ。")
                break

            # Parse with BeautifulSoup
            page_soup = BeautifulSoup(list_container_html, 'html.parser')
            # Find all user items (li.css-1qsnhpb) within this container
            user_item_elements_bs = page_soup.select(f"{user_list_item_selector_bs}") # Relative to page_soup

            if not user_item_elements_bs:
                if processed_pages == 0:
                    logger.info(f"{processed_pages + 1} ページ目にユーザーが見つかりませんでした（BS解析）。リストが空の可能性があります。")
                else:
                    logger.info(f"{processed_pages + 1} ページ目にユーザーが見つかりませんでした（BS解析）。これが最後のページかもしれません。")
                break

            logger.debug(f"ページ {processed_pages + 1}: BeautifulSoupで {len(user_item_elements_bs)} 件のユーザーアイテムを検出。並列解析開始 (max_workers={max_item_parsers})...")

            page_users_data = []
            item_html_contents = [str(item_bs) for item_bs in user_item_elements_bs]

            with ThreadPoolExecutor(max_workers=max_item_parsers) as executor:
                future_to_item = {executor.submit(_parse_user_item_bs, item_html): item_html for item_html in item_html_contents}
                for future in as_completed(future_to_item):
                    try:
                        user_data = future.result()
                        if user_data and user_data['url'] != "N/A":
                            # Optional: Check for duplicates before adding if fetching across all pages first
                            # For now, duplicates are handled by the caller or by checking all_users_data if needed
                            page_users_data.append(user_data)
                    except Exception as exc:
                        logger.error(f'アイテム解析中に例外が発生: {exc}', exc_info=True)

            valid_page_users_data = [ud for ud in page_users_data if ud['url'] != "N/A"]
            for ud in valid_page_users_data:
                 if max_users_to_fetch is not None and len(all_users_data) >= max_users_to_fetch:
                     break
                 if not any(existing_ud['url'] == ud['url'] for existing_ud in all_users_data): # Avoid duplicates across pages
                    all_users_data.append(ud)
                    logger.debug(f"  追加 (BS): {ud['name']} ({ud['url'].split('/')[-1]}), フォローバック: {ud['is_followed_back']}")

            page_end_time = time.time()
            logger.info(f"ページ {processed_pages + 1} の {len(user_item_elements_bs)} アイテム処理完了 ({len(valid_page_users_data)}件有効)。所要時間: {page_end_time - page_start_time:.2f}秒。")
            processed_pages += 1
            logger.info(f"現在 {len(all_users_data)} 件のユーザー情報を取得。")

            # Pagination logic (Selenium)
            next_button = None
            for sel_idx, next_sel in enumerate(next_page_button_selector_candidates):
                try:
                    candidate_button = driver.find_element(By.CSS_SELECTOR, next_sel)
                    if candidate_button.is_displayed() and candidate_button.is_enabled():
                        next_button = candidate_button
                        logger.debug(f"「次へ」ボタンをセレクタ '{next_sel}' で発見。")
                        break
                except NoSuchElementException:
                    logger.debug(f"「次へ」ボタン候補 '{next_sel}' は見つかりませんでした。({sel_idx+1}/{len(next_page_button_selector_candidates)})")

            if next_button:
                logger.info("「次へ」ボタンをクリックします。")
                prev_url_for_transition_check = driver.current_url
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
                time.sleep(0.5)
                next_button.click()
                try:
                    WebDriverWait(driver, 15).until(
                        lambda d: d.current_url != prev_url_for_transition_check or \
                                  EC.presence_of_element_located((By.CSS_SELECTOR, user_list_container_selector_selenium)) # Wait for new container
                    )
                    # Ensure the new container is actually different or updated if URL doesn't change
                    # For simplicity, we wait for the container to be present again.
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, user_list_container_selector_selenium))
                    )
                    logger.info(f"次のページ ({driver.current_url}) へ遷移成功。")
                    time.sleep(1.5)
                except TimeoutException:
                    logger.info("「次へ」ボタンクリック後、ページ遷移/内容更新の確認タイムアウト。最後のページかもしれません。")
                    break
            else:
                logger.info("「次へ」ボタンが見つからないか、無効です。最後のページと判断します。")
                break
        except TimeoutException:
            logger.warning(f"{processed_pages + 1} ページ目のリストコンテナ要素の取得またはHTML取得でタイムアウト。処理を終了します。")
            break
        except Exception as e_page:
            logger.error(f"ページ処理中に予期せぬエラー: {e_page}", exc_info=True)
            save_screenshot(driver, "FollowingListPageError_BS", f"UID_{my_user_id}_Page{processed_pages+1}")
            break

    logger.info(f"フォロー中ユーザーの情報を合計 {len(all_users_data)} 件取得しました（BS+ThreadPool最適化）。")
    return all_users_data

# ... (rest of the file, e.g., get_my_followers_profiles, is_user_following_me, etc.) ...
# If get_my_followers_profiles needs similar optimization, it would follow the same pattern.

def get_my_followers_profiles(driver, my_user_id, max_users_to_fetch=None, max_pages_to_check=None):
    """
    自分の「フォロワー」リストページから、自分をフォローしているユーザーのプロフィール情報
    (URL、名前、自分がそのユーザーをフォローバックしているか) のリストを取得します。
    ※注意: 現状この関数は「自分が相手をフォローバックしているか」のステータスは取得しません。
             主に is_user_following_me のヘルパーとして、フォロワーのURLと名前を取得するために使われます。
             「自分が相手をフォローバックしているか」は、相手のカードにある「フォローする/フォロー中」ボタンで判断します。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        my_user_id (str): 自分のYAMAPユーザーID。
        max_users_to_fetch (int, optional): 取得する最大のユーザープロファイル数。Noneの場合は制限なし。
        max_pages_to_check (int, optional): 確認する最大のページ数。Noneの場合は全ページ。

    Returns:
        list[dict]: フォロワーの情報のリスト。
                      各辞書は {'url': str, 'name': str} を含む。(is_followed_by_me はここでは取得しない)
    """
    if not my_user_id:
        logger.error("自分のユーザーIDが指定されていないため、フォロワーリストを取得できません。")
        return []

    followers_list_url = f"{BASE_URL}/users/{my_user_id}?tab=followers#tabs"
    logger.info(f"自分のフォロワーリスト ({followers_list_url}) からプロフィール情報を取得します。")
    logger.info(f"取得上限: ユーザー数={max_users_to_fetch or '無制限'}, ページ数={max_pages_to_check or '無制限'}")

    # --- Selectors (same as get_my_following_users_profiles as structure is similar) ---
    user_list_container_selector = "main.css-1ed9ptx ul.css-18aka15"
    user_list_item_selector = "li.css-1qsnhpb"
    user_profile_link_selector = "a.css-e5vv35"
    user_name_selector_within_link = "h2.css-o7x4kv"
    # "フォローされています" (div.css-b8hsdn) はこのページでは「相手が自分をフォローしている」ことを示すので、
    # 「自分が相手をフォローしているか」とは直接関係ない。相手のカードのボタンを見る必要がある。
    next_page_button_selector_candidates = [
        "nav.css-t3h2hz button:not([disabled])[aria-label='次のページに移動する']",
        "button.btn-next"
    ]

    current_url_before_get = driver.current_url
    if not driver.current_url.startswith(followers_list_url.split('#')[0]):
        driver.get(followers_list_url)

    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, user_list_container_selector))
        )
        logger.info(f"フォロワーリストコンテナ ({user_list_container_selector}) の表示を確認しました。")
    except TimeoutException:
        logger.error(f"フォロワーリストコンテナ ({user_list_container_selector}) の読み込みタイムアウト。")
        from .driver_utils import save_screenshot # 遅延インポート
        save_screenshot(driver, "FollowerListContainerTimeout", f"UID_{my_user_id}")
        return []

    users_data = [] # ここでは {'url': str, 'name': str} のみ格納
    processed_pages = 0

    while True: # Pagination loop
        if max_pages_to_check is not None and processed_pages >= max_pages_to_check:
            logger.info(f"最大確認ページ数 ({max_pages_to_check}) に達しました。")
            break
        if max_users_to_fetch is not None and len(users_data) >= max_users_to_fetch:
            logger.info(f"最大取得ユーザー数 ({max_users_to_fetch}) に達しました。")
            break

        logger.info(f"フォロワーリストの {processed_pages + 1} ページ目を処理中...")
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, f"{user_list_container_selector} > {user_list_item_selector}"))
            )
            user_items = driver.find_elements(By.CSS_SELECTOR, f"{user_list_container_selector} > {user_list_item_selector}")

            if not user_items and processed_pages == 0:
                logger.info(f"{processed_pages + 1} ページ目にユーザーが見つかりませんでした。リストが空の可能性があります。")
                break
            elif not user_items:
                logger.info(f"{processed_pages + 1} ページ目にユーザーが見つかりませんでした。これが最後のページかもしれません。")
                break

            for item_idx, item in enumerate(user_items):
                if max_users_to_fetch is not None and len(users_data) >= max_users_to_fetch:
                    break

                profile_url = "N/A"
                user_name = "N/A"
                try:
                    profile_link_element = item.find_element(By.CSS_SELECTOR, user_profile_link_selector)
                    href = profile_link_element.get_attribute('href')
                    if href and "/users/" in href:
                        profile_url = href if href.startswith(BASE_URL) else BASE_URL + href

                    name_element = profile_link_element.find_element(By.CSS_SELECTOR, user_name_selector_within_link)
                    user_name = name_element.text.strip()

                    if profile_url != "N/A" and not any(u['url'] == profile_url for u in users_data):
                        users_data.append({'url': profile_url, 'name': user_name})
                        logger.debug(f"  フォロワー追加: {user_name} ({profile_url.split('/')[-1]})")
                    elif profile_url == "N/A":
                         logger.warning(f"  フォロワーアイテム {item_idx}: プロフィールURLが取得できませんでした。スキップ。")

                except NoSuchElementException as e_nse_item:
                    logger.warning(f"フォロワーリストアイテム {item_idx} 内で必須要素が見つかりません: {e_nse_item}。スキップ。")
                except Exception as e_item:
                    logger.error(f"フォロワーアイテム {item_idx} 処理中にエラー: {e_item}", exc_info=True)

            processed_pages += 1
            logger.info(f"{processed_pages} ページ目まで処理完了。現在 {len(users_data)} 件のフォロワー情報を取得。")

            next_button = None
            for sel_idx, next_sel in enumerate(next_page_button_selector_candidates):
                try:
                    candidate_button = driver.find_element(By.CSS_SELECTOR, next_sel)
                    if candidate_button.is_displayed() and candidate_button.is_enabled():
                        next_button = candidate_button
                        logger.debug(f"「次へ」ボタンをセレクタ '{next_sel}' で発見。")
                        break
                except NoSuchElementException:
                    logger.debug(f"「次へ」ボタン候補 '{next_sel}' は見つかりませんでした。({sel_idx+1}/{len(next_page_button_selector_candidates)})")

            if next_button:
                logger.info("「次へ」ボタンをクリックします。")
                prev_url_for_transition_check = driver.current_url
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
                time.sleep(0.5)
                next_button.click()
                try:
                    WebDriverWait(driver, 15).until(
                        lambda d: d.current_url != prev_url_for_transition_check or \
                                  EC.staleness_of(user_items[0] if user_items else None) or \
                                  EC.presence_of_element_located((By.CSS_SELECTOR, f"{user_list_container_selector} > {user_list_item_selector}"))
                    )
                    logger.info(f"次のページ ({driver.current_url}) へ遷移成功。")
                    time.sleep(1.5)
                except TimeoutException:
                    logger.info("「次へ」ボタンクリック後、ページ遷移/内容更新の確認タイムアウト。最後のページかもしれません。")
                    break
            else:
                logger.info("「次へ」ボタンが見つからないか、無効です。最後のページと判断します。")
                break
        except TimeoutException:
            logger.info(f"{processed_pages + 1} ページ目のフォロワーリスト読み込みタイムアウト。")
            break
        except Exception as e_page:
            logger.error(f"フォロワーページ処理中に予期せぬエラー: {e_page}", exc_info=True)
            break

    logger.info(f"フォロワーの情報を {len(users_data)} 件取得しました。")
    return users_data


def is_user_following_me(driver, target_user_profile_url, my_user_id, my_followers_list=None):
    """
    指定されたユーザー (target_user_profile_url) が、自分 (my_user_id) をフォローしているかを確認します。
    事前に取得した自分のフォロワーリスト (my_followers_list) を提供することで、
    API/ページアクセスを減らし、効率的に確認できます。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス (フォロワーリスト未提供時に使用)。
        target_user_profile_url (str): 確認対象ユーザーのプロフィールURL。
        my_user_id (str): 自分のYAMAPユーザーID。
        my_followers_list (list[str], optional): 事前に取得した自分のフォロワーのプロフィールURLリスト。
                                                Noneの場合、この関数内でフォロワーリストを取得します。

    Returns:
        bool or None: フォローされていればTrue、されていなければFalse。確認中にエラーが発生した場合はNone。
    """
    target_user_id_log = target_user_profile_url.split('/')[-1].split('?')[0]
    logger.info(f"ユーザー ({target_user_id_log}) が自分 ({my_user_id}) をフォローしているか確認します。")

    if not my_user_id:
        logger.error("自分のユーザーIDが不明なため、フォロー状況を確認できません。")
        return None

    # target_user_profile_url から target_user_id を抽出 (正規化)
    # 例: "https://yamap.com/users/12345" -> "12345"
    # 例: "https://yamap.com/users/12345?tab=activities" -> "12345"
    normalized_target_user_id = target_user_profile_url.split('/')[-1].split('?')[0]
    normalized_target_profile_url = f"{BASE_URL}/users/{normalized_target_user_id}"


    if my_followers_list is None:
        logger.info("自分のフォロワーリストが提供されていないため、取得を試みます。")
        # ここでフォロワーリスト取得の上限をどうするか。全件取得は時間がかかる可能性がある。
        # 設定ファイルから読み込むか、ここでは限定的な件数（例：最初の数ページ）のみ取得する。
        # 今回は、ひとまず限定的に取得する方針で実装。
        # TODO: 設定でフォロワーリスト取得の範囲を指定できるようにする。
        main_conf = get_main_config()
        unfollow_settings = main_conf.get("unfollow_inactive_users_settings", {})
        max_pages_for_follower_check = unfollow_settings.get("max_pages_for_is_following_me_check", 3) # 例: 3ページまで

        my_followers_list = get_my_followers_profiles(driver, my_user_id, max_pages_to_check=max_pages_for_follower_check)
        if not my_followers_list: # 取得失敗またはフォロワー0
            logger.warning(f"自分のフォロワーリストの取得に失敗したか、フォロワーがいません。ユーザー ({target_user_id_log}) はフォローしていないと仮定します。")
            return False # フォロワーリストが空なら、誰も自分をフォローしていない

    # 自分のフォロワーリストの中に、対象ユーザーの正規化されたプロフィールURLが存在するか確認
    for follower_url in my_followers_list:
        normalized_follower_id = follower_url.split('/')[-1].split('?')[0]
        if normalized_follower_id == normalized_target_user_id:
            logger.info(f"ユーザー ({target_user_id_log}) は自分をフォローしています。")
            return True

    logger.info(f"ユーザー ({target_user_id_log}) は自分をフォローしていません（提供または取得したフォロワーリスト内に見つかりませんでした）。")
    return False

    # 代替案: 対象ユーザーの「フォロー中」リストを確認する (非常にコスト高で非推奨)
    # 1. target_user_profile_url の「フォロー中」リストページにアクセス
    # 2. そのリスト内に自分の my_user_id が含まれるか確認
    # この方法は、相手のフォロー中リストが大規模な場合に非常に時間がかかり、現実的ではない。
    # また、プライバシー設定によってはリストが公開されていない可能性もある。
    # よって、自分のフォロワーリストとの照合が現実的。
