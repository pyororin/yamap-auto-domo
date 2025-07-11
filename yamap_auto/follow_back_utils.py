# coding: utf-8
"""
YAMAP フォローバック関連ユーティリティ関数群
自分をフォローしてくれたユーザーへのフォローバック操作を担当
"""
import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver  # 並列処理でwebdriverを直接使うため

# .driver_utils から main_config の読み込み関数と Cookie付きドライバ作成関数、スクリーンショット保存関数をインポート
from .driver_utils import get_main_config, create_driver_with_cookies, get_driver_options, save_screenshot
# .follow_utils からフォローボタン検索・クリック関数をインポート
from .follow_utils import find_follow_button_in_list_item, click_follow_button_and_verify

logger = logging.getLogger(__name__)

# --- グローバル定数 ---
BASE_URL = "https://yamap.com"  # このファイルでも直接URLを組み立てるために必要

# --- 設定情報の読み込み ---
_main_config_cache = None


def _get_config_cached():
    """ 設定情報をキャッシュを使って取得 """
    global _main_config_cache
    if _main_config_cache is None:
        _main_config_cache = get_main_config()
        if not _main_config_cache:
            logger.error("follow_back_utils: main_config の読み込みに失敗しました。")
            _main_config_cache = {}  # フォールバック
    return _main_config_cache


def _get_follow_back_settings():
    config = _get_config_cached()
    settings = config.get("follow_back_settings", {})
    if not settings:
        logger.warning("follow_back_utils: config.yaml に follow_back_settings が見つからないか空です。")
    return settings


def _get_action_delays():
    config = _get_config_cached()
    return config.get("action_delays", {})

# --- 並列処理用ワーカースレッドタスク ---


def _follow_back_task(page_url, user_profile_url_to_find, user_name_to_find, shared_cookies, follow_back_settings_for_task, action_delays_for_task, current_user_id_for_task):
    """
    並列処理用のワーカースレッドタスク。
    指定されたページURLにアクセスし、対象ユーザーを見つけてフォローバックを試みる。
    """
    task_driver = None
    followed_in_task = False
    user_id_short = user_profile_url_to_find.split('/')[-1]
    # page_url からドメイン部分を除去してログを見やすくする (例: /users/12345/followers?page=2)
    page_path_for_log = page_url.replace(BASE_URL, "")
    log_prefix_task = f"[FB_TASK][UID:{user_id_short}][Page:{page_path_for_log}] "
    status_message = f"{log_prefix_task}ユーザー「{user_name_to_find}」({user_id_short}): "

    logger.info(f"{log_prefix_task}並列フォローバックタスク開始。対象ユーザー名: {user_name_to_find}, プロフィールURL: {user_profile_url_to_find}, 処理対象ページ: {page_url}")

    try:
        logger.info(f"{log_prefix_task}新しいWebDriverインスタンスを作成し、Cookieを設定・検証します (ログイン中ユーザーID: {current_user_id_for_task})。")
        # `create_driver_with_cookies` は強化されたログイン検証（マイページでのアバター/URL確認など）を実行する
        task_driver = create_driver_with_cookies(shared_cookies, current_user_id_for_task)

        if not task_driver:
            # create_driver_with_cookies が None を返した場合、内部でエラーログとスクリーンショット取得済みのはず
            logger.error(f"{log_prefix_task}WebDriverの作成またはCookie/ログイン検証に失敗しました。タスクを中止します。")
            return {"profile_url": user_profile_url_to_find, "followed": False, "error": "WebDriver/ログイン検証失敗"}

        logger.info(f"{log_prefix_task}WebDriver作成とログイン検証成功。現在のURL: {task_driver.current_url} (マイページのはず)")
        logger.info(f"{log_prefix_task}目的のフォロワーリストページ ({page_url}) にアクセスします。")
        task_driver.get(page_url)
        logger.info(f"{log_prefix_task}フォロワーリストページ ({page_url}) にアクセス完了。現在のURL: {task_driver.current_url}")

        # フォロワーリストページで、リストコンテナが表示されるのを待つ
        followers_list_container_selector = "ul.css-18aka15"
        try:
            logger.debug(f"{log_prefix_task}フォロワーリストコンテナ ({followers_list_container_selector}) の表示を待ちます...")
            WebDriverWait(task_driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, followers_list_container_selector))
            )
            logger.info(f"{log_prefix_task}フォロワーリストコンテナをページ ({page_url}) で確認しました。")
        except TimeoutException:
            logger.error(f"{log_prefix_task}フォロワーリストページ ({page_url}) でリストコンテナの表示がタイムアウトしました。タスクを中止します。")
            context_info = f"UID_{current_user_id_for_task}_TargetURL_{page_url.replace('/', '_').replace(':', '_')}"
            save_screenshot(task_driver, "FollowerListLoadFail_FBTask", context_info)
            # HTMLも保存検討
            return {"profile_url": user_profile_url_to_find, "followed": False, "error": "フォロワーページ読み込み失敗"}

        time.sleep(0.7)  # 描画の安定待ちを少し延長

        # ページ内で対象ユーザーのカードを探す
        user_card_selector_in_task = "div[data-testid='user']"
        logger.debug(f"{log_prefix_task}ページ ({page_url}) 内で対象ユーザーカード ({user_card_selector_in_task}) を探します...")
        all_cards_on_page_in_task = task_driver.find_elements(By.CSS_SELECTOR, user_card_selector_in_task)
        logger.info(f"{log_prefix_task}{len(all_cards_on_page_in_task)} 件のユーザーカード候補を検出しました。")

        target_card_element = None
        for card_idx, card in enumerate(all_cards_on_page_in_task):
            try:
                user_link_in_card_sel = "a.css-e5vv35[href^='/users/']"
                link_el = card.find_element(By.CSS_SELECTOR, user_link_in_card_sel)
                href_attr = link_el.get_attribute("href")
                if href_attr:
                    full_href = href_attr if href_attr.startswith(BASE_URL) else BASE_URL + href_attr
                    if full_href == user_profile_url_to_find:
                        logger.debug(f"{log_prefix_task}対象ユーザーカード候補 {card_idx+1} のリンク ({full_href}) が目的のURLと一致。")
                        target_card_element = card
                        break
                    else:
                        logger.trace(f"{log_prefix_task}カード候補 {card_idx+1} のリンク ({full_href}) は対象外。")
            except NoSuchElementException:
                logger.trace(f"{log_prefix_task}カード候補 {card_idx+1} でユーザーリンク要素 ({user_link_in_card_sel}) が見つかりません。")
                continue

        if not target_card_element:
            logger.warning(f"{status_message}ページ ({page_url}) 内で対象ユーザーのカードが見つかりませんでした。")
            return {"profile_url": user_profile_url_to_find, "followed": False, "error": "対象ユーザーカード発見失敗"}

        logger.info(f"{status_message}対象ユーザーのカードを発見。フォロー状態を確認します。")
        follow_button = find_follow_button_in_list_item(target_card_element) # この関数は内部でログを出すはず
        if follow_button:
            logger.info(f"{status_message}はまだフォローしていません。並列タスク内でフォローバックを実行します。")
            delay_worker_action = follow_back_settings_for_task.get("delay_per_worker_action_sec", 2.5)
            logger.debug(f"{log_prefix_task}フォローアクション実行前の遅延: {delay_worker_action}秒")
            # click_follow_button_and_verify は内部でログを出すはず
            if click_follow_button_and_verify(task_driver, follow_button, user_name_to_find): # user_name_to_find はログ用
                followed_in_task = True
                logger.info(f"{status_message}フォローバック成功。")
            else:
                logger.warning(f"{status_message}フォローバック試行失敗。")
            time.sleep(delay_worker_action) # アクション後の遅延
        else:
            logger.info(f"{status_message}は既にフォロー済みか、フォローボタンが見つかりませんでした（並列タスク内）。")
            time.sleep(0.3)

        logger.info(f"{log_prefix_task}タスク処理完了。結果: {'フォロー成功' if followed_in_task else 'フォローせず/失敗'}。")
        return {"profile_url": user_profile_url_to_find, "followed": followed_in_task, "error": None}

    except Exception as e_task:
        logger.error(f"{status_message}並列処理タスク中に予期せぬエラーが発生しました: {e_task}", exc_info=True)
        # エラー発生時にもスクリーンショットを保存
        if task_driver: # driverが初期化されていれば
             context_info_err = f"UID_{current_user_id_for_task}_TargetUser_{user_id_short}_Page_{page_path_for_log.replace('/', '_')}"
             save_screenshot(task_driver, "ErrorInFBTask", context_info_err)
        return {"profile_url": user_profile_url_to_find, "followed": False, "error": f"タスク内エラー: {str(e_task)}"}
    finally:
        if task_driver:
            logger.debug(f"{log_prefix_task}WebDriverインスタンスを終了します。")
            task_driver.quit()
        logger.info(f"{log_prefix_task}並列フォローバックタスク終了。")

# --- フォローバック機能 (メインロジック) ---


def follow_back_users_new(driver, current_user_id, shared_cookies_from_main=None):
    """
    自分をフォローしてくれたユーザーをフォローバックする機能。
    config.yaml の follow_back_settings に従って動作する。
    並列処理に対応。
    """
    # main_config_root = _get_config_cached() # 呼び出し元でチェックするため不要
    fb_settings = _get_follow_back_settings()
    action_delays = _get_action_delays()

    # 呼び出し元の yamap_auto_domo.py の execute_main_tasks で
    # main_config.get("enable_follow_back") をチェックしているので、ここでのガードは不要。
    # if not main_config_root.get("enable_follow_back", False):
    #     logger.info("フォローバック機能は設定で無効になっています。(from follow_back_utils)")
    #     return 0

    is_parallel_enabled = fb_settings.get("enable_parallel_follow_back", False)
    max_workers = fb_settings.get("max_workers_follow_back", 2) if is_parallel_enabled else 1
    # shared_cookies_from_main は yamap_auto_domo.py から渡される想定
    # 並列処理でCookieが必須なので、なければ逐次実行にフォールバックも検討できる
    if is_parallel_enabled and not shared_cookies_from_main:
        logger.warning("並列フォローバックが有効ですが、共有Cookieが提供されませんでした。逐次処理にフォールバックします。")
        is_parallel_enabled = False

    logger.info(f">>> フォローバック機能を開始します... (並列処理: {'有効' if is_parallel_enabled else '無効'})")
    base_followers_url = f"{BASE_URL}/users/{current_user_id}?tab=followers"
    current_page_number = 1

    # メインのdriverで初期ページにアクセス
    logger.info(f"フォロワー一覧の初期ページへアクセス: {base_followers_url}#tabs (メインドライバー使用)")
    driver.get(base_followers_url + "#tabs")

    max_to_follow_back_total = fb_settings.get("max_users_to_follow_back", 10)
    max_pages_to_check = fb_settings.get("max_pages_for_follow_back", 100)
    # 逐次処理用の遅延 (並列時はワーカースレッド側で `delay_per_worker_action_sec` を使用)
    sequential_delay_between_actions = action_delays.get(
        "after_follow_action_sec",
        fb_settings.get("delay_after_follow_back_action_sec", 3.0)
    )
    delay_after_pagination_fb = action_delays.get("delay_after_pagination_sec", 3.0)

    total_followed_this_session = 0
    # processed_profile_urls_this_session は、メインスレッドでURLを収集し、
    # タスク投入前に重複チェックするために使用する。タスク側では処理しない。
    processed_profile_urls_this_session = set()

    followers_list_container_selector = "ul.css-18aka15"
    user_card_selector = "div[data-testid='user']"
    user_link_in_card_selector = "a.css-e5vv35[href^='/users/']"
    next_button_selectors = [
        "button[aria-label=\"次のページに移動する\"]",
        "a[data-testid='pagination-next-button']", "a[rel='next']", "a.next",
        "a.pagination__next", "button.next", "button.pagination__next",
        "a[aria-label*='次へ']:not([aria-disabled='true'])", "a[aria-label*='Next']:not([aria-disabled='true'])",
        "button[aria-label*='次へ']:not([disabled])", "button[aria-label*='Next']:not([disabled])"
    ]

    with ThreadPoolExecutor(max_workers=max_workers) if is_parallel_enabled else nullcontext() as executor:
        futures = []  # 並列処理の場合のFutureオブジェクトリスト

        while current_page_number <= max_pages_to_check:
            if total_followed_this_session >= max_to_follow_back_total:
                logger.info(f"セッション中のフォローバック上限 ({max_to_follow_back_total}人) に達しました。ページネーションを停止。")
                break  # ページネーションループ (while) を抜ける

            current_page_url_for_task = driver.current_url  # タスクに渡す現在のページURL
            logger.info(f"フォロワーリストの {current_page_number} ページ目 ({current_page_url_for_task}) を処理します。")

            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, followers_list_container_selector))
                )
                logger.info("フォロワーリストのコンテナをメインドライバーで発見。")
                time.sleep(1.0)  # リスト内容の描画待ち (メインドライバー)

                user_cards_all_on_page = driver.find_elements(By.CSS_SELECTOR, user_card_selector)
                logger.info(f"{current_page_number} ページ目から {len(user_cards_all_on_page)} 件のユーザーカード候補を検出 (メインドライバー)。")

                user_cards_to_process_this_page = user_cards_all_on_page
                if fb_settings.get("enable_per_page_skip", True):
                    skip_count = fb_settings.get("users_to_skip_per_page", 3)
                    if skip_count > 0 and len(user_cards_all_on_page) > skip_count:
                        user_cards_to_process_this_page = user_cards_all_on_page[skip_count:]
                        logger.info(f"各ページ先頭{skip_count}件のスキップ設定が有効なため、このページの先頭{skip_count}件を除いた {len(user_cards_to_process_this_page)} 件を処理対象とします。")
                    elif skip_count > 0:
                        logger.info(f"スキップ対象がカード数以上のため、このページでは全件スキップ。")
                        user_cards_to_process_this_page = []
                else:
                    logger.info("各ページ先頭のユーザースキップ機能は無効。検出された全ユーザーを処理対象とします。")

                if not user_cards_to_process_this_page:
                    logger.info(f"{current_page_number} ページ目には処理対象となるフォロワーが見つかりませんでした（スキップ処理後を含む）。")
                    # 「次へ」ボタンの処理はループの最後で行う

                tasks_for_this_page = []
                for card_idx, user_card_element_main_driver in enumerate(user_cards_to_process_this_page):
                    if total_followed_this_session + len(futures) >= max_to_follow_back_total and is_parallel_enabled:
                        logger.info(f"フォローバック上限 ({max_to_follow_back_total}人) に近づいたため、新規タスク投入を停止します。")
                        break
                    if total_followed_this_session >= max_to_follow_back_total and not is_parallel_enabled:
                        logger.info(f"フォローバック上限 ({max_to_follow_back_total}人) に達しました。")
                        break

                    user_name_main = f"ユーザー{card_idx+1} (Page {current_page_number}, MainDriver)"
                    profile_url_main = ""
                    try:
                        user_link_element_main = user_card_element_main_driver.find_element(By.CSS_SELECTOR, user_link_in_card_selector)
                        profile_url_main = user_link_element_main.get_attribute("href")

                        name_el_candidates_main = user_link_element_main.find_elements(By.CSS_SELECTOR, "h2, span[class*='UserListItem_name__'], span.name")
                        for name_el_candidate_main in name_el_candidates_main:
                            if name_el_candidate_main.text.strip():
                                user_name_main = name_el_candidate_main.text.strip()
                                break

                        if not profile_url_main:
                            logger.warning(f"{user_name_main}: プロフィールURL取得失敗。スキップ。")
                            continue
                        if profile_url_main.startswith("/"):
                            profile_url_main = BASE_URL + profile_url_main

                        if f"/users/{current_user_id}" in profile_url_main or not profile_url_main.startswith(f"{BASE_URL}/users/"):
                            logger.debug(f"スキップ対象: 自分自身または無効なURL ({profile_url_main})")
                            continue
                        if profile_url_main in processed_profile_urls_this_session:
                            logger.info(f"ユーザー「{user_name_main}」({profile_url_main.split('/')[-1]}) は既に処理試行済み。スキップ。")
                            continue

                    except NoSuchElementException:
                        logger.warning(f"{user_name_main}: カード必須要素(リンク等)が見つかりません。スキップ。")
                        continue
                    except Exception as e_card_parse_main:
                        logger.warning(f"{user_name_main}: カード解析中に予期せぬエラー: {e_card_parse_main}。スキップ。")
                        continue

                    processed_profile_urls_this_session.add(profile_url_main)  # メインスレッドで処理済みとしてマーク

                    # --- ここで逐次処理と並列処理の分岐 ---
                    if is_parallel_enabled and executor:
                        # 新規追加: ワーカー起動前の遅延
                        delay_before_start = fb_settings.get("delay_before_worker_start_sec", 0.5)
                        if delay_before_start > 0 and len(futures) > 0: # 最初のタスク投入時は遅延させない場合もあるので len(futures) > 0 を追加検討
                            logger.debug(f"次のワーカー起動前に {delay_before_start} 秒待機します...")
                            time.sleep(delay_before_start)

                        # 並列処理: タスクを投入
                        logger.info(f"フォロワー「{user_name_main}」(URL: {profile_url_main.split('/')[-1]}) のフォローバックタスクを投入します...")
                        # fb_settings と action_delays をタスクに渡す
                        future = executor.submit(
                            _follow_back_task,
                            current_page_url_for_task,
                            profile_url_main,
                            user_name_main,
                            shared_cookies_from_main,
                            fb_settings,
                            action_delays,
                            current_user_id
                        )
                        futures.append(future)
                    else:
                        # 逐次処理: メインドライバーで直接処理
                        logger.info(f"フォロワー「{user_name_main}」(URL: {profile_url_main.split('/')[-1]}) のフォロー状態を逐次確認します...")
                        follow_button_main = find_follow_button_in_list_item(user_card_element_main_driver)
                        if follow_button_main:
                            logger.info(f"ユーザー「{user_name_main}」はまだフォローしていません。逐次フォローバックを実行します。")
                            if click_follow_button_and_verify(driver, follow_button_main, user_name_main):
                                total_followed_this_session += 1
                            time.sleep(sequential_delay_between_actions)
                        else:
                            logger.info(f"ユーザー「{user_name_main}」は既にフォロー済みか、ボタンが見つかりませんでした（逐次）。")
                            time.sleep(0.5)
                # --- ページ内の全ユーザーカード処理後 (逐次処理の場合) ---
                if not is_parallel_enabled and total_followed_this_session >= max_to_follow_back_total:
                    logger.info("逐次処理でフォローバック上限に達したため、ページネーションを停止します。")
                    break  # while ループを抜ける

            except TimeoutException:
                logger.warning(f"{current_page_number} ページ目のリストコンテナ読み込みタイムアウト(メインドライバー)。")
                break  # while ループを抜ける
            except Exception as e_page_process_main:
                logger.error(f"{current_page_number} ページ目の処理中(メインドライバー)に予期せぬエラー: {e_page_process_main}", exc_info=True)
                break  # while ループを抜ける

            # --- 「次へ」ボタンの処理 (メインドライバー) ---
            if total_followed_this_session >= max_to_follow_back_total and not is_parallel_enabled:
                break
            if is_parallel_enabled and executor and (total_followed_this_session + len(futures) >= max_to_follow_back_total):
                logger.info("並列タスク投入数が上限に近いため、次のページへは進みません。残タスク処理後に終了します。")
                break

            next_button_found_on_page = False
            current_url_before_pagination = driver.current_url
            logger.info("現在のページのフォロワー処理完了(メインドライバー)。「次へ」ボタンを探します...")
            for selector_idx, selector in enumerate(next_button_selectors):
                try:
                    next_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    if next_button.is_displayed() and next_button.is_enabled():
                        logger.info(f"「次へ」ボタンをセレクタ '{selector}' で発見(メインドライバー)。クリックします。")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
                        time.sleep(0.5)
                        next_button.click()
                        next_button_found_on_page = True
                        break
                except TimeoutException:
                    logger.debug(f"セレクタ '{selector}' で「次へ」ボタンが見つからずタイムアウト ({selector_idx+1}/{len(next_button_selectors)}).")
                except Exception as e_click_next_main:
                    logger.warning(f"セレクタ '{selector}' で「次へ」ボタンのクリック試行中(メインドライバー)にエラー: {e_click_next_main}")

            if not next_button_found_on_page:
                logger.info("「次へ」ボタンが見つかりませんでした(メインドライバー)。最終ページと判断。")
                break  # while ループを抜ける

            try:
                WebDriverWait(driver, 15).until(EC.url_changes(current_url_before_pagination))
                logger.info(f"次のフォロワーページ ({driver.current_url}) へ正常に遷移(メインドライバー)。")
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, followers_list_container_selector))
                )
                time.sleep(delay_after_pagination_fb)
            except TimeoutException:
                logger.warning("「次へ」ボタンクリック後、ページ遷移またはリスト再表示タイムアウト(メインドライバー)。")
                break  # while ループを抜ける
            current_page_number += 1
        # --- ページネーションループ (while) 終了 ---

        # 並列処理の場合、残っているタスクの結果を処理
        if is_parallel_enabled and futures:
            logger.info(f"投入済みの {len(futures)} 件の並列フォローバックタスクの結果を処理します...")
            for future_item in as_completed(futures):
                if total_followed_this_session >= max_to_follow_back_total:
                    pass  # 上限には達したが、エラー等がないか確認するために結果は処理する

                try:
                    result = future_item.result()
                    profile_url_res = result.get("profile_url", "不明なURL")
                    user_name_res = profile_url_res.split('/')[-1]  # 簡易表示用
                    if result.get("error"):
                        logger.error(f"並列タスクエラー (ユーザー: {user_name_res}): {result['error']}")
                    elif result.get("followed"):
                        logger.info(f"ユーザー「{user_name_res}」のフォローバックに成功しました（並列タスク）。")
                        if total_followed_this_session < max_to_follow_back_total:
                            total_followed_this_session += 1
                        else:
                            logger.info(f"ユーザー「{user_name_res}」はフォロー成功しましたが、既に上限 ({max_to_follow_back_total}) に達していたためカウント外とします。")
                    else:
                        logger.info(f"ユーザー「{user_name_res}」は並列タスク内でフォローバックされませんでした。")
                except Exception as e_future:
                    logger.error(f"並列フォローバックタスクの結果取得中にエラー: {e_future}", exc_info=True)

    logger.info(f"<<< フォローバック機能完了。このセッションで合計 {total_followed_this_session} 人をフォローバックしました。")
    return total_followed_this_session

# nullcontext for Python < 3.7 (concurrent.futures might be used without `with`)
try:
    from contextlib import nullcontext
except ImportError:
    import contextlib

    @contextlib.contextmanager
    def nullcontext(enter_result=None):
        yield enter_result