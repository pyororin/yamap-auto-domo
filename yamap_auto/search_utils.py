# coding: utf-8
"""
YAMAP 検索関連ユーティリティ関数群
活動記録検索ページからのユーザー発見、フォロー、DOMO操作を担当
"""
import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# .driver_utils から main_config の読み込み関数をインポート
from .driver_utils import get_main_config
# .user_profile_utils から必要な関数をインポート
from .user_profile_utils import (
    get_latest_activity_url,
    get_user_follow_counts,
    find_follow_button_on_profile_page
)
# .domo_utils から domo_activity をインポート
from .domo_utils import domo_activity
# .follow_utils から click_follow_button_and_verify をインポート
# (find_follow_button_in_list_item は検索結果ページでは直接使わないが、
#  click_follow_button_and_verify が依存している可能性があるため、
#  もしそうなら follow_utils 側でよしなに解決されている想定。
#  ここでは search_follow_and_domo_users が直接依存するものを中心に記述)
from .follow_utils import click_follow_button_and_verify


logger = logging.getLogger(__name__)

# --- グローバル定数 ---
BASE_URL = "https://yamap.com"
SEARCH_ACTIVITIES_URL_DEFAULT = f"{BASE_URL}/search/activities"

# --- 設定情報の読み込み ---
try:
    main_config = get_main_config()
    if not main_config:
        logger.error("search_utils: main_config の読み込みに失敗しました。")
        # main_config がないと後続の処理でエラーになるため、空の辞書で初期化
        main_config = {}

    # SEARCH_AND_FOLLOW_SETTINGS と ACTION_DELAYS を main_config から取得
    SEARCH_AND_FOLLOW_SETTINGS = main_config.get("search_and_follow_settings", {})
    ACTION_DELAYS = main_config.get("action_delays", {}) # こちらも main_config 直下を想定

    if not SEARCH_AND_FOLLOW_SETTINGS:
        logger.warning("search_utils: config.yaml に search_and_follow_settings が見つからないか空です。")
    # ACTION_DELAYS は必須ではないかもしれないので warning は出さない

except Exception as e:
    logger.error(f"search_utils: 設定情報 (main_config) の読み込み中にエラー: {e}", exc_info=True)
    # エラー発生時は空の辞書でフォールバックし、機能が安全に何もしないようにする
    SEARCH_AND_FOLLOW_SETTINGS = {}
    ACTION_DELAYS = {}


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
    delay_pagination = ACTION_DELAYS.get("delay_after_pagination_sec", 3.0)


    total_followed_count = 0
    total_domoed_count = 0

    activity_card_selector = "article[data-testid='activity-entry']"
    user_profile_link_in_card_selector = "div.css-1vh31zw > a.css-k2fvpp[href^='/users/']"

    processed_profile_urls = set()

    for page_num in range(1, max_pages + 1):
        processed_users_on_current_page = 0
        current_page_url_before_action = driver.current_url

        if page_num > 1:
            logger.info(f"{page_num-1}ページ目の処理完了。次のページ ({page_num}ページ目) へ遷移を試みます。")
            next_button_selectors = [
                "a[data-testid='pagination-next-button']", "a[rel='next']", "a.next",
                "a.pagination__next", "button.next", "button.pagination__next",
                "a[aria-label*='次へ']:not([aria-disabled='true'])", "a[aria-label*='Next']:not([aria-disabled='true'])",
                "button[aria-label*='次へ']:not([disabled])", "button[aria-label*='Next']:not([disabled])"
            ]
            next_button_found = False
            for selector in next_button_selectors:
                try:
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
                except TimeoutException: logger.debug(f"セレクタ '{selector}' で次のページボタンが見つからずタイムアウト。")
                except Exception as e_click: logger.warning(f"セレクタ '{selector}' でボタンクリック試行中にエラー: {e_click}")

            if not next_button_found:
                logger.info("試行した全てのセレクタで、クリック可能な「次へ」ボタンが見つかりませんでした。検索結果のページネーション処理を終了します。")
                break
            try:
                WebDriverWait(driver, 10).until(EC.url_changes(current_page_url_before_action))
                logger.info(f"{page_num}ページ目へ遷移しました。新しいURL: {driver.current_url}")
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                logger.info(f"{page_num}ページ目の活動記録カードの読み込みを確認。")
                time.sleep(delay_pagination)
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
            WebDriverWait(driver, 15).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, activity_card_selector)))
        except TimeoutException:
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
                except TimeoutException:
                    logger.warning(f"ユーザープロフィールページ ({user_profile_url}) の読み込みタイムアウト（複合条件）。このユーザーの処理をスキップします。")
                    driver.get(search_page_url_before_profile_visit)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    continue
                if user_profile_url not in driver.current_url:
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
                            if domo_activity(driver, latest_act_url, BASE_URL): # BASE_URL を渡す
                                total_domoed_count += 1
                        else:
                            logger.info(f"ユーザー「{user_name_for_log}」の最新活動記録が見つからず、DOMOできませんでした。")
                processed_users_on_current_page += 1
                logger.info(f"--- ユーザー「{user_name_for_log}」の処理終了 ---")
                logger.debug(f"ユーザー処理後、検索結果ページ ({search_page_url_before_profile_visit}) に戻ります。")
                driver.get(search_page_url_before_profile_visit)
                try:
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                except TimeoutException: logger.warning(f"検索結果ページ ({search_page_url_before_profile_visit}) に戻った後、活動記録カードの再表示タイムアウト。")
                time.sleep(delay_user_processing)
            except NoSuchElementException: logger.warning(f"活動記録カード {card_idx+1} からユーザー情報取得に必要な要素が見つかりません。スキップ。")
            except Exception as e_user_proc:
                logger.error(f"ユーザー「{user_name_for_log}」の処理中にエラー: {e_user_proc}", exc_info=True)
                try:
                    current_search_url_for_recovery = start_url if page_num == 1 else driver.current_url
                    if driver.current_url != current_search_url_for_recovery:
                         driver.get(current_search_url_for_recovery)
                         WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                except Exception as e_recover: logger.error(f"エラー後の検索ページ復帰試行中にもエラー: {e_recover}")
        logger.info(f"{page_num}ページ目の処理が完了しました。")
    logger.info(f"<<< 検索からのフォロー＆DOMO機能完了。合計フォロー: {total_followed_count}人, 合計DOMO: {total_domoed_count}件。")
