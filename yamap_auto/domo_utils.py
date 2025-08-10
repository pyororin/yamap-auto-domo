# coding: utf-8
"""
YAMAP DOMO関連ユーティリティ関数群
"""
import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains

from .driver_utils import get_main_config, save_screenshot

logger = logging.getLogger(__name__)

BASE_URL = "https://yamap.com"
TIMELINE_URL = f"{BASE_URL}/timeline"

try:
    main_config = get_main_config()
    TIMELINE_DOMO_SETTINGS = main_config.get("timeline_domo_settings", {})
except Exception as e:
    logger.error(f"domo_utils: 設定情報の読み込み中にエラー: {e}", exc_info=True)
    main_config = {}
    TIMELINE_DOMO_SETTINGS = {}

def _domo_an_activity(driver, feed_item_element):
    """
    タイムラインの単一フィードアイテム上で直接DOMOを実行します。
    """
    activity_id_for_log = "N/A"
    try:
        link_element = feed_item_element.find_element(By.CSS_SELECTOR, "a[href*='/activities/']")
        activity_url = link_element.get_attribute("href")
        if activity_url and "/activities/" in activity_url:
            activity_id_for_log = activity_url.split('/')[-1]
    except NoSuchElementException:
        pass # Not a log-critical error

    log_prefix = f"[DOMO_ACTION][{activity_id_for_log}]"

    # 1. Check if already reacted
    try:
        feed_item_element.find_element(By.CSS_SELECTOR, "button.emoji-button.viewer-has-reacted")
        logger.info(f"{log_prefix} 既にリアクション済みのためスキップします。")
        return False
    except NoSuchElementException:
        # Not reacted, can proceed
        pass

    # 2. Click the 'add emoji' button and then the 'DOMO' button
    try:
        add_emoji_button = feed_item_element.find_element(By.CSS_SELECTOR, "button.emoji-add-button")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", add_emoji_button)
        time.sleep(0.5)
        add_emoji_button.click()
        logger.info(f"{log_prefix} 絵文字追加ボタン(+)をクリックしました。")

        # Wait for the DOMO button to appear in the picker and click it
        domo_emoji_selector = "button[title='DOMO']"
        domo_emoji = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, domo_emoji_selector))
        )
        domo_emoji.click()
        logger.info(f"{log_prefix} DOMOボタンをクリックしました。")
        time.sleep(1.5) # Wait for action to complete
        return True

    except (NoSuchElementException, TimeoutException) as e:
        logger.warning(f"{log_prefix} DOMO処理に失敗しました。ボタンが見つからないかタイムアウトしました。詳細: {type(e).__name__}")
        save_screenshot(driver, "DOMO_TimelineFail", activity_id_for_log)
        # Try to close any lingering emoji picker by clicking the body
        try:
            driver.find_element(By.TAG_NAME, 'body').click()
        except Exception as e_click_body:
            logger.debug(f"{log_prefix} DOMO失敗後のリカバリクリックでエラー: {e_click_body}")
        return False
    except Exception as e:
        logger.error(f"{log_prefix} 予期せぬエラー: {e}", exc_info=True)
        save_screenshot(driver, "DOMO_TimelineError", activity_id_for_log)
        return False

def domo_timeline_activities(driver):
    """
    タイムライン上の活動記録にDOMOする機能（逐次処理版）。
    設定に従い、タイムライン上の活動に順次DOMOします。
    """
    logger.info(">>> タイムラインDOMO機能を開始します...")
    driver.get(TIMELINE_URL)

    max_domo = TIMELINE_DOMO_SETTINGS.get("max_activities_to_domo_on_timeline", 10)
    domoed_count = 0
    processed_activities = set()

    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li.TimelineList__Feed"))
        )
        logger.info("タイムラインのフィードアイテム群を発見。")
        time.sleep(TIMELINE_DOMO_SETTINGS.get("wait_after_feed_load_sec", 2.0))

        feed_items = driver.find_elements(By.CSS_SELECTOR, "li.TimelineList__Feed")
        logger.info(f"タイムラインから {len(feed_items)} 件のフィードアイテムを検出しました。")

        for i, item in enumerate(feed_items):
            if domoed_count >= max_domo:
                logger.info(f"DOMOの上限 ({max_domo}件) に達しました。")
                break

            try:
                # Get a unique identifier for the activity to avoid re-processing
                activity_link_element = item.find_element(By.CSS_SELECTOR, "a[href*='/activities/']")
                activity_url = activity_link_element.get_attribute('href')

                if activity_url in processed_activities:
                    continue
                processed_activities.add(activity_url)

                if _domo_an_activity(driver, item):
                    domoed_count += 1

                # Wait a bit before processing the next item
                time.sleep(TIMELINE_DOMO_SETTINGS.get("delay_between_item_processing_sec", 0.5))

            except StaleElementReferenceException:
                logger.warning(f"フィードアイテム {i+1} の処理中に StaleElementReferenceException が発生しました。DOMが変更されたため、このアイテムをスキップします。")
                feed_items = driver.find_elements(By.CSS_SELECTOR, "li.TimelineList__Feed") # Re-fetch items
                continue
            except NoSuchElementException:
                # Not an activity item, just a moment or other feed type
                logger.debug(f"フィードアイテム {i+1} は活動記録ではないためスキップします。")
                continue
            except Exception as e:
                logger.error(f"フィードアイテム {i+1} の処理中に予期せぬエラー: {e}", exc_info=True)

    except TimeoutException:
        logger.warning("タイムライン活動記録の読み込みでタイムアウトしました。")
    except Exception as e:
        logger.error(f"タイムラインDOMO処理中に予期せぬエラーが発生しました。", exc_info=True)
        save_screenshot(driver, "DomoTimeline_FatalError")

    logger.info(f"<<< タイムラインDOMO機能完了。合計 {domoed_count} 件の活動記録にDOMOしました。")
    return domoed_count
