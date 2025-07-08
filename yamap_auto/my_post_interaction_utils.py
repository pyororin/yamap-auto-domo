# coding: utf-8
"""
自分の投稿へのDOMOユーザーに対するインタラクション機能関連ユーティリティ
"""
import time
import logging
from datetime import datetime, timedelta

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from .driver_utils import get_main_config, BASE_URL, save_screenshot, create_driver_with_cookies
from .user_profile_utils import get_latest_activity_url
from .domo_utils import domo_activity
# from .follow_back_utils import _follow_back_task # フォローバック処理の一部を再利用検討 # 今回の修正では直接使わない
from .user_profile_utils import find_follow_button_on_profile_page # 正しいモジュールからインポート
from .follow_utils import click_follow_button_and_verify # click_follow_button_and_verify は follow_utils のまま

logger = logging.getLogger(__name__)

# --- 設定情報の読み込み ---
_main_config_cache = None

def _get_config_cached():
    global _main_config_cache
    if _main_config_cache is None:
        _main_config_cache = get_main_config()
    return _main_config_cache

def _get_my_post_interaction_settings():
    config = _get_config_cached()
    return config.get("new_feature_my_post_interaction", {})

def _get_follow_back_settings_for_interaction(): # 新機能用のフォローバック設定取得
    config = _get_config_cached()
    return config.get("follow_back_settings", {})


def get_my_activities_within_period(driver, user_profile_url, days_to_check):
    """
    自分のプロフィールページから指定期間内の活動記録URLリストを取得する。
    Args:
        driver: Selenium WebDriverインスタンス。
        user_profile_url (str): 自分のプロフィールURL。
        days_to_check (int): 何日前までの活動記録を対象とするか。

    Returns:
        list[str]: 対象期間内の活動記録URLのリスト。
    """
    logger.info(f"過去{days_to_check}日間の自分の活動記録を取得します。プロフィールURL: {user_profile_url}")
    activities_within_period = []

    target_profile_page_url_base = user_profile_url.split('?')[0] # クエリパラメータを除いたベースURL

    # ユーザーのプロフィールページにアクセス
    # 現在のURLが既にターゲットのベースURLでない場合、または末尾のスラッシュの有無を考慮して判定
    current_url_base = driver.current_url.split('?')[0].rstrip('/')
    target_url_to_get = target_profile_page_url_base.rstrip('/')

    if target_url_to_get != current_url_base:
        logger.info(f"プロフィールページ ({target_url_to_get}) にアクセスします。")
        driver.get(target_url_to_get) # URLの末尾スラッシュを統一
        try:
            # URLがターゲットのベースURLで始まることを確認 (より柔軟なチェック)
            # 例: https://yamap.com/users/123 や https://yamap.com/users/123?tab=activities などにマッチ
            WebDriverWait(driver, 15).until(
                EC.url_matches(f"^{target_url_to_get}(?:/|\\?.*)?$")
            )
            logger.info(f"プロフィールページ ({target_url_to_get}) の読み込みを確認しました。")
        except TimeoutException:
            logger.warning(f"プロフィールページ ({target_url_to_get}) の読み込み確認タイムアウト。")
            save_screenshot(driver, "ProfilePageLoadTimeout", target_url_to_get.split('/')[-1])
            return activities_within_period
    else:
        logger.info(f"既にプロフィールページ ({target_url_to_get}) または互換URLに滞在中です。")

    # 活動記録一覧が直接表示されていることを期待して待機
    activity_list_container_selector = "ul.UserActivityList__List"
    first_activity_item_selector = "li.UserActivityList__Item"

    logger.info(f"活動記録リストコンテナ ({activity_list_container_selector}) の表示を待ちます...")
    try:
        WebDriverWait(driver, 20).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, activity_list_container_selector))
        )
        logger.info(f"活動記録リストコンテナ ({activity_list_container_selector}) が表示されました。")

        logger.info(f"リスト内の最初の活動記録アイテム ({first_activity_item_selector}) の表示を待ちます...")
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, first_activity_item_selector))
        )
        logger.info(f"最初の活動記録アイテム ({first_activity_item_selector}) の表示を確認しました。")

    except TimeoutException:
        logger.warning(f"活動記録リストコンテナまたは最初のアイテムの表示タイムアウト (最大30秒)。リストが空であるか、ページの読み込みに問題がある可能性があります。")
        save_screenshot(driver, "ActivityListOrItemTimeout", target_url_to_get.split('/')[-1])
        # 処理は継続し、後続の find_elements が空リストを返すのに任せる

    activity_item_selector = "li.UserActivityList__Item"
    activity_link_selector = "a.ActivityItem__Link"
    activity_date_selector = "span.ActivityItem__Date"

    try:
        list_container_elements = driver.find_elements(By.CSS_SELECTOR, activity_list_container_selector)
        if not list_container_elements:
            logger.warning(f"活動記録リストコンテナ ({activity_list_container_selector}) が見つかりませんでした。")
            # スクリーンショットは ActivityListOrItemTimeout で撮られている可能性があるのでここでは不要かも
            return activities_within_period

        list_container = list_container_elements[0]
        activity_elements = list_container.find_elements(By.CSS_SELECTOR, activity_item_selector)

        logger.info(f"{len(activity_elements)} 件の活動記録をプロフィールから検出しました。")

        if not activity_elements:
            logger.info("プロフィールに活動記録が見つかりませんでした（リストは存在するがアイテムが0件）。")
            return activities_within_period

        cutoff_date = datetime.now() - timedelta(days=days_to_check)
        logger.info(f"取得対象の日付範囲: {cutoff_date.strftime('%Y-%m-%d')} 以降")

        for item_idx, item in enumerate(activity_elements):
            try:
                date_element = item.find_element(By.CSS_SELECTOR, activity_date_selector)
                activity_date = None
                date_str_iso = date_element.get_attribute("datetime")
                date_str_text = date_element.text.strip()

                if date_str_iso:
                    try:
                        activity_date = datetime.fromisoformat(date_str_iso.replace('Z', '+00:00'))
                        logger.debug(f"活動記録 {item_idx+1}: ISO日付 '{date_str_iso}' -> {activity_date.strftime('%Y-%m-%d')}")
                    except ValueError:
                        logger.warning(f"活動記録 {item_idx+1}: ISO日付形式 ({date_str_iso}) の解析に失敗。テキスト日付を試みます。")
                        activity_date = None

                if not activity_date and date_str_text:
                    try:
                        date_text_main_part = date_str_text.split('(')[0]
                        activity_date = datetime.strptime(date_text_main_part, "%Y.%m.%d")
                        logger.debug(f"活動記録 {item_idx+1}: テキスト日付 '{date_str_text}' (解析対象: '{date_text_main_part}') -> {activity_date.strftime('%Y-%m-%d')}")
                    except ValueError:
                         logger.warning(f"活動記録 {item_idx+1}: テキスト日付形式 ({date_str_text}) も不明です。スキップします。")
                         continue
                elif not activity_date and not date_str_text:
                    logger.warning(f"活動記録 {item_idx+1}: 日付情報が取得できませんでした。スキップします。")
                    continue

                if not activity_date:
                    logger.warning(f"活動記録 {item_idx+1}: 有効な日付が特定できませんでした。スキップします。")
                    continue

                logger.debug(f"活動記録 {item_idx+1}: 最終的な解析日付 '{activity_date.strftime('%Y-%m-%d')}'")

                if activity_date.date() >= cutoff_date.date():
                    activity_url = None
                    try:
                        link_elements = item.find_elements(By.CSS_SELECTOR, activity_link_selector)
                        if link_elements:
                            activity_url_path = link_elements[0].get_attribute("href")
                            if activity_url_path:
                                if activity_url_path.startswith("/"):
                                    activity_url = BASE_URL + activity_url_path
                                elif activity_url_path.startswith(BASE_URL):
                                    activity_url = activity_url_path

                                if activity_url and "/activities/" in activity_url:
                                    logger.info(f"  対象期間内の活動記録を発見: {activity_url.split('/')[-1].split('?')[0]} (日付: {activity_date.strftime('%Y-%m-%d')})")
                                    activities_within_period.append(activity_url)
                                else:
                                    logger.warning(f"  取得したURLが無効か、活動記録ではありません: {activity_url_path}。アイテム {item_idx+1}")
                            else:
                                logger.warning(f"  活動記録アイテム {item_idx+1}: href属性が空でした。({activity_link_selector})")
                        else:
                            logger.warning(f"  活動記録アイテム {item_idx+1}: リンク要素 ({activity_link_selector}) が見つかりません。")
                    except NoSuchElementException: # Should not happen with find_elements
                        logger.warning(f"  活動記録アイテム {item_idx+1}: リンク要素 ({activity_link_selector}) の取得で予期せぬエラー。")
                else:
                    log_activity_id = f"アイテムインデックス {item_idx+1}"
                    try:
                        temp_link_elements = item.find_elements(By.CSS_SELECTOR, "a[href*='/activities/']")
                        if temp_link_elements:
                            temp_href = temp_link_elements[0].get_attribute("href")
                            if temp_href and "/activities/" in temp_href:
                                log_activity_id = temp_href.split('/')[-1].split('?')[0]
                    except: pass

                    logger.info(f"活動記録 {log_activity_id} (日付: {activity_date.strftime('%Y-%m-%d')}) は対象期間外です。これ以降の投稿も期間外とみなし処理を終了。")
                    break
            except NoSuchElementException as e_nse_item:
                logger.warning(f"活動記録アイテム {item_idx+1} 内で必須要素 (日付等) が見つかりません: {e_nse_item}。スキップします。")
            except Exception as e_item_process:
                logger.error(f"活動記録アイテム {item_idx+1} の処理中に予期せぬエラー: {e_item_process}", exc_info=True)

    except Exception as e_outer_list:
        logger.error(f"活動記録リストの処理のどこかで予期せぬエラー: {e_outer_list}", exc_info=True)

    logger.info(f"取得した対象期間内の活動記録URL数: {len(activities_within_period)} 件")
    return activities_within_period


def get_domo_users_from_activity(driver, activity_url):
    """
    特定の活動記録のDOMO一覧ページからDOMOしたユーザーの情報を取得する。
    Args:
        driver: Selenium WebDriverインスタンス。
        activity_url (str): DOMOユーザーを取得する活動記録のURL。

    Returns:
        list[dict]: DOMOしたユーザーの情報のリスト。各辞書は {'name': str, 'profile_url': str} を含む。
    """
    domo_page_url = activity_url.split('?')[0] + "/domos"
    logger.info(f"活動記録 ({activity_url.split('/')[-1].split('?')[0]}) のDOMOユーザー一覧ページへアクセス: {domo_page_url}")
    domo_users = []

    driver.get(domo_page_url)
    try:
        WebDriverWait(driver, 10).until(EC.url_contains("/domos"))
    except TimeoutException:
        logger.error(f"DOMO一覧ページ ({domo_page_url}) への遷移確認タイムアウト。")
        save_screenshot(driver, "DomoListPageLoadFail", activity_url.split('/')[-1].split('?')[0])
        return domo_users

    user_list_container_selector = "ul[class*='UserList_list']"
    user_card_selector = "li[class*='UserListItem_container']"
    user_name_selector = "h2[class*='UserListItem_name']"
    user_link_selector = "a[class*='UserListItem_avatarLink']"

    page_num = 1
    while True:
        logger.info(f"DOMOユーザー一覧の {page_num} ページ目を処理中...")
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, user_list_container_selector))
            )
            logger.debug(f"DOMOユーザーリストコンテナ ({user_list_container_selector}) を発見。")
        except TimeoutException:
            logger.warning(f"DOMOユーザーリストコンテナの読み込みタイムアウト (ページ {page_num})。")
            break

        time.sleep(1.0)

        user_elements = driver.find_elements(By.CSS_SELECTOR, user_card_selector)
        if not user_elements:
            logger.info(f"ページ {page_num} にDOMOユーザーが見つかりませんでした。")
            if page_num == 1:
                logger.info(f"活動記録 ({activity_url.split('/')[-1].split('?')[0]}) にDOMOユーザーはいません。")
            break

        logger.info(f"{len(user_elements)} 件のDOMOユーザー候補をページ {page_num} で検出。")
        for user_el in user_elements:
            try:
                name = user_el.find_element(By.CSS_SELECTOR, user_name_selector).text.strip()
                link_el = user_el.find_element(By.CSS_SELECTOR, user_link_selector)
                profile_url = link_el.get_attribute("href")
                if profile_url:
                    if profile_url.startswith("/"):
                        profile_url = BASE_URL + profile_url.split('?')[0] # クエリパラメータを除去
                    else:
                        profile_url = profile_url.split('?')[0] # クエリパラメータを除去

                    if "/users/" in profile_url:
                        domo_users.append({"name": name, "profile_url": profile_url})
                        logger.debug(f"  DOMOユーザー発見: {name} ({profile_url})")
                    else:
                        logger.warning(f"  無効なプロフィールURL: {profile_url} (ユーザー名: {name})")
            except NoSuchElementException:
                logger.warning("DOMOユーザーカード内で名前またはリンク要素が見つかりません。")
            except Exception as e_user_parse:
                logger.error(f"DOMOユーザー情報の解析中にエラー: {e_user_parse}", exc_info=True)

        next_button_selector = "button[aria-label='次のページに移動する']:not([disabled])"
        try:
            next_button = driver.find_element(By.CSS_SELECTOR, next_button_selector)
            if next_button.is_displayed() and next_button.is_enabled():
                logger.info("「次へ」ボタンを発見。クリックします。")
                driver.execute_script("arguments[0].scrollIntoView(true);", next_button)
                time.sleep(0.5)
                next_button.click()
                page_num += 1
                time.sleep(2.0)
            else:
                logger.info("「次へ」ボタンが無効または非表示です。最終ページと判断。")
                break
        except NoSuchElementException:
            logger.info("「次へ」ボタンが見つかりません。最終ページと判断。")
            break
        except Exception as e_next:
            logger.error(f"「次へ」ボタン処理中にエラー: {e_next}", exc_info=True)
            break

    logger.info(f"活動記録 ({activity_url.split('/')[-1].split('?')[0]}) から合計 {len(domo_users)} 件のDOMOユーザー情報を取得しました。")
    return domo_users


def interact_with_domo_users_on_my_posts(driver, current_user_id, shared_cookies):
    """
    自分の指定期間内の投稿にDOMOしたユーザーに対し、フォローバックや最新投稿へのDOMOを行う。
    """
    mpi_settings = _get_my_post_interaction_settings()
    if not mpi_settings.get("enable_my_post_interaction", False):
        logger.info("自分の投稿へのDOMOユーザーインタラクション機能は無効です。")
        return 0, 0

    logger.info(">>> 自分の投稿へのDOMOユーザーインタラクション機能を開始します...")
    days_to_check = mpi_settings.get("max_days_to_check_my_posts", 7)
    my_profile_url = f"{BASE_URL}/users/{current_user_id}"

    my_activities = get_my_activities_within_period(driver, my_profile_url, days_to_check)
    if not my_activities:
        logger.info("対象期間内に処理すべき自分の活動記録が見つかりませんでした。")
        return 0, 0

    total_followed_back_count = 0
    total_domoed_to_users_count = 0

    fb_settings_for_interaction = _get_follow_back_settings_for_interaction()
    action_delays = _get_config_cached().get("action_delays", {})
    processed_user_interactions_this_session = set()

    for activity_url in my_activities:
        activity_id_log = activity_url.split('/')[-1].split('?')[0]
        logger.info(f"--- 活動記録 ({activity_id_log}) のDOMOユーザーへのインタラクションを開始 ---")
        domo_users = get_domo_users_from_activity(driver, activity_url)
        if not domo_users:
            logger.info(f"活動記録 ({activity_id_log}) にDOMOユーザーがいませんでした。")
            continue

        for domo_user in domo_users:
            user_name = domo_user["name"]
            user_profile_url = domo_user["profile_url"] # 既にクエリ除去済みのはず
            user_id_short = user_profile_url.split('/')[-1]

            if user_id_short == str(current_user_id): # 自分自身はスキップ
                logger.debug(f"DOMOユーザー ({user_name}) は自分自身なのでスキップします。")
                continue

            if (user_profile_url, 'follow_back') not in processed_user_interactions_this_session:
                logger.info(f"DOMOユーザー ({user_name}, {user_id_short}) のフォロー状態を確認・試行します。")
                driver.get(user_profile_url) # 相手のプロフィールページへ
                try:
                    WebDriverWait(driver, 10).until(EC.url_contains(user_id_short))
                    follow_button_on_profile = find_follow_button_on_profile_page(driver)
                    if follow_button_on_profile:
                        logger.info(f"ユーザー ({user_name}) はまだフォローしていません。フォローバックを試みます。")
                        if click_follow_button_and_verify(driver, follow_button_on_profile, user_name):
                            total_followed_back_count += 1
                            logger.info(f"ユーザー ({user_name}) のフォローバックに成功しました。")
                        else:
                            logger.warning(f"ユーザー ({user_name}) のフォローバック試行に失敗しました。")
                        time.sleep(action_delays.get("after_follow_action_sec", 2.0))
                    else:
                        logger.info(f"ユーザー ({user_name}) は既にフォロー済みか、フォローボタンが見つかりませんでした。")
                    processed_user_interactions_this_session.add((user_profile_url, 'follow_back'))
                except TimeoutException:
                    logger.error(f"ユーザー ({user_name}) のプロフィールページ ({user_profile_url}) 読み込みタイムアウト。フォローバック処理スキップ。")
                    save_screenshot(driver, f"FollowBackProfileLoadTimeout_{user_id_short}")
                except Exception as e_fb:
                    logger.error(f"ユーザー ({user_name}) のフォローバック処理中にエラー: {e_fb}", exc_info=True)
                    save_screenshot(driver, f"FollowBackError_{user_id_short}")
            else:
                logger.info(f"ユーザー ({user_name}) のフォローバックは既に試行済みです。")

            if mpi_settings.get("enable_domo_to_latest_activity", True): # 設定でDOMO返しを制御
                if (user_profile_url, 'domo_latest') not in processed_user_interactions_this_session:
                    logger.info(f"DOMOユーザー ({user_name}, {user_id_short}) の最新活動記録へのDOMOを試みます。")
                    # 最新活動記録URLを取得するためには、再度相手のプロフィールページにいる必要がある。
                    # フォローバック処理で既にそのページにいるはずだが、念のため driver.get(user_profile_url) を実行しても良い。
                    # ただし、get_latest_activity_url が内部でページ遷移を伴う場合があるので注意。
                    # ここでは、前のフォローバック処理で相手のプロフィールページにいることを期待。
                    latest_activity_url = get_latest_activity_url(driver, user_profile_url) # この関数は相手のプロフィールページで実行される想定
                    if latest_activity_url:
                        logger.info(f"ユーザー ({user_name}) の最新活動記録URL: {latest_activity_url.split('?')[0]}")
                        if domo_activity(driver, latest_activity_url):
                            total_domoed_to_users_count += 1
                            logger.info(f"ユーザー ({user_name}) の最新活動記録へのDOMOに成功しました。")
                        else:
                            logger.info(f"ユーザー ({user_name}) の最新活動記録へのDOMOはスキップまたは失敗しました。")
                    else:
                        logger.info(f"ユーザー ({user_name}) の最新活動記録が見つかりませんでした。")
                    processed_user_interactions_this_session.add((user_profile_url, 'domo_latest'))
                else:
                    logger.info(f"ユーザー ({user_name}) の最新投稿へのDOMOは既に試行済みです。")
            else:
                logger.info(f"DOMOユーザー ({user_name}) の最新活動記録へのDOMOは設定で無効です。")


            time.sleep(mpi_settings.get("delay_between_user_interaction_sec", 3.0))

        logger.info(f"--- 活動記録 ({activity_id_log}) のDOMOユーザーへのインタラクションを終了 ---")

    logger.info(f"<<< 自分の投稿へのDOMOユーザーインタラクション機能完了。")
    logger.info(f"  合計フォローバック数: {total_followed_back_count}")
    logger.info(f"  合計DOMO成功数（DOMOユーザーへ）: {total_domoed_to_users_count}")
    return total_followed_back_count, total_domoed_to_users_count
