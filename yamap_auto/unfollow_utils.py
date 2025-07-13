# coding: utf-8
import time
import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .driver_utils import create_driver_with_cookies
from .user_profile_utils import get_last_activity_date, get_my_following_users_profiles
from .follow_utils import unfollow_user

logger = logging.getLogger(__name__)


def _fetch_user_last_activity_task(user_profile_url, shared_cookies_for_task, current_user_id_for_login_check):
    """
    Worker task to fetch the last activity date for a single user.
    Creates its own WebDriver instance.
    """
    task_driver = None
    user_id_log = user_profile_url.split('/')[-1].split('?')[0]
    log_prefix_task = f"[ActivityDateTask][UID:{user_id_log}] "
    logger.info(f"{log_prefix_task}Fetching last activity date for {user_profile_url}")

    try:
        task_driver = create_driver_with_cookies(shared_cookies_for_task, current_user_id_for_login_check)
        if not task_driver:
            logger.error(f"{log_prefix_task}Failed to create WebDriver or verify login for task. Cannot fetch activity date.")
            return {'url': user_profile_url, 'last_activity_date': None, 'error': 'WebDriver/Login failure in task'}

        last_activity = get_last_activity_date(task_driver, user_profile_url)

        if last_activity:
            logger.info(f"{log_prefix_task}Successfully fetched last activity date: {last_activity}")
            return {'url': user_profile_url, 'last_activity_date': last_activity, 'error': None}
        else:
            logger.warning(f"{log_prefix_task}Could not fetch last activity date.")
            return {'url': user_profile_url, 'last_activity_date': None, 'error': 'Date not found'}

    except Exception as e_task:
        logger.error(f"{log_prefix_task}Exception in fetching activity date: {e_task}", exc_info=True)
        return {'url': user_profile_url, 'last_activity_date': None, 'error': str(e_task)}
    finally:
        if task_driver:
            try:
                task_driver.quit()
                logger.debug(f"{log_prefix_task}Task WebDriver quit successfully.")
            except Exception as e_quit:
                logger.error(f"{log_prefix_task}Error quitting task WebDriver: {e_quit}", exc_info=True)


def _unfollow_user_task(user_profile_url_to_unfollow, user_name_for_log, shared_cookies_for_task, current_user_id_for_login_check, unfollow_settings_for_task):
    """
    Worker task to unfollow a single user.
    Creates its own WebDriver instance.
    """
    task_driver = None
    user_id_log = user_profile_url_to_unfollow.split('/')[-1].split('?')[0]
    log_prefix_task = f"[UnfollowTask][UID:{user_id_log}] "
    logger.info(f"{log_prefix_task}Attempting to unfollow user: {user_name_for_log} ({user_profile_url_to_unfollow})")
    unfollowed_successfully = False

    try:
        task_driver = create_driver_with_cookies(shared_cookies_for_task, current_user_id_for_login_check)
        if not task_driver:
            logger.error(f"{log_prefix_task}Failed to create WebDriver or verify login for unfollow task.")
            return {'url': user_profile_url_to_unfollow, 'unfollowed': False, 'error': 'WebDriver/Login failure in task'}

        delay_before_action = unfollow_settings_for_task.get("delay_before_unfollow_action_sec", 2.0)
        logger.debug(f"{log_prefix_task}Waiting {delay_before_action}s before unfollow action.")
        time.sleep(delay_before_action)

        if unfollow_user(task_driver, user_profile_url_to_unfollow):
            logger.info(f"{log_prefix_task}Successfully unfollowed user: {user_name_for_log}")
            unfollowed_successfully = True
        else:
            logger.warning(f"{log_prefix_task}Failed to unfollow user: {user_name_for_log}")
            time.sleep(unfollow_settings_for_task.get("delay_after_action_error_sec", 1.0))

        delay_after_action = unfollow_settings_for_task.get("delay_per_worker_unfollow_sec", 2.0)
        logger.debug(f"{log_prefix_task}Waiting {delay_after_action}s after unfollow action.")
        time.sleep(delay_after_action)

        return {'url': user_profile_url_to_unfollow, 'unfollowed': unfollowed_successfully, 'error': None}

    except Exception as e_task:
        logger.error(f"{log_prefix_task}Exception during unfollow task for {user_name_for_log}: {e_task}", exc_info=True)
        return {'url': user_profile_url_to_unfollow, 'unfollowed': False, 'error': str(e_task)}
    finally:
        if task_driver:
            try:
                task_driver.quit()
                logger.debug(f"{log_prefix_task}Unfollow Task WebDriver quit successfully.")
            except Exception as e_quit:
                logger.error(f"{log_prefix_task}Error quitting Unfollow Task WebDriver: {e_quit}", exc_info=True)


def unfollow_inactive_not_following_back_users(driver, my_user_id, settings, shared_cookies=None):
    """
    フォローしているユーザーの中で、指定された条件に基づいてユーザーをアンフォローします。
    条件：
    1. 自分をフォローバックしていない。
    2. 最終活動記録が指定日数以上前である (個別プロフィールページから並列取得)。
    3. アンフォローアクション自体も設定に応じて並列実行可能。
    """
    logger.info("非アクティブかつフォローバックしていないユーザーのアンフォロー処理を開始します。")

    inactive_threshold_days = settings.get("inactive_threshold_days", 90)
    max_to_unfollow_total = settings.get("max_users_to_unfollow_per_run", 5)
    max_pages_to_check_following = settings.get("max_pages_for_my_following_list", 10)

    activity_date_workers = settings.get("parallel_profile_page_workers", 3)
    enable_parallel_unfollow_action = settings.get("enable_parallel_unfollow_action", False)
    unfollow_action_workers = settings.get("max_workers_unfollow_action", 3)

    unfollowed_this_run_count = 0

    logger.info(f"自分がフォローしているユーザーのリストとフォローバック状況を取得します (最大 {max_pages_to_check_following} ページ)。")
    my_following_user_details = get_my_following_users_profiles(driver, my_user_id, max_pages_to_check=max_pages_to_check_following)

    if not my_following_user_details:
        logger.info("フォロー中のユーザーが見つからないか、リストの取得に失敗しました。")
        return 0
    logger.info(f"{len(my_following_user_details)} 件のフォロー中ユーザー情報を取得しました。")

    non_followers_back = [
        ud for ud in my_following_user_details if not ud['is_followed_back']
    ]
    logger.info(f"{len(my_following_user_details) - len(non_followers_back)} 件は相互フォローのため対象外。")

    if not non_followers_back:
        logger.info("フォローバックしていないユーザーが見つかりませんでした。処理を終了します。")
        return 0

    logger.info(f"{len(non_followers_back)} 件のフォローバックしていないユーザーについて、最終活動日を並列で確認します (最大ワーカー数: {activity_date_workers})。")
    users_with_activity_dates = {}
    activity_futures = []
    if not shared_cookies:
        logger.warning("共有Cookieが利用できません。並列タスクでのログイン状態が不安定になる可能性があります。")

    with ThreadPoolExecutor(max_workers=activity_date_workers, thread_name_prefix='ActivityDateFetch') as executor:
        for user_data in non_followers_back:
            future = executor.submit(_fetch_user_last_activity_task, user_data['url'], shared_cookies, my_user_id)
            activity_futures.append(future)

        for future in as_completed(activity_futures):
            try:
                result = future.result()
                if result and result.get('url'):
                    users_with_activity_dates[result['url']] = result.get('last_activity_date')
                    if result.get('error'):
                        logger.warning(f"ユーザー ({result['url'].split('/')[-1]}) の最終活動日取得タスクでエラー: {result['error']}")
            except Exception as e_future:
                logger.error(f"最終活動日取得の並列タスク実行中に例外: {e_future}", exc_info=True)

    logger.info(f"{len(users_with_activity_dates)}/{len(non_followers_back)} 件のフォローバックしていないユーザーの最終活動日情報を収集完了。")

    inactive_unfollowed_candidates = []
    for user_data in non_followers_back:
        user_profile_url = user_data['url']
        last_activity_date = users_with_activity_dates.get(user_profile_url)
        if last_activity_date:
            days_since_last_activity = (datetime.date.today() - last_activity_date).days
            if days_since_last_activity >= inactive_threshold_days:
                inactive_unfollowed_candidates.append(user_data)
            else:
                logger.info(f"ユーザー {user_data['name']} ({user_profile_url.split('/')[-1]}) は活動閾値内 ({days_since_last_activity}日前)。アンフォロー対象外。")
        else:
            logger.warning(f"ユーザー {user_data['name']} ({user_profile_url.split('/')[-1]}) の最終活動日不明。アンフォロー対象外。")

    if not inactive_unfollowed_candidates:
        logger.info("非アクティブと判定されたフォローバックしていないユーザーが見つかりませんでした。")
        return 0

    logger.info(f"{len(inactive_unfollowed_candidates)} 件の非アクティブかつ未フォローバックユーザーをアンフォロー対象候補とします。")

    users_to_actually_unfollow = inactive_unfollowed_candidates[:max_to_unfollow_total]
    logger.info(f"最大アンフォロー数 ({max_to_unfollow_total}) に基づき、{len(users_to_actually_unfollow)} 件を処理します。")

    if enable_parallel_unfollow_action:
        logger.info(f"アンフォローアクションを並列で実行します (最大ワーカー数: {unfollow_action_workers})。")
        unfollow_futures = []
        with ThreadPoolExecutor(max_workers=unfollow_action_workers, thread_name_prefix='UnfollowAction') as executor:
            for user_to_unfollow_data in users_to_actually_unfollow:
                if unfollowed_this_run_count >= max_to_unfollow_total: break

                future = executor.submit(_unfollow_user_task,
                                         user_to_unfollow_data['url'],
                                         user_to_unfollow_data['name'],
                                         shared_cookies,
                                         my_user_id,
                                         settings)
                unfollow_futures.append(future)

            for future in as_completed(unfollow_futures):
                try:
                    result = future.result()
                    if result and result.get('unfollowed'):
                        unfollowed_this_run_count += 1
                    if result and result.get('error'):
                        logger.error(f"並列アンフォロータスクでエラー (URL: {result.get('url', 'N/A')}): {result['error']}")
                except Exception as e_future_unfollow:
                    logger.error(f"並列アンフォロータスクの結果取得中に例外: {e_future_unfollow}", exc_info=True)
    else:
        logger.info("アンフォローアクションを逐次実行します。")
        for user_data_to_unfollow_seq in users_to_actually_unfollow:
            if unfollowed_this_run_count >= max_to_unfollow_total:
                logger.info(f"アンフォロー上限 ({max_to_unfollow_total}人) に達しました (逐次処理中)。")
                break

            user_profile_url_seq = user_data_to_unfollow_seq['url']
            user_name_seq = user_data_to_unfollow_seq['name']
            user_id_log_seq = user_profile_url_seq.split('/')[-1].split('?')[0]

            logger.info(f"--- 逐次アンフォロー試行: {user_name_seq} ({user_id_log_seq}) ---")
            delay_before_unfollow_seq = settings.get("delay_before_unfollow_action_sec", 2.0)
            logger.debug(f"    アンフォロー実行前に {delay_before_unfollow_seq} 秒待機します。")
            time.sleep(delay_before_unfollow_seq)

            if unfollow_user(driver, user_profile_url_seq):
                logger.info(f"    ユーザー {user_name_seq} ({user_id_log_seq}) のアンフォローに成功しました。")
                unfollowed_this_run_count += 1
            else:
                logger.warning(f"    ユーザー {user_name_seq} ({user_id_log_seq}) のアンフォローに失敗しました。")
                time.sleep(settings.get("delay_after_action_error_sec", 3.0))

            if unfollowed_this_run_count < max_to_unfollow_total:
                time.sleep(settings.get("delay_per_worker_unfollow_sec", 2.0))
            logger.info(f"--- 逐次アンフォロー試行完了: {user_name_seq} ({user_id_log_seq}) ---")

    logger.info(f"非アクティブユーザーのアンフォロー処理完了。この実行で合計 {unfollowed_this_run_count} 人をアンフォローしました。")
    return unfollowed_this_run_count
