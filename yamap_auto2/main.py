import os
import asyncio
from playwright.async_api import async_playwright
from datetime import datetime, timedelta, timezone

async def main():
    """
    This function logs into YAMAP using Playwright.
    """
    yamap_email = os.environ.get("YAMAP_LOGIN_ID")
    yamap_password = os.environ.get("YAMAP_LOGIN_PASSWORD")
    yamap_user_id = os.environ.get("YAMAP_USER_ID")
    user_name = "ぴょろりん" # The user's name to verify login

    if not yamap_email or not yamap_password or not yamap_user_id:
        print("Error: YAMAP_LOGIN_ID, YAMAP_LOGIN_PASSWORD, and YAMAP_USER_ID environment variables must be set.")
        return

    # Create debug directory if it doesn't exist
    debug_dir = "yamap_auto2/debug"
    os.makedirs(debug_dir, exist_ok=True)

    print("Launching browser...")
    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(headless=False) # Run in headed mode for debugging
            page = await browser.new_page()

            print("Navigating to YAMAP login page...")
            await page.goto("https://yamap.com/login")

            print("Filling in login credentials...")
            await page.fill("input[name='email']", yamap_email)
            await page.fill("input[name='password']", yamap_password)

            print("Clicking login button...")
            await page.click("button[type='submit']")

            # Wait for the URL to change to the homepage
            await page.wait_for_url("https://yamap.com/", timeout=30000)
            print("Navigated to homepage.")

            print("Verifying login...")
            # Use a more direct selector based on the alt text of the image
            avatar_selector = f"img[alt='{user_name}']"
            await page.wait_for_selector(avatar_selector, timeout=30000)
            print("Login successful! Avatar found.")
            await page.screenshot(path=os.path.join(debug_dir, "login_successful.png"))

            # ------------------------------------------------------------------
            # Step 3: Navigate to the user's profile page
            # ------------------------------------------------------------------
            profile_url = f"https://yamap.com/users/{yamap_user_id}"
            print(f"Navigating to profile page: {profile_url}")
            await page.goto(profile_url)
            # Instead of networkidle, wait for a specific element that indicates the page is ready.
            # The activity entries themselves are a good indicator.
            await page.wait_for_selector("article[data-testid='activity-entry']", timeout=30000)
            print("Profile page loaded and activities are visible.")

            # ------------------------------------------------------------------
            # Step 4: Collect activity URLs from the last 2 weeks
            # ------------------------------------------------------------------
            print("Collecting recent activity URLs...")
            activity_urls = []
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=14)

            # Based on yamap_auto/my_post_interaction_utils.py, this is a reliable selector
            activity_entries = await page.locator("article[data-testid='activity-entry']").all()
            print(f"Found {len(activity_entries)} activity entries on the page.")

            for entry in activity_entries:
                try:
                    time_element = entry.locator("time").first
                    datetime_str = await time_element.get_attribute("datetime")
                    activity_date = datetime.fromisoformat(datetime_str)

                    if activity_date >= cutoff_date:
                        link_element = entry.locator("a").first
                        href = await link_element.get_attribute("href")
                        if href:
                            # Ensure the URL is absolute
                            if href.startswith("/"):
                                activity_url = f"https://yamap.com{href}"
                            else:
                                activity_url = href

                            if "/activities/" in activity_url:
                                activity_urls.append(activity_url)
                                print(f"  [OK] Found activity within date range: {activity_url} (Date: {activity_date.date()})")
                    else:
                        print(f"  [SKIP] Activity from {activity_date.date()} is older than 14 days. Stopping search.")
                        break # Assuming activities are sorted chronologically
                except Exception as e:
                    print(f"Could not process an activity entry: {e}")

            print(f"Found {len(activity_urls)} activities in the last 14 days.")

            # ------------------------------------------------------------------
            # Step 5: Process each activity and get users who reacted
            # ------------------------------------------------------------------
            all_reactions = {}
            if not activity_urls:
                print("No recent activities to process.")
            else:
                print("Processing activities to find users who reacted...")

            for url in activity_urls:
                try:
                    print(f"\n--- Processing activity: {url} ---")
                    await page.goto(url)

                    reaction_link_xpath = "//a[contains(@class, 'ActivityToolBar__ReactionLink') and contains(@href, '/reactions')]"

                    await page.wait_for_selector(reaction_link_xpath, timeout=20000)

                    reaction_link = page.locator(reaction_link_xpath)

                    if await reaction_link.count() > 0:
                        print("  Found reaction link. Clicking it...")
                        await reaction_link.click()

                        await page.wait_for_url(f"{url}/reactions", timeout=15000)
                        print("  Navigated to reactions page.")

                        more_button_xpath = "//button[contains(normalize-space(), 'もっと見る')]"
                        click_count = 0
                        while await page.locator(more_button_xpath).count() > 0:
                            click_count += 1
                            print(f"  Loading more users (page {click_count})...")
                            try:
                                button_to_click = page.locator(more_button_xpath).first
                                if not await button_to_click.is_visible():
                                    break
                                await button_to_click.click(timeout=5000)
                                await page.wait_for_timeout(3000)
                            except Exception as e_more:
                                print(f"  Could not click 'More' button or it disappeared: {e_more}")
                                break
                            if click_count > 20:
                                print("  Safety break after 20 'More' clicks.")
                                break

                        print("  All users loaded. Scraping user data...")
                        user_links = await page.locator("a[href^='/users/']").all()

                        activity_reactions = []
                        for link in user_links:
                            try:
                                user_href = await link.get_attribute("href")
                                if f"/users/{yamap_user_id}" in user_href:
                                    continue

                                img = link.locator("img").first
                                user_name = await img.get_attribute("alt")

                                if user_name and user_href:
                                    user_profile_url = f"https://yamap.com{user_href}" if user_href.startswith("/") else user_href
                                    activity_reactions.append({"name": user_name, "profile_url": user_profile_url})

                            except Exception as e_user:
                                print(f"  Could not process a user link: {e_user}")

                        all_reactions[url] = activity_reactions
                        print(f"  Found {len(activity_reactions)} users who reacted to this activity.")

                    else:
                        print("  No reaction link found for this activity.")
                        all_reactions[url] = []

                except Exception as e_activity:
                    print(f"  [ERROR] Failed to process activity {url}: {e_activity}")

            # ------------------------------------------------------------------
            # Step 6: Output the results
            # ------------------------------------------------------------------
            print("\n\n--- All Reactions Summary ---")
            if not all_reactions:
                print("No reactions found for any activities in the last 14 days.")
            else:
                for activity_url, users in all_reactions.items():
                    print(f"\nActivity: {activity_url}")
                    if not users:
                        print("  No one has reacted to this activity yet.")
                    else:
                        print(f"  {len(users)} users reacted:")
                        for user in users:
                            print(f"    - Name: {user['name']}, Profile: {user['profile_url']}")
            print("\n--- End of Summary ---")

        except Exception as e:
            print(f"An error occurred: {e}")
            if 'page' in locals() and not page.is_closed():
                await page.screenshot(path=os.path.join(debug_dir, "login_failed.png"))
                html = await page.content()
                with open(os.path.join(debug_dir, "login_failed.html"), "w", encoding="utf-8") as f:
                    f.write(html)
        finally:
            if browser:
                print("Closing browser...")
                await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
