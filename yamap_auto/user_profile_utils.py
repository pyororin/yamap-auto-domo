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
from .driver_utils import get_main_config, BASE_URL, wait_for_page_transition

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
    logger.info(f"プロフィール ({user_id_log}) の最新活動日時を取得します。")

    current_page_url = driver.current_url
    if user_profile_url not in current_page_url:
        logger.debug(f"対象のユーザープロフィールページ ({user_profile_url}) に遷移します。")
        driver.get(user_profile_url)
        try:
            WebDriverWait(driver, 10).until(
                EC.any_of(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[data-testid='profile-tab-activities']")),
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h1[class*='UserProfileScreen_userName']"))
                )
            )
        except TimeoutException:
            logger.warning(f"ユーザー ({user_id_log}) のプロフィールページ主要要素の読み込みタイムアウト。最新活動日時取得失敗の可能性。")
            return None
    else:
        logger.debug(f"既にユーザープロフィールページ ({user_profile_url}) 付近にいます。")

    try:
        # 活動記録の日時情報が含まれる可能性のある要素のセレクタ
        # YAMAPのUI構造に依存するため、複数の候補を試す
        date_selectors = [
            "article[data-testid='activity-entry'] time[datetime]", # 標準的な構造
            "a[data-testid='activity-card-link'] time[datetime]",
            ".ActivityCard_card__XXXXX time[datetime]", # 古い可能性のあるクラス名
            "time.css-1vh94j7", # 実際のUIで確認されたセレクタの例 (変わりやすい)
            "div[class*='ActivityEntry_meta'] time", # メタ情報内のtime要素
        ]
        action_delays = main_conf.get("action_delays", {})
        wait_time_for_activity_date = action_delays.get("wait_for_activity_link_sec", 7) # activity_linkの待機時間を流用

        for selector in date_selectors:
            try:
                WebDriverWait(driver, wait_time_for_activity_date).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                time_element = driver.find_element(By.CSS_SELECTOR, selector)
                datetime_str = time_element.get_attribute("datetime")
                if datetime_str:
                    # ISO 8601形式 (YYYY-MM-DDTHH:MM:SSZ や YYYY-MM-DDTHH:MM:SS+09:00) を想定
                    try:
                        # タイムゾーン情報を考慮してdatetimeオブジェクトに変換
                        # ZはUTCを示す
                        if datetime_str.endswith('Z'):
                            dt_object = datetime.strptime(datetime_str[:-1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                        else:
                            # Python 3.7+ では fromisoformat が使える
                            dt_object = datetime.fromisoformat(datetime_str)

                        activity_date = dt_object.date()
                        logger.info(f"ユーザー ({user_id_log}) の最新活動日時: {activity_date} (selector: {selector}, raw: {datetime_str})")
                        return activity_date
                    except ValueError as ve:
                        logger.debug(f"日時文字列 '{datetime_str}' (selector: {selector}) のパースに失敗: {ve}。他の形式を試行します。")
                        # 単純な日付形式 (YYYY-MM-DD) や他の一般的な形式も試す (フォールバック)
                        try:
                            activity_date = datetime.strptime(datetime_str.split('T')[0], "%Y-%m-%d").date()
                            logger.info(f"ユーザー ({user_id_log}) の最新活動日時 (フォールバックパース): {activity_date} (selector: {selector}, raw: {datetime_str})")
                            return activity_date
                        except ValueError:
                            continue # 次のセレクタへ
                else: # datetime属性がない場合、テキストから抽出を試みる (限定的)
                    date_text = time_element.text.strip()
                    # "YYYY年MM月DD日" や "MM月DD日" (当年と仮定) などの形式に対応 (必要に応じて拡張)
                    try:
                        if "年" in date_text and "月" in date_text and "日" in date_text:
                            dt_object = datetime.strptime(date_text, "%Y年%m月%d日")
                            activity_date = dt_object.date()
                            logger.info(f"ユーザー ({user_id_log}) の最新活動日時 (テキストパース): {activity_date} (selector: {selector}, text: {date_text})")
                            return activity_date
                        # 他のテキスト形式のパースロジックを追加可能
                    except ValueError:
                        logger.debug(f"日時テキスト '{date_text}' (selector: {selector}) のパースに失敗。")
                        continue

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
    自分の「フォロー中」リストページから、フォローしているユーザーのプロフィールURLのリストを取得します。
    ページネーションに対応し、指定された最大ユーザー数または最大ページ数まで取得します。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        my_user_id (str): 自分のYAMAPユーザーID。
        max_users_to_fetch (int, optional): 取得する最大のユーザープロファイル数。Noneの場合は制限なし。
        max_pages_to_check (int, optional): 確認する最大のページ数。Noneの場合は全ページ。

    Returns:
        list[str]: フォロー中ユーザーのプロフィールURLのリスト。
    """
    if not my_user_id:
        logger.error("自分のユーザーIDが指定されていないため、フォロー中ユーザーリストを取得できません。")
        return []

    following_list_url = f"{BASE_URL}/users/{my_user_id}?tab=follows#tabs" # URL形式を修正
    logger.info(f"自分のフォロー中ユーザーリスト ({following_list_url}) からプロフィールURLを取得します。")
    logger.info(f"取得上限: ユーザー数={max_users_to_fetch or '無制限'}, ページ数={max_pages_to_check or '無制限'}")

    # ユーザーリストアイテムとユーザーリンクのセレクタ (YAMAPのUIに依存)
    user_list_item_selector = "main.css-1ed9ptx ul.UserFollowList__List > li.UserFollowList__Item" # より具体的に修正
    user_profile_link_selector = "div.UserItem a[href^='/users/']" # 変更なし（li要素の中から探すため）
    # 「次へ」ボタンのセレクタ (YAMAPのUIに依存)
    next_page_button_selector = "button.btn-next" # 変更なし

    current_url_before_get = driver.current_url
    driver.get(following_list_url)
    # ページ遷移とリスト表示の待機 (main要素内の ul.UserFollowList__List の出現を期待)
    wait_for_page_transition(driver, timeout=30, expected_element_selector=(By.CSS_SELECTOR, "main.css-1ed9ptx ul.UserFollowList__List"), previous_url=current_url_before_get if current_url_before_get != following_list_url else None)


    user_profile_urls = []
    processed_pages = 0

    while True:
        if max_pages_to_check is not None and processed_pages >= max_pages_to_check:
            logger.info(f"最大確認ページ数 ({max_pages_to_check}) に達したため、処理を終了します。")
            break
        if max_users_to_fetch is not None and len(user_profile_urls) >= max_users_to_fetch:
            logger.info(f"最大取得ユーザー数 ({max_users_to_fetch}) に達したため、処理を終了します。")
            break

        logger.info(f"フォロー中リストの {processed_pages + 1} ページ目を処理中...")
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, user_list_item_selector))
            )
            user_items = driver.find_elements(By.CSS_SELECTOR, user_list_item_selector)
            if not user_items:
                logger.info(f"{processed_pages + 1} ページ目にユーザーが見つかりませんでした。")
                break # ユーザーがいないなら終了

            for item in user_items:
                if max_users_to_fetch is not None and len(user_profile_urls) >= max_users_to_fetch:
                    break
                try:
                    profile_link_element = item.find_element(By.CSS_SELECTOR, user_profile_link_selector)
                    href = profile_link_element.get_attribute('href')
                    if href and "/users/" in href:
                        full_url = href if href.startswith(BASE_URL) else BASE_URL + href
                        if full_url not in user_profile_urls: # 重複を避ける
                            user_profile_urls.append(full_url)
                            logger.debug(f"  追加: {full_url.split('/')[-1]}")
                except NoSuchElementException:
                    logger.warning("ユーザーリストアイテム内でプロフィールリンクが見つかりませんでした。スキップします。")
                except Exception as e_item:
                    logger.error(f"ユーザーアイテム処理中にエラー: {e_item}", exc_info=True)

            processed_pages += 1
            logger.info(f"{processed_pages} ページ目まで処理完了。現在 {len(user_profile_urls)} 件のURLを取得。")

            # 次のページへ
            try:
                next_button = driver.find_element(By.CSS_SELECTOR, next_page_button_selector)
                if next_button.is_displayed() and next_button.is_enabled():
                    logger.info("「次へ」ボタンをクリックします。")
                    prev_url = driver.current_url
                    driver.execute_script("arguments[0].scrollIntoView(true);", next_button)
                    time.sleep(0.5) # スクロール後の安定待ち
                    next_button.click()
                    # ページ遷移待機 (URL変更とリストアイテムの出現を期待)
                    wait_for_page_transition(driver, timeout=10, expected_element_selector=(By.CSS_SELECTOR, user_list_item_selector), previous_url=prev_url)
                    time.sleep(1) # 追加の安定待ち
                else:
                    logger.info("「次へ」ボタンが見つからないか、無効です。最後のページと判断します。")
                    break
            except NoSuchElementException:
                logger.info("「次へ」ボタンが見つかりませんでした。最後のページと判断します。")
                break
            except Exception as e_pagination:
                logger.error(f"ページネーション処理中にエラー: {e_pagination}", exc_info=True)
                break

        except TimeoutException:
            logger.info(f"{processed_pages + 1} ページ目のユーザーリスト読み込みタイムアウト。処理を終了します。")
            break
        except Exception as e_page:
            logger.error(f"ページ処理中に予期せぬエラー: {e_page}", exc_info=True)
            break

    logger.info(f"フォロー中ユーザーのプロフィールURLを {len(user_profile_urls)} 件取得しました。")
    return user_profile_urls


def get_my_followers_profiles(driver, my_user_id, max_users_to_fetch=None, max_pages_to_check=None):
    """
    自分の「フォロワー」リストページから、自分をフォローしているユーザーのプロフィールURLのリストを取得します。
    get_my_following_users_profiles とほぼ同じロジックですが、対象URLが異なります。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        my_user_id (str): 自分のYAMAPユーザーID。
        max_users_to_fetch (int, optional): 取得する最大のユーザープロファイル数。Noneの場合は制限なし。
        max_pages_to_check (int, optional): 確認する最大のページ数。Noneの場合は全ページ。

    Returns:
        list[str]: フォロワーのプロフィールURLのリスト。
    """
    if not my_user_id:
        logger.error("自分のユーザーIDが指定されていないため、フォロワーリストを取得できません。")
        return []

    followers_list_url = f"{BASE_URL}/users/{my_user_id}?tab=followers#tabs" # URL形式を修正
    logger.info(f"自分のフォロワーリスト ({followers_list_url}) からプロフィールURLを取得します。")
    logger.info(f"取得上限: ユーザー数={max_users_to_fetch or '無制限'}, ページ数={max_pages_to_check or '無制限'}")

    # ユーザーリストアイテムとユーザーリンクのセレクタ (YAMAPのUIに依存)
    user_list_item_selector = "main.css-1ed9ptx ul.UserFollowList__List > li.UserFollowList__Item" # より具体的に修正
    user_profile_link_selector = "div.UserItem a[href^='/users/']" # 変更なし
    next_page_button_selector = "button.btn-next" # 変更なし

    # 以降のロジックは get_my_following_users_profiles とほぼ同じ
    current_url_before_get = driver.current_url
    driver.get(followers_list_url)
    # ページ遷移とリスト表示の待機 (main要素内の ul.UserFollowList__List の出現を期待)
    wait_for_page_transition(driver, timeout=30, expected_element_selector=(By.CSS_SELECTOR, "main.css-1ed9ptx ul.UserFollowList__List"), previous_url=current_url_before_get if current_url_before_get != followers_list_url else None)

    user_profile_urls = []
    processed_pages = 0

    while True:
        if max_pages_to_check is not None and processed_pages >= max_pages_to_check:
            logger.info(f"最大確認ページ数 ({max_pages_to_check}) に達したため、処理を終了します。")
            break
        if max_users_to_fetch is not None and len(user_profile_urls) >= max_users_to_fetch:
            logger.info(f"最大取得ユーザー数 ({max_users_to_fetch}) に達したため、処理を終了します。")
            break

        logger.info(f"フォロワーリストの {processed_pages + 1} ページ目を処理中...")
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, user_list_item_selector))
            )
            user_items = driver.find_elements(By.CSS_SELECTOR, user_list_item_selector)
            if not user_items:
                logger.info(f"{processed_pages + 1} ページ目にユーザーが見つかりませんでした。")
                break

            for item in user_items:
                if max_users_to_fetch is not None and len(user_profile_urls) >= max_users_to_fetch:
                    break
                try:
                    profile_link_element = item.find_element(By.CSS_SELECTOR, user_profile_link_selector)
                    href = profile_link_element.get_attribute('href')
                    if href and "/users/" in href:
                        full_url = href if href.startswith(BASE_URL) else BASE_URL + href
                        if full_url not in user_profile_urls:
                            user_profile_urls.append(full_url)
                            logger.debug(f"  追加: {full_url.split('/')[-1]}")
                except NoSuchElementException:
                    logger.warning("ユーザーリストアイテム内でプロフィールリンクが見つかりませんでした。スキップします。")
                except Exception as e_item:
                    logger.error(f"ユーザーアイテム処理中にエラー: {e_item}", exc_info=True)

            processed_pages += 1
            logger.info(f"{processed_pages} ページ目まで処理完了。現在 {len(user_profile_urls)} 件のURLを取得。")

            try:
                next_button = driver.find_element(By.CSS_SELECTOR, next_page_button_selector)
                if next_button.is_displayed() and next_button.is_enabled():
                    logger.info("「次へ」ボタンをクリックします。")
                    prev_url = driver.current_url
                    driver.execute_script("arguments[0].scrollIntoView(true);", next_button)
                    time.sleep(0.5)
                    next_button.click()
                    wait_for_page_transition(driver, timeout=10, expected_element_selector=(By.CSS_SELECTOR, user_list_item_selector), previous_url=prev_url)
                    time.sleep(1)
                else:
                    logger.info("「次へ」ボタンが見つからないか、無効です。最後のページと判断します。")
                    break
            except NoSuchElementException:
                logger.info("「次へ」ボタンが見つかりませんでした。最後のページと判断します。")
                break
            except Exception as e_pagination:
                logger.error(f"ページネーション処理中にエラー: {e_pagination}", exc_info=True)
                break
        except TimeoutException:
            logger.info(f"{processed_pages + 1} ページ目のユーザーリスト読み込みタイムアウト。処理を終了します。")
            break
        except Exception as e_page:
            logger.error(f"ページ処理中に予期せぬエラー: {e_page}", exc_info=True)
            break

    logger.info(f"フォロワーのプロフィールURLを {len(user_profile_urls)} 件取得しました。")
    return user_profile_urls


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
