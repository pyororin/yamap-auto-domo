import os
import asyncio
from playwright.async_api import async_playwright

async def main():
    """
    This function logs into YAMAP using Playwright.
    """
    yamap_email = os.environ.get("YAMAP_LOGIN_ID")
    yamap_password = os.environ.get("YAMAP_LOGIN_PASSWORD")
    user_name = "ぴょろりん" # The user's name to verify login

    if not yamap_email or not yamap_password:
        print("Error: YAMAP_LOGIN_ID and YAMAP_LOGIN_PASSWORD environment variables must be set.")
        return

    # Create debug directory if it doesn't exist
    debug_dir = "yamap_auto2/debug"
    os.makedirs(debug_dir, exist_ok=True)

    print("Launching browser...")
    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(headless=True)
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
