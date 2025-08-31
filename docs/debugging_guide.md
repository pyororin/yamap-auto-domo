# Debugging Guide

This document outlines the debugging process for the web scraping and automation scripts in this repository.

## HTML Dumping for Debugging

When a script fails to interact with a web page correctly (e.g., it can't find an element), it's often because the page's HTML structure is different from what the script expects. To debug this, we need to inspect the HTML of the page as it was seen by the script.

### `dump_html.py` Script

We have a dedicated script for this purpose: `yamap_auto2/debug/dump_html.py`. This script uses Playwright to navigate to a given URL and saves the full HTML of the page to a file.

#### Usage

To use the script, run it from the command line with the URL you want to inspect as an argument:

```bash
python yamap_auto2/debug/dump_html.py <URL>
```

**Example:**

To get the HTML of the YAMAP login page, you would run:

```bash
python yamap_auto2/debug/dump_html.py https://yamap.com/login
```

This will create a file named `login.html` inside the `yamap_auto2/debug/` directory. You can then open this file to inspect the HTML and find the correct selectors for the elements you need to interact with.

### Integration with other scripts

The main login script (`yamap_auto2/main.py`) also has this debugging functionality built-in. If the script fails to log in, it will automatically save a screenshot (`login_failed.png`) and the HTML of the page (`login_failed.html`) to the `yamap_auto2/debug/` directory. This allows for quick debugging of login-related issues.
