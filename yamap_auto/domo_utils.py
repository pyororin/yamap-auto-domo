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
from .driver_utils import get_main_config # main_config を取得するため

logger = logging.getLogger(__name__) # このモジュール用のロガーを取得

# --- グローバル定数 (必要に応じてメインスクリプトから渡すか、ここで定義) ---
# BASE_URL は driver_utils からインポートするか、メインスクリプトから渡す方が望ましい
# ここでは一旦、メインスクリプト側で定義されているものを利用する想定
# from .driver_utils import BASE_URL # driver_utils にあるならこちらが良い

# --- 設定情報の読み込み ---
# main_config はこのモジュールがロードされた時点で driver_utils 経由で読み込まれる想定
# ただし、循環参照や初期化順序に注意が必要。
# 安全策としては、関数呼び出し時に main_config を引数として渡す方が良い。
# ここでは、yamap_auto_domo.py の既存実装に合わせて、グローバルに main_config を参照する。
try:
    main_config = get_main_config()
    if not main_config:
        logger.error("domo_utils: main_config の読み込みに失敗しました。")
        # ここでエラーを発生させるか、デフォルト設定でフォールバックするかは設計次第
        main_config = {} # 空の辞書でフォールバック (エラーを回避するため)
except Exception as e:
    logger.error(f"domo_utils: 設定情報 (main_config) の読み込み中にエラー: {e}", exc_info=True)
    main_config = {}


def domo_activity(driver, activity_url, base_url="https://yamap.com"):
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
