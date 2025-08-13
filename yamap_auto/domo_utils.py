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

def domo_activity(driver, activity_url, base_url_for_log=None):
    """
    指定された活動記録URLのページに直接アクセスし、DOMOを実行します。
    この関数は search_utils など、特定の活動にDOMOしたい場合に使用されます。
    """
    activity_id_for_log = activity_url.split('/')[-1] if activity_url else "N/A"
    log_prefix = f"[DOMO_PAGE][{activity_id_for_log}]"
    logger.info(f"{log_prefix} 活動記録ページ ({activity_url}) にDOMOを実行します。")

    if not activity_url:
        logger.error(f"{log_prefix} activity_urlが提供されませんでした。")
        return False

    current_url = driver.current_url
    if activity_url not in current_url:
        logger.info(f"{log_prefix} ページ ({activity_url}) へ遷移します。")
        driver.get(activity_url)
        try:
            # ページ読み込み待機：より堅牢なセレクタに変更
            # 1. 主要なコンテナが表示されるのを待つ
            # 2. その後、インタラクション対象のボタンが表示されるのを待つ
            WebDriverWait(driver, 25).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.ActivityDetailTabLayout, [data-testid='activity-detail-layout']"))
            )
            logger.info(f"{log_prefix} 主要コンテナの表示を確認。")

            # 絵文字ボタンが表示されるまで追加で待機
            # ユーザー提供HTML: <button ... aria-label="絵文字をおくる" class="... emoji-add-button ...">
            add_emoji_button_selector = "button[aria-label='絵文字をおくる']"
            WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, add_emoji_button_selector))
            )
            logger.info(f"{log_prefix} 絵文字追加ボタンのクリック準備完了。ページ読み込み完了と判断。")

        except TimeoutException:
            logger.error(f"{log_prefix} ページ読み込みまたは絵文字ボタン表示タイムアウト。")
            save_screenshot(driver, "DOMO_PageLoadOrButtonTimeout", activity_id_for_log)
            return False

    try:
        # 1. 既にリアクション済みか確認 (セレクタを更新)
        try:
            # リアクションするとボタンの data-testid が変わる可能性がある。より汎用的なセレクタで確認。
            driver.find_element(By.CSS_SELECTOR, "button[data-testid='viewer-reaction-button']")
            logger.info(f"{log_prefix} 既にリアクション済みのためスキップします。")
            return False
        except NoSuchElementException:
            pass # OK

        # 2. 絵文字追加ボタン(+)をクリック
        # ページ読み込み待機でセレクタは検証済みなので、ここでは確定で探しに行く
        add_emoji_button_selector = "button[aria-label='絵文字をおくる']"
        try:
            add_emoji_button = driver.find_element(By.CSS_SELECTOR, add_emoji_button_selector)
            # クリック前に画面内にスクロール
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", add_emoji_button)
            time.sleep(0.7) # スクロール後の安定待ち
            add_emoji_button.click()
        except NoSuchElementException:
             # このエラーは発生しづらいはずだが、念のため
            logger.error(f"{log_prefix} 絵文字追加ボタン({add_emoji_button_selector})が見つかりませんでした。")
            save_screenshot(driver, "DOMO_AddButtonNotFound_AfterWait", activity_id_for_log)
            return False
        logger.info(f"{log_prefix} 絵文字追加ボタン(+)をクリックしました。")

        # 3. DOMO絵文字をクリック
        # セレクタをより堅牢な data-emoji-key に変更
        domo_emoji_selector = "button[data-emoji-key='domo']"
        try:
            domo_emoji = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, domo_emoji_selector))
            )
            # ActionChainsを使用してクリックすることで、通常のclick()が失敗するケースに対応
            ActionChains(driver).move_to_element(domo_emoji).click().perform()
        except TimeoutException:
            logger.error(f"{log_prefix} DOMO絵文字ボタン ({domo_emoji_selector}) の待機タイムアウト。")
            save_screenshot(driver, "DOMO_EmojiButtonTimeout", activity_id_for_log)
            # リカバリのため、開いている可能性のあるピッカーを閉じる試み
            try:
                # bodyをクリックするか、閉じるボタンを探す
                driver.find_element(By.CSS_SELECTOR, "body").click()
            except Exception:
                pass
            return False
        logger.info(f"{log_prefix} DOMOボタンをクリックしました。")

        # 成功したかどうかの確認
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "button.emoji-button.viewer-has-reacted"))
            )
            logger.info(f"{log_prefix} DOMO成功を確認。")
            return True
        except TimeoutException:
            logger.warning(f"{log_prefix} DOMO後の確認に失敗。成功した可能性はあります。")
            return False # 確認できなかったのでFalse

    except (NoSuchElementException, TimeoutException) as e:
        logger.error(f"{log_prefix} DOMO処理中にエラーが発生しました: {type(e).__name__}")
        save_screenshot(driver, "DOMO_ActionFailed", activity_id_for_log)
        # HTMLも保存する
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
    except Exception as e:
        logger.error(f"{log_prefix} 予期せぬエラー: {e}", exc_info=True)
        save_screenshot(driver, "DOMO_UnexpectedError", activity_id_for_log)
        return False
