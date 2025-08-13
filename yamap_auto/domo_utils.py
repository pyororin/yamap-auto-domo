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

import os
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

def domo_timeline_activities(driver):
    """
    タイムライン上の活動記録にDOMOします。各活動記録ページに直接アクセスする方式。
    """
    logger.info(">>> タイムラインDOMO機能を開始します (個別ページ訪問方式)...")
    driver.get(TIMELINE_URL)

    max_domo = TIMELINE_DOMO_SETTINGS.get("max_activities_to_domo_on_timeline", 5)
    domoed_count = 0

    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li.TimelineList__Feed a[href*='/activities/']"))
        )
        logger.info("タイムラインのフィードアイテム群を発見。")
        time.sleep(TIMELINE_DOMO_SETTINGS.get("wait_after_feed_load_sec", 2.0))

        # 1. Collect all unique activity URLs first.
        activity_urls = []
        # より具体的なセレクタに変更して、コメントやリアクションのリンクを除外
        feed_links = driver.find_elements(By.CSS_SELECTOR, "div.TimelineActivityItem__Body > a.TimelineActivityItem__BodyLink[href*='/activities/']")
        for link in feed_links:
            try:
                url = link.get_attribute('href')
                if url and url not in activity_urls:
                    activity_urls.append(url)
            except StaleElementReferenceException:
                logger.warning("URL収集中にStaleElementReferenceExceptionが発生しました。スキップします。")
                continue

        unique_urls = sorted(list(set(activity_urls)))
        logger.info(f"タイムラインから {len(unique_urls)} 件のユニークな活動記録URLを検出しました。")

        # 2. Iterate over the collected URLs and visit each page.
        for i, activity_url in enumerate(unique_urls):
            if domoed_count >= max_domo:
                logger.info(f"DOMOの上限 ({max_domo}件) に達しました。")
                break

            activity_id = activity_url.split('/')[-1]
            logger.info(f"処理中 ({i+1}/{len(unique_urls)}): activity_id={activity_id}")

            # The existing domo_activity function will be called here.
            # I will refine it in the next step.
            if domo_activity(driver, activity_url):
                domoed_count += 1

            # Use a reasonable delay between processing items
            time.sleep(TIMELINE_DOMO_SETTINGS.get("delay_between_item_processing_sec", 1.5))

    except TimeoutException:
        logger.warning("タイムライン活動記録の読み込みでタイムアウトしました。")
        save_screenshot(driver, "DomoTimeline_LoadTimeout")
    except Exception as e:
        logger.error(f"タイムラインDOMO処理中に予期せぬエラーが発生しました。", exc_info=True)
        save_screenshot(driver, "DomoTimeline_FatalError")

    logger.info(f"<<< タイムラインDOMO機能完了。合計 {domoed_count} 件の活動記録にDOMOしました。")
    return domoed_count

def domo_activity(driver, activity_url, base_url_for_log=None):
    """
    指定された活動記録URLのページに直接アクセスし、DOMOを実行します。
    (堅牢性を向上させるためにリファクタリング)
    """
    activity_id_for_log = activity_url.split('/')[-1] if activity_url else "N/A"
    log_prefix = f"[DOMO_PAGE][{activity_id_for_log}]"
    logger.info(f"{log_prefix} 活動記録ページ ({activity_url}) にDOMOを実行します。")

    if not activity_url:
        logger.error(f"{log_prefix} activity_urlが提供されませんでした。")
        return False

    try:
        # Navigate if necessary
        if activity_url not in driver.current_url:
            logger.info(f"{log_prefix} ページ ({activity_url}) へ遷移します。")
            driver.get(activity_url)
            WebDriverWait(driver, 25).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.ActivityDetailTabLayout, [data-testid='activity-detail-layout']"))
            )
            logger.info(f"{log_prefix} 主要コンテナの表示を確認。")

        # Check if already reacted
        try:
            driver.find_element(By.CSS_SELECTOR, "button[data-testid='viewer-reaction-button']")
            logger.info(f"{log_prefix} 既にリアクション済みのためスキップします。")
            return False
        except NoSuchElementException:
            pass # Not reacted yet, proceed.

        # Click the 'add emoji' button
        add_emoji_button_selector = "button[aria-label='絵文字をおくる']"
        add_emoji_button = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, add_emoji_button_selector))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", add_emoji_button)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", add_emoji_button) # JS click
        logger.info(f"{log_prefix} 絵文字追加ボタン(+)を(JSで)クリックしました。")

        # Click the DOMO emoji in the picker
        domo_emoji_selector = "button[data-emoji-key='domo']"
        domo_emoji = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, domo_emoji_selector))
        )
        ActionChains(driver).move_to_element(domo_emoji).click().perform() # ActionChains click
        logger.info(f"{log_prefix} DOMOボタンをクリックしました。")

        # Verify success with an increased timeout
        logger.info(f"{log_prefix} DOMO成功の確認待機を開始... (最大15秒)")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "button.emoji-button.viewer-has-reacted[data-emoji-key='domo']"))
        )
        logger.info(f"{log_prefix} DOMO成功を確認。")
        return True

    except Exception as e:
        logger.warning(f"{log_prefix} DOMO処理中にエラーが発生しました: {type(e).__name__}")
        save_screenshot(driver, "DOMO_ActionFailed", activity_id_for_log)
        # Try to save HTML for debugging
        try:
            html_source = driver.page_source
            debug_html_dir = "logs/debug_html"
            os.makedirs(debug_html_dir, exist_ok=True)
            filename = f"DOMO_ActionFailed_{activity_id_for_log}_{time.strftime('%Y%m%d-%H%M%S')}.html"
            with open(os.path.join(debug_html_dir, filename), "w", encoding="utf-8") as f:
                f.write(html_source)
            logger.info(f"{log_prefix} デバッグ用のHTMLを保存しました: {filename}")
        except Exception as e_html:
            logger.error(f"{log_prefix} デバッグ用HTMLの保存に失敗: {e_html}")
        return False
