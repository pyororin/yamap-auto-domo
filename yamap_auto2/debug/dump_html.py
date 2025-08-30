import os
import asyncio
import sys
from playwright.async_api import async_playwright
from urllib.parse import urlparse

async def dump_html(url: str):
    """
    Dumps the HTML of a given URL to a file.
    The filename is derived from the URL's path.
    """
    if not url:
        print("Error: URL must be provided.", file=sys.stderr)
        return

    # Create a filename from the URL
    parsed_url = urlparse(url)
    path = parsed_url.path.strip('/').replace('/', '_')
    if not path:
        path = "index"
    filename = f"{path}.html"

    debug_dir = "yamap_auto2/debug"
    os.makedirs(debug_dir, exist_ok=True)
    filepath = os.path.join(debug_dir, filename)

    print(f"Dumping HTML of {url} to {filepath}...")

    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url)
            html = await page.content()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"Successfully dumped HTML to {filepath}")

        except Exception as e:
            print(f"An error occurred: {e}", file=sys.stderr)
        finally:
            if browser:
                await browser.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python dump_html.py <URL>", file=sys.stderr)
        sys.exit(1)

    target_url = sys.argv[1]
    asyncio.run(dump_html(target_url))
