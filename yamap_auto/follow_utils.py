# coding: utf-8
"""
YAMAP フォロー関連ユーティリティ関数群
主にリストアイテム内やプロフィールページでのフォロー操作を担当
"""
import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from .driver_utils import get_main_config
# user_profile_utils と domo_utils からのインポートは、
# search_follow_and_domo_users 関数が移動したため不要になった
# from .user_profile_utils import (
#     get_latest_activity_url,
#     get_user_follow_counts,
#     find_follow_button_on_profile_page
# )
# from .domo_utils import domo_activity

# Selenium と time のインポートは最初のブロックでカバーされているので、
# 重複したものは削除 (実際には既に一箇所にまとまっているように見える)
# from selenium.webdriver.common.by import By
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
# from selenium.common.exceptions import TimeoutException, NoSuchElementException
# import time # time モジュールをインポート

logger = logging.getLogger(__name__)

# --- グローバル定数 ---
# BASE_URL は残された関数では直接使用されていないため削除
# SEARCH_ACTIVITIES_URL_DEFAULT は search_utils.py に移動

# --- 設定情報の読み込み ---
try:
    main_config = get_main_config()
    if not main_config:
        logger.error("follow_utils: main_config の読み込みに失敗しました。")
        main_config = {}

    # フォロー関連の設定セクションを読み込む
    # FOLLOW_BACK_SETTINGS は follow_back_utils.py に移動
    # SEARCH_AND_FOLLOW_SETTINGS は search_utils.py に移動
    # action_delays は main_config 直下にある想定 (汎用的に使われる可能性あり)
    ACTION_DELAYS = main_config.get("action_delays", {})


    # if not FOLLOW_BACK_SETTINGS: # follow_back_utils.py に移動
    #     logger.warning("follow_utils: config.yaml に follow_back_settings が見つからないか空です。")
    # if not SEARCH_AND_FOLLOW_SETTINGS: # search_utils.py に移動
    #     logger.warning("follow_utils: config.yaml に search_and_follow_settings が見つからないか空です。")

except Exception as e:
    logger.error(f"follow_utils: 設定情報 (main_config) の読み込み中にエラー: {e}", exc_info=True)
    main_config = {} # エラー発生時は空の辞書でフォールバック
    # FOLLOW_BACK_SETTINGS = {} # follow_back_utils.py に移動
    # SEARCH_AND_FOLLOW_SETTINGS = {} # search_utils.py に移動
    ACTION_DELAYS = {}


def find_follow_button_in_list_item(user_list_item_element):
    """
    ユーザーリストアイテム要素（例: フォロワー一覧の各ユーザー項目）内から
    「フォローする」ボタンを探します。
    既に「フォロー中」である場合や、クリック可能な「フォローする」ボタンがない場合はNoneを返します。

    Args:
        user_list_item_element (WebElement): 対象のユーザーリストアイテムのSelenium WebElement。

    Returns:
        WebElement or None: 「フォローする」ボタンのWebElement。見つからない場合はNone。
    """
    try:
        # 1. 「フォロー中」ボタンの確認 (aria-pressed='true' が主な指標)
        try:
            following_button = user_list_item_element.find_element(By.CSS_SELECTOR, "button[aria-pressed='true']")
            if following_button and following_button.is_displayed():
                button_text = following_button.text.strip()
                span_text = ""
                try:
                    span_elements = following_button.find_elements(By.CSS_SELECTOR, "span")
                    if span_elements:
                        span_text = " ".join(s.text.strip() for s in span_elements if s.text.strip())
                except: pass

                if "フォロー中" in button_text or "フォロー中" in span_text:
                    logger.debug("リストアイテム内で「フォロー中」ボタンを発見 (aria-pressed='true' + テキスト)。既にフォロー済みと判断。")
                    return None
                else:
                    logger.debug(f"aria-pressed='true' ボタン発見もテキスト不一致 (Button: '{button_text}', Span: '{span_text}')。フォロー済みと判断。")
                    return None
        except NoSuchElementException:
            logger.debug("リストアイテム内に aria-pressed='true' の「フォロー中」ボタンは見つかりませんでした。フォロー可能かもしれません。")
        except Exception as e_text_check:
             logger.debug(f"aria-pressed='true' ボタンのテキスト確認中にエラー: {e_text_check}。フォロー済みと仮定。")
             return None

        # 2. 「フォローする」ボタンの探索
        try:
            potential_follow_buttons = user_list_item_element.find_elements(By.CSS_SELECTOR, "button[aria-pressed='false']")
            if potential_follow_buttons:
                for button_candidate in potential_follow_buttons:
                    if button_candidate and button_candidate.is_displayed() and button_candidate.is_enabled():
                        button_text = button_candidate.text.strip()
                        span_text = ""
                        try:
                            span_elements = button_candidate.find_elements(By.CSS_SELECTOR, "span")
                            if span_elements:
                                span_text = " ".join(s.text.strip() for s in span_elements if s.text.strip())
                        except: pass

                        if "フォローする" in button_text or "フォローする" in span_text:
                            logger.debug("リストアイテム内で「フォローする」ボタンを発見 (aria-pressed='false' + テキスト)。")
                            return button_candidate
            else:
                logger.debug("リストアイテム内に aria-pressed='false' のボタン候補は見つかりませんでした。")
        except NoSuchElementException:
            logger.debug("リストアイテム内で aria-pressed='false' のボタン探索でエラー（通常発生しない）。")

        try:
            follow_button_xpath_str = ".//button[normalize-space(.)='フォローする']"
            button_by_text = user_list_item_element.find_element(By.XPATH, follow_button_xpath_str)
            if button_by_text and button_by_text.is_displayed() and button_by_text.is_enabled():
                logger.debug(f"リストアイテム内で「フォローする」ボタンをテキストで発見 (XPath: {follow_button_xpath_str})。")
                return button_by_text
        except NoSuchElementException:
            logger.debug(f"リストアイテム内でテキスト「フォローする」でのボタン発見試行失敗 (XPath)。")

        try:
            follow_button_aria_label = user_list_item_element.find_element(By.CSS_SELECTOR, "button[aria-label*='フォローする']")
            if follow_button_aria_label and follow_button_aria_label.is_displayed() and follow_button_aria_label.is_enabled():
                 logger.debug(f"リストアイテム内で「フォローする」ボタンをaria-labelで発見。")
                 return follow_button_aria_label
        except NoSuchElementException:
            logger.debug("リストアイテム内で aria-label*='フォローする' のボタンは見つかりませんでした。")

        logger.debug("ユーザーリストアイテム内にクリック可能な「フォローする」ボタンが見つかりませんでした。")
        return None
    except Exception as e:
        logger.error(f"ユーザーリストアイテム内のフォローボタン検索で予期せぬエラー: {e}", exc_info=True)
        return None

def click_follow_button_and_verify(driver, follow_button_element, user_name_for_log=""):
    """
    指定された「フォローする」ボタンをクリックし、ボタンの状態が「フォロー中」に変わったことを確認します。
    状態変化の確認は、ボタンの data-testid, aria-label, またはテキストの変更を監視します。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        follow_button_element (WebElement): クリック対象の「フォローする」ボタンのWebElement。
        user_name_for_log (str, optional): ログ出力用のユーザー名。

    Returns:
        bool: フォローに成功し、状態変化も確認できた場合はTrue。それ以外はFalse。
    """
    try:
        logger.info(f"ユーザー「{user_name_for_log}」のフォローボタンをクリックします...")

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", follow_button_element)
        time.sleep(0.1)
        follow_button_element.click()

        action_delays = main_config.get("action_delays", {}) # ACTION_DELAYS グローバル変数を使うように変更も検討
        delay_after_action = action_delays.get("after_follow_action_sec", 2.0)

        WebDriverWait(driver, 10).until(
            lambda d: (
                (follow_button_element.get_attribute("data-testid") == "FollowingButton") or
                ("フォロー中" in (follow_button_element.get_attribute("aria-label") or "")) or
                ("フォロー中" in follow_button_element.text) or
                (not follow_button_element.is_displayed()) # ボタンが消える場合も成功とみなす
            )
        )

        final_testid = follow_button_element.get_attribute("data-testid")
        final_aria_label = follow_button_element.get_attribute("aria-label")
        final_text = ""
        try:
            # 要素が非表示になった場合 text プロパティアクセスでエラーになるため try-except
            if follow_button_element.is_displayed():
                final_text = follow_button_element.text
        except: pass

        if final_testid == "FollowingButton" or \
           (final_aria_label and "フォロー中" in final_aria_label) or \
           (final_text and "フォロー中" in final_text) or \
           (not follow_button_element.is_displayed()): # 非表示も成功条件に含める
            logger.info(f"ユーザー「{user_name_for_log}」をフォローしました。状態: testid='{final_testid}', label='{final_aria_label}', text='{final_text}', displayed={follow_button_element.is_displayed() if final_testid != 'FollowingButton' else 'N/A (likely changed)'}")
            time.sleep(delay_after_action)
            return True
        else:
            logger.warning(f"フォローボタンクリック後、状態変化が期待通りではありません (ユーザー「{user_name_for_log}」)。状態: testid='{final_testid}', label='{final_aria_label}', text='{final_text}'")
            return False
    except TimeoutException:
        logger.warning(f"フォロー後の状態変化待機中にタイムアウト (ユーザー: {user_name_for_log})。")
        # フォロー自体は成功している可能性もあるが、確認できないためFalse
        return False
    except Exception as e: # StaleElementReferenceExceptionなどもキャッチ
        logger.error(f"フォローボタンクリックまたは確認中にエラー (ユーザー: {user_name_for_log})", exc_info=True)
        return False

# --- search_follow_and_domo_users 関数全体を search_utils.py に移動 ---

# --- follow_back_users_new 関数全体を follow_back_utils.py に移動 ---
