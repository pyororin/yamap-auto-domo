# coding: utf-8
"""
Debug script to test clicking the DOMO emoji on an activity page.
This script will help diagnose the MoveTargetOutOfBoundsException.
"""
import os
import sys
import time
import logging

# Add the current directory to sys.path to allow imports from yamap_auto
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains

from yamap_auto.logging_utils import setup_logger
from yamap_auto.driver_utils import save_screenshot
from yamap_auto.yamap_auto_domo import initialize_driver_new, perform_login

# --- Logger setup ---
setup_logger()
logger = logging.getLogger(__name__)

# --- Configuration ---
YAMAP_EMAIL = os.environ.get("YAMAP_LOGIN_ID")
YAMAP_PASSWORD = os.environ.get("YAMAP_LOGIN_PASSWORD")
MY_USER_ID = os.environ.get("YAMAP_USER_ID")

ACTIVITY_URL = "https://yamap.com/activities/42140143"

def main():
    """Main debug function"""
    logger.info("========== Starting DOMO emoji click debug script (v4) ==========")
    driver = None

    if not all([YAMAP_EMAIL, YAMAP_PASSWORD, MY_USER_ID]):
        logger.critical("Missing environment variables.")
        return

    try:
        driver = initialize_driver_new()
        if not driver:
            return

        if not perform_login(driver, YAMAP_EMAIL, YAMAP_PASSWORD, MY_USER_ID):
            return

        driver.get(ACTIVITY_URL)
        logger.info(f"Navigated to: {ACTIVITY_URL}")

        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.ActivityDetailTabLayout, [data-testid='activity-detail-layout']"))
        )
        logger.info("Activity page layout loaded.")

        time.sleep(3)

        add_emoji_button_selector = "button[aria-label='絵文字をおくる']"
        logger.info(f"Attempting to find the 'add emoji' button with selector: {add_emoji_button_selector}")

        try:
            add_emoji_button = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, add_emoji_button_selector))
            )
            logger.info("Found the 'add emoji' button. Using direct .click().")
            add_emoji_button.click()

            time.sleep(2) # Give it a moment to appear

            # Try to find the picker, but don't fail if it's not there
            emoji_picker_selector = "div[aria-label='絵文字ピッカー']"
            try:
                WebDriverWait(driver, 5).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, emoji_picker_selector))
                )
                logger.info("SUCCESS: Emoji picker is visible.")
            except TimeoutException:
                logger.warning("WARNING: Emoji picker did not appear after 5 seconds.")

            # Save page source AFTER the click attempt
            page_source_path = "activity_page_source_after_click.html"
            with open(page_source_path, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            logger.info(f"Saved page source after click attempt to {page_source_path}")

            # Get browser logs
            logger.info("--- Browser Console Logs ---")
            for entry in driver.get_log('browser'):
                logger.info(entry)
            logger.info("----------------------------")

        except Exception as e:
            logger.error("An error occurred during the emoji click process.", exc_info=True)
            save_screenshot(driver, "Debug_EmojiClick_Error")


    except Exception as e:
        logger.critical("An unexpected error occurred during the debug script.", exc_info=True)
        if driver:
            save_screenshot(driver, "Debug_EmojiClick_FatalError")

    finally:
        if driver:
            logger.info("Debug script finished. Closing WebDriver...")
            driver.quit()
        logger.info("========== Simplified debug script finished ==========")

if __name__ == "__main__":
    main()
