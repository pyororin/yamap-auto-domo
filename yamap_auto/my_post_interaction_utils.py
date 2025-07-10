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

import time
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from .driver_utils import get_main_config, BASE_URL, save_screenshot, create_driver_with_cookies
from .user_profile_utils import get_latest_activity_url, find_follow_button_on_profile_page, get_user_follow_counts
from .domo_utils import domo_activity
from .follow_utils import click_follow_button_and_verify

logger = logging.getLogger(__name__)

# --- 設定情報の読み込み ---
_main_config_cache = None # Cache variable

def _get_config_cached(): # Generic config cache function
    global _main_config_cache
    if _main_config_cache is None:
        _main_config_cache = get_main_config()
    return _main_config_cache

# This function is being removed:
# def _get_my_post_interaction_settings(): # このモジュール固有の設定
#     config = _get_config_cached()
#     return config.get("new_feature_my_post_interaction", {})

def _get_domo_back_settings(): # DOMO返し機能の設定
    config = _get_config_cached()
    return config.get("new_feature_domo_back_to_past_domo_users", {})

def _get_search_follow_settings_for_domo_back(): # フォロー条件参照用
    config = _get_config_cached()
    return config.get("search_and_follow_settings", {})

def _get_action_delays_mpi(): # アクション遅延設定 (名前はそのままMPIだが汎用的に使える)
    config = _get_config_cached()
    return config.get("action_delays", {})


# nullcontext for Python < 3.7 (search_utils.py から拝借)
try:
    from contextlib import nullcontext
except ImportError:
    import contextlib
    @contextlib.contextmanager
    def nullcontext(enter_result=None):
        yield enter_result


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

    target_profile_page_url_base = user_profile_url.split('?')[0]

    current_url_base = driver.current_url.split('?')[0].rstrip('/')
    target_url_to_get = target_profile_page_url_base.rstrip('/')

    if target_url_to_get != current_url_base:
        logger.info(f"プロフィールページ ({target_url_to_get}) にアクセスします。")
        driver.get(target_url_to_get)
        try:
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

    activity_list_container_selector = "ul.css-qksbms"
    activity_item_selector_in_container = "article[data-testid='activity-entry']"

    logger.info(f"活動記録リストコンテナ ({activity_list_container_selector}) の表示を待ちます...")
    try:
        list_container_element = WebDriverWait(driver, 20).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, activity_list_container_selector))
        )
        logger.info(f"活動記録リストコンテナ ({activity_list_container_selector}) が表示されました。")

        logger.info(f"リスト内の最初の活動記録アイテム ({activity_item_selector_in_container}) の表示を待ちます...")
        WebDriverWait(list_container_element, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, f"li > {activity_item_selector_in_container}"))
        )
        logger.info(f"最初の活動記録アイテム ({activity_item_selector_in_container}) の表示を確認しました。")

        activity_elements = list_container_element.find_elements(By.CSS_SELECTOR, f"li > {activity_item_selector_in_container}")

    except TimeoutException:
        logger.warning(f"活動記録リストコンテナまたは最初のアイテムの表示タイムアウト (最大30秒)。")
        save_screenshot(driver, "ActivityListOrItemTimeoutNew", target_url_to_get.split('/')[-1])
        return activities_within_period
    except NoSuchElementException:
        logger.warning(f"活動記録リストコンテナ ({activity_list_container_selector}) が見つかりませんでした。")
        save_screenshot(driver, "ActivityListContainerNotFoundNew", target_url_to_get.split('/')[-1])
        return activities_within_period

    activity_link_selector_in_item = "h3.css-m9icgg > a.css-1pla16"
    activity_date_selector_in_item = "p.css-1oi95vk > span.css-125iqyy"

    logger.info(f"{len(activity_elements)} 件の活動記録を検出しました。")

    if not activity_elements:
        logger.info("プロフィールに活動記録が見つかりませんでした（リストは存在するがアイテムが0件）。")
        return activities_within_period

    cutoff_date = datetime.now() - timedelta(days=days_to_check)
    logger.info(f"取得対象の日付範囲: {cutoff_date.strftime('%Y-%m-%d')} 以降")

    for item_idx, item_article_element in enumerate(activity_elements):
        try:
            date_element = item_article_element.find_element(By.CSS_SELECTOR, activity_date_selector_in_item)
            activity_date = None
            date_str_text = date_element.text.strip()

            if date_str_text:
                try:
                    date_text_main_part = date_str_text.split('(')[0].strip()
                    activity_date = datetime.strptime(date_text_main_part, "%Y.%m.%d")
                    logger.debug(f"活動記録 {item_idx+1}: テキスト日付 '{date_str_text}' (解析対象: '{date_text_main_part}') -> {activity_date.strftime('%Y-%m-%d')}")
                except ValueError:
                     logger.warning(f"活動記録 {item_idx+1}: テキスト日付形式 ({date_str_text}) も不明です。スキップします。")
                     continue
            else:
                logger.warning(f"活動記録 {item_idx+1}: 日付情報が取得できませんでした。スキップします。")
                continue

            if not activity_date:
                logger.warning(f"活動記録 {item_idx+1}: 有効な日付が特定できませんでした。スキップします。")
                continue

            logger.debug(f"活動記録 {item_idx+1}: 最終的な解析日付 '{activity_date.strftime('%Y-%m-%d')}'")

            if activity_date.date() >= cutoff_date.date():
                activity_url = None
                try:
                    link_element = item_article_element.find_element(By.CSS_SELECTOR, activity_link_selector_in_item)
                    activity_url_path = link_element.get_attribute("href")

                    if activity_url_path:
                        if activity_url_path.startswith("/"):
                            activity_url = BASE_URL + activity_url_path
                        elif activity_url_path.startswith(BASE_URL):
                            activity_url = activity_url_path

                        if activity_url and "/activities/" in activity_url:
                            activity_id_for_log = activity_url.split('/')[-1].split('?')[0]
                            logger.info(f"  対象期間内の活動記録を発見: {activity_id_for_log} (日付: {activity_date.strftime('%Y-%m-%d')})")
                            activities_within_period.append(activity_url)
                        else:
                            logger.warning(f"  取得したURLが無効か、活動記録ではありません: {activity_url_path}。アイテム {item_idx+1}")
                    else:
                        logger.warning(f"  活動記録アイテム {item_idx+1}: href属性が空でした。({activity_link_selector_in_item})")
                except NoSuchElementException:
                    logger.warning(f"  活動記録アイテム {item_idx+1}: リンク要素 ({activity_link_selector_in_item}) が見つかりません。")
            else:
                log_activity_id = f"アイテムインデックス {item_idx+1}"
                try:
                    if 'activity_url_path' in locals() and activity_url_path and "/activities/" in activity_url_path:
                        log_activity_id = activity_url_path.split('/')[-1].split('?')[0]
                except Exception:
                    pass
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
    activity_id_for_log = activity_url.split('/')[-1].split('?')[0]
    logger.info(f"活動記録 ({activity_id_for_log}) ページへアクセス: {activity_url}")
    domo_users = []

    driver.get(activity_url)
    # Attempt to wait for a general activity page container
    activity_page_container_selector = "div.ActivitiesId" # 新しいセレクタ案
    activity_title_selector = "h1.ActivityDetailTabLayout__Title" # これは div.ActivitiesId の内部にある想定

    try:
        logger.info(f"活動記録ページ ({activity_id_for_log}) の主要コンテナ ({activity_page_container_selector}) の表示を待ちます...")
        WebDriverWait(driver, 35).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, activity_page_container_selector))
        )
        logger.info(f"活動記録ページ ({activity_id_for_log}) の主要コンテナ ({activity_page_container_selector}) の表示を確認。")

        # 主要コンテナが表示された後、少し待ってからタイトル要素の確認を試みる (念のため)
        time.sleep(0.5)
        try:
            title_element = driver.find_element(By.CSS_SELECTOR, activity_title_selector)
            if title_element.is_displayed():
                logger.info(f"活動記録ページ ({activity_id_for_log}) のタイトル要素 ({activity_title_selector}) を発見。")
            else:
                logger.warning(f"活動記録ページ ({activity_id_for_log}) のタイトル要素 ({activity_title_selector}) は見つかりましたが、表示されていません。")
        except NoSuchElementException:
            logger.warning(f"活動記録ページ ({activity_id_for_log}) のタイトル要素 ({activity_title_selector}) が見つかりませんでした。処理は続行します。")

    except TimeoutException:
        logger.error(f"活動記録ページ ({activity_url}) の主要コンテナ ({activity_page_container_selector}) の読み込み確認タイムアウト。")
        save_screenshot(driver, "ActivityPageContainerLoadFail_NewSel", activity_id_for_log) # スクリーンショットファイル名変更
        return domo_users
    except Exception as e_page_load:
        logger.error(f"活動記録ページ ({activity_url}) の読み込み中に予期せぬエラー: {e_page_load}", exc_info=True)
        save_screenshot(driver, "ActivityPageLoadGenericError_NewSel", activity_id_for_log) # スクリーンショットファイル名変更
        return domo_users

    # DOMOしたユーザー一覧へ遷移するボタンを探す (クラス名とテキスト内容で判断)
    domo_button_xpath = "//button[contains(@class, 'ActivityToolBar__Button') and contains(normalize-space(), '人')]"
    try:
        logger.info(f"DOMOしたユーザー一覧へのボタンを探しています (XPath: {domo_button_xpath})...")
        domo_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, domo_button_xpath))
        )
        button_text_for_log = domo_button.text.strip()
        logger.info(f"DOMOしたユーザー一覧へのボタン ('{button_text_for_log}') を発見。")

        # DOMO数をパース
        domo_count = 0
        try:
            # "人" を取り除き、数値に変換
            domo_count_str = button_text_for_log.replace("人", "").strip()
            if domo_count_str.isdigit(): # "コメントする" など他のテキストでないことを確認
                domo_count = int(domo_count_str)
            else:
                # "人" を含むが数値ではない場合 (例: "コメントする" のような想定外のボタンを拾った場合)
                # 基本的にXPathで `contains(normalize-space(), '人')` を指定しているので、
                # 純粋な数字+"人" の形式を期待している。
                logger.warning(f"DOMOボタンのテキスト ('{button_text_for_log}') からDOMO数をパースできませんでした。DOMO数0として扱います。")
                domo_count = 0 # 安全のため0人扱い

        except ValueError:
            logger.warning(f"DOMOボタンのテキスト ('{button_text_for_log}') からDOMO数をパース中にエラー。DOMO数0として扱います。")
            domo_count = 0 # パース失敗時も0人扱い

        if domo_count == 0:
            logger.info(f"DOMOユーザー数が見つかったボタンテキスト ('{button_text_for_log}') から0人と判断されたため、DOMOユーザー一覧の取得処理をスキップします。")
            return domo_users # 空のリストを返す

        # DOMO数が0より大きい場合のみクリックと待機処理を行う
        logger.info(f"DOMOユーザー数が {domo_count} 人のため、ボタンをクリックします。")
        domo_button.click()

        # DOMOユーザー一覧ページへの遷移/表示を待機
        # 最初のユーザーリンクが表示されることを期待する
        domo_list_page_indicator_selector = "a.DomoUserListItem__UserLink"

        logger.info(f"DOMOユーザー一覧の表示を待ちます (セレクタ: {domo_list_page_indicator_selector})...")
        WebDriverWait(driver, 15).until(
            EC.any_of(
                EC.url_contains("/domos"), # URLでの確認も残す
                EC.presence_of_element_located((By.CSS_SELECTOR, domo_list_page_indicator_selector))
            )
        )
        logger.info("DOMOユーザー一覧ページへの遷移/表示を確認。")

    except TimeoutException:
        # このTimeoutExceptionは、主にDOMOボタン自体が見つからない場合に発生する
        logger.warning(f"DOMOしたユーザー一覧へのボタンが見つからないか、クリック後のDOMOユーザー一覧表示でタイムアウトしました。活動記録 ({activity_id_for_log})")
        save_screenshot(driver, "DomoButtonOrListTimeout", activity_id_for_log)
        return domo_users
    except Exception as e_button_click:
        logger.error(f"DOMOボタンの処理または遷移待機中に予期せぬエラー: {e_button_click}", exc_info=True)
        save_screenshot(driver, "DomoButtonProcessingError", activity_id_for_log)
        return domo_users

    # --- ここからDOMOユーザー一覧ページでの処理 ---
    # ユーザー提供のHTMLに基づいたセレクタ
    # <button data-v-a51e5818="" data-v-5bf08ddc="" class="DomoUserListModal__ReadMore BaseButton is-size-m is-variant-outline" data-v-70a616f8="">
    # <a data-v-5eca6d0a="" href="/users/3462839" class="DomoUserListItem__UserLink">
    #   <div data-v-69308071="" data-v-5eca6d0a="" class="DomoUserListItem__UserAvatar RidgeUserAvatarImage RidgeUserAvatarImage--size40">
    #     <img data-v-69308071="" src="..." alt="mako" ...>
    #   </div>
    # </a>
    # 親要素の特定が難しいため、DomoUserListItem__UserLink を持つ要素を直接探す
    user_list_container_selector = "body" # 広めに取っておき、個別のユーザーリンクを探す
    user_link_selector_specific = "a.DomoUserListItem__UserLink" # ユーザープロファイルへのリンク
    # ユーザー名は img の alt 属性から取得する想定
    user_avatar_image_selector_in_link = "img.RidgeUserAvatarImage__Avatar"

    # 「もっと見る」ボタンのセレクタ
    read_more_button_selector = "button.DomoUserListModal__ReadMore.BaseButton.is-size-m.is-variant-outline"

    processed_profile_urls = set() # 既に処理したプロフィールURLを記録

    while True: # 「もっと見る」がなくなるまでループ
        try:
            # ユーザーリストが表示されていることを確認 (ここではbodyの存在で代用)
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, user_list_container_selector))
            )
        except TimeoutException:
            logger.warning(f"DOMOユーザーリストのコンテナ ({user_list_container_selector}) の読み込みタイムアウト。")
            break

        time.sleep(1.5) # ユーザーリストの描画や更新を待つ

        # 現在表示されているすべてのユーザーリンクを取得
        user_link_elements = driver.find_elements(By.CSS_SELECTOR, user_link_selector_specific)
        logger.info(f"{len(user_link_elements)} 件のユーザーリンク候補を検出。")

        new_users_found_in_this_iteration = 0
        for link_el in user_link_elements:
            try:
                profile_url_raw = link_el.get_attribute("href")
                if profile_url_raw:
                    profile_url = profile_url_raw.split('?')[0]
                    if profile_url.startswith("/"):
                        profile_url = BASE_URL + profile_url

                    if "/users/" in profile_url and profile_url not in processed_profile_urls:
                        user_name = "N/A" # デフォルト名
                        try:
                            # リンク内のアバター画像を探し、altテキストからユーザー名を取得
                            avatar_img = link_el.find_element(By.CSS_SELECTOR, user_avatar_image_selector_in_link)
                            user_name = avatar_img.get_attribute("alt")
                            if not user_name: # altが空の場合もあるかもしれない
                                user_name = f"User_{profile_url.split('/')[-1]}" # IDから仮名を生成
                        except NoSuchElementException:
                            logger.warning(f"プロフィール ({profile_url}) のアバター画像または名前が見つかりません。")
                            user_name = f"User_{profile_url.split('/')[-1]}" # IDから仮名を生成

                        domo_users.append({"name": user_name, "profile_url": profile_url})
                        processed_profile_urls.add(profile_url)
                        new_users_found_in_this_iteration +=1
                        logger.debug(f"  DOMOユーザー発見: {user_name} ({profile_url})")
                    elif profile_url in processed_profile_urls:
                        logger.debug(f"  DOMOユーザー ({profile_url}) は既にリストに追加済みです。")
                    else:
                        logger.warning(f"  無効なプロフィールURL: {profile_url_raw}")
            except Exception as e_user_parse:
                logger.error(f"DOMOユーザー情報の解析中にエラー: {e_user_parse}", exc_info=True)

        if new_users_found_in_this_iteration == 0 and len(user_link_elements) > 0 :
            logger.info("新しいDOMOユーザーは見つかりませんでした。既に全ユーザーを取得済みか、ページの構造が予期しない形になっている可能性があります。")
            # 状況によってはここでbreakしても良いかもしれないが、「もっと見る」がある限りは続行する

        # 「もっと見る」ボタンを探してクリック
        try:
            read_more_button = driver.find_element(By.CSS_SELECTOR, read_more_button_selector)
            if read_more_button.is_displayed() and read_more_button.is_enabled():
                logger.info("「もっと見る」ボタンを発見。クリックします。")
                # ボタンが画面内にないとクリックできないことがあるため、スクロールする
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", read_more_button)
                time.sleep(0.5) # スクロール後の安定待ち
                read_more_button.click()
                logger.info("「もっと見る」ボタンをクリックしました。次のユーザーリストの読み込みを待ちます。")
                time.sleep(2.5) # DOMの更新や追加読み込みを待つ時間
            else:
                logger.info("「もっと見る」ボタンが無効または非表示です。全てのDOMOユーザーを取得したと判断します。")
                break
        except NoSuchElementException:
            logger.info("「もっと見る」ボタンが見つかりません。全てのDOMOユーザーを取得したと判断します。")
            break
        except Exception as e_read_more:
            logger.error(f"「もっと見る」ボタン処理中にエラー: {e_read_more}", exc_info=True)
            break

    logger.info(f"活動記録 ({activity_id_for_log}) から合計 {len(domo_users)} 件のDOMOユーザー情報を取得しました。")
    return domo_users


# The function interact_with_domo_users_on_my_posts has been removed as its functionality
# is superseded by domo_back_to_past_domo_users.


def _domo_back_and_follow_task(user_profile_url, user_name_for_log, shared_cookies, current_user_id_for_task, db_settings, sf_settings, ad_settings):
    """
    並列処理用のワーカースレッドタスク。
    指定されたユーザーのプロフィールページにアクセスし、設定に基づいてフォローを試み、
    その後、ユーザーの最新の活動記録にDOMOを試みます。

    Args:
        user_profile_url (str): 対象ユーザーのプロフィールURL。
        user_name_for_log (str): ログ出力用のユーザー名。
        shared_cookies (list): ログインセッションを共有するためのCookieのリスト。
        current_user_id_for_task (str): 現在操作中のYAMAPユーザーID（自分自身）。
        db_settings (dict): DOMO返し機能 (`new_feature_domo_back_to_past_domo_users`) の設定。
        sf_settings (dict): 検索＆フォロー機能 (`search_and_follow_settings`) の設定（フォロー条件参照用）。
        ad_settings (dict): アクション遅延 (`action_delays`) の設定。

    Returns:
        dict: 処理結果。以下のキーを含む可能性があります:
            - profile_url (str): 処理対象のプロフィールURL。
            - user_name (str): 処理対象のユーザー名。
            - followed (int): このタスクでフォローした場合は1、そうでなければ0。
            - domoed (int): このタスクでDOMOした場合は1、そうでなければ0。
            - error (str | None): エラーが発生した場合のエラーメッセージ。
            - duration_sec (float): タスクの実行時間（秒）。
            - status (str): タスクの終了状態 ("success", "failure_driver_creation", etc.)。
            - skipped_reason (str, optional): スキップされた場合の理由。
    """
    task_driver = None
    task_followed_count = 0
    task_domoed_count = 0
    user_id_for_log = user_profile_url.split('/')[-1]
    log_prefix_task = f"[DBF_TASK][{user_id_for_log}] " # DOMO_BACK_FOLLOW_TASK
    status_message = f"ユーザー「{user_name_for_log}」(ID: {user_id_for_log}): "
    task_start_time = time.time()
    logger.info(f"{log_prefix_task}処理開始。ユーザー: {user_name_for_log} ({user_profile_url})")

    try:
        # 1. WebDriver作成とCookie設定
        logger.info(f"{log_prefix_task}WebDriverを作成し、Cookieを設定・検証します。(ログインユーザーID: {current_user_id_for_task})")
        task_driver = create_driver_with_cookies(shared_cookies, current_user_id_for_task)
        if not task_driver:
            logger.error(f"{log_prefix_task}WebDriverの作成またはCookie/ログイン検証に失敗。タスクを中止。")
            return {"profile_url": user_profile_url, "user_name": user_name_for_log, "followed": 0, "domoed": 0, "error": "WebDriver/ログイン検証失敗", "duration_sec": time.time() - task_start_time, "status": "failure_driver_creation"}

        # 2. プロフィールページアクセス
        logger.info(f"{log_prefix_task}ログイン検証済み。対象のプロフィールページ ({user_profile_url}) へアクセスします。")
        task_driver.get(user_profile_url)
        try:
            WebDriverWait(task_driver, 20).until(EC.url_contains(user_id_for_log)) # 簡単なURL検証
            logger.info(f"{log_prefix_task}プロフィールページ ({user_profile_url}) へアクセス完了。")
        except TimeoutException:
            logger.warning(f"{log_prefix_task}プロフィールページ ({user_profile_url}) の読み込みタイムアウト。")
            return {"profile_url": user_profile_url, "user_name": user_name_for_log, "followed": 0, "domoed": 0, "error": "プロフィールページ読み込みタイムアウト", "duration_sec": time.time() - task_start_time, "status": "failure_profile_load_timeout"}

        # 3. フォロー判定・実行
        if db_settings.get("enable_follow_during_domo_back", False):
            logger.info(f"{log_prefix_task}{status_message}フォロー試行を確認します。")
            follow_button = find_follow_button_on_profile_page(task_driver)
            if follow_button:
                # search_and_follow_settings からフォロー条件を取得
                # sf_settings は既に _domo_back_and_follow_task の引数として渡されている
                min_followers = sf_settings.get("min_followers_for_search_follow", 20) # デフォルト値も search_utils と合わせる
                ratio_threshold = sf_settings.get("follow_ratio_threshold_for_search", 0.9) # 同上

                follows, followers = get_user_follow_counts(task_driver, user_profile_url)
                if follows != -1 and followers != -1:
                    logger.info(f"{log_prefix_task}{status_message}現在のフォロー/フォロワー数: F中={follows}, Fワー={followers} (条件: MinFollowers>={min_followers}, Ratio>={ratio_threshold})")
                    if followers < min_followers:
                        logger.info(f"{log_prefix_task}{status_message}フォロワー数 ({followers}) が閾値 ({min_followers}) 未満。フォローせず。")
                    else:
                        current_ratio = (follows / followers) if followers > 0 else float('inf')
                        # F中/Fワーは上でログ済みなのでRatioのみをログ出力
                        logger.info(f"{log_prefix_task}{status_message}計算されたRatio={current_ratio:.2f} (閾値 >={ratio_threshold})")
                        if current_ratio >= ratio_threshold:
                            logger.info(f"{log_prefix_task}{status_message}フォロー条件合致。フォローします。")
                            if click_follow_button_and_verify(task_driver, follow_button, user_name_for_log): # user_name_for_log を渡す
                                task_followed_count = 1
                                logger.info(f"{log_prefix_task}{status_message}フォロー成功。")
                                time.sleep(ad_settings.get("after_follow_action_sec", 2.0)) # ad_settings も引数で渡されている
                            else:
                                logger.warning(f"{log_prefix_task}{status_message}フォロー失敗。")
                        else:
                            logger.info(f"{log_prefix_task}{status_message}Ratio ({current_ratio:.2f}) が閾値 ({ratio_threshold}) 未満。フォローせず。")
                else:
                    logger.warning(f"{log_prefix_task}{status_message}フォロー数/フォロワー数取得失敗。フォローせず。")
            else:
                logger.info(f"{log_prefix_task}{status_message}既にフォロー済みかボタンなし。フォローせず。")
        else:
            logger.info(f"{log_prefix_task}{status_message}DOMO返し時のフォロー機能は無効です。")

        # 4. 最新活動記録へのDOMO実行
        should_domo = True
        # enable_domo_only_if_not_following_me の判定 (自分をフォローしてくれているか) は、
        # このタスク内では直接行わず、DOMO返し機能全体の大枠のスイッチとして解釈。
        # 厳密な判定はメインスレッド側でのフィルタリング等が必要。
        # logger.debug(f"{log_prefix_task}DOMO条件 enable_domo_only_if_not_following_me: {db_settings.get('enable_domo_only_if_not_following_me')}")

        if db_settings.get("enable_domo_only_if_i_am_not_following", True): # デフォルトTrue
            # 自分が相手をフォローしているかどうかの確認 (このタスクでのフォロー試行結果も含む)
            is_already_following_after_attempt = False
            if task_followed_count == 1: # このタスクでフォローした
                is_already_following_after_attempt = True
            else: # このタスクでフォローしていない場合、改めてボタンを確認
                # find_follow_button_on_profile_page は「フォローする」ボタンを探す。
                # ボタンがない場合は「フォロー中」と判断できる。
                if not find_follow_button_on_profile_page(task_driver): # ボタンがない = フォロー中
                    is_already_following_after_attempt = True

            if is_already_following_after_attempt:
                 logger.info(f"{log_prefix_task}{status_message}自分が既に相手をフォローしている(または今回フォローした)ため、DOMO返し条件 (enable_domo_only_if_i_am_not_following=true) によりDOMOスキップ。")
                 should_domo = False

        if should_domo:
            logger.info(f"{log_prefix_task}{status_message}最新活動記録へDOMO返しを試みます。")
            # プロフィールページに既にいるので、get_latest_activity_url は driver と base_url だけ渡せば良いはず
            # ただし、get_latest_activity_url が内部で再度プロフィールページにアクセスする設計ならそのままでOK
            latest_activity_url = get_latest_activity_url(task_driver, user_profile_url)
            if latest_activity_url:
                activity_id_log = latest_activity_url.split('/')[-1].split('?')[0]
                logger.info(f"{log_prefix_task}{status_message}最新活動記録URL: {activity_id_log}")
                if domo_activity(task_driver, latest_activity_url, BASE_URL): # domo_activity に BASE_URL を渡す
                    task_domoed_count = 1
                    logger.info(f"{log_prefix_task}{status_message}最新活動記録 ({activity_id_log}) へのDOMO成功。")
                    # DOMO後の遅延は domo_activity 内で考慮されている想定 (action_delays.after_domo_sec)
                else:
                    logger.info(f"{log_prefix_task}{status_message}最新活動記録 ({activity_id_log}) へのDOMOはスキップまたは失敗。")
            else:
                logger.info(f"{log_prefix_task}{status_message}最新活動記録が見つからず、DOMO返しできませんでした。")

        # タスク固有の遅延 (並列処理の場合)
        time.sleep(db_settings.get("delay_per_worker_domo_back_sec", 2.5))

        total_task_duration = time.time() - task_start_time
        logger.info(f"{log_prefix_task}処理完了。総所要時間: {total_task_duration:.2f}秒。結果: Followed={task_followed_count}, Domoed={task_domoed_count}")
        return {"profile_url": user_profile_url, "user_name": user_name_for_log, "followed": task_followed_count, "domoed": task_domoed_count, "error": None, "duration_sec": total_task_duration, "status": "success"}

    except Exception as e_task:
        total_task_duration = time.time() - task_start_time
        logger.error(f"{log_prefix_task}{status_message}並列処理タスク中に予期せぬエラー: {e_task}", exc_info=True)
        return {"profile_url": user_profile_url, "user_name": user_name_for_log, "followed": 0, "domoed": 0, "error": str(e_task), "duration_sec": total_task_duration, "status": "failure_exception"}
    finally:
        if task_driver:
            task_driver.quit()
            logger.debug(f"{log_prefix_task}WebDriverを終了しました。")


def domo_back_to_past_domo_users(driver, current_user_id, shared_cookies):
    """
    自分の過去の活動記録にDOMOしてくれたユーザーに対して、そのユーザーの最新の活動記録にDOMOを返し、
    設定に基づいてフォローも試みます。並列処理に対応。

    Args:
        driver: メインのSelenium WebDriverインスタンス。主に自分の活動記録リストや
                各活動のDOMOユーザーリスト取得に使用されます。
                並列処理が無効の場合は、個々のユーザーインタラクションにも使用されます。
        current_user_id (str): 現在操作中のYAMAPユーザーID（自分自身）。
        shared_cookies (list): ログインセッションを共有するためのCookieのリスト。
                               並列処理時に各ワーカースレッドに渡されます。

    Returns:
        tuple[int, int]: フォローしたユーザーの総数と、DOMO返しに成功した総数。
                         (total_followed_count, total_domoed_back_count)
    """
    config = _get_config_cached() # main_config全体を取得
    if not config.get("enable_domo_back_to_past_users", False): # トップレベルのキーを参照
        logger.info("過去記事DOMOユーザーへのDOMO返し機能は設定で無効です。 (トップレベル設定による)")
        return 0, 0 # フォロー数とDOMO数を返す

    db_settings = _get_domo_back_settings() # 詳細設定は引き続き専用セクションから取得
    sf_settings = _get_search_follow_settings_for_domo_back() # フォロー条件用
    ad_settings = _get_action_delays_mpi() # アクション遅延用

    is_parallel_enabled = db_settings.get("enable_parallel_domo_back", False)
    max_workers = db_settings.get("max_workers_domo_back", 2) if is_parallel_enabled else 1
    if is_parallel_enabled and not shared_cookies:
        logger.warning("並列DOMO返しが有効ですが、共有Cookieが提供されませんでした。逐次処理にフォールバックします。")
        is_parallel_enabled = False

    log_prefix_main = "[DBF_MAIN] " # DOMO_BACK_FOLLOW_MAIN
    logger.info(f"{log_prefix_main}>>> 過去記事DOMOユーザーへのDOMO返し＆フォロー機能を開始します... (並列処理: {'有効 (MaxWorkers: ' + str(max_workers) + ')' if is_parallel_enabled else '無効'})")
    start_time = time.time()

    days_to_check_past = db_settings.get("max_days_to_check_past_activities", 30)
    max_past_activities_to_process = db_settings.get("max_past_activities_to_process", 5)
    max_users_per_activity = db_settings.get("max_users_to_domo_back_per_activity", 10) # 1活動あたりの処理ユーザー上限
    max_total_users_overall = db_settings.get("max_total_domo_back_users_per_run", 20) # 全体での処理ユーザー上限

    # 逐次処理用の遅延 (並列時はワーカースレッド側で `delay_per_worker_domo_back_sec` を使用)
    sequential_delay_action_sec = db_settings.get("delay_between_domo_back_action_sec", 5.0)

    my_profile_url = f"{BASE_URL}/users/{current_user_id}"
    total_domoed_back_count_session = 0
    total_followed_count_session = 0
    processed_users_for_domo_back_this_session = set() # (user_profile_url) を記録。セッション中重複処理防止

    processed_user_count_overall = 0 # 実際に処理(タスク投入or逐次処理)した総ユーザー数 (上限管理用)

    # 1. 自分の過去の活動記録を取得 (メインドライバー使用)
    logger.info(f"{log_prefix_main}過去 {days_to_check_past} 日間の自分の活動記録を取得します (最大 {max_past_activities_to_process} 件処理)。")
    my_past_activities_urls = get_my_activities_within_period(driver, my_profile_url, days_to_check_past)
    if not my_past_activities_urls:
        logger.info(f"{log_prefix_main}DOMO返し対象の過去の活動記録が見つかりませんでした。")
        return 0, 0

    activities_to_process = my_past_activities_urls[:max_past_activities_to_process]
    logger.info(f"{log_prefix_main}{len(activities_to_process)} 件の過去活動記録を処理対象とします。")

    with ThreadPoolExecutor(max_workers=max_workers) if is_parallel_enabled else nullcontext() as executor:
        for activity_idx, past_activity_url in enumerate(activities_to_process):
            if processed_user_count_overall >= max_total_users_overall:
                logger.info(f"{log_prefix_main}今回の実行での総処理ユーザー数が上限 ({max_total_users_overall}) に達しました。活動記録の確認を中断。")
                break

            activity_id_log = past_activity_url.split('/')[-1].split('?')[0]
            logger.info(f"{log_prefix_main}--- [{activity_idx+1}/{len(activities_to_process)}] 過去活動記録 ({activity_id_log}) のDOMOユーザーを確認 ---")

            # 2. 各過去記事のDOMOユーザーリストを取得 (メインドライバー使用)
            # get_domo_users_from_activity は内部で活動記録ページに遷移し、DOMOリストページにも遷移する
            current_url_before_domo_list = driver.current_url # DOMOユーザーリスト取得前のURLを保持
            past_domo_users_info = get_domo_users_from_activity(driver, past_activity_url)

            # DOMOユーザーリスト取得後、元のページ（または適切なページ）に戻る処理が必要な場合がある
            # ここでは、次の活動記録処理の前に driver.get(my_profile_url) 等でリセットされることを期待。
            # もし get_domo_users_from_activity が元のページに戻らない仕様なら、ここで戻す。
            # 今回は get_my_activities_within_period が最初にプロフィールページにいることを期待しているため、
            # get_domo_users_from_activity がどこに遷移しても、次のループの get_domo_users_from_activity や
            # ループ終了後の driver の状態はあまり問題にならないかもしれない。
            # ただし、逐次処理でメインドライバーを使う場合は、DOMOリスト取得後に元の活動記録検索ページなどに戻る必要がある。
            # 今回はDOMO返しなので、次の get_domo_users_from_activity のためにドライバーが特定の状態である必要はない。

            if not past_domo_users_info:
                logger.info(f"{log_prefix_main}活動記録 ({activity_id_log}) にDOMOユーザーがいませんでした。")
                continue

            users_processed_for_this_activity = 0
            futures_this_activity = []

            for domo_user_info in past_domo_users_info:
                if processed_user_count_overall >= max_total_users_overall:
                    logger.info(f"{log_prefix_main}総処理ユーザー数上限 ({max_total_users_overall}) のため、この活動記録内のユーザー処理中断。")
                    break
                if users_processed_for_this_activity >= max_users_per_activity:
                    logger.info(f"{log_prefix_main}活動記録 ({activity_id_log}) での処理ユーザー数が上限 ({max_users_per_activity}) に達しました。")
                    break

                user_profile_url = domo_user_info["profile_url"]
                user_name = domo_user_info["name"]
                user_id_short = user_profile_url.split('/')[-1]

                if user_id_short == str(current_user_id):
                    logger.debug(f"{log_prefix_main}ユーザー ({user_name}) は自分自身のためスキップ。")
                    continue
                if user_profile_url in processed_users_for_domo_back_this_session:
                    logger.debug(f"{log_prefix_main}ユーザー ({user_name}) はこのセッションで既に処理試行済みのためスキップ。")
                    continue

                processed_users_for_domo_back_this_session.add(user_profile_url) # これから処理するので追加

                if is_parallel_enabled and executor:
                    logger.info(f"{log_prefix_main}並列タスク投入: ユーザー「{user_name}」(ID: {user_id_short})")
                    future = executor.submit(_domo_back_and_follow_task,
                                             user_profile_url, user_name, shared_cookies,
                                             current_user_id, db_settings, sf_settings, ad_settings)
                    futures_this_activity.append(future)
                else: # 逐次処理
                    logger.info(f"{log_prefix_main}逐次処理開始: ユーザー「{user_name}」(ID: {user_id_short})")
                    # ---- 逐次処理ロジック (メインドライバー使用) ----
                    # プロフィールページへ移動
                    driver.get(user_profile_url)
                    try:
                        WebDriverWait(driver, 15).until(EC.url_contains(user_id_short))
                    except TimeoutException:
                        logger.warning(f"{log_prefix_main}ユーザー「{user_name}」プロフィールページ読み込みタイムアウト（逐次）。スキップ。")
                        # 元のページに戻る処理 (get_domo_users_from_activity がどこにいるかによる)
                        # driver.get(current_url_before_domo_list) # 例えば
                        continue

                    temp_followed_count = 0
                    temp_domoed_count = 0

                    # フォロー試行 (逐次)
                    if db_settings.get("enable_follow_during_domo_back", False):
                        follow_button_seq = find_follow_button_on_profile_page(driver)
                        if follow_button_seq:
                            min_f_seq = sf_settings.get("min_followers_for_search_follow", 20)
                            ratio_t_seq = sf_settings.get("follow_ratio_threshold_for_search", 0.9)
                            f_counts_seq, f_ers_seq = get_user_follow_counts(driver, user_profile_url)
                            if f_counts_seq != -1 and f_ers_seq != -1 and f_ers_seq >= min_f_seq:
                                ratio_seq = (f_counts_seq / f_ers_seq) if f_ers_seq > 0 else float('inf')
                                if ratio_seq >= ratio_t_seq:
                                    if click_follow_button_and_verify(driver, follow_button_seq, user_name):
                                        temp_followed_count = 1
                                        total_followed_count_session +=1
                                        time.sleep(ad_settings.get("after_follow_action_sec", 2.0))

                    # DOMO試行 (逐次)
                    should_domo_seq = True
                    if db_settings.get("enable_domo_only_if_i_am_not_following", True):
                         is_following_now_seq = (temp_followed_count == 1) or (not find_follow_button_on_profile_page(driver))
                         if is_following_now_seq:
                             should_domo_seq = False
                             logger.info(f"{log_prefix_main}自分がフォロー中のためDOMOスキップ（逐次）: {user_name}")

                    if should_domo_seq:
                        latest_act_url_seq = get_latest_activity_url(driver, user_profile_url)
                        if latest_act_url_seq:
                            if domo_activity(driver, latest_act_url_seq, BASE_URL):
                                temp_domoed_count = 1
                                total_domoed_back_count_session += 1
                        else: logger.info(f"{log_prefix_main}最新活動なし DOMOスキップ（逐次）: {user_name}")

                    logger.info(f"{log_prefix_main}逐次処理完了: {user_name}, Followed: {temp_followed_count}, Domoed: {temp_domoed_count}")
                    time.sleep(sequential_delay_action_sec) # 逐次処理のユーザー間遅延
                    # 逐次処理の場合、次のユーザーのために driver の状態をリセットする必要があるか確認。
                    # get_domo_users_from_activity の後の状態による。
                    # driver.get(current_url_before_domo_list) など。
                    # 今回は次のユーザーもプロフィールページに直接飛ぶので、大きな問題はない。

                users_processed_for_this_activity += 1
                processed_user_count_overall +=1


            # この活動記録の並列タスク結果処理 (is_parallel_enabled の場合のみ)
            if is_parallel_enabled and futures_this_activity:
                logger.info(f"{log_prefix_main}活動記録 ({activity_id_log}): 投入された {len(futures_this_activity)} 件の並列タスクの結果を処理...")
                for future_item in as_completed(futures_this_activity):
                    try:
                        result = future_item.result()
                        res_user_name_log = result.get("user_name", "不明ユーザー")
                        if result.get("error"):
                            logger.error(f"{log_prefix_main}並列タスクエラー (ユーザー: {res_user_name_log}): {result['error']}")
                        else:
                            log_level = logging.INFO if result.get("followed") or result.get("domoed") else logging.DEBUG
                            logger.log(log_level, f"{log_prefix_main}並列タスク完了 (ユーザー: {res_user_name_log}, "
                                                f"Followed: {result.get('followed',0)}, Domoed: {result.get('domoed',0)}, "
                                                f"Skipped: '{result.get('skipped_reason','なし')}', Duration: {result.get('duration_sec', -1):.2f}s)")
                            total_followed_count_session += result.get("followed", 0)
                            total_domoed_back_count_session += result.get("domoed", 0)
                    except Exception as e_future_res:
                        logger.error(f"{log_prefix_main}並列DOMO返しタスクの結果取得/処理中にエラー: {e_future_res}", exc_info=True)

            logger.info(f"{log_prefix_main}--- 活動記録 ({activity_id_log}) のDOMOユーザーへの処理終了 ---")
            # メインドライバーがDOMOユーザー一覧ページなどにいる可能性があるので、次の活動記録処理の前にリセットする方が安全
            if activity_idx < len(activities_to_process) - 1: #最後の活動でなければ
                logger.debug(f"{log_prefix_main}次の活動記録処理のため、メインドライバーをプロフィールページに戻します。")
                driver.get(my_profile_url)
                WebDriverWait(driver, 10).until(EC.url_contains(current_user_id))


    end_time = time.time()
    logger.info(f"{log_prefix_main}<<< 過去記事DOMOユーザーへのDOMO返し＆フォロー機能完了。処理時間: {end_time - start_time:.2f}秒。")
    logger.info(f"{log_prefix_main}  合計フォロー成功数: {total_followed_count_session}")
    logger.info(f"{log_prefix_main}  合計DOMO返し成功数: {total_domoed_back_count_session}")
    return total_followed_count_session, total_domoed_back_count_session
