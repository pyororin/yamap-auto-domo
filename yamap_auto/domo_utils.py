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
from selenium.webdriver.common.action_chains import ActionChains # ActionChainsをインポート
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
    # 呼び出し元の yamap_auto_domo.py の execute_main_tasks で
    # main_config.get("enable_timeline_domo") をチェックしているので、ここでのガードは不要。
    # if not main_config.get("enable_timeline_domo", False): # main_config はグローバル/モジュールレベルで利用可能
    #     logger.info("タイムラインDOMO機能は設定で無効になっています。(from domo_utils.domo_timeline_activities)")
    #     return # 呼び出し元は戻り値を期待していないので、そのままreturn

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
    return domoed_count


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
            # JavaScript経由のクリック(domo_button.click() や driver.execute_script("arguments[0].click();", domo_button))では
            # DOMO後の状態変化が確認できなかったため、ActionChainsを使用する。
            ActionChains(driver).move_to_element(domo_button).click().perform()
            logger.debug(f"DOMOボタンクリック実行 (ActionChains経由) (item: {activity_id_for_log})。")
        except Exception as e_click:
            logger.error(f"DOMOボタンのクリック (ActionChains経由) に失敗しました (item: {activity_id_for_log}): {e_click}", exc_info=True)
            save_screenshot(driver, error_type="DOMO_ClickError_Timeline_ActionChains", context_info=f"{activity_id_for_log}")
            return False

        # 4. ページ遷移が発生したか確認
        # (ActionChainsの使用により、意図しないページ遷移の問題は発生しにくくなったはずだが、安全のためにチェック処理は残す)
        time.sleep(0.5) # ページ遷移が発生する可能性を考慮した短い待機
        url_after_click = driver.current_url
        if url_after_click != url_before_click:
            logger.warning(
                f"DOMOボタンクリック後、意図しないページ遷移が発生しました (item: {activity_id_for_log})。"
                f"遷移前URL: {url_before_click}, 遷移後URL: {url_after_click}。"
                f"元のタイムライン ({timeline_url}) に戻ろうと試みます。"
            )
            save_screenshot(driver, error_type="UnexpectedPageTransition_DOMO_Timeline", context_info=f"{activity_id_for_log}_to_{url_after_click.split('/')[-1]}")
            driver.get(timeline_url) # 元のタイムラインに戻る
            try:
                # タイムラインに戻った後、主要な要素（例：フィードアイテム）が再認識されるように少し待つ
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "li.TimelineList__Feed"))
                )
                logger.info(f"元のタイムライン ({timeline_url}) に正常に戻りました。")
            except TimeoutException:
                logger.error(f"タイムライン ({timeline_url}) に戻ろうとしましたが、フィードアイテムの再表示確認でタイムアウトしました。このアイテムの処理は中断します。")
            return False # ページ遷移が発生した場合は、DOMO成否に関わらずこのアイテムの処理は失敗として扱う

        # 5. DOMO後の状態変化確認 (ページ遷移がなかった場合のみ実行される)
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


# --- タイムラインDOMO機能 (並列処理対応版) ---
def domo_timeline_activities_parallel(driver, shared_cookies, current_user_id): # Added current_user_id
    """
    タイムライン上の活動記録にDOMOする機能の並列処理版です。
    `config.yaml` の `timeline_domo_settings` および `parallel_processing_settings` に従って動作します。
    メインのWebDriverでタイムラインからDOMO対象の活動記録アイテムのインデックスを収集し、
    収集したインデックス群に対して `ThreadPoolExecutor` を使用して並列でDOMO処理を行います。

    Args:
        driver (webdriver.Chrome): メインのSelenium WebDriverインスタンス (URL収集用)。
        shared_cookies (list[dict]): メインのWebDriverから取得したログインセッションCookie。
        current_user_id (str): 現在ログインしているユーザーのID。
    """
    # 機能が有効かチェック (config.yaml)
    # 呼び出し元の yamap_auto_domo.py の execute_main_tasks で
    # main_config.get("enable_timeline_domo") をチェックしているので、ここでのガードは不要。
    # if not main_config.get("enable_timeline_domo", False): # main_config はグローバル/モジュールレベルで利用可能
    #     logger.info("タイムラインDOMO機能は設定で無効になっています。(from domo_utils.domo_timeline_activities_parallel)")
    #     return 0 # DOMO件数0を返す

    # 並列処理自体が有効かチェック (config.yaml)
    # PARALLEL_PROCESSING_SETTINGS は main_config から取得済みなのでそのまま利用
    if not PARALLEL_PROCESSING_SETTINGS.get("enable_parallel_processing", False):
        logger.info("並列処理が無効なため、タイムラインDOMOは逐次実行されます (一覧DOMO版)。")
        # 逐次版 (domo_timeline_activities) は既に一覧DOMOに対応済みのため、それを呼び出す
        return domo_timeline_activities(driver) # domo_timeline_activities がカウントを返すように改修済み

    # --- 並列処理版のロジック (一覧上での直接DOMOに対応) ---
    # メインのWebDriverでタイムラインからDOMO対象の活動記録アイテムのインデックスを収集し、
    # 収集したインデックス群に対して `ThreadPoolExecutor` を使用して並列でDOMO処理を行います。
    # 各タスクは新しいWebDriverインスタンスを生成し、`domo_activity_on_timeline` を実行します。

    logger.info(">>> [PARALLEL] タイムラインDOMO機能 (一覧上で直接DOMO) を開始します...")
    timeline_page_url = TIMELINE_URL
    # メインドライバーはタイムラインページにいる想定だが、念のため遷移または確認
    current_url = driver.current_url
    if current_url != timeline_page_url:
        logger.info(f"メインドライバーをタイムラインページ ({timeline_page_url}) へ移動します。(現在URL: {current_url})")
        driver.get(timeline_page_url)
        try:
            WebDriverWait(driver, 15).until(EC.url_to_be(timeline_page_url))
            logger.info(f"メインドライバーのタイムラインページ ({timeline_page_url}) への移動を確認しました。")
        except TimeoutException:
            logger.error(f"メインドライバーをタイムラインページ ({timeline_page_url}) へ移動試行後、URL遷移確認でタイムアウト。処理を中止します。")
            return # ページ遷移に失敗した場合は処理を続行できない
    else:
        logger.info(f"メインドライバーは既にタイムラインページ ({timeline_page_url}) にいます。")

    max_activities_to_domo = TIMELINE_DOMO_SETTINGS.get("max_activities_to_domo_on_timeline", 10)
    max_workers = PARALLEL_PROCESSING_SETTINGS.get("max_workers", 3)

    # DOMO対象となるフィードアイテムの「インデックス」を収集する。
    # 注意: DOM操作によりインデックスがずれる可能性あり。より堅牢なのは各アイテムの一意なID(例: data-activity-id)だが、
    #       現状はインデックスベースで動作確認済みのため、この方式を維持。問題発生時に改善を検討。
    feed_item_indices_to_domo = []

    try:
        feed_item_selector = "li.TimelineList__Feed"
        activity_item_indicator_selector = "div.TimelineActivityItem" # 活動記録アイテムであることの目印

        logger.info(f"タイムラインのフィードアイテム ({feed_item_selector}) の出現を待ち、DOMO対象インデックスを収集します...")
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, feed_item_selector))
        )
        logger.info("タイムラインのフィードアイテム群を発見。DOMO対象の選定を開始します。")
        time.sleep(TIMELINE_DOMO_SETTINGS.get("wait_after_feed_load_sec", 1.5)) # ページ描画安定待ち

        # メインドライバーで表示されているフィードアイテムのリストを取得。
        # ここでは活動記録アイテムであるかどうかのフィルタリングとインデックス収集のみを行う。
        # DOMO済み判定や実際のDOMO処理は各並列タスクに委ねる。
        all_feed_items_on_page = driver.find_elements(By.CSS_SELECTOR, feed_item_selector)
        if not all_feed_items_on_page:
            logger.info("タイムラインにフィードアイテムが見つかりませんでした（DOMO対象収集フェーズ）。")
            return

        logger.info(f"検出されたフィードアイテム総数: {len(all_feed_items_on_page)} 件。活動記録アイテムをフィルタリングします。")
        collected_count = 0
        for idx, feed_item_element in enumerate(all_feed_items_on_page):
            if collected_count >= max_activities_to_domo:
                logger.info(f"DOMO対象の収集上限 ({max_activities_to_domo}件) に達しました。")
                break
            try:
                # このアイテムが活動記録アイテムであるかを確認
                if feed_item_element.find_elements(By.CSS_SELECTOR, activity_item_indicator_selector):
                    # DOMO済みかどうかをメインスレッドで判定するのはコストが高い場合がある。
                    # (各アイテムのボタン状態を確認する必要があるため)
                    # ここでは、活動記録アイテムであれば一旦インデックスを収集し、
                    # DOMO済み判定は各並列タスク内の domo_activity_on_timeline に委ねる。
                    feed_item_indices_to_domo.append(idx)
                    collected_count +=1
                    logger.debug(f"DOMO候補インデックス追加: {idx} (収集済み: {collected_count}件)")
                else:
                    logger.debug(f"フィードアイテム (インデックス: {idx}) は活動記録ではないためスキップ。")
            except Exception as e_collect:
                logger.warning(f"タイムラインからのDOMO対象収集中にエラー (アイテムインデックス {idx}): {e_collect}")

        logger.info(f"収集したDOMO対象候補のフィードアイテムインデックスは {len(feed_item_indices_to_domo)} 件です。")
        if not feed_item_indices_to_domo:
            logger.info("DOMO対象となる活動記録アイテムが見つかりませんでした。")
            return

        # 並列処理の実行
        total_domoed_count_parallel = 0
        # domo_activity_on_timeline で使用するセレクタと設定を渡す
        domo_button_selectors_for_timeline = TIMELINE_DOMO_SETTINGS.get(
            "domo_button_selectors_on_timeline",
            [
                "button[data-testid='ActivityDomoButton']",
                "button#DomoActionButton",
                "div.ActivityItemActions__DomoActionContainer button"
            ]
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            # タスクに渡す引数を準備
            # shared_cookies はこの関数の引数として渡されているものを使用
            # timeline_url は TIMELINE_URL グローバル定数を使用
            # timeline_domo_settings は TIMELINE_DOMO_SETTINGS グローバル/モジュールレベル変数を使用

            for i, item_idx in enumerate(feed_item_indices_to_domo):
                # タスク間の開始タイミングを少しずらすための遅延 (任意)
                # task_start_delay = PARALLEL_PROCESSING_SETTINGS.get("delay_between_thread_starts_sec", 0.2) * i
                # time.sleep(task_start_delay) # メインスレッドで遅延させるか、タスク側で遅延させるか

                futures.append(executor.submit(
                    domo_timeline_item_task, # 新しいタスク関数
                    item_idx,
                    shared_cookies,
                    current_user_id, # Pass current_user_id
                    TIMELINE_URL, # タイムラインページのURL
                    domo_button_selectors_for_timeline,
                    TIMELINE_DOMO_SETTINGS, # timeline_domo_settings を渡す
                    PARALLEL_PROCESSING_SETTINGS.get("delay_between_thread_tasks_sec", 0.1) * i # 個別タスク遅延
                ))

            for future in as_completed(futures):
                try:
                    if future.result(): # domo_timeline_item_task が True を返せばカウント
                        total_domoed_count_parallel += 1
                except Exception as e_future:
                    logger.error(f"並列DOMOタスクの実行結果取得中にエラー: {e_future}", exc_info=True)

        logger.info(f"<<< [PARALLEL] タイムラインDOMO機能 (一覧上で直接DOMO) 完了。合計 {total_domoed_count_parallel} 件の活動記録にDOMOしました (試行対象インデックス数: {len(feed_item_indices_to_domo)}件)。")

    except TimeoutException:
        logger.warning("[PARALLEL] タイムライン活動記録のDOMO対象収集でタイムアウトしました。")
        return 0 # エラー時は0件
    except Exception as e:
        logger.error(f"[PARALLEL] タイムラインDOMO処理 (一覧上で直接DOMO) 中に予期せぬエラーが発生しました。", exc_info=True)
        return 0 # エラー時は0件
    return total_domoed_count_parallel

# 新しい並列タスク関数
def domo_timeline_item_task(
    feed_item_index,
    shared_cookies,
    current_user_id, # Added current_user_id
    timeline_url_to_load,
    domo_button_selectors,
    timeline_domo_config_settings, # timeline_domo_settings全体を渡す
    initial_delay_sec # このタスクが実際に処理を開始するまでの遅延
):
    """
    単一のタイムラインフィードアイテムに対してDOMO処理を行うタスク関数（並列処理用）。
    新しいWebDriverインスタンスを作成し、指定されたインデックスのフィードアイテムにDOMOを試みます。
    """
    task_driver = None
    action_delays = main_config.get("action_delays", {}) # main_config はグローバルアクセス可能想定

    log_prefix = f"[DOMO_TASK Idx:{feed_item_index}]"
    logger.info(f"{log_prefix} DOMOタスク開始。初期遅延: {initial_delay_sec:.2f}秒。")
    time.sleep(initial_delay_sec)

    try:
        # 1. 新しいWebDriverインスタンスを作成し、共有Cookieでログイン状態を再現
        # create_driver_with_cookies は current_user_id を必須とするように変更された
        logger.info(f"{log_prefix} WebDriverを作成し、Cookieを設定・検証します。(User ID: {current_user_id})")
        task_driver = create_driver_with_cookies(shared_cookies, current_user_id)
        if not task_driver:
            # create_driver_with_cookies がNoneを返した場合、内部でエラーログとスクショ取得済み
            logger.error(f"{log_prefix} WebDriverの作成またはCookie/ログイン検証に失敗。タスクを中止。")
            return False

        # create_driver_with_cookies が成功した場合、ドライバーはログイン済みで、
        # 現在のページはユーザー自身のマイページのはず。
        # 次に、このタスクの目的であるタイムラインページに遷移する。
        logger.info(f"{log_prefix} ログイン検証済み。対象のタイムラインページ ({timeline_url_to_load}) にアクセスします。")
        task_driver.get(timeline_url_to_load)

        # タイムラインページが正しく読み込まれたか確認
        try:
            WebDriverWait(task_driver, 15).until(EC.url_to_be(timeline_url_to_load))
            logger.info(f"{log_prefix} タイムラインページ ({timeline_url_to_load}) への遷移を確認。")
        except TimeoutException:
            logger.error(f"{log_prefix} タイムラインページ ({timeline_url_to_load}) へのURL遷移が15秒以内に確認できませんでした。現在のURL: {task_driver.current_url}")
            save_screenshot(task_driver, "TimelineNavFail_DomoTask", f"idx_{feed_item_index}")
            return False # ページ遷移失敗

        # 以前のタスク内での冗長なログイン確認ブロックは削除。
        # create_driver_with_cookies での検証に一本化。

        # 3. タイムラインのフィードアイテムリストを再取得
        feed_item_selector_in_task = "li.TimelineList__Feed"
        # 要素が表示されるまで待機 (少し長めに設定)
        wait_time_for_feed = timeline_domo_config_settings.get("wait_for_feed_items_in_task_sec", 20)
        logger.debug(f"{log_prefix} フィードアイテム ({feed_item_selector_in_task}) の出現を待ちます (最大{wait_time_for_feed}秒)...")
        WebDriverWait(task_driver, wait_time_for_feed).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, feed_item_selector_in_task))
        )
        feed_items_in_task = task_driver.find_elements(By.CSS_SELECTOR, feed_item_selector_in_task)
        logger.debug(f"{log_prefix} {len(feed_items_in_task)} 件のフィードアイテムを検出。")


        if feed_item_index >= len(feed_items_in_task):
            logger.warning(f"{log_prefix} 指定インデックス {feed_item_index} がフィードアイテム数 {len(feed_items_in_task)} を超えています。タスク中止。")
            # StaleElement対策として、メインスレッドでの収集時とアイテム数が変わる可能性も考慮
            save_screenshot(task_driver, "TimelineItemIndexError", f"idx_{feed_item_index}_total_{len(feed_items_in_task)}")
            return False

        target_feed_item_element = feed_items_in_task[feed_item_index]
        logger.info(f"{log_prefix} 対象のフィードアイテム (インデックス: {feed_item_index}) を取得。")

        # 4. 取得したフィードアイテム要素に対して domo_activity_on_timeline を呼び出し
        #    この関数は既にページ遷移しないように修正されている前提
        #    timeline_url_to_load は、万が一ページ遷移した場合の戻り先として渡す
        domo_result = domo_activity_on_timeline(
            task_driver,
            target_feed_item_element,
            domo_button_selectors, # メインから渡されたセレクタリスト
            timeline_domo_config_settings, # メインから渡された設定辞書
            timeline_url_to_load
        )

        if domo_result:
            logger.info(f"{log_prefix} DOMO成功。")
        else:
            logger.info(f"{log_prefix} DOMO失敗または既にDOMO済み/対象外。")

        # 短い遅延を入れてWebDriverの終了処理が早すぎないようにする (任意)
        time.sleep(action_delays.get("after_task_completion_sec", 0.2))
        return domo_result

    except TimeoutException as e_timeout:
        logger.error(f"{log_prefix} DOMOタスク処理中にタイムアウト発生: {e_timeout}", exc_info=False)
        save_screenshot(task_driver, "TimelineItemTaskTimeout", f"idx_{feed_item_index}")
        return False
    except NoSuchElementException as e_no_such: # 個別の要素が見つからない場合など
        logger.error(f"{log_prefix} DOMOタスク処理中に要素が見つかりません: {e_no_such}", exc_info=False)
        save_screenshot(task_driver, "TimelineItemTaskNoSuchElement", f"idx_{feed_item_index}")
        return False
    except Exception as e:
        logger.error(f"{log_prefix} DOMOタスク中に予期せぬエラー: {type(e).__name__} - {e}", exc_info=True)
        save_screenshot(task_driver, "TimelineItemTaskError", f"idx_{feed_item_index}_{type(e).__name__}")
        return False
    finally:
        if task_driver:
            try:
                task_driver.quit()
                logger.debug(f"{log_prefix} WebDriverを終了しました。")
            except Exception as e_quit:
                logger.error(f"{log_prefix} WebDriver終了中にエラー: {e_quit}")
        logger.info(f"{log_prefix} DOMOタスク終了。")
