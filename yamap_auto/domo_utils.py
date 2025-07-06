# coding: utf-8
"""
YAMAP DOMO関連ユーティリティ関数群
"""
import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# driver_utilsから設定情報を取得するためのインポート (直接configを読むのではなく、メインスクリプトから渡す設計も考慮)
# 現状は yamap_auto_domo.py と同様に直接 main_config を参照する形を一旦取る
from .driver_utils import get_main_config, create_driver_with_cookies # main_config を取得するため
# user_profile_utils は現時点では domo_utils 内で直接使用されていないが、
# 将来的にDOMO関連の高度な機能でユーザー情報を参照する可能性を考慮してコメントアウトで残す
# from .user_profile_utils import get_latest_activity_url
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from concurrent.futures import ThreadPoolExecutor, as_completed
import time # time モジュールをインポート

logger = logging.getLogger(__name__) # このモジュール用のロガーを取得

# --- グローバル定数 ---
BASE_URL = "https://yamap.com" # yamap_auto_domo.py から移動
TIMELINE_URL = f"{BASE_URL}/timeline" # yamap_auto_domo.py から移動

# --- 設定情報の読み込み ---
try:
    main_config = get_main_config()
    if not main_config:
        logger.error("domo_utils: main_config の読み込みに失敗しました。")
        main_config = {}

    # DOMO関連の設定セクションを読み込む
    TIMELINE_DOMO_SETTINGS = main_config.get("timeline_domo_settings", {})
    PARALLEL_PROCESSING_SETTINGS = main_config.get("parallel_processing_settings", {})

    if not TIMELINE_DOMO_SETTINGS:
        logger.warning("domo_utils: config.yaml に timeline_domo_settings が見つからないか空です。")
    if not PARALLEL_PROCESSING_SETTINGS:
        logger.warning("domo_utils: config.yaml に parallel_processing_settings が見つからないか空です。")

except Exception as e:
    logger.error(f"domo_utils: 設定情報 (main_config) の読み込み中にエラー: {e}", exc_info=True)
    main_config = {} # エラー発生時は空の辞書でフォールバック
    TIMELINE_DOMO_SETTINGS = {}
    PARALLEL_PROCESSING_SETTINGS = {}


def domo_activity(driver, activity_url, base_url="https://yamap.com"): # base_url引数は維持しつつ、デフォルト値をグローバル定数と合わせる
    """
    指定された活動日記URLのページを開き、DOMOボタンを探してクリックします。
    既にDOMO済みの場合は実行しません。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        activity_url (str): DOMO対象の活動日記の完全なURL。
        base_url (str): YAMAPのベースURL。

    Returns:
        bool: DOMOに成功した場合はTrue。既にDOMO済み、ボタンが見つからない、
              またはエラーが発生した場合はFalse。
    """
    activity_id_for_log = activity_url.split('/')[-1] # ログ用に活動日記ID部分を抽出
    logger.info(f"活動日記 ({activity_id_for_log}) へDOMOを試みます。")
    try:
        # 1. 対象の活動日記ページへ遷移 (既にそのページにいなければ)
        current_page_url = driver.current_url
        if current_page_url != activity_url:
            logger.debug(f"対象の活動日記ページ ({activity_url}) に遷移します。")
            driver.get(activity_url)
            # URLが正しく遷移したことを確認 (活動日記IDが含まれるかで判断)
            WebDriverWait(driver, 15).until(EC.url_contains(activity_id_for_log))
        else:
            logger.debug(f"既に活動日記ページ ({activity_url}) にいます。")

        # 2. DOMOボタンの探索
        primary_domo_button_selector = "button[data-testid='ActivityDomoButton']"
        id_domo_button_selector = "button#DomoActionButton"

        domo_button = None
        current_selector_used = ""

        for idx, selector in enumerate([primary_domo_button_selector, id_domo_button_selector]):
            try:
                logger.debug(f"DOMOボタン探索試行 (セレクタ: {selector})")
                wait_time = 5 if idx == 0 else 2
                domo_button_candidate = WebDriverWait(driver, wait_time).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                if domo_button_candidate:
                    domo_button = domo_button_candidate
                    current_selector_used = selector
                    logger.debug(f"DOMOボタンを発見 (セレクタ: '{selector}')")
                    break
            except TimeoutException:
                logger.debug(f"DOMOボタンがセレクタ '{selector}' で見つからず、またはタイムアウトしました。")
                continue

        if not domo_button:
            logger.warning(f"DOMOボタンが見つかりませんでした: {activity_id_for_log}")
            return False

        # 3. DOMO済みかどうかの判定
        aria_label_before = domo_button.get_attribute("aria-label")
        is_domoed = False

        if aria_label_before and ("Domo済み" in aria_label_before or "domoed" in aria_label_before.lower() or "ドモ済み" in aria_label_before):
            is_domoed = True
            logger.info(f"既にDOMO済みです (aria-label='{aria_label_before}'): {activity_id_for_log}")
        else:
            try:
                icon_span = domo_button.find_element(By.CSS_SELECTOR, "span[class*='DomoActionContainer__DomoIcon'], span.RidgeIcon")
                if "is-active" in icon_span.get_attribute("class"):
                    is_domoed = True
                    logger.info(f"既にDOMO済みです (アイコン is-active 確認): {activity_id_for_log}")
            except NoSuchElementException:
                logger.debug("DOMOボタン内のis-activeアイコンspanが見つかりませんでした。aria-labelに依存します。")

        # 4. DOMO実行 (まだDOMOしていなければ)
        if not is_domoed:
            logger.info(f"DOMOを実行します: {activity_id_for_log} (使用ボタンセレクタ: '{current_selector_used}')")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", domo_button)
            time.sleep(0.1)
            domo_button.click()

            action_delays = main_config.get("action_delays", {})
            delay_after_action = action_delays.get("after_domo_sec", 1.5)

            try:
                WebDriverWait(driver, 5).until(
                    lambda d: ("Domo済み" in (d.find_element(By.CSS_SELECTOR, current_selector_used).get_attribute("aria-label") or "")) or \
                              ("is-active" in (d.find_element(By.CSS_SELECTOR, f"{current_selector_used} span[class*='DomoActionContainer__DomoIcon'], {current_selector_used} span.RidgeIcon").get_attribute("class") or ""))
                )
                aria_label_after = driver.find_element(By.CSS_SELECTOR, current_selector_used).get_attribute("aria-label")
                logger.info(f"DOMOしました: {activity_id_for_log} (aria-label: {aria_label_after})")
                time.sleep(delay_after_action)
                return True
            except TimeoutException:
                logger.warning(f"DOMO実行後、状態変化の確認でタイムアウト: {activity_id_for_log}")
                time.sleep(delay_after_action)
                return False
        else:
            return False

    except TimeoutException:
        logger.warning(f"DOMO処理中にタイムアウト ({activity_id_for_log})。ページ要素が見つからないか、読み込みが遅い可能性があります。")
    except NoSuchElementException:
        logger.warning(f"DOMOボタンまたはその構成要素が見つかりません ({activity_id_for_log})。セレクタが古い可能性があります。")
    except Exception as e:
        logger.error(f"DOMO実行中に予期せぬエラー ({activity_id_for_log}):", exc_info=True)
    return False


# --- タイムラインDOMO機能 ---
def domo_timeline_activities(driver):
    """
    タイムライン上の活動記録にDOMOする機能（逐次処理版）。
    `config.yaml` の `timeline_domo_settings` に従って動作します。
    タイムラインページにアクセスし、表示されている活動記録に対して順次DOMO処理を行います。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
    """
    # 機能が有効かチェック (config.yaml の設定)
    if not TIMELINE_DOMO_SETTINGS.get("enable_timeline_domo", False):
        logger.info("タイムラインDOMO機能は設定で無効になっています。")
        return

    logger.info(">>> タイムラインDOMO機能を開始します...")
    timeline_page_url = TIMELINE_URL # タイムラインページのURL
    logger.info(f"タイムラインページへアクセス: {timeline_page_url}")
    driver.get(timeline_page_url) # ページ遷移

    # 設定値の読み込み
    max_activities_to_domo = TIMELINE_DOMO_SETTINGS.get("max_activities_to_domo_on_timeline", 10) # DOMOする最大件数
    domoed_count = 0 # このセッションでDOMOした件数
    processed_activity_urls = set() # 既に処理試行した活動記録URLのセット (重複処理防止)

    try:
        # --- タイムライン要素のセレクタ定義 ---
        # YAMAPのUI変更に備え、セレクタは適宜更新が必要になる可能性があります。
        feed_item_selector = "li.TimelineList__Feed" # 各フィードアイテム（投稿単位）
        activity_item_indicator_selector = "div.TimelineActivityItem" # フィードアイテムが「活動日記」であることを示す要素
        activity_link_in_item_selector = "a.TimelineActivityItem__BodyLink[href^='/activities/']" # 活動日記へのリンク

        # タイムラインのフィードアイテム群が表示されるまで待機
        logger.info(f"タイムラインのフィードアイテム ({feed_item_selector}) の出現を待ちます...")
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, feed_item_selector))
        )
        logger.info("タイムラインのフィードアイテム群を発見。")
        time.sleep(1.5) # スクロールや追加コンテンツ読み込みを考慮した描画安定待ち (以前は2.5秒)

        # ページ上のフィードアイテム要素を全て取得
        feed_items = driver.find_elements(By.CSS_SELECTOR, feed_item_selector)
        logger.info(f"タイムラインから {len(feed_items)} 件のフィードアイテム候補を検出しました。")

        if not feed_items: # アイテムがなければ処理終了
            logger.info("タイムラインにフィードアイテムが見つかりませんでした。")
            return

        initial_feed_item_count = len(feed_items) # 処理開始時のアイテム数を記録
        logger.info(f"処理対象の初期フィードアイテム数: {initial_feed_item_count}")

        # 各フィードアイテムを処理
        for idx in range(initial_feed_item_count): # StaleElement対策のため、インデックスベースでループ
            if domoed_count >= max_activities_to_domo: # DOMO上限に達したら終了
                logger.info(f"タイムラインDOMOの上限 ({max_activities_to_domo}件) に達しました。")
                break

            activity_url = None # 対象の活動記録URL
            try:
                # DOM操作やページ遷移で要素が無効になる (StaleElementReferenceException) 可能性を考慮し、
                # ループの各反復でフィードアイテム要素を再取得します。
                feed_items_on_page = driver.find_elements(By.CSS_SELECTOR, feed_item_selector)
                if idx >= len(feed_items_on_page): # インデックスが現在の要素数を超えた場合 (DOMが大きく変わった可能性)
                    logger.warning(f"フィードアイテムインデックス {idx} が現在のアイテム数 {len(feed_items_on_page)} を超えています。DOM変更の可能性。スキップします。")
                    continue
                feed_item_element = feed_items_on_page[idx] # 現在処理対象のフィードアイテム

                # このフィードアイテムが「活動日記」であるかを確認
                activity_indicator_elements = feed_item_element.find_elements(By.CSS_SELECTOR, activity_item_indicator_selector)
                if not activity_indicator_elements: # 活動日記でなければスキップ
                    logger.debug(f"フィードアイテム {idx+1}/{initial_feed_item_count} は活動日記ではありません。スキップ。")
                    continue

                # 活動日記であれば、その中の活動記録ページへのリンクを取得
                link_element = activity_indicator_elements[0].find_element(By.CSS_SELECTOR, activity_link_in_item_selector)
                activity_url = link_element.get_attribute("href")

                # URLの整形と検証
                if activity_url:
                    if activity_url.startswith("/"): # 相対URLならベースURLを付与
                        activity_url = BASE_URL + activity_url
                    if not activity_url.startswith(f"{BASE_URL}/activities/"): # 不正な形式なら無効化
                        logger.warning(f"無効な活動記録URL形式です: {activity_url}。スキップします。")
                        activity_url = None

                if not activity_url: # URLが取得できなかった場合
                    logger.warning(f"フィードアイテム {idx+1}/{initial_feed_item_count} から有効な活動記録URLを取得できませんでした。スキップ。")
                    continue

                if activity_url in processed_activity_urls: # 既に処理試行済みならスキップ
                    logger.info(f"活動記録 ({activity_url.split('/')[-1]}) は既に処理試行済みです。スキップ。")
                    continue
                processed_activity_urls.add(activity_url) # 処理済みセットに追加

                logger.info(f"タイムライン活動記録 {idx+1}/{initial_feed_item_count} (URL: {activity_url.split('/')[-1]}) のDOMOを試みます。")

                current_main_page_url = driver.current_url # DOMO処理前のURLを保存 (タイムラインページのURL)

                # DOMO実行 (domo_activity関数は内部でページ遷移する可能性あり)
                if domo_activity(driver, activity_url, BASE_URL): # BASE_URL を引数に追加
                    domoed_count += 1

                # DOMO処理後、元のタイムラインページに戻る (URLが変わっていた場合)
                if driver.current_url != current_main_page_url:
                    logger.debug(f"DOMO処理後、元のタイムラインページ ({current_main_page_url}) に戻ります。")
                    driver.get(current_main_page_url)
                    try:
                        # 戻った後、フィードアイテムが再認識されるように待つ
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, feed_item_selector))
                        )
                        time.sleep(0.2) # 短い追加の安定待ち (0.5秒から短縮)
                    except TimeoutException:
                        logger.warning(f"タイムラインページ ({current_main_page_url}) に戻った後、フィードアイテムの再表示タイムアウト。")
                        # 処理は続行を試みる

            except NoSuchElementException:
                logger.warning(f"フィードアイテム {idx+1}/{initial_feed_item_count} 内で活動記録リンクが見つかりません。スキップします。")
            except Exception as e_card_proc: # StaleElementReferenceExceptionもここでキャッチされる想定
                logger.error(f"フィードアイテム {idx+1}/{initial_feed_item_count} (URL: {activity_url.split('/')[-1] if activity_url else 'N/A'}) の処理中にエラー: {e_card_proc}", exc_info=True)

    except TimeoutException: # タイムライン全体の読み込みタイムアウト
        logger.warning("タイムライン活動記録の読み込みでタイムアウトしました。")
    except Exception as e: # その他の予期せぬエラー
        logger.error(f"タイムラインDOMO処理中に予期せぬエラーが発生しました。", exc_info=True)

    logger.info(f"<<< タイムラインDOMO機能完了。合計 {domoed_count} 件の活動記録にDOMOしました。")


# --- 並列処理用タスク関数 ---
def domo_activity_task(activity_url, shared_cookies, task_delay_sec):
    """
    単一の活動記録URLに対してDOMO処理を行うタスク関数です。
    `ThreadPoolExecutor` から呼び出されることを想定しており、並列処理で使用されます。
    新しいWebDriverインスタンスを作成し、共有されたCookieを使用してログイン状態を再現し、DOMO処理を実行します。

    Args:
        activity_url (str): DOMO対象の活動記録の完全なURL。
        shared_cookies (list[dict]): メインのWebDriverから取得したログインセッションCookie。
        task_delay_sec (float): このタスクを開始する前に挿入する遅延時間 (秒単位)。
                                他のタスクとの同時アクセスを緩和するために使用。

    Returns:
        bool: DOMOに成功した場合はTrue、それ以外はFalse。
    """
    activity_id_for_log = activity_url.split('/')[-1]
    logger.info(f"[TASK] 活動記録 ({activity_id_for_log}) のDOMOタスク開始。")
    task_driver = None # このタスク専用のWebDriverインスタンス
    domo_success = False
    try:
        time.sleep(task_delay_sec) # 他タスクとの実行タイミングをずらすための遅延
        # 共有Cookieを使って新しいWebDriverインスタンスを作成 (ログイン状態を再現)
        task_driver = create_driver_with_cookies(shared_cookies, BASE_URL)
        if not task_driver: # WebDriver作成に失敗した場合
            logger.error(f"[TASK] DOMOタスク用WebDriver作成失敗 ({activity_id_for_log})。")
            return False

        # (オプション) ここで task_driver が実際にログイン状態か確認するロジックを追加可能
        # 例: 特定のログイン後要素が存在するかチェック

        # 既存のDOMO関数を呼び出してDOMO処理を実行
        domo_success = domo_activity(task_driver, activity_url, BASE_URL) # BASE_URL を引数に追加
        if domo_success:
            logger.info(f"[TASK] 活動記録 ({activity_id_for_log}) へのDOMO成功。")
        else:
            logger.info(f"[TASK] 活動記録 ({activity_id_for_log}) へのDOMO失敗または既にDOMO済み。")
        return domo_success
    except Exception as e: # タスク実行中の予期せぬエラー
        logger.error(f"[TASK] 活動記録 ({activity_id_for_log}) のDOMOタスク中にエラー: {e}", exc_info=True)
        return False
    finally:
        if task_driver: # タスク完了後、専用WebDriverを必ず閉じる
            task_driver.quit()
        logger.debug(f"[TASK] 活動記録 ({activity_id_for_log}) のDOMOタスク終了。")


# --- タイムラインDOMO機能 (並列処理対応版) ---
def domo_timeline_activities_parallel(driver, shared_cookies):
    """
    タイムライン上の活動記録にDOMOする機能の並列処理版です。
    `config.yaml` の `timeline_domo_settings` および `parallel_processing_settings` に従って動作します。
    メインのWebDriverでタイムラインからDOMO対象の活動記録URLを収集し、
    収集したURL群に対して `ThreadPoolExecutor` を使用して並列でDOMO処理を行います。

    Args:
        driver (webdriver.Chrome): メインのSelenium WebDriverインスタンス (URL収集用)。
        shared_cookies (list[dict]): メインのWebDriverから取得したログインセッションCookie。
                                   並列実行される各タスクのWebDriverに共有されます。
    """
    # 機能が有効かチェック (config.yaml)
    if not TIMELINE_DOMO_SETTINGS.get("enable_timeline_domo", False):
        logger.info("タイムラインDOMO機能は設定で無効になっています。")
        return
    # 並列処理自体が有効かチェック (config.yaml)
    if not PARALLEL_PROCESSING_SETTINGS.get("enable_parallel_processing", False):
        logger.info("並列処理が無効なため、タイムラインDOMOは逐次実行されます。")
        return domo_timeline_activities(driver) # 並列無効時は逐次版を呼び出す

    logger.info(">>> [PARALLEL] タイムラインDOMO機能を開始します...")
    timeline_page_url = TIMELINE_URL
    logger.info(f"タイムラインページへアクセスし、DOMO対象URLを収集します: {timeline_page_url}")
    driver.get(timeline_page_url) # URLリスト収集はメインのドライバーで行う

    # 設定値の読み込み
    max_activities_to_domo = TIMELINE_DOMO_SETTINGS.get("max_activities_to_domo_on_timeline", 10) # DOMO上限
    max_workers = PARALLEL_PROCESSING_SETTINGS.get("max_workers", 3) # 並列ワーカー数
    task_delay_base = PARALLEL_PROCESSING_SETTINGS.get("delay_between_thread_tasks_sec", 1.0) # タスク間の基本遅延

    activity_urls_to_domo = [] # DOMO対象の活動記録URLを格納するリスト
    processed_urls_for_collection = set() # URL収集段階での重複排除用セット

    try:
        # --- URL収集フェーズ ---
        # タイムライン要素のセレクタ (逐次版と同じ)
        feed_item_selector = "li.TimelineList__Feed"
        activity_item_indicator_selector = "div.TimelineActivityItem"
        activity_link_in_item_selector = "a.TimelineActivityItem__BodyLink[href^='/activities/']"

        logger.info(f"タイムラインのフィードアイテム ({feed_item_selector}) の出現を待ちます...")
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, feed_item_selector))
        )
        logger.info("タイムラインのフィードアイテム群を発見。URL収集を開始します。")
        time.sleep(1.5) # 描画安定待ち

        feed_items = driver.find_elements(By.CSS_SELECTOR, feed_item_selector)
        if not feed_items:
            logger.info("タイムラインにフィードアイテムが見つかりませんでした（URL収集フェーズ）。")
            return

        # 各フィードアイテムから活動記録URLを収集
        for idx, feed_item_element in enumerate(feed_items):
            if len(activity_urls_to_domo) >= max_activities_to_domo: # 収集上限に達したら終了
                logger.info(f"DOMO対象URLの収集上限 ({max_activities_to_domo}件) に達しました。")
                break
            try:
                # このフィードアイテムが活動日記か確認
                activity_indicator_elements = feed_item_element.find_elements(By.CSS_SELECTOR, activity_item_indicator_selector)
                if not activity_indicator_elements: continue # 活動日記でなければスキップ

                # 活動記録URLを取得
                link_element = activity_indicator_elements[0].find_element(By.CSS_SELECTOR, activity_link_in_item_selector)
                activity_url = link_element.get_attribute("href")

                # URLの整形と検証、重複チェック
                if activity_url:
                    if activity_url.startswith("/"): activity_url = BASE_URL + activity_url
                    if not activity_url.startswith(f"{BASE_URL}/activities/"): continue # 不正形式
                    if activity_url in processed_urls_for_collection: continue # 既に収集済み

                    activity_urls_to_domo.append(activity_url) # リストに追加
                    processed_urls_for_collection.add(activity_url) # セットに追加
                    logger.debug(f"DOMO候補URL追加: {activity_url.split('/')[-1]} (収集済み: {len(activity_urls_to_domo)}件)")
            except Exception as e_collect: # URL収集中にエラーが発生した場合 (StaleElementなど)
                logger.warning(f"タイムラインからのURL収集中にエラー (アイテム {idx+1}): {e_collect}")
                # ここではシンプルにスキップし、次のアイテムの処理を試みる

        logger.info(f"収集したDOMO対象URLは {len(activity_urls_to_domo)} 件です。")
        if not activity_urls_to_domo: # DOMO対象URLが0件なら終了
            logger.info("DOMO対象となる活動記録URLが収集できませんでした。")
            return

        # --- 並列DOMO実行フェーズ ---
        total_domoed_count_parallel = 0 # 並列処理でDOMOした総数
        # ThreadPoolExecutorを使用して、収集したURLに対して並列でDOMOタスクを実行
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [] # 各タスクのFutureオブジェクトを格納するリスト
            for i, url in enumerate(activity_urls_to_domo):
                # 各タスクに少しずつ異なる遅延を与えることで、同時アクセスを緩和
                delay_for_this_task = task_delay_base + (i * 0.1) # 例: 0.1秒ずつ開始をずらす
                # domo_activity_task をサブミット (引数としてURL, 共有Cookie, 遅延時間を渡す)
                futures.append(executor.submit(domo_activity_task, url, shared_cookies, delay_for_this_task))

            # 全てのタスクが完了するのを待ち、結果を集計
            for future in as_completed(futures): # 完了したものから順に処理
                try:
                    if future.result(): # domo_activity_task が True (DOMO成功) を返した場合
                        total_domoed_count_parallel += 1
                except Exception as e_future: # タスク実行中に例外が発生した場合
                    logger.error(f"並列DOMOタスクの実行結果取得中にエラー: {e_future}", exc_info=True)

        logger.info(f"<<< [PARALLEL] タイムラインDOMO機能完了。合計 {total_domoed_count_parallel} 件の活動記録にDOMOしました (試行対象: {len(activity_urls_to_domo)}件)。")

    except TimeoutException: # URL収集フェーズでのタイムアウト
        logger.warning("[PARALLEL] タイムライン活動記録のURL収集でタイムアウトしました。")
    except Exception as e: # その他の予期せぬエラー
        logger.error(f"[PARALLEL] タイムラインDOMO処理 (並列) 中に予期せぬエラーが発生しました。", exc_info=True)
