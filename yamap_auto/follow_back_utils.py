# coding: utf-8
"""
YAMAP フォローバック関連ユーティリティ関数群
自分をフォローしてくれたユーザーへのフォローバック操作を担当
"""
import time
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# .driver_utils から main_config の読み込み関数をインポート
from .driver_utils import get_main_config
# .follow_utils からフォローボタン検索・クリック関数をインポート
from .follow_utils import find_follow_button_in_list_item, click_follow_button_and_verify

logger = logging.getLogger(__name__)

# --- グローバル定数 ---
BASE_URL = "https://yamap.com" # このファイルでも直接URLを組み立てるために必要

# --- 設定情報の読み込み ---
try:
    main_config = get_main_config()
    if not main_config:
        logger.error("follow_back_utils: main_config の読み込みに失敗しました。")
        main_config = {} # フォールバック

    # FOLLOW_BACK_SETTINGS と ACTION_DELAYS を main_config から取得
    FOLLOW_BACK_SETTINGS = main_config.get("follow_back_settings", {})
    ACTION_DELAYS = main_config.get("action_delays", {}) # ページネーション遅延などで使用

    if not FOLLOW_BACK_SETTINGS:
        logger.warning("follow_back_utils: config.yaml に follow_back_settings が見つからないか空です。")
    # ACTION_DELAYS は必須ではないかもしれないので warning は出さない

except Exception as e:
    logger.error(f"follow_back_utils: 設定情報 (main_config) の読み込み中にエラー: {e}", exc_info=True)
    FOLLOW_BACK_SETTINGS = {} # フォールバック
    ACTION_DELAYS = {}       # フォールバック


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
    base_followers_url = f"{BASE_URL}/users/{current_user_id}?tab=followers"
    current_page_number = 1

    logger.info(f"フォロワー一覧の初期ページへアクセス: {base_followers_url}#tabs")
    driver.get(base_followers_url + "#tabs")

    max_to_follow_back_total = FOLLOW_BACK_SETTINGS.get("max_users_to_follow_back", 10)
    max_pages_to_check = FOLLOW_BACK_SETTINGS.get("max_pages_for_follow_back", 100) # 以前の max_pages_to_process_follow_back から変更された可能性
    delay_between_actions = FOLLOW_BACK_SETTINGS.get("delay_after_follow_back_action_sec", 3.0)
    delay_after_pagination_fb = ACTION_DELAYS.get("delay_after_pagination_sec", 3.0)


    total_followed_this_session = 0
    processed_profile_urls_this_session = set()

    followers_list_container_selector = "ul.css-18aka15" # フォロワー一覧のUL要素
    user_card_selector = "div[data-testid='user']" # 各ユーザーカードのコンテナ
    user_link_in_card_selector = "a.css-e5vv35[href^='/users/']" # カード内のユーザープロフへのリンク
    next_button_selectors = [ # 次のページボタンの可能性のあるセレクタリスト
        "a[data-testid='pagination-next-button']", "a[rel='next']", "a.next",
        "a.pagination__next", "button.next", "button.pagination__next",
        "a[aria-label*='次へ']:not([aria-disabled='true'])", "a[aria-label*='Next']:not([aria-disabled='true'])",
        "button[aria-label*='次へ']:not([disabled])", "button[aria-label*='Next']:not([disabled])"
    ]

    while current_page_number <= max_pages_to_check:
        logger.info(f"フォロワーリストの {current_page_number} ページ目を処理します。")
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, followers_list_container_selector))
            )
            logger.info("フォロワーリストのコンテナを発見。")
            time.sleep(1.0) # リスト内容の描画待ち

            user_cards_all_on_page = driver.find_elements(By.CSS_SELECTOR, user_card_selector)
            logger.info(f"{current_page_number} ページ目から {len(user_cards_all_on_page)} 件のユーザーカード候補を検出しました。")

            user_cards_to_process_this_page = user_cards_all_on_page
            # YAMAPのフォロワー一覧ページでは、最初の数件が「おすすめユーザー」の場合があるため除外するロジック
            # この除外数は設定可能にしてもよいが、ここでは固定値3で仮実装
            # (このロジックは、実際のYAMAPのUIに応じて調整が必要)
            if FOLLOW_BACK_SETTINGS.get("skip_recommended_users_on_first_page", True) and current_page_number == 1 and len(user_cards_all_on_page) > 3 : # 設定でON/OFFできるようにしても良い
                skip_count = FOLLOW_BACK_SETTINGS.get("recommended_users_to_skip_count", 3)
                if len(user_cards_all_on_page) > skip_count:
                    user_cards_to_process_this_page = user_cards_all_on_page[skip_count:]
                    logger.info(f"最初の{skip_count}件（レコメンドと仮定）を除いた {len(user_cards_to_process_this_page)} 件のフォロワー候補を処理対象とします。")
                else:
                    logger.info(f"レコメンド除外設定ですが、ユーザーカードが{len(user_cards_all_on_page)}件のため、全件処理します。")


            if not user_cards_to_process_this_page:
                logger.info(f"{current_page_number} ページ目には処理対象となるフォロワーが見つかりませんでした。")
                # 「次へ」ボタンがない場合はここでループを抜けるべき
                # (次の「次へ」ボタン探索ロジックで対応される)

            for card_idx, user_card_element in enumerate(user_cards_to_process_this_page):
                if total_followed_this_session >= max_to_follow_back_total:
                    logger.info(f"セッション中のフォローバック上限 ({max_to_follow_back_total}人) に達しました。")
                    break # このページのユーザー処理ループを抜ける

                user_name = f"ユーザー{card_idx+1} (Page {current_page_number})" # デフォルト名
                profile_url = ""
                try:
                    # ユーザーカードからプロフィールURLと名前を取得
                    user_link_element = user_card_element.find_element(By.CSS_SELECTOR, user_link_in_card_selector)
                    profile_url = user_link_element.get_attribute("href")

                    # 名前取得の試み (複数の可能性を考慮)
                    name_el_candidates = user_link_element.find_elements(By.CSS_SELECTOR, "h2, span[class*='UserListItem_name__'], span.name") # 一般的な名前要素候補
                    for name_el_candidate in name_el_candidates:
                        if name_el_candidate.text.strip():
                            user_name = name_el_candidate.text.strip()
                            break

                    if not profile_url:
                        logger.warning(f"フォロワーカード {card_idx+1} からプロフィールURLが取得できませんでした。スキップ。")
                        continue
                    if profile_url.startswith("/"): profile_url = BASE_URL + profile_url # 相対URLを絶対URLに

                    # 自分自身や無効なURLはスキップ
                    if f"/users/{current_user_id}" in profile_url or not profile_url.startswith(f"{BASE_URL}/users/"):
                        logger.debug(f"スキップ対象: 自分自身または無効なプロフィールURL ({profile_url})")
                        continue

                    # このセッションで既に処理（試行）したURLならスキップ
                    if profile_url in processed_profile_urls_this_session:
                        logger.info(f"ユーザー「{user_name}」({profile_url.split('/')[-1]}) はこのセッションで既に処理済みのためスキップ。")
                        continue

                except NoSuchElementException:
                    logger.warning(f"フォロワーカード {card_idx+1} の必須要素 (リンク等) が見つかりません。スキップ。")
                    continue
                except Exception as e_card_parse:
                    logger.warning(f"フォロワーカード {card_idx+1} の解析中に予期せぬエラー: {e_card_parse}。スキップ。")
                    continue

                processed_profile_urls_this_session.add(profile_url) # これから処理するのでセットに追加
                logger.info(f"フォロワー「{user_name}」(URL: {profile_url.split('/')[-1]}) のフォロー状態を確認します...")

                # フォローボタンを探す (follow_utilsからインポートした関数を使用)
                follow_button = find_follow_button_in_list_item(user_card_element)

                if follow_button:
                    logger.info(f"ユーザー「{user_name}」はまだフォローしていません。フォローバックを実行します。")
                    if click_follow_button_and_verify(driver, follow_button, user_name): # follow_utilsからインポート
                        total_followed_this_session += 1
                    time.sleep(delay_between_actions) # アクション後の遅延
                else:
                    logger.info(f"ユーザー「{user_name}」は既にフォロー済みであるか、フォローボタンが見つかりませんでした。スキップ。")
                    time.sleep(0.5) # 短い遅延

            # --- ページ内の全ユーザー処理後 ---
            if total_followed_this_session >= max_to_follow_back_total:
                logger.info("セッション中のフォローバック上限に達したため、ページネーションを停止します。")
                break # ページネーションループ (while) を抜ける

            # 「次へ」ボタンの探索とクリック
            next_button_found_on_page = False
            current_url_before_pagination = driver.current_url # URL変化の確認用
            logger.info("現在のページのフォロワー処理完了。「次へ」ボタンを探します...")

            for selector_idx, selector in enumerate(next_button_selectors):
                try:
                    # WebDriverWaitで要素がクリック可能になるまで待つ
                    next_button = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    if next_button.is_displayed() and next_button.is_enabled(): # 表示されていて有効か
                        logger.info(f"「次へ」ボタンをセレクタ '{selector}' で発見。クリックします。")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button) # ボタンを画面中央に表示
                        time.sleep(0.5) # スクロール後の短い待機
                        next_button.click()
                        next_button_found_on_page = True
                        break # ボタンを見つけてクリックしたらループを抜ける
                except TimeoutException:
                    logger.debug(f"セレクタ '{selector}' で「次へ」ボタンが見つからずタイムアウト ({selector_idx+1}/{len(next_button_selectors)}).")
                except Exception as e_click_next:
                    logger.warning(f"セレクタ '{selector}' で「次へ」ボタンのクリック試行中にエラー: {e_click_next}")

            if not next_button_found_on_page:
                logger.info("「次へ」ボタンが見つかりませんでした。これが最終ページと判断し、フォローバック処理を終了します。")
                break # ページネーションループ (while) を抜ける

            # ページ遷移とコンテンツ読み込みの確認
            try:
                WebDriverWait(driver, 15).until(EC.url_changes(current_url_before_pagination))
                logger.info(f"次のフォロワーページ ({driver.current_url}) へ正常に遷移しました。")
                # 新しいページのリストコンテナが表示されるまで待機
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, followers_list_container_selector))
                )
                time.sleep(delay_after_pagination_fb) # ページ読み込み後の遅延
            except TimeoutException:
                logger.warning("「次へ」ボタンクリック後、ページ遷移またはリスト再表示のタイムアウト。処理を停止します。")
                break # ページネーションループ (while) を抜ける

            current_page_number += 1 # 次のページ番号へ

        except TimeoutException:
            logger.warning(f"{current_page_number} ページ目のフォロワーリストコンテナの読み込みタイムアウト。処理を終了します。")
            break # ページネーションループ (while) を抜ける
        except Exception as e_page_process:
            logger.error(f"{current_page_number} ページ目の処理中に予期せぬエラーが発生しました: {e_page_process}", exc_info=True)
            break # ページネーションループ (while) を抜ける

    logger.info(f"<<< フォローバック機能完了。このセッションで合計 {total_followed_this_session} 人をフォローバックしました。")
