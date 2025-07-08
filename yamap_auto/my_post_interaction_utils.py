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
from .follow_back_utils import _follow_back_task # フォローバック処理の一部を再利用検討
from .follow_utils import find_follow_button_in_list_item, click_follow_button_and_verify # フォロー状態確認や実行に利用

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

    current_url = driver.current_url
    if user_profile_url not in current_url:
        driver.get(user_profile_url)
        WebDriverWait(driver, 10).until(EC.url_contains(user_profile_url.split('/')[-1]))

    # 活動記録一覧が表示されるまで待機
    activity_list_selector = "div[class*='UserProfileScreen_activities']" # プロフィールページの活動記録リストコンテナ
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, activity_list_selector))
        )
    except TimeoutException:
        logger.warning(f"プロフィールページで活動記録リスト ({activity_list_selector}) の読み込みタイムアウト。")
        return activities_within_period

    # 活動記録アイテムのセレクタ (日付とリンクを含む)
    # YAMAPのUIにより調整が必要
    activity_item_selector = "article[data-testid='activity-entry']" # 個々の活動記録
    activity_link_selector = "a[data-testid='activity-card-link']" # 活動記録へのリンク
    activity_date_selector = "time[class*='ActivityCard_date']" # 活動記録の日付

    try:
        activity_elements = driver.find_elements(By.CSS_SELECTOR, activity_item_selector)
        logger.info(f"{len(activity_elements)} 件の活動記録をプロフィールから検出しました。")

        if not activity_elements:
            logger.info("プロフィールに活動記録が見つかりませんでした。")
            return activities_within_period

        cutoff_date = datetime.now() - timedelta(days=days_to_check)
        logger.info(f"取得対象の日付範囲: {cutoff_date.strftime('%Y-%m-%d')} 以降")

        for item_idx, item in enumerate(activity_elements):
            try:
                date_element = item.find_element(By.CSS_SELECTOR, activity_date_selector)
                date_str = date_element.get_attribute("datetime") # 'YYYY-MM-DDTHH:mm:ssZ' 形式など
                if not date_str:
                    date_str_text = date_element.text # 'YYYY.MM.DD' 形式など
                    # 'YYYY.MM.DD' を 'YYYY-MM-DD' に変換しようと試みる
                    try:
                        activity_date = datetime.strptime(date_str_text, "%Y.%m.%d")
                    except ValueError:
                         logger.warning(f"活動記録 {item_idx+1} の日付形式 ({date_str_text}) が不明です。スキップします。")
                         continue
                else:
                    activity_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))

                logger.debug(f"活動記録 {item_idx+1}: 日付 '{activity_date.strftime('%Y-%m-%d')}'")

                if activity_date.date() >= cutoff_date.date():
                    link_element = item.find_element(By.CSS_SELECTOR, activity_link_selector)
                    activity_url = link_element.get_attribute("href")
                    if activity_url:
                        if activity_url.startswith("/"):
                            activity_url = BASE_URL + activity_url
                        if "/activities/" in activity_url:
                            logger.info(f"  対象期間内の活動記録を発見: {activity_url} (日付: {activity_date.strftime('%Y-%m-%d')})")
                            activities_within_period.append(activity_url)
                        else:
                            logger.warning(f"  取得したURLが無効です: {activity_url}")
                else:
                    logger.info(f"活動記録 {activity_url.split('/')[-1] if 'activity_url' in locals() else item_idx+1} (日付: {activity_date.strftime('%Y-%m-%d')}) は対象期間外です。これ以降の投稿も期間外とみなし処理を終了。")
                    break # 日付順に並んでいると仮定し、古すぎるものが見つかったら終了
            except NoSuchElementException:
                logger.warning(f"活動記録アイテム {item_idx+1} 内で日付またはリンク要素が見つかりません。スキップします。")
            except Exception as e_item:
                logger.error(f"活動記録アイテム {item_idx+1} の処理中にエラー: {e_item}", exc_info=True)

    except Exception as e_list:
        logger.error(f"活動記録リストの処理中にエラー: {e_list}", exc_info=True)

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
    domo_page_url = activity_url.split('?')[0] + "/domos" # クエリパラメータを除去して /domos を追加
    logger.info(f"活動記録 ({activity_url.split('/')[-1]}) のDOMOユーザー一覧ページへアクセス: {domo_page_url}")
    domo_users = []

    driver.get(domo_page_url)
    try:
        WebDriverWait(driver, 10).until(EC.url_contains("/domos"))
    except TimeoutException:
        logger.error(f"DOMO一覧ページ ({domo_page_url}) への遷移確認タイムアウト。")
        save_screenshot(driver, "DomoListPageLoadFail", activity_url.split('/')[-1])
        return domo_users

    # DOMOユーザーリストのコンテナセレクタ (YAMAPのUIにより調整が必要)
    # 例: ユーザーカードが並ぶ ul 要素など
    user_list_container_selector = "ul[class*='UserList_list']" # 仮のセレクタ
    user_card_selector = "li[class*='UserListItem_container']" # 仮のユーザーカードセレクタ
    user_name_selector = "h2[class*='UserListItem_name']" # 仮のユーザー名セレクタ
    user_link_selector = "a[class*='UserListItem_avatarLink']" # 仮のプロフィールリンクセレクタ (アバター画像などから)

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

        time.sleep(1.0) # リスト内容の描画待ち

        user_elements = driver.find_elements(By.CSS_SELECTOR, user_card_selector)
        if not user_elements:
            logger.info(f"ページ {page_num} にDOMOユーザーが見つかりませんでした。")
            if page_num == 1: # 最初のページに誰もいなければDOMOなしと判断
                logger.info(f"活動記録 ({activity_url.split('/')[-1]}) にDOMOユーザーはいません。")
            break

        logger.info(f"{len(user_elements)} 件のDOMOユーザー候補をページ {page_num} で検出。")
        for user_el in user_elements:
            try:
                name = user_el.find_element(By.CSS_SELECTOR, user_name_selector).text.strip()
                link_el = user_el.find_element(By.CSS_SELECTOR, user_link_selector)
                profile_url = link_el.get_attribute("href")
                if profile_url:
                    if profile_url.startswith("/"):
                        profile_url = BASE_URL + profile_url
                    if "/users/" in profile_url:
                        domo_users.append({"name": name, "profile_url": profile_url})
                        logger.debug(f"  DOMOユーザー発見: {name} ({profile_url})")
                    else:
                        logger.warning(f"  無効なプロフィールURL: {profile_url} (ユーザー名: {name})")
            except NoSuchElementException:
                logger.warning("DOMOユーザーカード内で名前またはリンク要素が見つかりません。")
            except Exception as e_user_parse:
                logger.error(f"DOMOユーザー情報の解析中にエラー: {e_user_parse}", exc_info=True)

        # 次へボタンの処理 (YAMAPのUIにより調整が必要)
        next_button_selector = "button[aria-label='次のページに移動する']:not([disabled])" # 仮
        try:
            next_button = driver.find_element(By.CSS_SELECTOR, next_button_selector)
            if next_button.is_displayed() and next_button.is_enabled():
                logger.info("「次へ」ボタンを発見。クリックします。")
                driver.execute_script("arguments[0].scrollIntoView(true);", next_button)
                time.sleep(0.5)
                next_button.click()
                page_num += 1
                time.sleep(2.0) # ページ遷移後の安定待ち
            else:
                logger.info("「次へ」ボタンが無効または非表示です。最終ページと判断。")
                break
        except NoSuchElementException:
            logger.info("「次へ」ボタンが見つかりません。最終ページと判断。")
            break
        except Exception as e_next:
            logger.error(f"「次へ」ボタン処理中にエラー: {e_next}", exc_info=True)
            break

    logger.info(f"活動記録 ({activity_url.split('/')[-1]}) から合計 {len(domo_users)} 件のDOMOユーザー情報を取得しました。")
    return domo_users


def interact_with_domo_users_on_my_posts(driver, current_user_id, shared_cookies):
    """
    自分の指定期間内の投稿にDOMOしたユーザーに対し、フォローバックや最新投稿へのDOMOを行う。
    """
    mpi_settings = _get_my_post_interaction_settings()
    if not mpi_settings.get("enable_my_post_interaction", False):
        logger.info("自分の投稿へのDOMOユーザーインタラクション機能は無効です。")
        return 0, 0 # followed_count, domoed_count

    logger.info(">>> 自分の投稿へのDOMOユーザーインタラクション機能を開始します...")
    days_to_check = mpi_settings.get("max_days_to_check_my_posts", 7)
    my_profile_url = f"{BASE_URL}/users/{current_user_id}"

    # 1. 自分の対象期間内の活動記録URLを取得
    my_activities = get_my_activities_within_period(driver, my_profile_url, days_to_check)
    if not my_activities:
        logger.info("対象期間内に処理すべき自分の活動記録が見つかりませんでした。")
        return 0, 0

    total_followed_back_count = 0
    total_domoed_to_users_count = 0

    # フォローバックに関する設定 (既存のものを流用)
    fb_settings_for_interaction = _get_follow_back_settings_for_interaction()
    action_delays = _get_config_cached().get("action_delays", {})

    processed_user_interactions_this_session = set() # (user_profile_url, interaction_type) のタプルを記録

    for activity_url in my_activities:
        logger.info(f"--- 活動記録 ({activity_url.split('/')[-1]}) のDOMOユーザーへのインタラクションを開始 ---")

        # 2. 当該活動記録のDOMOユーザーリストを取得
        #    DOMOユーザーリスト取得はメインドライバーで行う
        domo_users = get_domo_users_from_activity(driver, activity_url)
        if not domo_users:
            logger.info(f"活動記録 ({activity_url.split('/')[-1]}) にDOMOユーザーがいませんでした。")
            continue

        for domo_user in domo_users:
            user_name = domo_user["name"]
            user_profile_url = domo_user["profile_url"]
            user_id_short = user_profile_url.split('/')[-1]

            if user_profile_url == my_profile_url:
                logger.debug(f"DOMOユーザー ({user_name}) は自分自身なのでスキップします。")
                continue

            # a. フォローバック処理
            #    ここでは _follow_back_task を直接呼び出すのではなく、
            #    メインドライバーで相手のプロフィールページにアクセスし、フォロー状態を確認・実行する方式を採用。
            #    これは _follow_back_task が別スレッドでの動作を前提としているため。
            if (user_profile_url, 'follow_back') not in processed_user_interactions_this_session:
                logger.info(f"DOMOユーザー ({user_name}, {user_id_short}) のフォロー状態を確認・試行します。")
                driver.get(user_profile_url)
                try:
                    WebDriverWait(driver, 10).until(EC.url_contains(user_id_short))
                    # プロフィールページでフォローボタンを探す
                    follow_button_on_profile = find_follow_button_on_profile_page(driver)
                    if follow_button_on_profile:
                        logger.info(f"ユーザー ({user_name}) はまだフォローしていません。フォローバックを試みます。")
                        # フォロー条件の判定 (既存の follow_back_settings に基づく)
                        # ここでは簡略化のため、レシオ等の詳細な条件判定は省略し、
                        # 「フォローボタンがあればフォローする」という動作にする。
                        # 必要であれば、get_user_follow_counts 等で情報を取得し判定ロジックを追加。
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
                except Exception as e_fb:
                    logger.error(f"ユーザー ({user_name}) のフォローバック処理中にエラー: {e_fb}", exc_info=True)
            else:
                logger.info(f"ユーザー ({user_name}) のフォローバックは既に試行済みです。")


            # b. 最新投稿へのDOMO処理
            if (user_profile_url, 'domo_latest') not in processed_user_interactions_this_session:
                logger.info(f"DOMOユーザー ({user_name}, {user_id_short}) の最新活動記録へのDOMOを試みます。")
                # 最新活動記録URLを取得 (相手のプロフィールページにいるはずなので、driverをそのまま使用)
                latest_activity_url = get_latest_activity_url(driver, user_profile_url) # この関数は内部でページ遷移する場合あり
                if latest_activity_url:
                    logger.info(f"ユーザー ({user_name}) の最新活動記録URL: {latest_activity_url}")
                    if domo_activity(driver, latest_activity_url): # この関数も内部でページ遷移する場合あり
                        total_domoed_to_users_count += 1
                        logger.info(f"ユーザー ({user_name}) の最新活動記録へのDOMOに成功しました。")
                    else:
                        logger.info(f"ユーザー ({user_name}) の最新活動記録へのDOMOはスキップまたは失敗しました。")
                else:
                    logger.info(f"ユーザー ({user_name}) の最新活動記録が見つかりませんでした。")
                processed_user_interactions_this_session.add((user_profile_url, 'domo_latest'))
            else:
                logger.info(f"ユーザー ({user_name}) の最新投稿へのDOMOは既に試行済みです。")

            time.sleep(mpi_settings.get("delay_between_user_interaction_sec", 3.0)) # ユーザー間の処理遅延

        logger.info(f"--- 活動記録 ({activity_url.split('/')[-1]}) のDOMOユーザーへのインタラクションを終了 ---")

    logger.info(f"<<< 自分の投稿へのDOMOユーザーインタラクション機能完了。")
    logger.info(f"  合計フォローバック数: {total_followed_back_count}")
    logger.info(f"  合計DOMO成功数（DOMOユーザーへ）: {total_domoed_to_users_count}")
    return total_followed_back_count, total_domoed_to_users_count
