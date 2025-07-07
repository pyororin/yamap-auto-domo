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
from .driver_utils import get_main_config, create_driver_with_cookies, save_screenshot # save_screenshot をインポート
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
    activity_id_for_log = "N/A"
    if activity_url and isinstance(activity_url, str) and "/activities/" in activity_url:
        activity_id_for_log = activity_url.split('/')[-1]
    else:
        logger.warning(f"無効な activity_url が渡されました: {activity_url}。処理を試みますが、問題が発生する可能性があります。")
        if not activity_url or not isinstance(activity_url, str): # URLが空かstrでない場合は早期リターンも検討
             logger.error(f"activity_urlが空または文字列ではありません: {activity_url}。DOMO処理を中止します。")
             return False

    logger.info(f"活動日記 ({activity_id_for_log}) へDOMOを試みます。URL: {activity_url}")
    try:
        # 1. 対象の活動日記ページへ遷移 (既にそのページにいなければ)
        current_page_url = driver.current_url
        if current_page_url != activity_url:
            logger.debug(f"対象の活動日記ページ ({activity_url}) に遷移します。")
            driver.get(activity_url)
            # URLが正しく遷移したことを確認 (活動日記IDが含まれるかで判断)
            # activity_id_for_log が "N/A" の場合、この確認はスキップまたは別の方法を検討
            if activity_id_for_log != "N/A":
                WebDriverWait(driver, 15).until(EC.url_contains(activity_id_for_log))
            else: # activity_id_for_log が特定できない場合、URL全体で遷移を確認
                WebDriverWait(driver, 15).until(EC.url_to_be(activity_url))
        else:
            logger.debug(f"既に活動日記ページ ({activity_url}) にいます。")

        # 2. DOMOボタンの探索
        domo_button_selectors = [
            "button[data-testid='ActivityDomoButton']",  # プライマリセレクタ
            "button#DomoActionButton"                    # セカンダリセレクタ
        ]
        logger.debug(f"DOMOボタン探索開始。試行セレクタリスト: {domo_button_selectors} for activity: {activity_id_for_log}")

        domo_button = None
        current_selector_used = ""
        button_found_but_not_clickable = False

        for idx, selector in enumerate(domo_button_selectors):
            logger.debug(f"DOMOボタン探索試行 #{idx+1} (セレクタ: '{selector}') for activity: {activity_id_for_log}")
            try:
                wait_time = 5 if idx == 0 else 2 # 最初のセレクタは少し長めに待つ
                # まず要素が存在するか確認
                WebDriverWait(driver, wait_time).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                # 次に要素がクリック可能か確認
                domo_button_candidate = WebDriverWait(driver, 1).until( # クリック可能確認は短いタイムアウト
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                if domo_button_candidate:
                    domo_button = domo_button_candidate
                    current_selector_used = selector
                    logger.info(f"DOMOボタンを発見し、クリック可能です (使用セレクタ: '{selector}') for activity: {activity_id_for_log}")
                    button_found_but_not_clickable = False
                    break
                else: # WebDriverWait が None を返すことは通常ないが、念のため
                    logger.debug(f"セレクタ '{selector}' でDOMOボタン候補が見つかりましたが、無効な要素でした (activity: {activity_id_for_log})。")
            except TimeoutException:
                # presence_of_element_located は成功したが element_to_be_clickable でタイムアウトした場合
                try:
                    if driver.find_elements(By.CSS_SELECTOR, selector): # 要素自体は存在するか再確認
                        logger.warning(f"セレクタ '{selector}' でDOMOボタン要素は存在しますが、クリック可能状態になりませんでした (activity: {activity_id_for_log})。")
                        button_found_but_not_clickable = True # クリックできないボタンがあったフラグ
                    else:
                        logger.debug(f"セレクタ '{selector}' でDOMOボタンが見つからず、タイムアウトしました (activity: {activity_id_for_log})。")
                except Exception as e_find_check:
                     logger.debug(f"セレクタ '{selector}' でDOMOボタンの存在確認中にエラー: {e_find_check} (activity: {activity_id_for_log})")

            except Exception as e_sel: # その他の例外 (例: StaleElementなど)
                logger.warning(f"セレクタ '{selector}' でDOMOボタン探索中に予期せぬエラー: {type(e_sel).__name__} - {e_sel} (activity: {activity_id_for_log})", exc_info=True)
                # このセレクタでの探索は失敗として続行

        if not domo_button:
            if button_found_but_not_clickable:
                logger.error(f"DOMO失敗: DOMOボタン要素は見つかりましたがクリック可能な状態ではありませんでした (activity: {activity_id_for_log}, selectors: {domo_button_selectors})。")
            else:
                logger.error(f"DOMO失敗: DOMOボタンが見つかりませんでした (activity: {activity_id_for_log}, selectors: {domo_button_selectors})。")
            # スクリーンショットは各種例外ハンドラで撮影されるため、ここでは不要
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
                logger.info(f"DOMO成功を確認しました: {activity_id_for_log} (aria-label: {aria_label_after}, 使用セレクタ: '{current_selector_used}')")
                time.sleep(delay_after_action)
                return True
            except TimeoutException:
                # タイムアウト時の詳細ログ
                actual_aria_label = "取得失敗"
                actual_icon_class = "取得失敗"
                expected_aria_label_pattern = "Domo済み"
                expected_icon_class_pattern = "is-active"
                try:
                    button_element_after_click = driver.find_element(By.CSS_SELECTOR, current_selector_used)
                    actual_aria_label = button_element_after_click.get_attribute("aria-label") or "aria-labelなし"
                    try:
                        icon_span_after_click = button_element_after_click.find_element(By.CSS_SELECTOR, "span[class*='DomoActionContainer__DomoIcon'], span.RidgeIcon")
                        actual_icon_class = icon_span_after_click.get_attribute("class") or "classなし"
                    except NoSuchElementException:
                        actual_icon_class = "アイコンspanなし"
                except Exception as e_attr:
                    logger.error(f"DOMO後の属性取得中にエラー: {type(e_attr).__name__} - {e_attr} (activity: {activity_id_for_log})")

                logger.error(
                    f"DOMO失敗: DOMO実行後、状態変化の確認でタイムアウト (Activity: {activity_id_for_log}, 使用セレクタ: '{current_selector_used}'). "
                    f"期待状態: aria-labelに'{expected_aria_label_pattern}' OR アイコンクラスに'{expected_icon_class_pattern}'. "
                    f"実際の状態: aria-label='{actual_aria_label}', icon_class='{actual_icon_class}'"
                )
                save_screenshot(driver, error_type="DOMO_ConfirmTimeout", context_info=f"{activity_id_for_log}_selector_{current_selector_used.replace('.', '_').replace('#', '_')}")
                time.sleep(delay_after_action)
                return False
        else: # is_domoed is True
            logger.info(f"DOMOスキップ: 既にDOMO済みです ({activity_id_for_log})。")
            return False # DOMOを実行しなかったのでFalse

    except TimeoutException as e_timeout:
        logger.error(f"DOMO失敗: DOMO処理中に予期せぬタイムアウト ({activity_id_for_log})。エラー: {type(e_timeout).__name__} - {e_timeout}")
        save_screenshot(driver, error_type="TimeoutException_DOMO_Process", context_info=activity_id_for_log)
    except NoSuchElementException as e_no_such:
        logger.error(f"DOMO失敗: DOMOボタンまたは関連要素が見つかりません ({activity_id_for_log})。エラー: {type(e_no_such).__name__} - {e_no_such}")
        save_screenshot(driver, error_type="NoSuchElement_DOMO_Process", context_info=activity_id_for_log)
    except Exception as e:
        current_url_on_error = "取得失敗"
        try:
            current_url_on_error = driver.current_url
        except Exception as e_url:
            logger.error(f"予期せぬエラー発生時に現在のURL取得も失敗: {type(e_url).__name__} - {e_url}")

        logger.error(
            f"DOMO実行中に予期せぬエラー ({activity_id_for_log})。エラータイプ: {type(e).__name__}, メッセージ: {str(e)}. "
            f"発生時のURL: {current_url_on_error}",
            exc_info=True
        )
        save_screenshot(driver, error_type="UnhandledException", context_info=f"{activity_id_for_log}_{type(e).__name__}")
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

    logger.info(">>> タイムラインDOMO機能を開始します (一覧上で直接DOMO)...")
    timeline_page_url = TIMELINE_URL
    logger.info(f"タイムラインページへアクセス: {timeline_page_url}")
    driver.get(timeline_page_url)

    max_activities_to_domo = TIMELINE_DOMO_SETTINGS.get("max_activities_to_domo_on_timeline", 10)
    domoed_count = 0
    # processed_activity_ids: DOMO成功した活動記録ID（またはURL）を記録し、重複DOMOを防ぐ
    # タイムライン上で同じ活動記録が複数回表示されるケースは稀だが念のため
    processed_activity_identifiers = set()

    # DOMOボタンのセレクタリスト (domo_activity と同じものをデフォルトで使用)
    domo_button_selectors_for_timeline = TIMELINE_DOMO_SETTINGS.get(
        "domo_button_selectors_on_timeline", # config.yaml でタイムライン専用セレクタを指定可能にする
        [
            "button[data-testid='ActivityDomoButton']", # プライマリ (活動ページと同じ想定)
            "button#DomoActionButton",                   # セカンダリ (活動ページと同じ想定)
            "div.ActivityItemActions__DomoActionContainer button" # 提供されたHTMLに基づく追加候補
        ]
    )
    logger.debug(f"タイムラインDOMOで使用するボタンセレクタ: {domo_button_selectors_for_timeline}")


    try:
        feed_item_selector = "li.TimelineList__Feed"
        activity_item_indicator_selector = "div.TimelineActivityItem" # これで活動記録アイテムを特定
        # activity_link_in_item_selector はログ用URL取得に使うが、DOMO処理には必須ではない
        activity_link_in_item_selector = "a.TimelineActivityItem__BodyLink[href^='/activities/']"


        logger.info(f"タイムラインのフィードアイテム ({feed_item_selector}) の出現を待ちます...")
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, feed_item_selector))
        )
        logger.info("タイムラインのフィードアイテム群を発見。")
        time.sleep(TIMELINE_DOMO_SETTINGS.get("wait_after_feed_load_sec", 1.5)) # 設定から読み込み後待機時間を取得

        feed_items = driver.find_elements(By.CSS_SELECTOR, feed_item_selector)
        logger.info(f"タイムラインから {len(feed_items)} 件のフィードアイテム候補を検出しました。")

        if not feed_items:
            logger.info("タイムラインにフィードアイテムが見つかりませんでした。")
            return

        initial_feed_item_count = len(feed_items)
        logger.info(f"処理対象の初期フィードアイテム数: {initial_feed_item_count}")

        for idx in range(initial_feed_item_count):
            if domoed_count >= max_activities_to_domo:
                logger.info(f"タイムラインDOMOの上限 ({max_activities_to_domo}件) に達しました。")
                break

            activity_url_for_log = None # ログおよび重複判定用のURL
            activity_id_for_log = "N/A"

            try:
                # StaleElement対策: 各反復で要素を再取得
                current_feed_items = driver.find_elements(By.CSS_SELECTOR, feed_item_selector)
                if idx >= len(current_feed_items):
                    logger.warning(f"フィードアイテムインデックス {idx} が現在のアイテム数 {len(current_feed_items)} を超えました。スキップ。")
                    continue
                feed_item_element = current_feed_items[idx]

                # 活動記録アイテムか確認
                if not feed_item_element.find_elements(By.CSS_SELECTOR, activity_item_indicator_selector):
                    logger.debug(f"フィードアイテム {idx+1}/{initial_feed_item_count} は活動記録ではありません。スキップ。")
                    continue

                # URLを取得 (ログ用および重複DOMO防止用)
                try:
                    link_element = feed_item_element.find_element(By.CSS_SELECTOR, activity_link_in_item_selector)
                    activity_url_for_log = link_element.get_attribute("href")
                    if activity_url_for_log:
                        if activity_url_for_log.startswith("/"):
                            activity_url_for_log = BASE_URL + activity_url_for_log
                        if "/activities/" in activity_url_for_log:
                             activity_id_for_log = activity_url_for_log.split('/')[-1]
                        else: # 有効な活動記録URLでない場合
                            activity_url_for_log = None # 無効化
                            activity_id_for_log = f"non_activity_item_{idx}" # ログ用の一時ID
                except NoSuchElementException:
                    logger.debug(f"フィードアイテム {idx+1} から活動記録URLリンク要素が見つかりません (ログ用)。activity_id: {activity_id_for_log}")
                    activity_id_for_log = f"no_link_item_{idx}" # ログ用の一時ID

                # 重複DOMO試行の防止 (URLまたはIDが取得できた場合)
                identifier_for_check = activity_url_for_log if activity_url_for_log else activity_id_for_log
                if identifier_for_check != "N/A" and identifier_for_check in processed_activity_identifiers:
                    logger.info(f"活動記録 ({identifier_for_check}) は既にDOMO成功済みとして記録されています。スキップ。")
                    continue

                logger.info(f"タイムライン活動記録 {idx+1}/{initial_feed_item_count} (ID/URL: {identifier_for_check}) のDOMOを試みます。")

                # 新しい関数でフィードアイテム上で直接DOMO
                # timeline_page_url (driver.current_url のキャッシュ) を渡す
                if domo_activity_on_timeline(driver, feed_item_element, domo_button_selectors_for_timeline, TIMELINE_DOMO_SETTINGS, timeline_page_url):
                    domoed_count += 1
                    if identifier_for_check != "N/A":
                         processed_activity_identifiers.add(identifier_for_check) # DOMO成功したものを記録
                # domo_activity_on_timeline が False を返した場合 (既にDOMO済み、ボタンなし等) は domoed_count は増えない

                # ページ遷移は発生しないので、タイムラインに戻る処理は不要
                # StaleElementを避けるため、次のループの最初にフィードアイテムリストを再取得する
                time.sleep(TIMELINE_DOMO_SETTINGS.get("delay_between_item_processing_sec", 0.3)) # アイテム処理間の短い遅延

            except StaleElementReferenceException as e_stale:
                logger.warning(f"フィードアイテム {idx+1} の処理中に StaleElementReferenceException: {e_stale}。DOMが変更された可能性があります。このアイテムをスキップします。")
                # 必要であればここで driver.find_elements を再試行するなどのリカバリも検討できるが、一旦スキップ
                time.sleep(0.5) # DOM安定待ち
                continue # 次のアイテムへ
            except NoSuchElementException: # activity_item_indicator_selector などが見つからない場合
                logger.warning(f"フィードアイテム {idx+1}/{initial_feed_item_count} 内で必須要素が見つかりません。スキップします。")
            except Exception as e_card_proc:
                logger.error(f"フィードアイテム {idx+1}/{initial_feed_item_count} (ID/URL: {activity_url_for_log if activity_url_for_log else activity_id_for_log}) の処理中にエラー: {e_card_proc}", exc_info=True)

    except TimeoutException:
        logger.warning("タイムライン活動記録の読み込みでタイムアウトしました。")
    except Exception as e: # その他の予期せぬエラー
        logger.error(f"タイムラインDOMO処理中に予期せぬエラーが発生しました。", exc_info=True)

    logger.info(f"<<< タイムラインDOMO機能完了。合計 {domoed_count} 件の活動記録にDOMOしました。")


def domo_activity_on_timeline(driver, feed_item_element, domo_button_selectors, timeline_domo_settings, timeline_url):
    """
    タイムラインのフィードアイテム上で直接DOMOを実行します。
    意図しないページ遷移が発生した場合は検知し、元のタイムラインURLに戻ろうと試みます。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        feed_item_element (WebElement): DOMO対象のフィードアイテム要素。
        domo_button_selectors (list[str]): DOMOボタンを見つけるためのCSSセレクタのリスト。
        timeline_domo_settings (dict): タイムラインDOMO関連の設定。
        timeline_url (str): 元のタイムラインページのURL (ページ遷移時の復帰用)。

    Returns:
        bool: DOMOに成功し、ページ遷移も発生しなかった場合はTrue。
              既にDOMO済み、ボタンが見つからない、ページ遷移が発生した、
              またはその他のエラーが発生した場合はFalse。
    """
    activity_id_for_log = "N/A" # アイテムからIDが取れれば更新
    action_delays = main_config.get("action_delays", {})
    delay_after_action = action_delays.get("after_domo_sec", 1.5)

    try:
        # フィードアイテム内から活動記録URLを取得試行 (ログ用)
        activity_url_for_log = None
        try:
            link_element = feed_item_element.find_element(By.CSS_SELECTOR, "a.TimelineActivityItem__BodyLink[href^='/activities/']")
            activity_url_for_log = link_element.get_attribute("href")
            if activity_url_for_log and activity_url_for_log.startswith("/"):
                activity_url_for_log = BASE_URL + activity_url_for_log
            if activity_url_for_log and "/activities/" in activity_url_for_log:
                activity_id_for_log = activity_url_for_log.split('/')[-1]
        except NoSuchElementException:
            logger.debug(f"フィードアイテム内から活動記録URLの取得に失敗 (ログ用)。activity_id: {activity_id_for_log}")
            # URLがなくてもDOMO処理は続行

        logger.info(f"タイムラインアイテム ({activity_id_for_log}) へ直接DOMOを試みます。")

        # 1. DOMOボタンの探索 (フィードアイテム要素内を起点とする)
        domo_button = None
        current_selector_used = ""
        button_found_but_not_clickable = False

        for idx, selector in enumerate(domo_button_selectors):
            logger.debug(f"DOMOボタン探索試行 #{idx+1} (セレクタ: '{selector}') in feed item: {activity_id_for_log}")
            try:
                # presence_of_element_located は driver を起点とするため、feed_item_element.find_element を使う
                # WebDriverWait は要素の可視性やクリック可能性を待つために使用
                wait_time = timeline_domo_settings.get("domo_button_wait_sec_on_timeline", 3) # 設定から待機時間を取得

                # まず要素が存在するか確認 (feed_item_element を起点)
                # WebDriverWait で feed_item_element を起点とした検索は直接サポートされないため、
                # feed_item_element.find_element で探し、見つかればクリック可能か WebDriverWait で確認する
                candidate_buttons = feed_item_element.find_elements(By.CSS_SELECTOR, selector)
                if not candidate_buttons:
                    logger.debug(f"セレクタ '{selector}' でDOMOボタン候補が見つかりません (in feed item: {activity_id_for_log})。")
                    continue

                # 複数のボタンが見つかる可能性は低いが一応最初の要素を対象とする
                # クリック可能になるまで待機
                domo_button_candidate = WebDriverWait(driver, wait_time).until(
                    EC.element_to_be_clickable(candidate_buttons[0])
                )

                if domo_button_candidate:
                    domo_button = domo_button_candidate
                    current_selector_used = selector
                    logger.info(f"DOMOボタンをフィードアイテム内で発見し、クリック可能です (使用セレクタ: '{selector}') for item: {activity_id_for_log}")
                    button_found_but_not_clickable = False
                    break
                else:
                    logger.debug(f"セレクタ '{selector}' でDOMOボタン候補が見つかりましたが、無効な要素でした (in feed item: {activity_id_for_log})。")
            except TimeoutException:
                if feed_item_element.find_elements(By.CSS_SELECTOR, selector):
                    logger.warning(f"セレクタ '{selector}' でDOMOボタン要素はフィードアイテム内に存在しますが、クリック可能状態になりませんでした (item: {activity_id_for_log})。")
                    button_found_but_not_clickable = True
                else:
                    logger.debug(f"セレクタ '{selector}' でDOMOボタンがフィードアイテム内で見つからず、タイムアウトしました (item: {activity_id_for_log})。")
            except NoSuchElementException: # find_elements が空リストを返すので、ここは通常通らない
                 logger.debug(f"セレクタ '{selector}' でDOMOボタンがフィードアイテム内で見つかりませんでした (NoSuchElement) (item: {activity_id_for_log})。")
            except Exception as e_sel:
                logger.warning(f"セレクタ '{selector}' でフィードアイテム内のDOMOボタン探索中に予期せぬエラー: {type(e_sel).__name__} - {e_sel} (item: {activity_id_for_log})", exc_info=False) # exc_info=False でスタックトレースを抑制

        if not domo_button:
            if button_found_but_not_clickable:
                logger.error(f"DOMO失敗(Timeline): DOMOボタン要素はアイテム内に見つかりましたがクリック可能な状態ではありませんでした (item: {activity_id_for_log}, selectors: {domo_button_selectors})。")
            else:
                logger.error(f"DOMO失敗(Timeline): DOMOボタンがアイテム内で見つかりませんでした (item: {activity_id_for_log}, selectors: {domo_button_selectors})。")
            return False

        # 2. DOMO済みかどうかの判定
        aria_label_before = domo_button.get_attribute("aria-label")
        is_domoed = False

        if aria_label_before and ("Domo済み" in aria_label_before or "domoed" in aria_label_before.lower() or "ドモ済み" in aria_label_before):
            is_domoed = True
        else:
            try:
                # アイコンのクラスで判定 (提供されたHTML断片に基づく)
                # button要素の直接の子または孫に span.RidgeIcon がある想定
                icon_span = domo_button.find_element(By.CSS_SELECTOR, "span.RidgeIcon, span[class*='DomoActionContainer__DomoIcon']") # より汎用的に
                if "is-active" in (icon_span.get_attribute("class") or ""):
                    is_domoed = True
            except NoSuchElementException:
                logger.debug(f"DOMOボタン内のis-activeアイコンspanが見つかりませんでした (item: {activity_id_for_log})。aria-labelに依存します。")

        if is_domoed:
            logger.info(f"既にDOMO済みです (タイムラインアイテム: {activity_id_for_log}, aria-label='{aria_label_before}')")
            return False # 既にDOMO済みなのでFalseを返して処理終了 (DOMOは実行していない)

        # 3. DOMO実行 (まだDOMOしていなければ)
        logger.info(f"タイムラインアイテム ({activity_id_for_log}) 上でDOMOを実行します (使用ボタンセレクタ: '{current_selector_used}')")
        url_before_click = driver.current_url # クリック前のURLを記録

        try:
            # 要素が画面内に表示されるようにスクロール (中央揃え)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", domo_button)
            time.sleep(0.2) # スクロール後の描画待ち
            domo_button.click()
            logger.debug(f"DOMOボタンクリック実行 (item: {activity_id_for_log})。")
        except Exception as e_click:
            logger.error(f"DOMOボタンのクリックに失敗しました (item: {activity_id_for_log}): {e_click}", exc_info=True)
            save_screenshot(driver, error_type="DOMO_ClickError_Timeline", context_info=f"{activity_id_for_log}")
            return False

        # 4. ページ遷移が発生したか確認
        time.sleep(0.5) # ページ遷移が発生する可能性を考慮した短い待機
        url_after_click = driver.current_url
        if url_after_click != url_before_click:
            logger.warning(
                f"DOMOボタンクリック後、意図しないページ遷移が発生しました (item: {activity_id_for_log})。"
                f"遷移前URL: {url_before_click}, 遷移後URL: {url_after_click}。"
                f"元のタイムライン ({timeline_url}) に戻ります。"
            )
            save_screenshot(driver, error_type="UnexpectedPageTransition_DOMO_Timeline", context_info=f"{activity_id_for_log}_to_{url_after_click.split('/')[-1]}")
            driver.get(timeline_url)
            try:
                # タイムラインに戻った後、フィードアイテムが再認識されるように少し待つ
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "li.TimelineList__Feed")) # 一般的なフィードアイテムセレクタ
                )
                logger.info(f"元のタイムライン ({timeline_url}) に戻りました。")
            except TimeoutException:
                logger.error(f"タイムライン ({timeline_url}) に戻ろうとしましたが、フィードアイテムの再表示確認でタイムアウトしました。")
                # この場合、さらなる処理は困難なため False を返す
            return False # ページ遷移が発生した場合はDOMO成否不明のためFalse

        # 5. DOMO後の状態変化確認 (ページ遷移がなかった場合のみ)
        try:
            WebDriverWait(driver, 5).until(
                lambda d: ("Domo済み" in (feed_item_element.find_element(By.CSS_SELECTOR, current_selector_used).get_attribute("aria-label") or "")) or \
                          ("is-active" in (feed_item_element.find_element(By.CSS_SELECTOR, f"{current_selector_used} span.RidgeIcon, {current_selector_used} span[class*='DomoActionContainer__DomoIcon']").get_attribute("class") or ""))
            )

            final_button_state = "N/A"
            try:
                button_after_action = feed_item_element.find_element(By.CSS_SELECTOR, current_selector_used)
                aria_label_after = button_after_action.get_attribute("aria-label")
                icon_class_after = "N/A"
                try:
                    icon_after = button_after_action.find_element(By.CSS_SELECTOR, "span.RidgeIcon, span[class*='DomoActionContainer__DomoIcon']")
                    icon_class_after = icon_after.get_attribute("class")
                except: pass
                final_button_state = f"aria-label='{aria_label_after}', icon_class='{icon_class_after}'"
            except Exception as e_log_state:
                 logger.debug(f"DOMO後の状態取得中に軽微なエラー: {e_log_state}")

            logger.info(f"DOMO成功を確認しました (タイムラインアイテム: {activity_id_for_log}, 最終状態: {final_button_state})")
            time.sleep(delay_after_action)
            return True
        except TimeoutException:
            actual_aria_label = "取得失敗"
            actual_icon_class = "取得失敗"
            try:
                button_element_after_click = feed_item_element.find_element(By.CSS_SELECTOR, current_selector_used)
                actual_aria_label = button_element_after_click.get_attribute("aria-label") or "aria-labelなし"
                try:
                    icon_span_after_click = button_element_after_click.find_element(By.CSS_SELECTOR, "span.RidgeIcon, span[class*='DomoActionContainer__DomoIcon']")
                    actual_icon_class = icon_span_after_click.get_attribute("class") or "classなし"
                except NoSuchElementException:
                    actual_icon_class = "アイコンspanなし"
            except Exception as e_attr_confirm:
                logger.error(f"DOMO後の属性取得中(確認タイムアウト内)にエラー: {type(e_attr_confirm).__name__} (item: {activity_id_for_log})")

            logger.error(
                f"DOMO失敗(Timeline): DOMO実行後、状態変化の確認でタイムアウト (Item: {activity_id_for_log}, セレクタ: '{current_selector_used}'). "
                f"期待: aria-labelに'Domo済み' OR アイコンクラスに'is-active'. "
                f"実際: aria-label='{actual_aria_label}', icon_class='{actual_icon_class}'"
            )
            save_screenshot(driver, error_type="DOMO_ConfirmTimeout_Timeline", context_info=f"{activity_id_for_log}_selector_{current_selector_used.replace('.', '_').replace('#', '_')}")
            time.sleep(delay_after_action)
            return False

    except Exception as e:
        logger.error(f"タイムラインアイテム ({activity_id_for_log}) 上でのDOMO実行中に予期せぬエラー: {type(e).__name__} - {e}", exc_info=True)
        save_screenshot(driver, error_type="UnhandledException_DOMO_TimelineItem", context_info=f"{activity_id_for_log}_{type(e).__name__}")
    return False


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
        logger.info("並列処理が無効なため、タイムラインDOMOは逐次実行されます (一覧DOMO版)。")
        # 逐次版 (domo_timeline_activities) は既に一覧DOMOに対応済みのため、それを呼び出す
        return domo_timeline_activities(driver)

    # --- 以下、並列処理版のロジック (現状はURL収集ベースのまま) ---
    # TODO: この並列処理版も、domo_activity_on_timeline を使うように改修が必要。
    #       WebElementをスレッド間で安全に扱うか、あるいはフィードアイテムの
    #       一意な識別子（例：活動記録IDやdata属性）を収集し、各タスクで
    #       再度要素を検索・操作する方式を検討する必要がある。
    #       現状は、URLを収集して各URLのページに遷移してDOMOする古い方式のまま。
    logger.warning("[PARALLEL] 現在のタイムラインDOMO並列処理版は、まだ一覧上での直接DOMOに対応していません。")
    logger.warning("[PARALLEL] 各活動記録ページに遷移してDOMOする従来の並列処理を実行します。")

    logger.info(">>> [PARALLEL - Legacy URL based] タイムラインDOMO機能を開始します...")
    timeline_page_url = TIMELINE_URL
    logger.info(f"タイムラインページへアクセスし、DOMO対象URLを収集します: {timeline_page_url}")
    driver.get(timeline_page_url)

    max_activities_to_domo = TIMELINE_DOMO_SETTINGS.get("max_activities_to_domo_on_timeline", 10)
    max_workers = PARALLEL_PROCESSING_SETTINGS.get("max_workers", 3)
    task_delay_base = PARALLEL_PROCESSING_SETTINGS.get("delay_between_thread_tasks_sec", 1.0)

    activity_urls_to_domo = []
    processed_urls_for_collection = set()

    try:
        feed_item_selector = "li.TimelineList__Feed"
        activity_item_indicator_selector = "div.TimelineActivityItem"
        activity_link_in_item_selector = "a.TimelineActivityItem__BodyLink[href^='/activities/']"

        logger.info(f"タイムラインのフィードアイテム ({feed_item_selector}) の出現を待ちます...")
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, feed_item_selector))
        )
        logger.info("タイムラインのフィードアイテム群を発見。URL収集を開始します。")
        time.sleep(TIMELINE_DOMO_SETTINGS.get("wait_after_feed_load_sec", 1.5))


        feed_items = driver.find_elements(By.CSS_SELECTOR, feed_item_selector)
        if not feed_items:
            logger.info("タイムラインにフィードアイテムが見つかりませんでした（URL収集フェーズ）。")
            return

        for idx, feed_item_element in enumerate(feed_items):
            if len(activity_urls_to_domo) >= max_activities_to_domo:
                logger.info(f"DOMO対象URLの収集上限 ({max_activities_to_domo}件) に達しました。")
                break
            try:
                if not feed_item_element.find_elements(By.CSS_SELECTOR, activity_item_indicator_selector):
                    continue

                link_element = feed_item_element.find_element(By.CSS_SELECTOR, activity_link_in_item_selector)
                activity_url = link_element.get_attribute("href")

                if activity_url:
                    if activity_url.startswith("/"): activity_url = BASE_URL + activity_url
                    if not activity_url.startswith(f"{BASE_URL}/activities/"): continue
                    if activity_url in processed_urls_for_collection: continue

                    activity_urls_to_domo.append(activity_url)
                    processed_urls_for_collection.add(activity_url)
                    logger.debug(f"DOMO候補URL追加 (Legacy Parallel): {activity_url.split('/')[-1]} (収集済み: {len(activity_urls_to_domo)}件)")
            except Exception as e_collect:
                logger.warning(f"タイムラインからのURL収集中にエラー (アイテム {idx+1}, Legacy Parallel): {e_collect}")

        logger.info(f"収集したDOMO対象URLは {len(activity_urls_to_domo)} 件です (Legacy Parallel)。")
        if not activity_urls_to_domo:
            logger.info("DOMO対象となる活動記録URLが収集できませんでした (Legacy Parallel)。")
            return

        total_domoed_count_parallel = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for i, url in enumerate(activity_urls_to_domo):
                delay_for_this_task = task_delay_base + (i * 0.1)
                futures.append(executor.submit(domo_activity_task, url, shared_cookies, delay_for_this_task))

            for future in as_completed(futures):
                try:
                    if future.result():
                        total_domoed_count_parallel += 1
                except Exception as e_future:
                    logger.error(f"並列DOMOタスクの実行結果取得中にエラー (Legacy Parallel): {e_future}", exc_info=True)

        logger.info(f"<<< [PARALLEL - Legacy URL based] タイムラインDOMO機能完了。合計 {total_domoed_count_parallel} 件の活動記録にDOMOしました (試行対象: {len(activity_urls_to_domo)}件)。")

    except TimeoutException:
        logger.warning("[PARALLEL - Legacy URL based] タイムライン活動記録のURL収集でタイムアウトしました。")
    except Exception as e:
        logger.error(f"[PARALLEL - Legacy URL based] タイムラインDOMO処理中に予期せぬエラーが発生しました。", exc_info=True)
