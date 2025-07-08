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
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver # 並列処理でwebdriverを直接使うため

# .driver_utils から main_config の読み込み関数と Cookie付きドライバ作成関数、スクリーンショット保存関数をインポート
from .driver_utils import get_main_config, create_driver_with_cookies, get_driver_options, save_screenshot
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

# --- 設定情報の読み込み (キャッシュ対応) ---
_main_config_cache_sf = None
def _get_config_cached_sf():
    global _main_config_cache_sf
    if _main_config_cache_sf is None:
        _main_config_cache_sf = get_main_config()
        if not _main_config_cache_sf:
            logger.error("search_utils: main_config の読み込みに失敗しました。")
            _main_config_cache_sf = {}
    return _main_config_cache_sf

def _get_search_follow_settings():
    config = _get_config_cached_sf()
    settings = config.get("search_and_follow_settings", {})
    if not settings:
        logger.warning("search_utils: config.yaml に search_and_follow_settings が見つからないか空です。")
    return settings

def _get_action_delays_sf():
    config = _get_config_cached_sf()
    return config.get("action_delays", {})


# --- 並列処理用ワーカースレッドタスク ---
def _search_follow_domo_task(user_profile_url, user_name_for_log, shared_cookies, sf_settings, ad_settings, current_user_id_for_task):
    """
    並列処理用のワーカースレッドタスク。
    指定されたユーザープロフィールURLにアクセスし、条件確認、フォロー、DOMOを実行する。
    """
    task_driver = None
    task_followed_count = 0
    task_domoed_count = 0
    user_id_for_log = user_profile_url.split('/')[-1]
    log_prefix_task = f"[SF_TASK][{user_id_for_log}] "
    status_message = f"ユーザー「{user_name_for_log}」(ID: {user_id_for_log}): " # ログメッセージ統一のため調整
    task_start_time = time.time()
    logger.info(f"{log_prefix_task}処理開始。ユーザー: {user_name_for_log} ({user_profile_url})")

    try:
        step_start_time = time.time()
        logger.info(f"{log_prefix_task}WebDriverを作成し、Cookieを設定・検証します。(ログインユーザーID: {current_user_id_for_task})")
        task_driver = create_driver_with_cookies(shared_cookies, current_user_id_for_task)
        logger.debug(f"{log_prefix_task}WebDriver作成・Cookie設定・検証 所要時間: {time.time() - step_start_time:.2f}秒")
        if not task_driver:
            logger.error(f"{log_prefix_task}WebDriverの作成またはCookie/ログイン検証に失敗。タスクを中止。")
            return {"profile_url": user_profile_url, "user_name": user_name_for_log, "followed": 0, "domoed": 0, "error": "WebDriver/ログイン検証失敗", "duration_sec": time.time() - task_start_time, "status": "failure_driver_creation"}

        step_start_time = time.time()
        logger.info(f"{log_prefix_task}ログイン検証済み。対象のプロフィールページ ({user_profile_url}) へアクセスします。")
        task_driver.get(user_profile_url)
        try:
            WebDriverWait(task_driver, 20).until(
                EC.all_of(
                    EC.url_contains(user_id_for_log),
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "h1.css-jctfiw")),
                    lambda d: d.execute_script("return document.readyState") == "complete",
                    EC.presence_of_element_located((By.CSS_SELECTOR, "footer.css-1yg0z07"))
                )
            )
            logger.info(f"{log_prefix_task}プロフィールページ ({user_profile_url}) の主要要素読み込みを確認。所要時間: {time.time() - step_start_time:.2f}秒")
        except TimeoutException:
            logger.warning(f"{log_prefix_task}プロフィールページ ({user_profile_url}) の読み込みタイムアウト。所要時間: {time.time() - step_start_time:.2f}秒")
            return {"profile_url": user_profile_url, "user_name": user_name_for_log, "followed": 0, "domoed": 0, "error": "プロフィールページ読み込みタイムアウト", "duration_sec": time.time() - task_start_time, "status": "failure_profile_load_timeout"}

        if user_id_for_log not in task_driver.current_url: # URL検証をより厳密に
            logger.error(f"{log_prefix_task}URL不一致: 期待したプロフィールページ ({user_profile_url}) にいません。現在のURL: {task_driver.current_url}。スキップ。")
            return {"profile_url": user_profile_url, "user_name": user_name_for_log, "followed": 0, "domoed": 0, "error": "プロフィールページURL不一致", "duration_sec": time.time() - task_start_time, "status": "failure_profile_url_mismatch"}

        step_start_time = time.time()
        follow_button_on_profile = find_follow_button_on_profile_page(task_driver)
        logger.debug(f"{log_prefix_task}フォローボタン探索 所要時間: {time.time() - step_start_time:.2f}秒")
        if not follow_button_on_profile:
            logger.info(f"{status_message}既にフォロー済みか、フォローボタンがありません。スキップ。")
            return {"profile_url": user_profile_url, "user_name": user_name_for_log, "followed": 0, "domoed": 0, "error": None, "skipped_reason": "既にフォロー済み/ボタンなし", "duration_sec": time.time() - task_start_time, "status": "skipped_already_followed_or_no_button"}

        min_followers = sf_settings.get("min_followers_for_search_follow", 20)
        ratio_threshold = sf_settings.get("follow_ratio_threshold_for_search", 0.9)
        domo_after_follow_task = sf_settings.get("domo_latest_activity_after_follow", True)
        delay_worker_user_proc = sf_settings.get("delay_per_worker_user_processing_sec", 3.5)

        step_start_time = time.time()
        follows, followers = get_user_follow_counts(task_driver, user_profile_url)
        logger.debug(f"{log_prefix_task}フォロー数/フォロワー数取得 所要時間: {time.time() - step_start_time:.2f}秒")
        if follows == -1 or followers == -1:
            logger.warning(f"{status_message}フォロー数/フォロワー数が取得できませんでした。スキップ。")
            return {"profile_url": user_profile_url, "user_name": user_name_for_log, "followed": 0, "domoed": 0, "error": "フォロー数/フォロワー数取得失敗", "duration_sec": time.time() - task_start_time, "status": "failure_follow_counts_retrieval"}
        if followers < min_followers:
            logger.info(f"{status_message}フォロワー数 ({followers}) が閾値 ({min_followers}) 未満。スキップ。")
            return {"profile_url": user_profile_url, "user_name": user_name_for_log, "followed": 0, "domoed": 0, "error": None, "skipped_reason": f"フォロワー数不足({followers}<{min_followers})", "duration_sec": time.time() - task_start_time, "status": "skipped_low_followers"}

        current_ratio = (follows / followers) if followers > 0 else float('inf')
        logger.info(f"{status_message}F中={follows}, Fワー={followers}, Ratio={current_ratio:.2f} (閾値: >= {ratio_threshold})")
        if not (current_ratio >= ratio_threshold):
            logger.info(f"{status_message}Ratio ({current_ratio:.2f}) が閾値 ({ratio_threshold}) 未満。スキップ。")
            return {"profile_url": user_profile_url, "user_name": user_name_for_log, "followed": 0, "domoed": 0, "error": None, "skipped_reason": f"Ratio不足({current_ratio:.2f}<{ratio_threshold})", "duration_sec": time.time() - task_start_time, "status": "skipped_low_ratio"}

        logger.info(f"{status_message}フォロー条件を満たしました。フォローします。")
        step_start_time = time.time()
        if click_follow_button_and_verify(task_driver, follow_button_on_profile, user_name_for_log):
            task_followed_count = 1
            logger.info(f"{status_message}フォロー成功。所要時間: {time.time() - step_start_time:.2f}秒")
            if domo_after_follow_task:
                logger.info(f"{status_message}最新活動記録にDOMOを試みます。")
                domo_step_start_time = time.time()
                latest_act_url = get_latest_activity_url(task_driver, user_profile_url)
                logger.debug(f"{log_prefix_task}最新活動記録URL取得 所要時間: {time.time() - domo_step_start_time:.2f}秒")
                if latest_act_url:
                    domo_action_start_time = time.time()
                    if domo_activity(task_driver, latest_act_url, BASE_URL):
                        task_domoed_count = 1
                        logger.info(f"{status_message}最新活動記録へのDOMO成功。URL: {latest_act_url}。所要時間: {time.time() - domo_action_start_time:.2f}秒")
                    else:
                        logger.warning(f"{status_message}最新活動記録へのDOMO失敗。URL: {latest_act_url}。所要時間: {time.time() - domo_action_start_time:.2f}秒")
                else:
                    logger.info(f"{status_message}最新活動記録が見つからず、DOMOできませんでした。")
        else:
            logger.warning(f"{status_message}フォロー失敗。所要時間: {time.time() - step_start_time:.2f}秒")

        time.sleep(delay_worker_user_proc) # ユーザー処理後の共通遅延
        total_task_duration = time.time() - task_start_time
        logger.info(f"{log_prefix_task}処理完了。総所要時間: {total_task_duration:.2f}秒。結果: Followed={task_followed_count}, Domoed={task_domoed_count}")
        return {"profile_url": user_profile_url, "user_name": user_name_for_log, "followed": task_followed_count, "domoed": task_domoed_count, "error": None, "duration_sec": total_task_duration, "status": "success"}

    except Exception as e_task:
        total_task_duration = time.time() - task_start_time
        logger.error(f"{status_message}並列処理タスク中に予期せぬエラー: {e_task}", exc_info=True)
        return {"profile_url": user_profile_url, "user_name": user_name_for_log, "followed": 0, "domoed": 0, "error": str(e_task), "duration_sec": total_task_duration, "status": "failure_exception"}
    finally:
        if task_driver:
            task_driver.quit()
            logger.debug(f"{log_prefix_task}WebDriverを終了しました。")


# --- 検索からのフォロー＆DOMO機能 (メインロジック) ---
def search_follow_and_domo_users(driver, current_user_id, shared_cookies_from_main=None):
    """
    活動記録検索ページを巡回し、条件に合うユーザーをフォローし、
    そのユーザーの最新活動記録にDOMOする。
    config.yaml の search_and_follow_settings に従って動作する。並列処理対応。
    """
    sf_settings = _get_search_follow_settings()
    ad_settings = _get_action_delays_sf()

    if not sf_settings.get("enable_search_and_follow", False):
        logger.info("検索からのフォロー＆DOMO機能は設定で無効になっています。")
        return {'followed': 0, 'domoed': 0}

    is_parallel_enabled = sf_settings.get("enable_parallel_search_follow", False)
    max_workers = sf_settings.get("max_workers_search_follow", 2) if is_parallel_enabled else 1
    if is_parallel_enabled and not shared_cookies_from_main:
        logger.warning("並列検索＆フォローが有効ですが、共有Cookieが提供されませんでした。逐次処理にフォールバックします。")
        is_parallel_enabled = False

    log_prefix_main = "[SF_MAIN] "
    logger.info(f"{log_prefix_main}>>> 検索からのフォロー＆DOMO機能を開始します... (並列処理: {'有効 (MaxWorkers: ' + str(max_workers) + ')' if is_parallel_enabled else '無効'})")

    start_url = sf_settings.get("search_activities_url", SEARCH_ACTIVITIES_URL_DEFAULT)
    max_pages = sf_settings.get("max_pages_to_process_search", 1)
    max_users_per_page = sf_settings.get("max_users_to_process_per_page", 5)
    # 逐次処理用の遅延 (並列時はワーカースレッド側で `delay_per_worker_user_processing_sec` を使用)
    sequential_delay_user_processing = sf_settings.get("delay_between_user_processing_in_search_sec", 5.0)
    delay_pagination = ad_settings.get("delay_after_pagination_sec", 3.0) # これはACTION_DELAYSから取得

    # パフォーマンス計測用
    function_start_time = time.time()
    processed_user_count_session = 0 # 実際にタスク投入または逐次処理されたユーザー数

    # 並列/逐次共通の設定
    min_followers_seq = sf_settings.get("min_followers_for_search_follow", 20)
    ratio_threshold_seq = sf_settings.get("follow_ratio_threshold_for_search", 0.9)
    domo_after_follow_seq = sf_settings.get("domo_latest_activity_after_follow", True)


    total_followed_count_session = 0
    total_domoed_count_session = 0

    activity_card_selector = "article[data-testid='activity-entry']"
    user_profile_link_in_card_selector = "div.css-1vh31zw > a.css-k2fvpp[href^='/users/']"

    # processed_profile_urls はセッション全体で共有し、重複処理を避ける
    processed_profile_urls_session = set()


    with ThreadPoolExecutor(max_workers=max_workers) if is_parallel_enabled else nullcontext() as executor:
        for page_num in range(1, max_pages + 1):
            processed_users_on_current_page_count = 0 # このページで実際に処理(タスク投入or逐次処理)したユーザー数
            futures_this_page = [] # このページで投入した並列タスクのFuture

            current_page_url_for_log = driver.current_url # ページネーション前のURLをログ用に保持

            # --- ページネーション処理 (メインドライバー) ---
            if page_num > 1:
                logger.info(f"{page_num-1}ページ目({current_page_url_for_log})の処理完了。次のページ ({page_num}ページ目) へ遷移を試みます。")
                next_button_selectors = [
                    "button[data-testid='MoveToNextButton']",  # 最優先のセレクタ (2024/07/09確認)
                    "a[data-testid='pagination-next-button']", # 以前のdata-testid
                    "button[aria-label='次のページに移動する']",  # aria-labelによる指定 (日本語)
                    "button[aria-label='Go to next page']",    # aria-labelによる指定 (英語の可能性も考慮)
                    "a[rel='next']",
                    "a.next", "button.next", # 一般的なクラス名
                    "a.pagination__next", "button.pagination__next", # 一般的なページネーションクラス
                    # より広範なaria-label指定 (無効状態を除外)
                    "a[aria-label*='次へ']:not([aria-disabled='true'])",
                    "a[aria-label*='Next']:not([aria-disabled='true'])",
                    "button[aria-label*='次へ']:not([disabled])",
                    "button[aria-label*='Next']:not([disabled])"
                ]
                next_button_found = False
                for selector_idx, selector in enumerate(next_button_selectors):
                    log_prefix_paginate = f"[PAGINATE][Page {page_num-1} to {page_num}][Selector {selector_idx+1}/{len(next_button_selectors)} ('{selector}')]"
                    try:
                        logger.debug(f"{log_prefix_paginate} 「次へ」ボタンの探索開始...")
                        # 要素の存在と表示をまず確認
                        WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        # 次にクリック可能性を確認
                        next_button = WebDriverWait(driver, 2).until( # presence確認後なのでタイムアウト短縮
                            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                        )
                        # is_displayed() と is_enabled() は Selenium 4 ではより堅牢なチェックが推奨されるが、ここでは残す
                        if next_button and next_button.is_displayed() and next_button.is_enabled():
                            logger.info(f"{log_prefix_paginate} クリック可能な「次へ」ボタンを発見。クリックします。")
                            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center', inline: 'nearest'});", next_button)
                            time.sleep(0.7) # スクロールと描画の安定待ち
                            # クリック前に再度要素が stale になっていないか確認することも検討できる
                            # next_button.click() の代わりに JavaScript でクリックも検討
                            driver.execute_script("arguments[0].click();", next_button)
                            logger.info(f"{log_prefix_paginate} 「次へ」ボタンをクリック実行。")
                            next_button_found = True
                            break # セレクタのループを抜ける
                        else:
                            logger.debug(f"{log_prefix_paginate} ボタンは存在しましたが、表示されていないか有効ではありませんでした。")
                    except TimeoutException:
                        logger.debug(f"{log_prefix_paginate} 「次へ」ボタンが見つからずタイムアウト。")
                    except Exception as e_click:
                        logger.warning(f"{log_prefix_paginate} ボタン探索またはクリック試行中に予期せぬエラー: {e_click}", exc_info=False) # exc_info=Falseでスタックトレースを抑制

                if not next_button_found:
                    logger.error(f"ページ {page_num-1} ({current_page_url_for_log}) で試行した全てのセレクタで、クリック可能な「次へ」ボタンが見つかりませんでした。検索結果のページネーション処理を終了します。")
                    save_screenshot(driver, "NextButtonNotFound_Search", f"Page{page_num-1}_URL_{current_page_url_for_log.replace('/', '_')}")
                    break # for page_num ループを抜ける
                try:
                    logger.info(f"「次へ」ボタンクリック後、ページ遷移 ({page_num}ページ目) を確認します。旧URL: {current_page_url_for_log}")
                    WebDriverWait(driver, 15).until(EC.url_changes(current_page_url_for_log))
                    logger.info(f"{page_num}ページ目へ正常に遷移しました。新しいURL: {driver.current_url}")
                    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    logger.info(f"{page_num}ページ目の活動記録カードの読み込みを確認。")
                    time.sleep(delay_pagination)
                except TimeoutException:
                    logger.warning(f"{page_num}ページ目への遷移後、URL変化または活動記録カードの読み込みタイムアウト。処理を終了します。")
                    break # for page_num ループを抜ける
                except Exception as e_page_load:
                    logger.error(f"{page_num}ページ目への遷移または読み込み中に予期せぬエラー: {e_page_load}", exc_info=True)
                    break # for page_num ループを抜ける

            # 1ページ目のアクセス (driver.get はメインドライバーで行う)
            if page_num == 1 and driver.current_url != start_url :
                 logger.info(f"最初の活動記録検索結果 ({start_url}) にアクセスします。")
                 driver.get(start_url)
            try:
                WebDriverWait(driver, 15).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, activity_card_selector)))
            except TimeoutException:
                page_identifier_for_log = start_url if page_num == 1 else driver.current_url
                logger.warning(f"活動記録検索結果ページ ({page_identifier_for_log}) で活動記録カードの読み込みタイムアウト。このページの処理をスキップします。")
                continue # 次の for page_num へ

            initial_activity_cards_on_page = driver.find_elements(By.CSS_SELECTOR, activity_card_selector)
            logger.info(f"{page_num}ページ目: {len(initial_activity_cards_on_page)} 件の活動記録候補を検出。")
            if not initial_activity_cards_on_page:
                logger.info("このページには活動記録が見つかりませんでした。")
                continue # 次の for page_num へ

            # --- ユーザー情報収集 (メインドライバー) ---
            user_infos_for_tasks = []
            logger.info(f"{log_prefix_main}ページ {page_num}/{max_pages}: 活動記録カードからのユーザー情報収集開始 (最大{max_users_per_page}ユーザー)。")
            for card_idx, card_element in enumerate(initial_activity_cards_on_page):
                if len(user_infos_for_tasks) >= max_users_per_page : # このページで処理するユーザー数上限
                    logger.info(f"{log_prefix_main}ページ {page_num}: 処理対象ユーザー数上限 ({max_users_per_page}) に達したため、情報収集を停止。")
                    break

                temp_user_profile_url = None
                temp_user_name_for_log = f"活動記録{card_idx+1}のユーザー(P{page_num})"
                try:
                    # StaleElement対策のため、ループ内で毎回要素を再取得するのではなく、
                    # initial_activity_cards_on_page から得た card_element を使う。
                    # ただし、この card_element も後続のDOM変更でStaleになる可能性はあるが、
                    # ここではURLと名前の取得のみに留める。
                    profile_link_el = WebDriverWait(card_element, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, user_profile_link_in_card_selector))
                    )
                    href = profile_link_el.get_attribute("href")
                    if href:
                        if href.startswith("/"): temp_user_profile_url = BASE_URL + href
                        elif href.startswith(BASE_URL): temp_user_profile_url = href

                    if not temp_user_profile_url or f"/users/{current_user_id}" in temp_user_profile_url:
                        logger.debug(f"無効なプロフィールURLか自分自身 ({temp_user_profile_url}) のためスキップ(情報収集時)。")
                        continue
                    if temp_user_profile_url in processed_profile_urls_session: # セッション全体での重複チェック
                        logger.info(f"ユーザー ({temp_user_profile_url.split('/')[-1]}) はこのセッションで既に処理試行済みのためスキップ(情報収集時)。")
                        continue

                    try: # 名前取得はベストエフォート
                        name_el = profile_link_el.find_element(By.CSS_SELECTOR, "span, img[alt]")
                        if name_el.tag_name == "img": temp_user_name_for_log = name_el.get_attribute("alt")
                        else: temp_user_name_for_log = name_el.text.strip()
                        if not temp_user_name_for_log: temp_user_name_for_log = temp_user_profile_url.split('/')[-1]
                    except: pass

                    user_infos_for_tasks.append({"url": temp_user_profile_url, "name": temp_user_name_for_log})
                    processed_profile_urls_session.add(temp_user_profile_url) # タスク投入（または逐次処理）決定なので、ここで処理済みに追加

                except NoSuchElementException:
                    logger.warning(f"活動記録カード {card_idx+1} (P{page_num}) からユーザー情報取得に必要な要素が見つかりません。スキップ(情報収集時)。")
                except Exception as e_info_collect:
                    logger.error(f"活動記録カード {card_idx+1} (P{page_num}) の情報収集中にエラー: {e_info_collect}", exc_info=True)

            # --- タスク投入または逐次処理 ---
            search_page_url_before_profile_visit_main = driver.current_url # 逐次処理で戻るためのURL
            for user_info in user_infos_for_tasks:
                if processed_users_on_current_page_count >= max_users_per_page: # 二重チェック
                    break

                if is_parallel_enabled and executor:
                    logger.info(f"{log_prefix_main}ページ {page_num}: 並列タスク投入 - ユーザー「{user_info['name']}」(ID: {user_info['url'].split('/')[-1]})")
                    future = executor.submit(_search_follow_domo_task, user_info['url'], user_info['name'], shared_cookies_from_main, sf_settings, ad_settings, current_user_id)
                    futures_this_page.append(future)
                    processed_user_count_session +=1 # 並列タスク投入も処理ユーザーとしてカウント
                else: # 逐次処理
                    logger.info(f"{log_prefix_main}ページ {page_num}: 逐次処理開始 - ユーザー「{user_info['name']}」(ID: {user_info['url'].split('/')[-1]})")
                    processed_user_count_session +=1 # 逐次処理も処理ユーザーとしてカウント
                    # メインドライバーで直接処理
                    driver.get(user_info['url']) # プロフィールページへ
                    try:
                        WebDriverWait(driver, 20).until(
                            EC.all_of(
                                EC.url_contains(user_info['url'].split('/')[-1]),
                                EC.visibility_of_element_located((By.CSS_SELECTOR, "h1.css-jctfiw")),
                                lambda d: d.execute_script("return document.readyState") == "complete",
                                EC.presence_of_element_located((By.CSS_SELECTOR, "footer.css-1yg0z07"))
                            )
                        )
                    except TimeoutException:
                        logger.warning(f"ユーザー「{user_info['name']}」プロフィールページ読み込みタイムアウト（逐次）。スキップ。")
                        driver.get(search_page_url_before_profile_visit_main) # 検索結果ページに戻る
                        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                        continue # 次のユーザーへ

                    if user_info['url'] not in driver.current_url:
                         logger.error(f"URL不一致(逐次): プロフィールページ ({user_info['url']}) にいるはずが {driver.current_url} 。スキップ。")
                         driver.get(search_page_url_before_profile_visit_main)
                         WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                         continue

                    follow_button_seq = find_follow_button_on_profile_page(driver)
                    if not follow_button_seq:
                        logger.info(f"ユーザー「{user_info['name']}」は既にフォロー済みかボタンなし（逐次）。スキップ。")
                    else:
                        follows_seq, followers_seq = get_user_follow_counts(driver, user_info['url'])
                        if follows_seq != -1 and followers_seq != -1 and followers_seq >= min_followers_seq:
                            current_ratio_seq = (follows_seq / followers_seq) if followers_seq > 0 else float('inf')
                            if current_ratio_seq >= ratio_threshold_seq:
                                logger.info(f"ユーザー「{user_info['name']}」フォロー条件合致（逐次）。フォローします。")
                                if click_follow_button_and_verify(driver, follow_button_seq, user_info['name']):
                                    total_followed_count_session += 1
                                    if domo_after_follow_seq:
                                        logger.info(f"ユーザー「{user_info['name']}」最新活動記録DOMO試行（逐次）。")
                                        latest_act_url_seq = get_latest_activity_url(driver, user_info['url'])
                                        if latest_act_url_seq:
                                            if domo_activity(driver, latest_act_url_seq, BASE_URL):
                                                total_domoed_count_session += 1
                                        else: logger.info(f"ユーザー「{user_info['name']}」最新活動記録なし（逐次）。")
                            else: logger.info(f"ユーザー「{user_info['name']}」Ratio不足（逐次）。")
                        else: logger.info(f"ユーザー「{user_info['name']}」フォロワー数不足または取得失敗（逐次）。")

                    logger.info(f"--- ユーザー「{user_info['name']}」の逐次処理終了 ---")
                    driver.get(search_page_url_before_profile_visit_main) # 検索結果ページに戻る
                    try:
                        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    except TimeoutException: logger.warning(f"検索結果ページ ({search_page_url_before_profile_visit_main}) への復帰後、カード再表示タイムアウト。")
                    time.sleep(sequential_delay_user_processing) # 逐次処理のユーザー間遅延

                processed_users_on_current_page_count +=1


            # --- このページの並列タスク結果処理 (is_parallel_enabled の場合のみ) ---
            if is_parallel_enabled and futures_this_page:
                logger.info(f"{log_prefix_main}ページ {page_num}: 投入された {len(futures_this_page)} 件の並列タスクの結果を処理します...")
                for future_item in as_completed(futures_this_page):
                    try:
                        result = future_item.result() # _search_follow_domo_task からの戻り値
                        res_user_name_log = result.get("user_name", result.get("profile_url", "不明なユーザー").split('/')[-1])
                        res_status_log = result.get("status", "不明なステータス")
                        res_duration_log = result.get("duration_sec", -1)

                        if result.get("error"):
                            logger.error(f"{log_prefix_main}並列タスクエラー (ユーザー: {res_user_name_log}, ステータス: {res_status_log}, 所要時間: {res_duration_log:.2f}秒): {result['error']}")
                        else:
                            log_level = logging.INFO if result.get("followed") or result.get("domoed") or not result.get("skipped_reason") else logging.DEBUG
                            logger.log(log_level, f"{log_prefix_main}並列タスク完了 (ユーザー: {res_user_name_log}, "
                                                f"Followed: {result.get('followed',0)}, Domoed: {result.get('domoed',0)}, "
                                                f"Skipped: '{result.get('skipped_reason','なし')}', ステータス: {res_status_log}, 所要時間: {res_duration_log:.2f}秒)")
                            total_followed_count_session += result.get("followed", 0)
                            total_domoed_count_session += result.get("domoed", 0)
                    except Exception as e_future_res:
                        logger.error(f"{log_prefix_main}並列検索フォロータスクの結果取得/処理中に予期せぬエラー: {e_future_res}", exc_info=True)

            logger.info(f"{log_prefix_main}ページ {page_num}/{max_pages} の処理が完了しました。")
            # ページネーション後の遅延はループの先頭で次のページ読み込み後に行われる (delay_pagination)

    # --- パフォーマンスサマリー ---
    function_end_time = time.time()
    total_function_duration = function_end_time - function_start_time
    users_per_second = processed_user_count_session / total_function_duration if total_function_duration > 0 else 0

    logger.info(f"{log_prefix_main}---------- 検索＆フォロー機能 パフォーマンスサマリー ----------")
    logger.info(f"{log_prefix_main}総処理時間: {total_function_duration:.2f} 秒")
    logger.info(f"{log_prefix_main}処理対象として試行した総ユーザー数: {processed_user_count_session} 人")
    logger.info(f"{log_prefix_main}実際にフォローした総数: {total_followed_count_session} 人")
    logger.info(f"{log_prefix_main}実際にDOMOした総数: {total_domoed_count_session} 件")
    logger.info(f"{log_prefix_main}1秒あたりの処理ユーザー数 (スループット): {users_per_second:.2f} 人/秒")
    logger.info(f"{log_prefix_main}-------------------------------------------------------------")

    logger.info(f"{log_prefix_main}<<< 検索からのフォロー＆DOMO機能完了。セッション合計フォロー: {total_followed_count_session}人, セッション合計DOMO: {total_domoed_count_session}件。")
    return {'followed': total_followed_count_session, 'domoed': total_domoed_count_session}


# nullcontext for Python < 3.7
try:
    from contextlib import nullcontext
except ImportError:
    import contextlib
    @contextlib.contextmanager
    def nullcontext(enter_result=None):
        yield enter_result
