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
        # セレクタを変数化
        following_button_selector_css = "button[aria-pressed='true']"
        try:
            following_button = user_list_item_element.find_element(By.CSS_SELECTOR, following_button_selector_css)
            if following_button and following_button.is_displayed():
                button_text = ""
                try:
                    button_text = following_button.text.strip()
                except Exception: pass # テキスト取得失敗は許容
                span_text = ""
                try:
                    span_elements = following_button.find_elements(By.CSS_SELECTOR, "span")
                    if span_elements:
                        span_text = " ".join(s.text.strip() for s in span_elements if s.text.strip())
                except Exception: pass # spanテキスト取得失敗は許容

                if "フォロー中" in button_text or "フォロー中" in span_text:
                    logger.debug(f"リストアイテム内で「フォロー中」ボタンを発見 (セレクタ: '{following_button_selector_css}', テキスト: '{button_text}', SPAN: '{span_text}')。既にフォロー済みと判断。")
                    return None
                else:
                    logger.debug(f"aria-pressed='true' ボタン (セレクタ: '{following_button_selector_css}') 発見もテキスト不一致 (Button: '{button_text}', Span: '{span_text}')。フォロー済みと判断。")
                    return None
        except NoSuchElementException:
            logger.debug(f"リストアイテム内に「フォロー中」ボタン (セレクタ: '{following_button_selector_css}') は見つかりませんでした。フォロー可能かもしれません。")
        except Exception as e_text_check:
             logger.warning(f"aria-pressed='true' ボタン (セレクタ: '{following_button_selector_css}') のテキスト確認中にエラー: {e_text_check}。フォロー済みと仮定。")
             return None

        # 2. 「フォローする」ボタンの探索
        # セレクタを変数化
        follow_button_selector_css_false = "button[aria-pressed='false']"
        try:
            potential_follow_buttons = user_list_item_element.find_elements(By.CSS_SELECTOR, follow_button_selector_css_false)
            if potential_follow_buttons:
                for i, button_candidate in enumerate(potential_follow_buttons):
                    if button_candidate and button_candidate.is_displayed() and button_candidate.is_enabled():
                        button_text = ""
                        try:
                            button_text = button_candidate.text.strip()
                        except Exception: pass
                        span_text = ""
                        try:
                            span_elements = button_candidate.find_elements(By.CSS_SELECTOR, "span")
                            if span_elements:
                                span_text = " ".join(s.text.strip() for s in span_elements if s.text.strip())
                        except Exception: pass

                        logger.debug(f"  候補 {i+1}/{len(potential_follow_buttons)} (セレクタ: '{follow_button_selector_css_false}'): テキスト='{button_text}', SPAN='{span_text}', 表示={button_candidate.is_displayed()}, 有効={button_candidate.is_enabled()}")
                        if "フォローする" in button_text or "フォローする" in span_text:
                            logger.info(f"リストアイテム内で「フォローする」ボタンを発見 (セレクタ: '{follow_button_selector_css_false}', テキスト: '{button_text}', SPAN: '{span_text}')。")
                            return button_candidate
            else:
                logger.debug(f"リストアイテム内に「フォローする」ボタン候補 (セレクタ: '{follow_button_selector_css_false}') は見つかりませんでした。")
        except NoSuchElementException: # find_elements なので通常ここには来ない
            logger.debug(f"リストアイテム内で「フォローする」ボタン (セレクタ: '{follow_button_selector_css_false}') の探索でエラー（通常発生しない）。")

        # XPathでの探索
        follow_button_xpath_str = ".//button[normalize-space(.)='フォローする']"
        try:
            button_by_text = user_list_item_element.find_element(By.XPATH, follow_button_xpath_str)
            if button_by_text and button_by_text.is_displayed() and button_by_text.is_enabled():
                logger.info(f"リストアイテム内で「フォローする」ボタンをテキストで発見 (XPath: {follow_button_xpath_str})。")
                return button_by_text
        except NoSuchElementException:
            logger.debug(f"リストアイテム内でテキスト「フォローする」でのボタン発見試行失敗 (XPath: {follow_button_xpath_str})。")

        # aria-labelでの探索
        follow_button_aria_label_selector = "button[aria-label*='フォローする']"
        try:
            follow_button_aria_label = user_list_item_element.find_element(By.CSS_SELECTOR, follow_button_aria_label_selector)
            if follow_button_aria_label and follow_button_aria_label.is_displayed() and follow_button_aria_label.is_enabled():
                 logger.info(f"リストアイテム内で「フォローする」ボタンをaria-labelで発見 (セレクタ: '{follow_button_aria_label_selector}', aria-label='{follow_button_aria_label.get_attribute('aria-label')}')。")
                 return follow_button_aria_label
        except NoSuchElementException:
            logger.debug(f"リストアイテム内で aria-label を使用した「フォローする」ボタン (セレクタ: '{follow_button_aria_label_selector}') は見つかりませんでした。")

        logger.info("ユーザーリストアイテム内にクリック可能な「フォローする」ボタンが見つかりませんでした (全ての探索試行後)。")
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
        user_log_prefix = f"ユーザー「{user_name_for_log}」: " if user_name_for_log else ""
        initial_button_text = "N/A"
        initial_button_aria_label = "N/A"
        initial_button_testid = "N/A"
        try:
            initial_button_text = follow_button_element.text.strip()
            initial_button_aria_label = follow_button_element.get_attribute('aria-label') or "N/A"
            initial_button_testid = follow_button_element.get_attribute('data-testid') or "N/A"
        except Exception as e_pre_click_state:
            logger.debug(f"{user_log_prefix}クリック前のボタン状態取得中に軽微なエラー: {e_pre_click_state}")


        logger.info(f"{user_log_prefix}フォローボタンをクリックします... "
                    f"(現状態: Text='{initial_button_text}', "
                    f"AriaLabel='{initial_button_aria_label}', TestID='{initial_button_testid}')")

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", follow_button_element)
        time.sleep(0.1) # スクロール後の描画待ち
        follow_button_element.click()

        action_delays = main_config.get("action_delays", {})
        delay_after_action = action_delays.get("after_follow_action_sec", 2.0)
        wait_timeout = action_delays.get("follow_verify_timeout_sec", 10) # WebDriverWaitのタイムアウト

        # 状態変化確認のラムダ式を改善
        def check_button_state_changed(drv):
            # StaleElementReferenceExceptionを避けるため、要素を再取得する試みはここではしない
            # (呼び出し側で要素の有効性を保証するか、この関数が例外を投げるのを許容する)
            try:
                current_testid = follow_button_element.get_attribute("data-testid")
                current_aria_label = follow_button_element.get_attribute("aria-label") or ""
                current_text = follow_button_element.text.strip() if follow_button_element.is_displayed() else "" # 非表示ならテキストは空

                # ログ出力は状態変化が確認された後 or タイムアウト後に行うのでここでは詳細ログは出さない
                # logger.debug(f"{user_log_prefix}状態確認中: TestID='{current_testid}', AriaLabel='{current_aria_label}', Text='{current_text}', Displayed={follow_button_element.is_displayed()}")

                return (
                    (current_testid == "FollowingButton") or
                    ("フォロー中" in current_aria_label) or
                    ("フォロー中" in current_text) or
                    (not follow_button_element.is_displayed()) # ボタンが消える
                )
            except Exception as e_check: # StaleElementReferenceException など
                logger.debug(f"{user_log_prefix}状態確認中にボタン要素アクセスエラー: {e_check}。要素が無効になった可能性あり。")
                return True # 要素が無効になった＝変化した、とみなしてTrueを返す（成功と判断される）

        WebDriverWait(driver, wait_timeout).until(check_button_state_changed)

        # 最終状態の取得とログ出力
        final_testid = "N/A (アクセスエラー可能性)"
        final_aria_label = "N/A (アクセスエラー可能性)"
        final_text = "N/A (アクセスエラー可能性)"
        is_displayed_final = "N/A (アクセスエラー可能性)"
        try:
            final_testid = follow_button_element.get_attribute("data-testid") or "N/A"
            final_aria_label = follow_button_element.get_attribute("aria-label") or "N/A"
            if follow_button_element.is_displayed():
                is_displayed_final = True
                final_text = follow_button_element.text.strip()
            else:
                is_displayed_final = False
                final_text = "(非表示)"
        except Exception as e_final_state:
            logger.debug(f"{user_log_prefix}クリック後の最終状態取得中にボタン要素アクセスエラー: {e_final_state}。要素が無効になった可能性が高い。")
            # この場合、is_displayed_final が "N/A" のままになるので、成功判定は check_button_state_changed の結果に依存

        # 成功条件の再評価 (check_button_state_changed が True を返したはず)
        # ここでは主にログ出力のために状態を取得している
        if (final_testid == "FollowingButton" or
            ("フォロー中" in final_aria_label) or
            ("フォロー中" in final_text) or
            (is_displayed_final is False)): # is_displayed_final が bool False の場合
            logger.info(f"{user_log_prefix}フォロー成功を確認。最終状態: "
                        f"TestID='{final_testid}', AriaLabel='{final_aria_label}', "
                        f"Text='{final_text}', Displayed='{is_displayed_final}'")
            time.sleep(delay_after_action)
            return True
        else:
            # このブロックに来る場合、WebDriverWaitが成功したにも関わらず、
            # 上記の条件に一致しない稀なケース (check_button_state_changed のロジックと不整合の可能性)
            logger.warning(f"{user_log_prefix}フォロー後の状態変化確認でWebDriverWaitは成功しましたが、最終状態の検証で不一致。最終状態: "
                           f"TestID='{final_testid}', AriaLabel='{final_aria_label}', "
                           f"Text='{final_text}', Displayed='{is_displayed_final}'")
            return False # 本来ならTrueのはずだが、念のためFalse

    except TimeoutException:
        # タイムアウト時の状態をログに残す
        timeout_testid = "N/A"
        timeout_aria_label = "N/A"
        timeout_text = "N/A"
        is_displayed_timeout = "N/A"
        try:
            timeout_testid = follow_button_element.get_attribute("data-testid") or "N/A"
            timeout_aria_label = follow_button_element.get_attribute("aria-label") or "N/A"
            if follow_button_element.is_displayed():
                is_displayed_timeout = True
                timeout_text = follow_button_element.text.strip()
            else:
                is_displayed_timeout = False
                timeout_text = "(非表示)"
        except Exception as e_timeout_state:
            logger.debug(f"{user_log_prefix}タイムアウト後のボタン状態取得中にアクセスエラー: {e_timeout_state}")

        logger.warning(f"{user_log_prefix}フォロー後の状態変化待機中にタイムアウト ({wait_timeout}秒)。"
                       f"タイムアウト時のボタン状態: TestID='{timeout_testid}', AriaLabel='{timeout_aria_label}', "
                       f"Text='{timeout_text}', Displayed='{is_displayed_timeout}'")
        return False
    except Exception as e: # StaleElementReferenceExceptionなどもキャッチ
        logger.error(f"{user_log_prefix}フォローボタンクリックまたは確認中に予期せぬエラー", exc_info=True)
        return False

# --- search_follow_and_domo_users 関数全体を search_utils.py に移動 ---

# --- follow_back_users_new 関数全体を follow_back_utils.py に移動 ---

def find_following_button_on_profile_page(driver):
    """
    ユーザープロフィールページ上で「フォロー中」ボタンを探す。
    クリック可能な「フォロー中」ボタンがない場合はNoneを返します。
    この関数は、呼び出し元で対象ユーザーのプロフィールページに既に遷移していることを前提とします。
    user_profile_utils.find_follow_button_on_profile_page を参考に、こちらは「フォロー中」を探す。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。

    Returns:
        WebElement or None: 「フォロー中」ボタンのWebElement。見つからない場合はNone。
    """
    logger.info(f"プロフィールページ上の「フォロー中」ボタン探索開始。URL: {driver.current_url}")
    try:
        # 1. 「フォロー中」ボタンの確認 (aria-pressed='true' が主な指標)
        # YAMAPのUI構造に依存するため、複数のセレクタやコンテナ候補を試行。
        button_selectors = [
            "button[aria-pressed='true'][data-testid='FollowingButton']", # Test IDがある場合
            "button[aria-pressed='true']", # Test IDがない場合
            ".//button[normalize-space(.)='フォロー中']" # XPathでのテキスト検索
        ]
        button_container_candidates_css = "div.css-1fsc5gw, div.css-194f6e2" # ボタンを囲む可能性のあるコンテナ

        # コンテナ内での探索
        button_containers = driver.find_elements(By.CSS_SELECTOR, button_container_candidates_css)
        for container in button_containers:
            for selector in button_selectors:
                try:
                    if selector.startswith(".//"): # XPath
                        buttons = container.find_elements(By.XPATH, selector)
                    else: # CSS Selector
                        buttons = container.find_elements(By.CSS_SELECTOR, selector)

                    for btn in buttons:
                        if btn and btn.is_displayed() and btn.is_enabled():
                            # ボタンテキストまたは内部spanのテキストに「フォロー中」が含まれるか確認
                            btn_text = ""
                            try: btn_text = btn.text.strip()
                            except: pass
                            span_text = ""
                            try:
                                span_el = btn.find_element(By.CSS_SELECTOR, "span")
                                if span_el: span_text = span_el.text.strip()
                            except: pass

                            if "フォロー中" in btn_text or "フォロー中" in span_text:
                                logger.info(f"プロフィールページで「フォロー中」ボタン (コンテナ内, selector: {selector}) を発見。")
                                return btn
                except NoSuchElementException:
                    continue

        # グローバルな探索 (フォールバック)
        for selector in button_selectors:
            try:
                if selector.startswith(".//"): # XPath
                    buttons = driver.find_elements(By.XPATH, selector)
                else: # CSS Selector
                    buttons = driver.find_elements(By.CSS_SELECTOR, selector)

                for btn in buttons:
                    if btn and btn.is_displayed() and btn.is_enabled():
                        btn_text = ""
                        try: btn_text = btn.text.strip()
                        except: pass
                        span_text = ""
                        try:
                            span_el = btn.find_element(By.CSS_SELECTOR, "span")
                            if span_el: span_text = span_el.text.strip()
                        except: pass

                        if "フォロー中" in btn_text or "フォロー中" in span_text:
                            logger.info(f"プロフィールページで「フォロー中」ボタン (グローバル, selector: {selector}) を発見。")
                            return btn
            except NoSuchElementException:
                continue

        logger.info("プロフィールページでクリック可能な「フォロー中」ボタンが見つかりませんでした。")
        return None
    except Exception as e:
        logger.error(f"プロフィールページの「フォロー中」ボタン検索で予期せぬエラー: {e}", exc_info=True)
        return None


def unfollow_user(driver, user_profile_url):
    """
    指定されたユーザーのプロフィールページでアンフォロー操作を行います。
    「フォロー中」ボタンを探してクリックし、ボタンの表示が「フォローする」に変わったことを確認します。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        user_profile_url (str): アンフォロー対象ユーザーのプロフィールページの完全なURL。

    Returns:
        bool: アンフォローに成功し、状態変化も確認できた場合はTrue。それ以外はFalse。
    """
    user_id_log = user_profile_url.split('/')[-1].split('?')[0]
    logger.info(f"ユーザー ({user_id_log}, URL: {user_profile_url}) のアンフォロー処理を開始します。")

    # 1. 対象のユーザープロフィールページへ遷移
    current_page_url = driver.current_url
    if user_profile_url not in current_page_url:
        logger.debug(f"対象のユーザープロフィールページ ({user_profile_url}) に遷移します。")
        driver.get(user_profile_url)
        try:
            WebDriverWait(driver, 10).until(EC.url_contains(user_id_log))
        except TimeoutException:
            logger.warning(f"ユーザー ({user_id_log}) のプロフィールページへの遷移確認タイムアウト。アンフォロー失敗の可能性。")
            return False
    else:
        logger.debug(f"既にユーザープロフィールページ ({user_profile_url}) 付近にいます。")

    # 2. 「フォロー中」ボタンを探す
    #    user_profile_utils.find_follow_button_on_profile_page は「フォローする」ボタンを探すため、
    #    ここではアンフォロー対象の「フォロー中」ボタンを探すロジックが必要。
    #    find_following_button_on_profile_page を使う。
    following_button = find_following_button_on_profile_page(driver)

    if not following_button:
        logger.warning(f"ユーザー ({user_id_log}) のプロフィールページで「フォロー中」ボタンが見つかりませんでした。既にアンフォロー済みか、UIの変更の可能性があります。")
        # 「フォローする」ボタンが存在するか確認し、あればアンフォロー済みとみなす
        try:
            follow_button_check = driver.find_element(By.CSS_SELECTOR, "button[aria-pressed='false']")
            if follow_button_check and ("フォローする" in follow_button_check.text or "フォローする" in (follow_button_check.get_attribute("aria-label") or "")):
                 logger.info(f"ユーザー ({user_id_log}) は既にアンフォローされているようです（「フォローする」ボタン確認）。")
                 return True # アンフォロー済みなので成功とみなす
        except NoSuchElementException:
            pass # 「フォローする」ボタンも見つからない場合はそのまま
        return False

    try:
        user_log_prefix = f"ユーザー「{user_id_log}」: "
        initial_button_text = "N/A"
        try:
            initial_button_text = following_button.text.strip()
        except Exception: pass
        logger.info(f"{user_log_prefix}「フォロー中」ボタン (テキスト: '{initial_button_text}') をクリックしてアンフォローします...")

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", following_button)
        time.sleep(0.2) # スクロール後の描画待ち
        following_button.click()

        # アンフォロー後の遅延と確認タイムアウトをconfigから取得
        unfollow_settings = main_config.get("unfollow_inactive_users_settings", {})
        delay_after_action = unfollow_settings.get("delay_after_unfollow_action_sec", 3.0)
        wait_timeout = main_config.get("action_delays", {}).get("follow_verify_timeout_sec", 10) # フォロー確認のタイムアウトを流用

        # 状態変化確認：「フォローする」ボタンに変わる、または aria-pressed='false' になる
        def check_button_state_changed_to_follow(drv):
            try:
                # ボタン要素を再探索する必要があるかもしれない (StaleElement対策)
                # プロフィールページのフォローボタンは比較的安定していると仮定し、まずは同じ要素で試す
                current_aria_pressed = following_button.get_attribute("aria-pressed")
                current_text = ""
                if following_button.is_displayed(): # 表示されていればテキスト取得
                    current_text = following_button.text.strip()

                # logger.debug(f"{user_log_prefix}アンフォロー後の状態確認中: AriaPressed='{current_aria_pressed}', Text='{current_text}', Displayed={following_button.is_displayed()}")

                return (
                    (current_aria_pressed == 'false') or
                    ("フォローする" in current_text) or
                    (not following_button.is_displayed()) # ボタンが消える場合も変化とみなす（稀）
                )
            except Exception as e_check: # StaleElementReferenceException など
                logger.debug(f"{user_log_prefix}アンフォロー後の状態確認中にボタン要素アクセスエラー: {e_check}。要素が無効になった可能性あり。")
                # 要素が無効になった場合、新しい「フォローする」ボタンを探しに行く必要があるかもしれないが、
                # まずは変化したとみなしてTrueを返す (成功と判断される)
                # より堅牢にするには、ここで find_follow_button_on_profile_page を呼び出す
                return True

        WebDriverWait(driver, wait_timeout).until(check_button_state_changed_to_follow)

        # 最終状態の取得とログ出力 (主にログのため)
        final_aria_pressed = "N/A"
        final_text = "N/A"
        is_displayed_final = "N/A"
        try:
            final_aria_pressed = following_button.get_attribute("aria-pressed")
            if following_button.is_displayed():
                is_displayed_final = True
                final_text = following_button.text.strip()
            else:
                is_displayed_final = False
                final_text = "(非表示)"
        except Exception: # アクセスエラー時
             pass


        if (final_aria_pressed == 'false' or \
            ("フォローする" in final_text) or \
            (is_displayed_final is False) ):
            logger.info(f"{user_log_prefix}アンフォロー成功を確認。最終ボタン状態: AriaPressed='{final_aria_pressed}', Text='{final_text}', Displayed='{is_displayed_final}'")
            time.sleep(delay_after_action)
            return True
        else:
            logger.warning(f"{user_log_prefix}アンフォロー後の状態変化確認でWebDriverWaitは成功しましたが、最終状態の検証で不一致。AriaPressed='{final_aria_pressed}', Text='{final_text}'")
            return False # 念のためFalse

    except TimeoutException:
        logger.warning(f"{user_log_prefix}アンフォロー後の状態変化待機中にタイムアウト ({wait_timeout}秒)。")
        return False
    except Exception as e:
        logger.error(f"{user_log_prefix}アンフォロー処理中に予期せぬエラー: {e}", exc_info=True)
        return False
