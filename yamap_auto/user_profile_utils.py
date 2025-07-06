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

# driver_utilsから必要なものをインポート
from .driver_utils import get_main_config, BASE_URL

# --- Loggerの設定 ---
# このモジュール用のロガーを取得します。
# 基本的な設定はメインスクリプトで行われることを想定しています。
logger = logging.getLogger(__name__)

# --- ユーザープロフィール操作関連の補助関数 ---
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
