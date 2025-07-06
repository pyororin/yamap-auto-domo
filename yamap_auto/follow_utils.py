# coding: utf-8
"""
YAMAP フォロー関連ユーティリティ関数群
主にリストアイテム内やプロフィールページでのフォロー操作を担当
"""
import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from .driver_utils import get_main_config
# user_profile_utils から必要な関数をインポート
from .user_profile_utils import (
    get_latest_activity_url,
    get_user_follow_counts,
    find_follow_button_on_profile_page
)
# domo_utils から domo_activity をインポート
from .domo_utils import domo_activity

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time # time モジュールをインポート

logger = logging.getLogger(__name__)

# --- グローバル定数 ---
BASE_URL = "https://yamap.com" # yamap_auto_domo.py から移動
SEARCH_ACTIVITIES_URL_DEFAULT = f"{BASE_URL}/search/activities" # yamap_auto_domo.py から移動

# --- 設定情報の読み込み ---
try:
    main_config = get_main_config()
    if not main_config:
        logger.error("follow_utils: main_config の読み込みに失敗しました。")
        main_config = {}

    # フォロー関連の設定セクションを読み込む
    FOLLOW_BACK_SETTINGS = main_config.get("follow_back_settings", {})
    SEARCH_AND_FOLLOW_SETTINGS = main_config.get("search_and_follow_settings", {})
    # action_delays は main_config 直下にある想定
    ACTION_DELAYS = main_config.get("action_delays", {})


    if not FOLLOW_BACK_SETTINGS:
        logger.warning("follow_utils: config.yaml に follow_back_settings が見つからないか空です。")
    if not SEARCH_AND_FOLLOW_SETTINGS:
        logger.warning("follow_utils: config.yaml に search_and_follow_settings が見つからないか空です。")

except Exception as e:
    logger.error(f"follow_utils: 設定情報 (main_config) の読み込み中にエラー: {e}", exc_info=True)
    main_config = {} # エラー発生時は空の辞書でフォールバック
    FOLLOW_BACK_SETTINGS = {}
    SEARCH_AND_FOLLOW_SETTINGS = {}
    ACTION_DELAYS = {}


def find_follow_button_in_list_item(user_list_item_element):
    """
    ユーザーリストアイテム要素（例: フォロワー一覧の各ユーザー項目）内から
    「フォローする」ボタンを探します。
    既に「フォロー中」である場合や、クリック可能な「フォローする」ボタンがない場合はNoneを返します。

    Args:
        user_list_item_element (WebElement): 対象のユーザーリストアイテムのSelenium WebElement。

    Returns:
        WebElement or None: 「フォローする」ボタンのWebElement。見つからない場合はNone。
    """
    try:
        # 1. 「フォロー中」ボタンの確認 (aria-pressed='true' が主な指標)
        try:
            following_button = user_list_item_element.find_element(By.CSS_SELECTOR, "button[aria-pressed='true']")
            if following_button and following_button.is_displayed():
                button_text = following_button.text.strip()
                span_text = ""
                try:
                    span_elements = following_button.find_elements(By.CSS_SELECTOR, "span")
                    if span_elements:
                        span_text = " ".join(s.text.strip() for s in span_elements if s.text.strip())
                except: pass

                if "フォロー中" in button_text or "フォロー中" in span_text:
                    logger.debug("リストアイテム内で「フォロー中」ボタンを発見 (aria-pressed='true' + テキスト)。既にフォロー済みと判断。")
                    return None
                else:
                    logger.debug(f"aria-pressed='true' ボタン発見もテキスト不一致 (Button: '{button_text}', Span: '{span_text}')。フォロー済みと判断。")
                    return None
        except NoSuchElementException:
            logger.debug("リストアイテム内に aria-pressed='true' の「フォロー中」ボタンは見つかりませんでした。フォロー可能かもしれません。")
        except Exception as e_text_check:
             logger.debug(f"aria-pressed='true' ボタンのテキスト確認中にエラー: {e_text_check}。フォロー済みと仮定。")
             return None

        # 2. 「フォローする」ボタンの探索
        try:
            potential_follow_buttons = user_list_item_element.find_elements(By.CSS_SELECTOR, "button[aria-pressed='false']")
            if potential_follow_buttons:
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
                            logger.debug("リストアイテム内で「フォローする」ボタンを発見 (aria-pressed='false' + テキスト)。")
                            return button_candidate
            else:
                logger.debug("リストアイテム内に aria-pressed='false' のボタン候補は見つかりませんでした。")
        except NoSuchElementException:
            logger.debug("リストアイテム内で aria-pressed='false' のボタン探索でエラー（通常発生しない）。")

        try:
            follow_button_xpath_str = ".//button[normalize-space(.)='フォローする']"
            button_by_text = user_list_item_element.find_element(By.XPATH, follow_button_xpath_str)
            if button_by_text and button_by_text.is_displayed() and button_by_text.is_enabled():
                logger.debug(f"リストアイテム内で「フォローする」ボタンをテキストで発見 (XPath: {follow_button_xpath_str})。")
                return button_by_text
        except NoSuchElementException:
            logger.debug(f"リストアイテム内でテキスト「フォローする」でのボタン発見試行失敗 (XPath)。")

        try:
            follow_button_aria_label = user_list_item_element.find_element(By.CSS_SELECTOR, "button[aria-label*='フォローする']")
            if follow_button_aria_label and follow_button_aria_label.is_displayed() and follow_button_aria_label.is_enabled():
                 logger.debug(f"リストアイテム内で「フォローする」ボタンをaria-labelで発見。")
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
    指定された「フォローする」ボタンをクリックし、ボタンの状態が「フォロー中」に変わったことを確認します。
    状態変化の確認は、ボタンの data-testid, aria-label, またはテキストの変更を監視します。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        follow_button_element (WebElement): クリック対象の「フォローする」ボタンのWebElement。
        user_name_for_log (str, optional): ログ出力用のユーザー名。

    Returns:
        bool: フォローに成功し、状態変化も確認できた場合はTrue。それ以外はFalse。
    """
    try:
        logger.info(f"ユーザー「{user_name_for_log}」のフォローボタンをクリックします...")

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", follow_button_element)
        time.sleep(0.1)
        follow_button_element.click()

        action_delays = main_config.get("action_delays", {}) # ACTION_DELAYS グローバル変数を使うように変更も検討
        delay_after_action = action_delays.get("after_follow_action_sec", 2.0)

        WebDriverWait(driver, 10).until(
            lambda d: (
                (follow_button_element.get_attribute("data-testid") == "FollowingButton") or
                ("フォロー中" in (follow_button_element.get_attribute("aria-label") or "")) or
                ("フォロー中" in follow_button_element.text) or
                (not follow_button_element.is_displayed()) # ボタンが消える場合も成功とみなす
            )
        )

        final_testid = follow_button_element.get_attribute("data-testid")
        final_aria_label = follow_button_element.get_attribute("aria-label")
        final_text = ""
        try:
            # 要素が非表示になった場合 text プロパティアクセスでエラーになるため try-except
            if follow_button_element.is_displayed():
                final_text = follow_button_element.text
        except: pass

        if final_testid == "FollowingButton" or \
           (final_aria_label and "フォロー中" in final_aria_label) or \
           (final_text and "フォロー中" in final_text) or \
           (not follow_button_element.is_displayed()): # 非表示も成功条件に含める
            logger.info(f"ユーザー「{user_name_for_log}」をフォローしました。状態: testid='{final_testid}', label='{final_aria_label}', text='{final_text}', displayed={follow_button_element.is_displayed() if final_testid != 'FollowingButton' else 'N/A (likely changed)'}")
            time.sleep(delay_after_action)
            return True
        else:
            logger.warning(f"フォローボタンクリック後、状態変化が期待通りではありません (ユーザー「{user_name_for_log}」)。状態: testid='{final_testid}', label='{final_aria_label}', text='{final_text}'")
            return False
    except TimeoutException:
        logger.warning(f"フォロー後の状態変化待機中にタイムアウト (ユーザー: {user_name_for_log})。")
        # フォロー自体は成功している可能性もあるが、確認できないためFalse
        return False
    except Exception as e: # StaleElementReferenceExceptionなどもキャッチ
        logger.error(f"フォローボタンクリックまたは確認中にエラー (ユーザー: {user_name_for_log})", exc_info=True)
        return False


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
    # delay_pagination は ACTION_DELAYS から取得するよう変更
    delay_pagination = ACTION_DELAYS.get("delay_after_pagination_sec", 3.0)


    total_followed_count = 0
    total_domoed_count = 0
    # processed_users_on_current_page はページループ内で初期化する

    # 活動記録検索結果ページからユーザープロフィールへの典型的なパスを想定
    activity_card_selector = "article[data-testid='activity-entry']"
    user_profile_link_in_card_selector = "div.css-1vh31zw > a.css-k2fvpp[href^='/users/']"

    processed_profile_urls = set() # セッション内で同じユーザーを何度も処理しないため

    for page_num in range(1, max_pages + 1):
        processed_users_on_current_page = 0 # 各ページの開始時にリセット
        current_page_url_before_action = driver.current_url # ページ遷移の確認用

        if page_num > 1: # 2ページ目以降はページネーションが必要
            logger.info(f"{page_num-1}ページ目の処理完了。次のページ ({page_num}ページ目) へ遷移を試みます。")

            next_button_selectors = [
                "a[data-testid='pagination-next-button']",
                "a[rel='next']",
                "a.next", "a.pagination__next", "button.next", "button.pagination__next",
                "a[aria-label*='次へ']:not([aria-disabled='true'])",
                "a[aria-label*='Next']:not([aria-disabled='true'])",
                "button[aria-label*='次へ']:not([disabled])",
                "button[aria-label*='Next']:not([disabled])"
            ]

            next_button_found = False
            for selector in next_button_selectors:
                try:
                    logger.debug(f"次のページボタン探索試行 (セレクタ: {selector})")
                    next_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    if next_button.is_displayed() and next_button.is_enabled():
                        logger.info(f"次のページボタンをセレクタ '{selector}' で発見。クリックします。")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
                        time.sleep(0.5)
                        next_button.click()
                        next_button_found = True
                        break
                    else:
                        logger.debug(f"セレクタ '{selector}' でボタンは存在したが、表示されていないか無効でした。")
                except TimeoutException:
                    logger.debug(f"セレクタ '{selector}' で次のページボタンが見つからずタイムアウト。")
                except Exception as e_click:
                    logger.warning(f"セレクタ '{selector}' でボタンクリック試行中にエラー: {e_click}")

            if not next_button_found:
                logger.info("試行した全てのセレクタで、クリック可能な「次へ」ボタンが見つかりませんでした。検索結果のページネーション処理を終了します。")
                break

            try:
                WebDriverWait(driver, 10).until(
                    EC.url_changes(current_page_url_before_action)
                )
                logger.info(f"{page_num}ページ目へ遷移しました。新しいURL: {driver.current_url}")
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector))
                )
                logger.info(f"{page_num}ページ目の活動記録カードの読み込みを確認。")
                time.sleep(delay_pagination) # ACTION_DELAYSから取得した値を使用
            except TimeoutException:
                logger.warning(f"{page_num}ページ目への遷移後、URL変化または活動記録カードの読み込みタイムアウト。処理を終了します。")
                break
            except Exception as e_page_load:
                logger.error(f"{page_num}ページ目への遷移または読み込み中に予期せぬエラー: {e_page_load}", exc_info=True)
                break

        if page_num == 1 and driver.current_url != start_url :
             logger.info(f"{page_num}ページ目の活動記録検索結果 ({start_url}) にアクセスします。")
             driver.get(start_url)

        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, activity_card_selector))
            )
        except TimeoutException:
            # 1ページ目の読み込みの場合、current_url_to_loadは定義されていないのでstart_urlを参照
            page_identifier_for_log = start_url if page_num == 1 else driver.current_url
            logger.warning(f"活動記録検索結果ページ ({page_identifier_for_log}) で活動記録カードの読み込みタイムアウト。このページの処理をスキップします。")
            continue

        initial_activity_cards_on_page = driver.find_elements(By.CSS_SELECTOR, activity_card_selector)
        num_cards_to_process = len(initial_activity_cards_on_page)
        logger.info(f"{page_num}ページ目: {num_cards_to_process} 件の活動記録候補を検出。")

        if not initial_activity_cards_on_page:
            logger.info("このページには活動記録が見つかりませんでした。")
            continue

        for card_idx in range(num_cards_to_process):
            if processed_users_on_current_page >= max_users_per_page:
                logger.info(f"このページでの処理上限 ({max_users_per_page}ユーザー) に達しました。")
                break

            user_profile_url = None
            user_name_for_log = f"活動記録{card_idx+1}のユーザー"

            try:
                current_activity_cards = driver.find_elements(By.CSS_SELECTOR, activity_card_selector)
                if card_idx >= len(current_activity_cards):
                    logger.warning(f"カードインデックス {card_idx} が現在のカード数 {len(current_activity_cards)} を超えています。DOM構造が変更された可能性があります。このカードの処理をスキップします。")
                    continue
                card_element = current_activity_cards[card_idx]

                profile_link_el = WebDriverWait(card_element, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, user_profile_link_in_card_selector))
                )
                href = profile_link_el.get_attribute("href")
                if href:
                    if href.startswith("/"): user_profile_url = BASE_URL + href
                    elif href.startswith(BASE_URL): user_profile_url = href

                if not user_profile_url or f"/users/{current_user_id}" in user_profile_url:
                    logger.debug(f"無効なプロフィールURLか自分自身 ({user_profile_url}) のためスキップ。")
                    continue

                if user_profile_url in processed_profile_urls:
                    logger.info(f"ユーザー ({user_profile_url.split('/')[-1]}) は既に処理済みのためスキップ。")
                    continue

                try:
                    name_el = profile_link_el.find_element(By.CSS_SELECTOR, "span, img[alt]")
                    if name_el.tag_name == "img": user_name_for_log = name_el.get_attribute("alt")
                    else: user_name_for_log = name_el.text.strip()
                    if not user_name_for_log: user_name_for_log = user_profile_url.split('/')[-1]
                except: pass

                logger.info(f"--- ユーザー「{user_name_for_log}」(URL: {user_profile_url.split('/')[-1]}) の処理開始 ---")
                processed_profile_urls.add(user_profile_url)

                search_page_url_before_profile_visit = driver.current_url
                driver.get(user_profile_url)
                try:
                    WebDriverWait(driver, 20).until(
                        EC.all_of(
                            EC.url_contains(user_profile_url.split('/')[-1]),
                            EC.visibility_of_element_located((By.CSS_SELECTOR, "h1.css-jctfiw")),
                            lambda d: d.execute_script("return document.readyState") == "complete",
                            EC.presence_of_element_located((By.CSS_SELECTOR, "footer.css-1yg0z07"))
                        )
                    )
                    logger.debug(f"ユーザープロフィールページ ({user_profile_url}) の主要コンテンツ読み込み完了を確認。")
                except TimeoutException:
                    logger.warning(f"ユーザープロフィールページ ({user_profile_url}) の読み込みタイムアウト（複合条件）。このユーザーの処理をスキップします。")
                    driver.get(search_page_url_before_profile_visit)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    continue

                if user_profile_url not in driver.current_url: # 念のため再確認
                    logger.error(f"URL不一致: プロフィールページ ({user_profile_url}) にいるはずが、現在のURLは {driver.current_url} です。スキップします。")
                    driver.get(search_page_url_before_profile_visit)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    continue


                follow_button_on_profile = find_follow_button_on_profile_page(driver)
                if not follow_button_on_profile:
                    logger.info(f"ユーザー「{user_name_for_log}」は既にフォロー済みか、プロフィールにフォローボタンがありません。スキップ。")
                    driver.get(search_page_url_before_profile_visit)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    continue

                follows, followers = get_user_follow_counts(driver, user_profile_url)
                if follows == -1 or followers == -1:
                    logger.warning(f"ユーザー「{user_name_for_log}」のフォロー数/フォロワー数が取得できませんでした。スキップ。")
                    driver.get(search_page_url_before_profile_visit)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    continue

                if followers < min_followers:
                    logger.info(f"ユーザー「{user_name_for_log}」のフォロワー数 ({followers}) が閾値 ({min_followers}) 未満。スキップ。")
                    driver.get(search_page_url_before_profile_visit)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    continue

                current_ratio = (follows / followers) if followers > 0 else float('inf')
                logger.info(f"ユーザー「{user_name_for_log}」: F中={follows}, Fワー={followers}, Ratio={current_ratio:.2f} (閾値: >= {ratio_threshold})")

                if not (current_ratio >= ratio_threshold):
                    logger.info(f"Ratio ({current_ratio:.2f}) が閾値 ({ratio_threshold}) 未満です。スキップ。")
                    driver.get(search_page_url_before_profile_visit)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    continue

                logger.info(f"フォロー条件（Ratio >= {ratio_threshold}）を満たしました。ユーザー「{user_name_for_log}」をフォローします。")
                if click_follow_button_and_verify(driver, follow_button_on_profile, user_name_for_log):
                    total_followed_count += 1
                    if domo_after_follow:
                        logger.info(f"ユーザー「{user_name_for_log}」の最新活動記録にDOMOを試みます。")
                        latest_act_url = get_latest_activity_url(driver, user_profile_url)
                        if latest_act_url:
                            if domo_activity(driver, latest_act_url, BASE_URL):
                                total_domoed_count += 1
                        else:
                            logger.info(f"ユーザー「{user_name_for_log}」の最新活動記録が見つからず、DOMOできませんでした。")

                processed_users_on_current_page += 1
                logger.info(f"--- ユーザー「{user_name_for_log}」の処理終了 ---")

                logger.debug(f"ユーザー処理後、検索結果ページ ({search_page_url_before_profile_visit}) に戻ります。")
                driver.get(search_page_url_before_profile_visit)
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector))
                    )
                except TimeoutException:
                    logger.warning(f"検索結果ページ ({search_page_url_before_profile_visit}) に戻った後、活動記録カードの再表示タイムアウト。")
                time.sleep(delay_user_processing)

            except NoSuchElementException:
                logger.warning(f"活動記録カード {card_idx+1} からユーザー情報取得に必要な要素が見つかりません。スキップ。")
            except Exception as e_user_proc:
                logger.error(f"ユーザー「{user_name_for_log}」の処理中にエラー: {e_user_proc}", exc_info=True)
                try:
                    current_search_url_for_recovery = start_url if page_num == 1 else driver.current_url # 現在のページURLかスタートURL
                    if driver.current_url != current_search_url_for_recovery: # URLが変わってしまっていたら
                         driver.get(current_search_url_for_recovery)
                         WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                except Exception as e_recover:
                     logger.error(f"エラー後の検索ページ復帰試行中にもエラー: {e_recover}")

        logger.info(f"{page_num}ページ目の処理が完了しました。")

    logger.info(f"<<< 検索からのフォロー＆DOMO機能完了。合計フォロー: {total_followed_count}人, 合計DOMO: {total_domoed_count}件。")


# --- フォローバック機能 ---
def follow_back_users_new(driver, current_user_id):
    """
    自分をフォローしてくれたユーザーをフォローバックする機能。
    config.yaml の follow_back_settings に従って動作する。
    ページネーションに対応し、複数のフォロワーページを確認する。
    """
    if not FOLLOW_BACK_SETTINGS.get("enable_follow_back", False):
        logger.info("フォローバック機能は設定で無効になっています。")
        return

    logger.info(">>> フォローバック機能を開始します...")
    base_followers_url = f"{BASE_URL}/users/{current_user_id}?tab=followers"
    current_page_number = 1

    logger.info(f"フォロワー一覧の初期ページへアクセス: {base_followers_url}#tabs")
    driver.get(base_followers_url + "#tabs")

    max_to_follow_back_total = FOLLOW_BACK_SETTINGS.get("max_users_to_follow_back", 10)
    max_pages_to_check = FOLLOW_BACK_SETTINGS.get("max_pages_for_follow_back", 100)
    delay_between_actions = FOLLOW_BACK_SETTINGS.get("delay_after_follow_back_action_sec", 3.0)
    # delay_after_pagination は ACTION_DELAYS から取得
    delay_after_pagination_fb = ACTION_DELAYS.get("delay_after_pagination_sec", 3.0)


    total_followed_this_session = 0
    processed_profile_urls_this_session = set()

    followers_list_container_selector = "ul.css-18aka15"
    user_card_selector = "div[data-testid='user']"
    user_link_in_card_selector = "a.css-e5vv35[href^='/users/']"
    next_button_selectors = [
        "a[data-testid='pagination-next-button']", "a[rel='next']", "a.next",
        "a.pagination__next", "button.next", "button.pagination__next",
        "a[aria-label*='次へ']:not([aria-disabled='true'])", "a[aria-label*='Next']:not([aria-disabled='true'])",
        "button[aria-label*='次へ']:not([disabled])", "button[aria-label*='Next']:not([disabled])"
    ]

    while current_page_number <= max_pages_to_check:
        logger.info(f"フォロワーリストの {current_page_number} ページ目を処理します。")
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, followers_list_container_selector))
            )
            logger.info("フォロワーリストのコンテナを発見。")
            time.sleep(1.0)

            user_cards_all_on_page = driver.find_elements(By.CSS_SELECTOR, user_card_selector)
            logger.info(f"{current_page_number} ページ目から {len(user_cards_all_on_page)} 件のユーザーカード候補を検出しました。")

            user_cards_to_process_this_page = user_cards_all_on_page
            if current_page_number == 1 and len(user_cards_all_on_page) > 3:
                user_cards_to_process_this_page = user_cards_all_on_page[3:]
                logger.info(f"最初の3件（レコメンドと仮定）を除いた {len(user_cards_to_process_this_page)} 件のフォロワー候補を処理対象とします。")

            if not user_cards_to_process_this_page:
                logger.info(f"{current_page_number} ページ目には処理対象となるフォロワーが見つかりませんでした。")

            for card_idx, user_card_element in enumerate(user_cards_to_process_this_page):
                if total_followed_this_session >= max_to_follow_back_total:
                    logger.info(f"セッション中のフォローバック上限 ({max_to_follow_back_total}人) に達しました。")
                    break

                user_name = f"ユーザー{card_idx+1} (Page {current_page_number})"
                profile_url = ""
                try:
                    user_link_element = user_card_element.find_element(By.CSS_SELECTOR, user_link_in_card_selector)
                    profile_url = user_link_element.get_attribute("href")
                    name_el_candidates = user_link_element.find_elements(By.CSS_SELECTOR, "h2, span[class*='UserListItem_name__']")
                    for name_el in name_el_candidates:
                        if name_el.text.strip():
                            user_name = name_el.text.strip(); break
                    if not profile_url: logger.warning(f"カード {card_idx+1} からURL取得失敗。スキップ。"); continue
                    if profile_url.startswith("/"): profile_url = BASE_URL + profile_url
                    if f"/users/{current_user_id}" in profile_url or not profile_url.startswith(f"{BASE_URL}/users/"):
                        logger.debug(f"スキップ: 自分自身または無効URL ({profile_url})"); continue
                    if profile_url in processed_profile_urls_this_session:
                        logger.info(f"「{user_name}」({profile_url.split('/')[-1]}) は処理済み。スキップ。"); continue
                except NoSuchElementException: logger.warning(f"カード {card_idx+1} 必須要素なし。スキップ。"); continue
                except Exception as e_card_parse: logger.warning(f"カード {card_idx+1} 解析エラー: {e_card_parse}。スキップ。"); continue

                processed_profile_urls_this_session.add(profile_url)
                logger.info(f"フォロワー「{user_name}」(URL: {profile_url.split('/')[-1]}) のフォロー状態確認中...")
                follow_button = find_follow_button_in_list_item(user_card_element)

                if follow_button:
                    logger.info(f"ユーザー「{user_name}」はまだフォローしていません。フォローバックを試みます。")
                    if click_follow_button_and_verify(driver, follow_button, user_name):
                        total_followed_this_session += 1
                    time.sleep(delay_between_actions)
                else:
                    logger.info(f"ユーザー「{user_name}」は既にフォロー済みか、フォローボタンなし。スキップ。")
                    time.sleep(0.5)

            if total_followed_this_session >= max_to_follow_back_total:
                logger.info("セッション中のフォローバック上限に達したため、ページネーションを停止します。")
                break

            next_button_found_on_page = False
            current_url_before_pagination = driver.current_url
            logger.info("現在のページのフォロワー処理完了。「次へ」ボタンを探します...")
            for selector_idx, selector in enumerate(next_button_selectors):
                try:
                    next_button = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                    if next_button.is_displayed() and next_button.is_enabled():
                        logger.info(f"「次へ」ボタンをセレクタ '{selector}' で発見。クリックします。")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
                        time.sleep(0.5); next_button.click(); next_button_found_on_page = True; break
                except TimeoutException: logger.debug(f"セレクタ '{selector}' で「次へ」見つからず ({selector_idx+1}/{len(next_button_selectors)}).")
                except Exception as e_click_next: logger.warning(f"セレクタ '{selector}' で「次へ」クリックエラー: {e_click_next}")

            if not next_button_found_on_page: logger.info("「次へ」ボタンなし。最終ページと判断。"); break

            try:
                WebDriverWait(driver, 15).until(EC.url_changes(current_url_before_pagination))
                logger.info(f"次のフォロワーページ ({driver.current_url}) へ遷移成功。")
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, followers_list_container_selector)))
                time.sleep(delay_after_pagination_fb) # ACTION_DELAYSから取得した値
            except TimeoutException: logger.warning("「次へ」後、ページ遷移/再表示タイムアウト。停止します。"); break
            current_page_number += 1
        except TimeoutException: logger.warning(f"{current_page_number} ページ目読み込みタイムアウト。"); break
        except Exception as e_page_process: logger.error(f"{current_page_number} ページ目処理中エラー: {e_page_process}", exc_info=True); break
    logger.info(f"<<< フォローバック機能完了。合計 {total_followed_this_session} 人をフォローバックしました。")
