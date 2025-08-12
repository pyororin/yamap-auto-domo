# coding: utf-8
"""
Debug script to test finding the DOMO user list button/link on an activity page.
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

# Target activity URL from the logs
ACTIVITY_URL = "https://yamap.com/activities/42062405"

# New proposed selector for the DOMO link
# NEW_DOMO_SELECTOR_XPATH = "//a[contains(@class, 'ActivityToolBar__ReactionLink')]"
NEW_DOMO_SELECTOR_XPATH = "//a[contains(@href, '/reactions')]"


def main():
    """Main debug function"""
    logger.info("========== Starting DOMO finder debug script ==========")
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

        logger.info("Login successful. Navigating to activity page...")

        # 3. Navigate to the activity page
        driver.get(ACTIVITY_URL)
        logger.info(f"Navigated to: {ACTIVITY_URL}")

        # 4. Find the DOMO link/button using the new selector
        logger.info(f"Attempting to find the DOMO link with XPath: {NEW_DOMO_SELECTOR_XPATH}")

        try:
            domo_link = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, NEW_DOMO_SELECTOR_XPATH))
            )
            logger.info("SUCCESS: Found the DOMO link element.")

            # Print details about the element
            text = domo_link.text.strip()
            href = domo_link.get_attribute('href')
            aria_label = domo_link.get_attribute('aria-label')
            logger.info(f"  - Text: '{text}'")
            logger.info(f"  - Href: '{href}'")
            logger.info(f"  - Aria-label: '{aria_label}'")

            # Test parsing the count
            if "件" in text:
                count_str = text.replace("件", "").strip()
                if count_str.isdigit():
                    logger.info(f"  - Parsed count: {int(count_str)}")
                else:
                    logger.warning(f"  - Could not parse count from text: '{text}'")

            # 5. Click the link and verify
            logger.info("Attempting to click the DOMO link...")
            domo_link.click()

            # Wait for what we expect to see next.
            # The original code checks for a URL change or the presence of the user list.
            # Let's try that.
            logger.info("Waiting for URL to contain '/reactions' or for user list to appear...")
            time.sleep(2) # Add a small sleep to wait for animations

            # The old selector 'a.DomoUserListItem__UserLink' is not valid anymore.
            # Based on the page source, a better selector is one that finds links to user profiles.
            user_list_selector = "a[href^='/users/']"
            WebDriverWait(driver, 15).until(
                EC.any_of(
                    EC.url_contains("/reactions"),
                    EC.presence_of_element_located((By.CSS_SELECTOR, user_list_selector))
                )
            )
            logger.info("SUCCESS: URL changed to contain '/reactions' or user list appeared.")

            # Now, let's specifically check for the user list again
            logger.info(f"Checking again for the user list with selector: '{user_list_selector}'")
            try:
                user_links = driver.find_elements(By.CSS_SELECTOR, user_list_selector)
                if user_links:
                    logger.info(f"SUCCESS: Found {len(user_links)} user links on the page.")
                else:
                    logger.warning("Could not find any user links, but the page seems to have loaded.")
                    # Save the page source for inspection
                    page_source_path = "reactions_page_source.html"
                    with open(page_source_path, "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                    logger.info(f"Saved page source to {page_source_path} for debugging.")
            except Exception as e:
                logger.error(f"An error occurred while trying to find user links: {e}")

        except TimeoutException:
            logger.error("FAILURE: Timed out waiting to find the DOMO link or the user list after clicking.")
            # Save a screenshot for debugging
            screenshot_path = os.path.join("logs", "screenshots", "debug_domo_finder_failure.png")
            os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
            driver.save_screenshot(screenshot_path)
            logger.info(f"Saved screenshot to {screenshot_path}")

    except Exception as e:
        logger.critical("An unexpected error occurred during the debug script.", exc_info=True)
        if driver:
            # Save a screenshot for debugging
            screenshot_path = os.path.join("logs", "screenshots", "debug_domo_finder_error.png")
            os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
            driver.save_screenshot(screenshot_path)
            logger.info(f"Saved screenshot to {screenshot_path}")

    finally:
        if driver:
            logger.info("Debug script finished. Closing WebDriver in 5 seconds...")
            time.sleep(5)
            driver.quit()
        logger.info("========== DOMO finder debug script finished ==========")


if __name__ == "__main__":
    main()
