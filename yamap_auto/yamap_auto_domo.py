# coding: utf-8
# ==============================================================================
# YAMAP 自動操作スクリプト (yamap_auto_domo.py)
#
# 概要:
#   このスクリプトは、Seleniumを使用してYAMAPウェブサイト上での一部の操作を自動化します。
#   主な機能として、ログイン、フォローバック、タイムラインへのDOMO、
#   活動記録検索結果からのユーザーフォローおよびDOMOなどが含まれます。
#   並列処理によるタイムラインDOMOもサポートしています（実験的）。
#
# 依存ファイル:
#   - yamap_auto/config.yaml: スクリプトの動作設定を記述する設定ファイル。
#   - yamap_auto/credentials.yaml: YAMAPへのログイン認証情報（メールアドレス、パスワード、ユーザーID）を記述するファイル。
#
# 注意事項:
#   - このスクリプトの使用は、YAMAPの利用規約に従って自己責任で行ってください。
#     自動化ツールの使用が規約に抵触する場合があり、アカウントに影響が出る可能性があります。
#   - セレクタはYAMAPのウェブサイト構造に依存しているため、サイトのアップデートにより動作しなくなることがあります。
#     定期的なメンテナンスやセレクタの更新が必要になる場合があります。
#   - 過度な連続アクセスはサーバーに負荷をかける可能性があるため、設定ファイル内の遅延時間を適切に設定してください。
# ==============================================================================

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys # 現状直接は使われていないが、将来的な拡張のために残す
import time
import json # 現状直接は使われていないが、将来的な拡張のために残す (Cookie保存/読込など)
import os
import re # 現状直接は使われていないが、将来的な拡張のために残す (URLやテキストのパターンマッチなど)
import logging
# import yaml # driver_utils に移動
from concurrent.futures import ThreadPoolExecutor, as_completed

# driver_utils から必要なものをインポート
from .driver_utils import (
    get_driver_options,
    login as util_login, # login関数名がローカルにも存在しうるため別名でインポート
    create_driver_with_cookies,
    get_main_config,
    get_credentials,
    # BASE_URL as UTIL_BASE_URL, # driver_utils側のBASE_URLは内部利用とし、こちらは維持
    # LOGIN_URL as UTIL_LOGIN_URL # 同上
)
# user_profile_utils から必要なものをインポート
from .user_profile_utils import (
    get_latest_activity_url,
    get_user_follow_counts,
    find_follow_button_on_profile_page
)


# --- Loggerの設定 ---
# スクリプトの動作状況やエラー情報をログとして記録するための設定。
# コンソールとファイルの両方に出力します。
# この設定は driver_utils を含む他のモジュールにも影響します。
LOG_FILE_NAME = "yamap_auto_domo.log" # ログファイル名
logger = logging.getLogger() # ルートロガーを取得または生成
if not logger.handlers: # ハンドラがまだ設定されていない場合のみ設定（多重設定防止）
    logger.setLevel(logging.DEBUG) # ロガー自体のレベルはDEBUGに設定 (ハンドラ側でフィルタリング)

    # StreamHandler (コンソールへのログ出力設定)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO) # コンソールにはINFOレベル以上のログを出力
    stream_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    stream_handler.setFormatter(stream_formatter)
    logger.addHandler(stream_handler)

    # FileHandler (ログファイルへの出力設定)
    try:
        file_handler = logging.FileHandler(LOG_FILE_NAME, encoding='utf-8', mode='a') # 'a'モードで追記
        file_handler.setLevel(logging.DEBUG) # ファイルにはDEBUGレベル以上のログを全て記録
        file_formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(funcName)s:%(lineno)d] - %(message)s", # 関数名と行番号も記録
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        # ここでのlogger.errorはまだハンドラが完全に設定されていない可能性があるのでprintも使う
        print(f"ログファイルハンドラ ({LOG_FILE_NAME}) の設定に失敗しました: {e}")
        logger.error(f"ログファイルハンドラの設定に失敗しました: {e}")
else:
    logger = logging.getLogger(__name__) # 既に設定済みの場合は、このモジュール用のロガーを取得
# --- Logger設定完了 ---


# --- 設定情報の読み込み (driver_utils経由) ---
try:
    main_config = get_main_config()
    credentials = get_credentials()
    YAMAP_EMAIL = credentials.get("email")
    YAMAP_PASSWORD = credentials.get("password")
    MY_USER_ID = credentials.get("user_id")

    if not all([YAMAP_EMAIL, YAMAP_PASSWORD, MY_USER_ID, main_config]):
        logger.critical("設定情報 (main_config または credentials) の取得に失敗しました。driver_utilsからの読み込みを確認してください。")
        exit()

    # 各機能ごとの設定セクションを読み込み (存在しない場合は空の辞書として扱う)
    DOMO_SETTINGS = main_config.get("domo_settings", {})
    FOLLOW_SETTINGS = main_config.get("follow_settings", {})
    FOLLOW_BACK_SETTINGS = main_config.get("follow_back_settings", {})
    TIMELINE_DOMO_SETTINGS = main_config.get("timeline_domo_settings", {})
    SEARCH_AND_FOLLOW_SETTINGS = main_config.get("search_and_follow_settings", {})
    PARALLEL_PROCESSING_SETTINGS = main_config.get("parallel_processing_settings", {})

    if not all([FOLLOW_BACK_SETTINGS, TIMELINE_DOMO_SETTINGS, SEARCH_AND_FOLLOW_SETTINGS, PARALLEL_PROCESSING_SETTINGS]):
        logger.warning(
            "config.yamlに新しい機能（follow_back_settings, timeline_domo_settings, search_and_follow_settings, parallel_processing_settings）の"
            "一部または全ての設定セクションが見つからないか空です。デフォルト値で動作しようとしますが、"
            "意図した動作をしない可能性があります。config.yamlを確認してください。"
        )

except Exception as e: # 設定読み込み中の予期せぬエラー
    logger.critical(f"設定情報の読み込み中に致命的なエラーが発生しました (driver_utils経由): {e}", exc_info=True)
    exit()
# --- 設定情報の読み込み完了 ---


# --- グローバル定数 ---
# YAMAPウェブサイトの基本的なURLなどを定義します。
# driver_utils 側にも BASE_URL はあるが、こちらはメインスクリプト側のグローバル定数として維持
BASE_URL = "https://yamap.com"
# LOGIN_URL は driver_utils 側で定義・使用されるため、ここでは不要 (または driver_utils からインポート)
# LOGIN_URL = f"{BASE_URL}/login" # 不要になった
TIMELINE_URL = f"{BASE_URL}/timeline"
SEARCH_ACTIVITIES_URL_DEFAULT = f"{BASE_URL}/search/activities"

# --- WebDriver関連の関数は driver_utils に移動したため、ここでは削除 ---
# def get_driver_options(): ...
# def login(driver, email, password): ...
# def create_driver_with_cookies(cookies, base_url_to_visit_first="https://yamap.com/"): ...


# --- DOMO関連補助関数 (yamap_auto.pyから移植・調整) ---
# (get_latest_activity_url, find_follow_button_on_profile_page, get_user_follow_counts はユーザープロフィール操作関連として後述)

# --- フォロー関連補助関数 (yamap_auto.pyから移植・調整) ---
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
        #    YAMAPのUIでは、フォロー中のボタンは aria-pressed="true" になっていることが多い。
        #    例: <button type="button" aria-pressed="true" ...><span>フォロー中</span></button>
        try:
            following_button = user_list_item_element.find_element(By.CSS_SELECTOR, "button[aria-pressed='true']")
            if following_button and following_button.is_displayed():
                # ボタンのテキストも確認して、より確実に「フォロー中」であることを判定
                button_text = following_button.text.strip()
                span_text = ""
                try: # ボタン内部のspan要素のテキストも確認 (構造のバリエーションに対応)
                    span_elements = following_button.find_elements(By.CSS_SELECTOR, "span")
                    if span_elements:
                        span_text = " ".join(s.text.strip() for s in span_elements if s.text.strip())
                except: pass

                if "フォロー中" in button_text or "フォロー中" in span_text:
                    logger.debug("リストアイテム内で「フォロー中」ボタンを発見 (aria-pressed='true' + テキスト)。既にフォロー済みと判断。")
                    return None # フォロー中なので、フォローするボタンではない
                else:
                    # aria-pressed='true' だがテキストが「フォロー中」でない場合。YAMAPのUI変更の可能性も考慮。
                    # 安全策として、aria-pressed='true' であればフォロー済みとみなす。
                    logger.debug(f"aria-pressed='true' ボタン発見もテキスト不一致 (Button: '{button_text}', Span: '{span_text}')。フォロー済みと判断。")
                    return None
        except NoSuchElementException:
            logger.debug("リストアイテム内に aria-pressed='true' の「フォロー中」ボタンは見つかりませんでした。フォロー可能かもしれません。")
        except Exception as e_text_check: # テキスト確認中の予期せぬエラー
             logger.debug(f"aria-pressed='true' ボタンのテキスト確認中にエラー: {e_text_check}。フォロー済みと仮定。")
             return None # エラー時も安全策としてフォロー済み扱い

        # 2. 「フォローする」ボタンの探索
        #   - data-testid='FollowButton' (もしあれば優先) -> 現在はコメントアウト
        #   - aria-pressed='false' かつテキストが「フォローする」
        #   - XPathでテキストが「フォローする」
        #   - aria-labelに「フォローする」が含まれる

        # 2a. aria-pressed="false" のボタンを探し、テキストが「フォローする」か確認
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
                            return button_candidate # 発見
            else:
                logger.debug("リストアイテム内に aria-pressed='false' のボタン候補は見つかりませんでした。")
        except NoSuchElementException: # find_elements なので実際にはここは通らないはずだが念のため
            logger.debug("リストアイテム内で aria-pressed='false' のボタン探索でエラー（通常発生しない）。")

        # 2b. XPathによるテキストでのフォールバック検索
        try:
            follow_button_xpath_str = ".//button[normalize-space(.)='フォローする']"
            button_by_text = user_list_item_element.find_element(By.XPATH, follow_button_xpath_str)
            if button_by_text and button_by_text.is_displayed() and button_by_text.is_enabled():
                logger.debug(f"リストアイテム内で「フォローする」ボタンをテキストで発見 (XPath: {follow_button_xpath_str})。")
                return button_by_text
        except NoSuchElementException:
            logger.debug(f"リストアイテム内でテキスト「フォローする」でのボタン発見試行失敗 (XPath)。")

        # 2c. aria-label によるフォールバック検索
        try:
            follow_button_aria_label = user_list_item_element.find_element(By.CSS_SELECTOR, "button[aria-label*='フォローする']")
            if follow_button_aria_label and follow_button_aria_label.is_displayed() and follow_button_aria_label.is_enabled():
                 logger.debug(f"リストアイテム内で「フォローする」ボタンをaria-labelで発見。")
                 return follow_button_aria_label
        except NoSuchElementException:
            logger.debug("リストアイテム内で aria-label*='フォローする' のボタンは見つかりませんでした。")

        logger.debug("ユーザーリストアイテム内にクリック可能な「フォローする」ボタンが見つかりませんでした。")
        return None # 全ての探索で見つからなかった場合
    except Exception as e: # この関数全体の予期せぬエラー
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

        # ボタンが画面内に表示されるようにスクロールし、クリック
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", follow_button_element)
        time.sleep(0.1) # スクロール後の短い描画安定待ち (0.3秒から短縮)
        # クリック前にボタンが有効であることを最終確認 (オプション)
        # WebDriverWait(driver, 2).until(EC.element_to_be_clickable(follow_button_element))
        follow_button_element.click()

        # --- 状態変化の確認 ---
        # フォロー操作後、ボタンの表示が「フォロー中」に変わることを期待。
        # WebDriverWait を使用して、一定時間内に状態が変わるまで待機します。
        # 確認する属性: data-testid, aria-label, text, または要素が非表示になるケースも考慮。
        action_delays = main_config.get("action_delays", {}) # configから遅延設定を読み込み
        delay_after_action = action_delays.get("after_follow_action_sec", 2.0) # フォロー後の待機時間

        # 状態変化の確認ロジック (ラムダ関数で複数の条件をチェック)
        WebDriverWait(driver, 10).until( # 最大10秒待機
            lambda d: ( # いずれかの条件がTrueになればOK
                (follow_button_element.get_attribute("data-testid") == "FollowingButton") or # data-testidが "FollowingButton" に変わる
                ("フォロー中" in (follow_button_element.get_attribute("aria-label") or "")) or # aria-labelに "フォロー中" が含まれる
                ("フォロー中" in follow_button_element.text) or # ボタンテキストに "フォロー中" が含まれる
                (not follow_button_element.is_displayed()) # ボタン自体が非表示になる場合も成功とみなす (UIパターンによる)
            )
        )

        # 確認後の最終的なボタンの状態をログに出力
        final_testid = follow_button_element.get_attribute("data-testid")
        final_aria_label = follow_button_element.get_attribute("aria-label")
        final_text = ""
        try: # 要素が非表示になっていると .text でエラーになるため try-except
            final_text = follow_button_element.text
        except: pass

        # 最終確認: 期待通りに状態が変わったか
        if final_testid == "FollowingButton" or \
           (final_aria_label and "フォロー中" in final_aria_label) or \
           (final_text and "フォロー中" in final_text) or \
           (not follow_button_element.is_displayed()):
            logger.info(f"ユーザー「{user_name_for_log}」をフォローしました。状態: testid='{final_testid}', label='{final_aria_label}', text='{final_text}', displayed={follow_button_element.is_displayed()}")
            time.sleep(delay_after_action) # 設定された待機時間
            return True
        else:
            logger.warning(f"フォローボタンクリック後、状態変化が期待通りではありません (ユーザー「{user_name_for_log}」)。状態: testid='{final_testid}', label='{final_aria_label}', text='{final_text}'")
            return False
    except TimeoutException: # WebDriverWaitがタイムアウトした場合
        logger.warning(f"フォロー後の状態変化待機中にタイムアウト (ユーザー: {user_name_for_log})。")
        # UIの反映が遅いだけで実際には成功している可能性もあるが、ここでは失敗として扱う。
        return False
    except Exception as e: # その他の予期せぬエラー
        logger.error(f"フォローボタンクリックまたは確認中にエラー (ユーザー: {user_name_for_log})", exc_info=True)
        return False

# --- DOMO関連補助関数 (yamap_auto.pyから移植・調整) ---
def domo_activity(driver, activity_url):
    """
    指定された活動日記URLのページを開き、DOMOボタンを探してクリックします。
    既にDOMO済みの場合は実行しません。

    Args:
        driver (webdriver.Chrome): Selenium WebDriverインスタンス。
        activity_url (str): DOMO対象の活動日記の完全なURL。

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
        #    YAMAPのUI変更に対応するため、複数のセレクタ候補を優先順位をつけて試行します。
        #    - プライマリ: data-testid属性 (例: "button[data-testid='ActivityDomoButton']")
        #    - フォールバック1: ID属性 (例: "button#DomoActionButton")
        #    - (将来的にはclass名やaria-labelも検討)
        primary_domo_button_selector = "button[data-testid='ActivityDomoButton']" # 推奨
        id_domo_button_selector = "button#DomoActionButton" # 旧スクリプトで使用

        domo_button = None
        current_selector_used = "" # 実際にDOMOボタンを見つけたセレクタを保持

        for idx, selector in enumerate([primary_domo_button_selector, id_domo_button_selector]):
            try:
                logger.debug(f"DOMOボタン探索試行 (セレクタ: {selector})")
                # ボタンが表示され、クリック可能になるまで待機 (プライマリは5秒、他は2秒)
                wait_time = 5 if idx == 0 else 2
                domo_button_candidate = WebDriverWait(driver, wait_time).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                if domo_button_candidate: # 見つかったらループを抜ける
                    domo_button = domo_button_candidate
                    current_selector_used = selector
                    logger.debug(f"DOMOボタンを発見 (セレクタ: '{selector}')")
                    break
            except TimeoutException:
                logger.debug(f"DOMOボタンがセレクタ '{selector}' で見つからず、またはタイムアウトしました。")
                continue # 次のセレクタ候補へ

        if not domo_button: # 全てのセレクタ候補で見つからなかった場合
            logger.warning(f"DOMOボタンが見つかりませんでした: {activity_id_for_log}")
            return False

        # 3. DOMO済みかどうかの判定
        #    ボタンのaria-labelや内部アイコンのクラス属性などで判断します。
        #    例: aria-label="Domo済み", アイコンに "is-active" クラス
        aria_label_before = domo_button.get_attribute("aria-label")
        is_domoed = False

        if aria_label_before and ("Domo済み" in aria_label_before or "domoed" in aria_label_before.lower() or "ドモ済み" in aria_label_before):
            is_domoed = True
            logger.info(f"既にDOMO済みです (aria-label='{aria_label_before}'): {activity_id_for_log}")
        else:
            # aria-labelで判定できなかった場合、アイコンの状態で再確認
            try:
                # DOMOボタン内のアイコン要素 (span) を探し、クラス属性を確認
                icon_span = domo_button.find_element(By.CSS_SELECTOR, "span[class*='DomoActionContainer__DomoIcon'], span.RidgeIcon")
                if "is-active" in icon_span.get_attribute("class"):
                    is_domoed = True
                    logger.info(f"既にDOMO済みです (アイコン is-active 確認): {activity_id_for_log}")
            except NoSuchElementException:
                logger.debug("DOMOボタン内のis-activeアイコンspanが見つかりませんでした。aria-labelに依存します。")

        # 4. DOMO実行 (まだDOMOしていなければ)
        if not is_domoed:
            logger.info(f"DOMOを実行します: {activity_id_for_log} (使用ボタンセレクタ: '{current_selector_used}')")
            # ボタンが画面内に表示されるようにスクロールし、クリック
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", domo_button)
            time.sleep(0.1) # スクロール後の短い描画安定待ち (0.3秒から短縮)
            domo_button.click()

            # DOMO後の状態変化を待つ (aria-labelが "Domo済み" になるか、アイコンがis-activeになる)
            action_delays = main_config.get("action_delays", {}) # configから遅延設定を読み込み
            delay_after_action = action_delays.get("after_domo_sec", 1.5) # DOMO後の待機時間

            try:
                # 状態変化確認 (最大5秒待機)
                WebDriverWait(driver, 5).until(
                    lambda d: ("Domo済み" in (d.find_element(By.CSS_SELECTOR, current_selector_used).get_attribute("aria-label") or "")) or \
                              ("is-active" in (d.find_element(By.CSS_SELECTOR, f"{current_selector_used} span[class*='DomoActionContainer__DomoIcon'], {current_selector_used} span.RidgeIcon").get_attribute("class") or ""))
                )
                aria_label_after = driver.find_element(By.CSS_SELECTOR, current_selector_used).get_attribute("aria-label")
                logger.info(f"DOMOしました: {activity_id_for_log} (aria-label: {aria_label_after})")
                time.sleep(delay_after_action) # 設定された待機時間
                return True
            except TimeoutException: # 状態変化の確認でタイムアウト
                logger.warning(f"DOMO実行後、状態変化の確認でタイムアウト: {activity_id_for_log}")
                # タイムアウトしても実際にはDOMO成功している可能性もあるが、ここでは失敗扱いとする。
                time.sleep(delay_after_action) # 一応待機
                return False
        else: # 既にDOMO済みの場合
            return False # DOMOアクションは実行していないのでFalse

    except TimeoutException: # ページ遷移や要素探索のタイムアウト
        logger.warning(f"DOMO処理中にタイムアウト ({activity_id_for_log})。ページ要素が見つからないか、読み込みが遅い可能性があります。")
    except NoSuchElementException: # DOMOボタンやその構成要素が見つからない
        logger.warning(f"DOMOボタンまたはその構成要素が見つかりません ({activity_id_for_log})。セレクタが古い可能性があります。")
    except Exception as e: # その他の予期せぬエラー
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
                if domo_activity(driver, activity_url):
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
        domo_success = domo_activity(task_driver, activity_url)
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


# --- 検索からのフォロー＆DOMO機能 ---
def search_follow_and_domo_users(driver, current_user_id):
    """
    活動記録検索ページを巡回し、条件に合うユーザーをフォローし、
    そのユーザーの最新活動記録にDOMOする。
    config.yaml の search_and_follow_settings に従って動作する。
    """
    if not SEARCH_AND_FOLLOW_SETTINGS.get("enable_search_and_follow", False):
        logger.info("検索からのフォロー＆DOMO機能は設定で無効になっています。")
        return

    logger.info(">>> 検索からのフォロー＆DOMO機能を開始します...")

    start_url = SEARCH_AND_FOLLOW_SETTINGS.get("search_activities_url", SEARCH_ACTIVITIES_URL_DEFAULT)
    max_pages = SEARCH_AND_FOLLOW_SETTINGS.get("max_pages_to_process_search", 1)
    max_users_per_page = SEARCH_AND_FOLLOW_SETTINGS.get("max_users_to_process_per_page", 5)
    min_followers = SEARCH_AND_FOLLOW_SETTINGS.get("min_followers_for_search_follow", 20)
    ratio_threshold = SEARCH_AND_FOLLOW_SETTINGS.get("follow_ratio_threshold_for_search", 0.9)
    domo_after_follow = SEARCH_AND_FOLLOW_SETTINGS.get("domo_latest_activity_after_follow", True)
    delay_user_processing = SEARCH_AND_FOLLOW_SETTINGS.get("delay_between_user_processing_in_search_sec", 5.0)
    delay_pagination = SEARCH_AND_FOLLOW_SETTINGS.get("delay_after_pagination_sec", 3.0)

    total_followed_count = 0
    total_domoed_count = 0
    # processed_users_on_current_page はページループ内で初期化する

    # 活動記録検索結果ページからユーザープロフィールへの典型的なパスを想定
    activity_card_selector = "article[data-testid='activity-entry']" # タイムラインと同様のカードを想定 (要確認)
    # ユーザー提供HTMLに基づく修正: <div class="css-1vh31zw"><a class="css-k2fvpp" href="/users/3122085">...</a></div>
    user_profile_link_in_card_selector = "div.css-1vh31zw > a.css-k2fvpp[href^='/users/']"

    processed_profile_urls = set() # セッション内で同じユーザーを何度も処理しないため

    for page_num in range(1, max_pages + 1):
        processed_users_on_current_page = 0 # 各ページの開始時にリセット
        current_page_url_before_action = driver.current_url # ページ遷移の確認用

        if page_num > 1: # 2ページ目以降はページネーションが必要
            logger.info(f"{page_num-1}ページ目の処理完了。次のページ ({page_num}ページ目) へ遷移を試みます。")

            next_button_selectors = [
                "a[data-testid='pagination-next-button']", # data-testid があれば最優先
                "a[rel='next']",
                "a.next", # 一般的なクラス名
                "a.pagination__next", # 一般的なクラス名
                "button.next",
                "button.pagination__next",
                "a[aria-label*='次へ']:not([aria-disabled='true'])", # 無効化されていない次へボタン
                "a[aria-label*='Next']:not([aria-disabled='true'])",
                "button[aria-label*='次へ']:not([disabled])",
                "button[aria-label*='Next']:not([disabled])",
                # XPath for text (fallback, use if CSS selectors fail)
                # "//a[contains(text(),'次へ') or contains(text(),'Next')]",
                # "//button[contains(text(),'次へ') or contains(text(),'Next')]"
            ]

            next_button_found = False
            for selector in next_button_selectors:
                try:
                    logger.debug(f"次のページボタン探索試行 (セレクタ: {selector})")
                    # 要素が存在し、かつクリック可能であることを確認
                    next_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    if next_button.is_displayed() and next_button.is_enabled():
                        logger.info(f"次のページボタンをセレクタ '{selector}' で発見。クリックします。")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
                        time.sleep(0.5) # スクロール安定待ち
                        next_button.click()
                        next_button_found = True
                        break
                    else:
                        logger.debug(f"セレクタ '{selector}' でボタンは存在したが、表示されていないか無効でした。")
                except TimeoutException:
                    logger.debug(f"セレクタ '{selector}' で次のページボタンが見つからずタイムアウト。")
                except Exception as e_click:
                    logger.warning(f"セレクタ '{selector}' でボタンクリック試行中にエラー: {e_click}")
                    # エラーが発生した場合も次のセレクタを試す

            if not next_button_found:
                logger.info("試行した全てのセレクタで、クリック可能な「次へ」ボタンが見つかりませんでした。検索結果のページネーション処理を終了します。")
                break # ページネーションループを終了

            # ページ遷移とコンテンツの読み込みを待つ
            try:
                # URLが変わり、かつ新しいページで活動記録カードが表示されるまで待つ
                # タイムアウトは合計で最大20秒程度を見込む (URL変化10秒 + カード表示10秒など)
                WebDriverWait(driver, 10).until(
                    EC.url_changes(current_page_url_before_action)
                )
                logger.info(f"{page_num}ページ目へ遷移しました。新しいURL: {driver.current_url}")

                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector))
                )
                logger.info(f"{page_num}ページ目の活動記録カードの読み込みを確認。")

                # 設定ファイルから読み込んだ遅延、またはデフォルト値で待機
                actual_delay_pagination = SEARCH_AND_FOLLOW_SETTINGS.get("delay_after_pagination_sec", 3.0)
                time.sleep(actual_delay_pagination)

            except TimeoutException:
                logger.warning(f"{page_num}ページ目への遷移後、URL変化または活動記録カードの読み込みタイムアウト。処理を終了します。")
                break # ページネーションループを終了
            except Exception as e_page_load:
                logger.error(f"{page_num}ページ目への遷移または読み込み中に予期せぬエラー: {e_page_load}", exc_info=True)
                break


        # --- 1ページ目の処理、またはページネーション後の処理 ---
        # current_url_to_load は1ページ目のみ使用し、それ以降はページネーションに任せる
        if page_num == 1 and driver.current_url != start_url :
             logger.info(f"{page_num}ページ目の活動記録検索結果 ({start_url}) にアクセスします。")
             driver.get(start_url) # current_url_to_load を start_url に修正

        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, activity_card_selector))
            )
            # time.sleep(0.5) # 描画安定待ち (WebDriverWaitで十分なはず)
        except TimeoutException:
            logger.warning(f"活動記録検索結果ページ ({current_url_to_load}) で活動記録カードの読み込みタイムアウト。このページの処理をスキップします。")
            continue

        initial_activity_cards_on_page = driver.find_elements(By.CSS_SELECTOR, activity_card_selector)
        num_cards_to_process = len(initial_activity_cards_on_page)
        logger.info(f"{page_num}ページ目: {num_cards_to_process} 件の活動記録候補を検出。")

        if not initial_activity_cards_on_page:
            logger.info("このページには活動記録が見つかりませんでした。")
            continue

        processed_users_on_current_page = 0
        # activity_cards_on_page はループ内で再取得するので、ここではインデックスの範囲だけを使用
        for card_idx in range(num_cards_to_process):
            if processed_users_on_current_page >= max_users_per_page:
                logger.info(f"このページでの処理上限 ({max_users_per_page}ユーザー) に達しました。")
                break

            user_profile_url = None
            user_name_for_log = f"活動記録{card_idx+1}のユーザー" # ログ用のインデックスは0始まりを1始まりに

            try:
                # ループの各反復でカード要素を再取得
                # 元の検索ページに戻った後、要素が確実に存在するようにWebDriverWaitを挟む
                # (既存のWebDriverWaitはページ全体のカード読み込みなので、ここでは個別のカード再取得)
                current_activity_cards = driver.find_elements(By.CSS_SELECTOR, activity_card_selector)
                if card_idx >= len(current_activity_cards):
                    logger.warning(f"カードインデックス {card_idx} が現在のカード数 {len(current_activity_cards)} を超えています。DOM構造が変更された可能性があります。このカードの処理をスキップします。")
                    continue
                card_element = current_activity_cards[card_idx]

                # カードからユーザープロフィールURLを取得
                # StaleElementReferenceException がここで発生していた
                profile_link_el = WebDriverWait(card_element, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, user_profile_link_in_card_selector))
                )
                # profile_link_el = card_element.find_element(By.CSS_SELECTOR, user_profile_link_in_card_selector) # 元のコード
                href = profile_link_el.get_attribute("href")
                if href:
                    if href.startswith("/"): user_profile_url = BASE_URL + href
                    elif href.startswith(BASE_URL): user_profile_url = href

                if not user_profile_url or f"/users/{current_user_id}" in user_profile_url: # 自分自身は除外
                    logger.debug(f"無効なプロフィールURLか自分自身 ({user_profile_url}) のためスキップ。")
                    continue

                if user_profile_url in processed_profile_urls:
                    logger.info(f"ユーザー ({user_profile_url.split('/')[-1]}) は既に処理済みのためスキップ。")
                    continue

                # ユーザー名の取得 (ログ用、取得できなくても処理は続行)
                try:
                    name_el = profile_link_el.find_element(By.CSS_SELECTOR, "span, img[alt]") # span内やimgのalt属性など
                    if name_el.tag_name == "img": user_name_for_log = name_el.get_attribute("alt")
                    else: user_name_for_log = name_el.text.strip()
                    if not user_name_for_log: user_name_for_log = user_profile_url.split('/')[-1]
                except: pass # ユーザー名取得失敗は許容

                logger.info(f"--- ユーザー「{user_name_for_log}」(URL: {user_profile_url.split('/')[-1]}) の処理開始 ---")
                processed_profile_urls.add(user_profile_url) # ここで処理対象としてマーク

                # 1. プロフィールページでフォローボタンがあるか確認 (なければ既にフォロー済みか対象外)
                #    get_user_follow_counts の中でページ遷移するので、その前にURLを保持
                search_page_url_before_profile_visit = driver.current_url

                follow_button = find_follow_button_on_profile_page(driver) # この中で user_profile_url へ遷移する想定だったが...
                                                                       # find_follow_button_on_profile_page は driver.get を内部で行わないので修正が必要
                                                                       # 先に遷移する
                driver.get(user_profile_url)
                try:
                    # ページ遷移と主要コンテンツの読み込みをより確実に待つ
                    WebDriverWait(driver, 20).until( # タイムアウトを20秒に設定
                        EC.all_of(
                            EC.url_contains(user_profile_url.split('/')[-1]),
                            EC.visibility_of_element_located((By.CSS_SELECTOR, "h1.css-jctfiw")), # ユーザー名
                            lambda d: d.execute_script("return document.readyState") == "complete",
                            EC.presence_of_element_located((By.CSS_SELECTOR, "footer.css-1yg0z07")) # フッター要素
                        )
                    )
                    logger.debug(f"ユーザープロフィールページ ({user_profile_url}) の主要コンテンツ読み込み完了を確認。")
                except TimeoutException:
                    logger.warning(f"ユーザープロフィールページ ({user_profile_url}) の読み込みタイムアウト（複合条件）。このユーザーの処理をスキップします。")
                    logger.debug(f"Timeout context: URL={driver.current_url}, Title={driver.title}")
                    # 元の検索ページに戻る処理をここにも入れる（エラーリカバリのため）
                    driver.get(search_page_url_before_profile_visit)
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    continue # 次のカードへ

                # find_follow_button_on_profile_page を呼び出す直前にURLを再確認 (念のため維持)
                if user_profile_url not in driver.current_url:
                    logger.error(f"URL不一致（待機後）: プロフィールページ ({user_profile_url}) にいるはずが、現在のURLは {driver.current_url} です。スキップします。")
                    # driver.get(search_page_url_before_profile_visit) # 必要に応じて戻る処理
                    # WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                    continue

                follow_button_on_profile = find_follow_button_on_profile_page(driver)

                if not follow_button_on_profile:
                    logger.info(f"ユーザー「{user_name_for_log}」は既にフォロー済みか、プロフィールにフォローボタンがありません。スキップ。")
                    driver.get(search_page_url_before_profile_visit) # 元の検索ページに戻る
                    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector))) # 安定待ちをWebDriverWaitに
                    continue

                # 2. フォロー数/フォロワー数を取得して条件判定
                follows, followers = get_user_follow_counts(driver, user_profile_url) # driverは既にプロフィールページにいる想定

                if follows == -1 or followers == -1:
                    logger.warning(f"ユーザー「{user_name_for_log}」のフォロー数/フォロワー数が取得できませんでした。スキップ。")
                    driver.get(search_page_url_before_profile_visit)
                    # time.sleep(1) # WebDriverWaitに任せる
                    continue

                if followers < min_followers:
                    logger.info(f"ユーザー「{user_name_for_log}」のフォロワー数 ({followers}) が閾値 ({min_followers}) 未満。スキップ。")
                    driver.get(search_page_url_before_profile_visit)
                    # time.sleep(1) # WebDriverWaitに任せる
                    continue

                current_ratio = (follows / followers) if followers > 0 else float('inf') # ゼロ除算回避
                logger.info(f"ユーザー「{user_name_for_log}」: F中={follows}, Fワー={followers}, Ratio={current_ratio:.2f} (閾値: >= {ratio_threshold})")

                # 条件: 比率が閾値以上
                if not (current_ratio >= ratio_threshold):
                    logger.info(f"Ratio ({current_ratio:.2f}) が閾値 ({ratio_threshold}) 未満です。スキップ。")
                    driver.get(search_page_url_before_profile_visit)
                    # time.sleep(1) # WebDriverWaitに任せる
                    continue

                # 3. 条件を満たせばフォロー実行
                logger.info(f"フォロー条件（Ratio >= {ratio_threshold}）を満たしました。ユーザー「{user_name_for_log}」をフォローします。")
                if click_follow_button_and_verify(driver, follow_button_on_profile, user_name_for_log):
                    total_followed_count += 1

                    # 4. フォロー後、DOMOが有効なら最新活動記録にDOMO
                    if domo_after_follow:
                        logger.info(f"ユーザー「{user_name_for_log}」の最新活動記録にDOMOを試みます。")
                        # get_latest_activity_url は内部で user_profile_url に遷移する
                        latest_act_url = get_latest_activity_url(driver, user_profile_url)
                        if latest_act_url:
                            if domo_activity(driver, latest_act_url): # domo_activity は内部で遷移
                                total_domoed_count += 1
                        else:
                            logger.info(f"ユーザー「{user_name_for_log}」の最新活動記録が見つからず、DOMOできませんでした。")

                processed_users_on_current_page += 1
                logger.info(f"--- ユーザー「{user_name_for_log}」の処理終了 ---")

                # 元の検索結果ページに戻る
                logger.debug(f"ユーザー処理後、検索結果ページ ({search_page_url_before_profile_visit}) に戻ります。")
                driver.get(search_page_url_before_profile_visit)
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector))
                    ) # 戻り確認とカード表示待ち
                except TimeoutException:
                    logger.warning(f"検索結果ページ ({search_page_url_before_profile_visit}) に戻った後、活動記録カードの再表示タイムアウト。")
                    # この場合でも、次のユーザー処理に進む前に設定された遅延は実行する
                time.sleep(delay_user_processing) # 次のユーザー処理までの意図的な待機

            except NoSuchElementException:
                logger.warning(f"活動記録カード {card_idx+1} からユーザー情報取得に必要な要素が見つかりません。スキップ。")
            except Exception as e_user_proc:
                logger.error(f"ユーザー「{user_name_for_log}」の処理中にエラー: {e_user_proc}", exc_info=True)
                # エラーが発生したら、元の検索ページに戻ることを試みる
                try:
                    current_search_url = start_url # page_numに応じて変更が必要だが、一旦start_url
                    if driver.current_url != current_search_url:
                         driver.get(current_search_url)
                         WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, activity_card_selector)))
                except Exception as e_recover:
                     logger.error(f"エラー後の検索ページ復帰試行中にもエラー: {e_recover}")


        logger.info(f"{page_num}ページ目の処理が完了しました。")
        if page_num < max_pages and len(activity_cards_on_page) > 0 : # 次のページがある場合のみ
             # ページネーション処理が実装されたら、ここで break しない
             pass
        # else:
        #      logger.info("最大ページ数に達したか、これ以上活動記録がありません。")
        #      break # ループ終了

    logger.info(f"<<< 検索からのフォロー＆DOMO機能完了。合計フォロー: {total_followed_count}人, 合計DOMO: {total_domoed_count}件。")


# --- フォローバック機能 ---
def follow_back_users_new(driver, current_user_id):
    """
    自分をフォローしてくれたユーザーをフォローバックする機能。
    config.yaml の follow_back_settings に従って動作する。
    ページネーションに対応し、複数のフォロワーページを確認する。
    """
    if not FOLLOW_BACK_SETTINGS.get("enable_follow_back", False):
        logger.info("フォローバック機能は設定で無効になっています。")
        return

    logger.info(">>> フォローバック機能を開始します...")
    # Initial followers page URL
    base_followers_url = f"{BASE_URL}/users/{current_user_id}?tab=followers" # #tabs removed for cleaner page tracking
    current_page_number = 1

    # Navigate to the initial followers page
    logger.info(f"フォロワー一覧の初期ページへアクセス: {base_followers_url}#tabs")
    driver.get(base_followers_url + "#tabs") # Initial load with #tabs

    max_to_follow_back_total = FOLLOW_BACK_SETTINGS.get("max_users_to_follow_back", 10)
    # New setting for max pages to check, defaults to a high number if not set, effectively "all pages"
    # For now, let's assume we'll add this to config later. For this implementation,
    # we'll rely on max_to_follow_back_total and the absence of a "Next" button.
    max_pages_to_check = FOLLOW_BACK_SETTINGS.get("max_pages_for_follow_back", 100) # Default to 100 pages if not in config

    delay_between_actions = FOLLOW_BACK_SETTINGS.get("delay_after_follow_back_action_sec", 3.0)
    delay_after_pagination = main_config.get("action_delays", {}).get("delay_after_pagination_sec", 3.0) # Use existing general pagination delay

    total_followed_this_session = 0
    processed_profile_urls_this_session = set() # Track users processed in this session to avoid re-processing on re-runs if script is restarted

    # --- セレクタ定義 ---
    followers_list_container_selector = "ul.css-18aka15"
    user_card_selector = "div[data-testid='user']"
    user_link_in_card_selector = "a.css-e5vv35[href^='/users/']"
    # name_element_css_selector_in_link = "h2.css-o7x4kv" # Not strictly needed for core logic here

    # Selectors for "Next" button, adapted from search_follow_and_domo_users
    next_button_selectors = [
        "a[data-testid='pagination-next-button']",
        "a[rel='next']",
        "a.next", "a.pagination__next", "button.next", "button.pagination__next",
        "a[aria-label*='次へ']:not([aria-disabled='true'])", "a[aria-label*='Next']:not([aria-disabled='true'])",
        "button[aria-label*='次へ']:not([disabled])", "button[aria-label*='Next']:not([disabled])"
    ]

    while current_page_number <= max_pages_to_check:
        logger.info(f"フォロワーリストの {current_page_number} ページ目を処理します。")

        try:
            logger.info(f"フォロワーリストのコンテナ ({followers_list_container_selector}) の出現を待ちます...")
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, followers_list_container_selector))
            )
            logger.info("フォロワーリストのコンテナを発見。")
            time.sleep(1.0) # Allow dynamic content to settle after container appears

            user_cards_all_on_page = driver.find_elements(By.CSS_SELECTOR, user_card_selector)
            logger.info(f"{current_page_number} ページ目から {len(user_cards_all_on_page)} 件のユーザーカード候補を検出しました。")

            # Recommendation skipping logic (applied per page)
            if current_page_number == 1 and len(user_cards_all_on_page) > 3: # Only skip on the very first page
                user_cards_to_process_this_page = user_cards_all_on_page[3:]
                logger.info(f"最初の3件（レコメンドと仮定）を除いた {len(user_cards_to_process_this_page)} 件のフォロワー候補を処理対象とします。")
            else:
                user_cards_to_process_this_page = user_cards_all_on_page

            if not user_cards_to_process_this_page:
                logger.info(f"{current_page_number} ページ目には処理対象となるフォロワーが見つかりませんでした。")
                # This might mean it's the end of followers, or an empty page after recommendations
                # Check for next button before breaking to be sure

            for card_idx, user_card_element in enumerate(user_cards_to_process_this_page):
                if total_followed_this_session >= max_to_follow_back_total:
                    logger.info(f"セッション中のフォローバック上限 ({max_to_follow_back_total}人) に達しました。")
                    break # Break from user card loop

                user_name = f"ユーザー{card_idx+1} (Page {current_page_number})"
                profile_url = ""

                try:
                    user_link_element = user_card_element.find_element(By.CSS_SELECTOR, user_link_in_card_selector)
                    profile_url = user_link_element.get_attribute("href")

                    name_el_candidates = user_link_element.find_elements(By.CSS_SELECTOR, "h2, span[class*='UserListItem_name__']")
                    for name_el in name_el_candidates:
                        if name_el.text.strip():
                            user_name = name_el.text.strip()
                            break

                    if not profile_url:
                        logger.warning(f"カード {card_idx+1} (Page {current_page_number}) からプロフィールURL取得失敗。スキップ。")
                        continue
                    if profile_url.startswith("/"): profile_url = BASE_URL + profile_url
                    if f"/users/{current_user_id}" in profile_url or not profile_url.startswith(f"{BASE_URL}/users/"):
                        logger.debug(f"スキップ: 自分自身または無効なURL ({profile_url})")
                        continue

                    if profile_url in processed_profile_urls_this_session:
                        logger.info(f"ユーザー「{user_name}」({profile_url.split('/')[-1]}) はこのセッションで既に処理済み。スキップ。")
                        continue

                except NoSuchElementException:
                    logger.warning(f"カード {card_idx+1} (Page {current_page_number}) の必須要素が見つかりません。スキップ。")
                    continue
                except Exception as e_card_parse:
                    logger.warning(f"カード {card_idx+1} (Page {current_page_number}) 解析エラー: {e_card_parse}。スキップ。")
                    continue

                processed_profile_urls_this_session.add(profile_url) # Mark as processed for this session
                logger.info(f"フォロワー「{user_name}」(URL: {profile_url.split('/')[-1]}) のフォロー状態を確認中...")
                follow_button = find_follow_button_in_list_item(user_card_element)

                if follow_button:
                    logger.info(f"ユーザー「{user_name}」はまだフォローしていません。フォローバックを試みます。")
                    if click_follow_button_and_verify(driver, follow_button, user_name):
                        total_followed_this_session += 1
                    time.sleep(delay_between_actions)
                else:
                    logger.info(f"ユーザー「{user_name}」は既にフォロー済みか、フォローボタンなし。スキップ。")
                    time.sleep(0.5)

            if total_followed_this_session >= max_to_follow_back_total:
                logger.info("セッション中のフォローバック上限に達したため、ページネーションを停止します。")
                break # Break from page loop

            # --- Attempt to navigate to the next page ---
            next_button_found_on_page = False
            current_url_before_pagination = driver.current_url
            logger.info("現在のページのフォロワー処理完了。「次へ」ボタンを探します...")

            for selector_idx, selector in enumerate(next_button_selectors):
                try:
                    # Use a shorter wait for the next button itself
                    next_button = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    if next_button.is_displayed() and next_button.is_enabled():
                        logger.info(f"「次へ」ボタンをセレクタ '{selector}' で発見。クリックします。")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
                        time.sleep(0.5)
                        next_button.click()
                        next_button_found_on_page = True
                        break
                except TimeoutException:
                    logger.debug(f"セレクタ '{selector}' で「次へ」ボタン見つからずタイムアウト ({selector_idx+1}/{len(next_button_selectors)}).")
                except Exception as e_click_next:
                    logger.warning(f"セレクタ '{selector}' で「次へ」ボタンクリック試行中にエラー: {e_click_next}")

            if not next_button_found_on_page:
                logger.info("クリック可能な「次へ」ボタンが見つかりませんでした。フォロワーリストの最終ページと判断します。")
                break # Break from page loop

            # Wait for page content to update (URL change or new content)
            try:
                WebDriverWait(driver, 15).until(
                    EC.url_changes(current_url_before_pagination)
                )
                logger.info(f"次のフォロワーページ ({driver.current_url}) へ遷移成功。")
                # 新しいページでフォロワーリストコンテナが表示されるまで待つ
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, followers_list_container_selector))
                )
                # 設定された遅延時間で待機
                actual_delay_pagination_fb = main_config.get("action_delays", {}).get("delay_after_pagination_sec", 3.0)
                time.sleep(actual_delay_pagination_fb)
            except TimeoutException:
                logger.warning("「次へ」クリック後、ページ遷移またはフォロワーリストの再表示タイムアウト。ページネーションを停止します。")
                break # Break from page loop

            current_page_number += 1

        except TimeoutException:
            logger.warning(f"{current_page_number} ページ目のフォロワー一覧読み込みでタイムアウト。")
            break # Break from page loop if main container doesn't load
        except Exception as e_page_process:
            logger.error(f"{current_page_number} ページ目の処理中に予期せぬエラー: {e_page_process}", exc_info=True)
            break # Break from page loop on unexpected error

    logger.info(f"<<< フォローバック機能完了。合計 {total_followed_this_session} 人をフォローバックしました。")


# --- mainブロック (テスト用) ---
if __name__ == "__main__":
    logger.info(f"=========== {os.path.basename(__file__)} スクリプト開始 ===========")
    driver = None
    try:
        # driver_utilsからWebDriverオプションを取得
        driver_options = get_driver_options() # これは driver_utils.get_driver_options() を指す
        driver = webdriver.Chrome(options=driver_options)

        # implicit_wait_sec は main_config (driver_utils経由で取得済み) から読む
        implicit_wait = main_config.get("implicit_wait_sec", 7)
        driver.implicitly_wait(implicit_wait)

        logger.info(f"認証情報: email={YAMAP_EMAIL}, user_id={MY_USER_ID}") # パスワードはログ出力しない

        # driver_utils の login (util_loginとしてインポート) を使用
        if util_login(driver, YAMAP_EMAIL, YAMAP_PASSWORD, MY_USER_ID): # MY_USER_ID を引数に追加
            logger.info(f"ログイン成功。現在のURL: {driver.current_url}")
            shared_cookies = None
            if PARALLEL_PROCESSING_SETTINGS.get("enable_parallel_processing", False) and \
               PARALLEL_PROCESSING_SETTINGS.get("use_cookie_sharing", True):
                try:
                    shared_cookies = driver.get_cookies()
                    logger.info(f"ログイン後のCookieを {len(shared_cookies)} 個取得しました。並列処理で利用します。")
                except Exception as e_cookie_get:
                    logger.error(f"ログイン後のCookie取得に失敗しました: {e_cookie_get}", exc_info=True)
                    shared_cookies = None

            # --- 各機能の呼び出し ---
            if MY_USER_ID: # MY_USER_ID は driver_utils 経由で取得済み
                # フォローバック機能
                if FOLLOW_BACK_SETTINGS.get("enable_follow_back", False):
                    start_time = time.time()
                    # TODO: フォローバック機能の並列化対応 (domo_timeline_activities_parallel と同様の構造で)
                    logger.info("現時点ではフォローバック機能は並列化未対応のため、逐次実行します。")
                    follow_back_users_new(driver, MY_USER_ID)
                    end_time = time.time()
                    logger.info(f"フォローバック機能の処理時間: {end_time - start_time:.2f}秒")
                else:
                    logger.info("フォローバック機能は設定で無効です。")

                # タイムラインDOMO機能
                if TIMELINE_DOMO_SETTINGS.get("enable_timeline_domo", False):
                    start_time = time.time()
                    if PARALLEL_PROCESSING_SETTINGS.get("enable_parallel_processing", False) and shared_cookies:
                        domo_timeline_activities_parallel(driver, shared_cookies) # メインドライバーとCookieを渡す
                    else:
                        if PARALLEL_PROCESSING_SETTINGS.get("enable_parallel_processing", False) and not shared_cookies:
                            logger.warning("並列処理が有効ですがCookie共有ができなかったため、タイムラインDOMOは逐次実行されます。")
                        domo_timeline_activities(driver) # 従来の逐次実行
                    end_time = time.time()
                    logger.info(f"タイムラインDOMO機能の処理時間: {end_time - start_time:.2f}秒")
                else:
                    logger.info("タイムラインDOMO機能は設定で無効です。")

                # 検索結果からのフォロー＆DOMO機能
                if SEARCH_AND_FOLLOW_SETTINGS.get("enable_search_and_follow", False):
                    start_time = time.time()
                    # TODO: 検索からのフォロー＆DOMO機能の並列化対応
                    logger.info("現時点では検索からのフォロー＆DOMO機能は並列化未対応のため、逐次実行します。")
                    search_follow_and_domo_users(driver, MY_USER_ID)
                    end_time = time.time()
                    logger.info(f"検索結果からのフォロー＆DOMO機能の処理時間: {end_time - start_time:.2f}秒")
                else:
                    logger.info("検索結果からのフォロー＆DOMO機能は設定で無効です。")

            else:
                logger.error("MY_USER_IDが不明なため、ユーザーIDが必要な機能は実行できません。")

            logger.info("全ての有効な処理が完了しました。")
            time.sleep(3) # 処理完了後の状態を少し確認できるように
        else:
            logger.critical("ログインに失敗したため、処理を中止します。")

    except Exception as main_e:
        logger.critical("スクリプト実行中に予期せぬ致命的なエラーが発生しました。", exc_info=True)
    finally:
        if driver:
            logger.info("ブラウザを閉じるまで5秒待機します...")
            time.sleep(5)
            driver.quit()
            logger.info("ブラウザを終了しました。")
        logger.info(f"=========== {os.path.basename(__file__)} スクリプト終了 ===========")
