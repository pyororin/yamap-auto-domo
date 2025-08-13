# coding: utf-8
"""
Debug script to save the HTML of the timeline page for analysis.
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
from selenium.common.exceptions import TimeoutException

from yamap_auto.logging_utils import setup_logger
from yamap_auto.yamap_auto_domo import initialize_driver_new, perform_login

# --- Logger setup ---
setup_logger()
logger = logging.getLogger(__name__)

# --- Configuration ---
# Get credentials from environment variables
YAMAP_EMAIL = os.environ.get("YAMAP_LOGIN_ID")
YAMAP_PASSWORD = os.environ.get("YAMAP_LOGIN_PASSWORD")
MY_USER_ID = os.environ.get("YAMAP_USER_ID")

TIMELINE_URL = "https://yamap.com/timeline"
OUTPUT_HTML_FILE = "timeline_page_source.html"

def main():
    """Main debug function"""
    logger.info("========== Starting timeline investigation script ==========")
    driver = None

    if not all([YAMAP_EMAIL, YAMAP_PASSWORD, MY_USER_ID]):
        logger.critical("Missing one or more environment variables: YAMAP_LOGIN_ID, YAMAP_LOGIN_PASSWORD, YAMAP_USER_ID")
        return

    try:
        # 1. Initialize WebDriver
        driver = initialize_driver_new()
        if not driver:
            logger.critical("Failed to initialize WebDriver.")
            return

        # 2. Log in
        if not perform_login(driver, YAMAP_EMAIL, YAMAP_PASSWORD, MY_USER_ID):
            logger.critical("Login failed. Aborting debug script.")
            return

        logger.info("Login successful. Navigating to timeline page...")

        # 3. Navigate to the timeline page
        driver.get(TIMELINE_URL)
        logger.info(f"Navigated to: {TIMELINE_URL}")

        # 4. Wait for the timeline feed to load
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li.TimelineList__Feed"))
            )
            logger.info("Timeline feed items detected. Waiting a bit more for dynamic content.")
            time.sleep(5) # Wait for any additional dynamic loading

            # 5. Save the page source
            with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            logger.info(f"SUCCESS: Saved page source to {OUTPUT_HTML_FILE}")

        except TimeoutException:
            logger.error("FAILURE: Timed out waiting for timeline feed items to load.")
            screenshot_path = os.path.join("logs", "screenshots", "investigate_timeline_failure.png")
            os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
            driver.save_screenshot(screenshot_path)
            logger.info(f"Saved screenshot to {screenshot_path}")

    except Exception as e:
        logger.critical("An unexpected error occurred during the investigation script.", exc_info=True)
        if driver:
            screenshot_path = os.path.join("logs", "screenshots", "investigate_timeline_error.png")
            os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
            driver.save_screenshot(screenshot_path)
            logger.info(f"Saved screenshot to {screenshot_path}")

    finally:
        if driver:
            logger.info("Investigation script finished. Closing WebDriver...")
            driver.quit()
        logger.info("========== Timeline investigation script finished ==========")


if __name__ == "__main__":
    main()
