#!/usr/bin/env python3
"""
Local Proxy Web Scraper
-----------------------
A local HTTP/HTTPS proxy that intercepts browser traffic and saves
the content of every webpage you visit.

SETUP:
  pip install mitmproxy beautifulsoup4

RUN:
  python proxy_scraper.py

CONFIGURE YOUR BROWSER:
  Set your browser's proxy to:
    Host: 127.0.0.1
    Port: 8080

  For HTTPS, also install the mitmproxy certificate:
    Visit http://mitm.it in your browser while the proxy is running.

OUTPUT:
  Scraped pages are saved to ./scraped_pages/
  A log of all visited URLs is saved to ./visited_urls.log
"""

import os
import re
import json
from datetime import datetime
from urllib.parse import urlparse

from mitmproxy import http
from bs4 import BeautifulSoup


# --- Configuration ---
OUTPUT_DIR = "scraped_pages"
URL_LOG = "visited_urls.log"
SAVE_HTML = True       # Save raw HTML files
SAVE_TEXT = True       # Save plain text (no HTML tags)
SAVE_JSON = True       # Save structured JSON (title, links, text)
SKIP_EXTENSIONS = {    # Skip non-page resources
    ".css", ".js", ".png", ".jpg", ".jpeg",
    ".gif", ".svg", ".ico", ".woff", ".woff2",
    ".ttf", ".mp4", ".mp3", ".pdf", ".zip"
}

os.makedirs(OUTPUT_DIR, exist_ok=True)


def sanitize_filename(url: str, max_len: int = 80) -> str:
    """Turn a URL into a safe filename."""
    parsed = urlparse(url)
    name = parsed.netloc + parsed.path
    name = re.sub(r"[^\w\-_.]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name[:max_len]


def should_skip(url: str) -> bool:
    """Return True for non-HTML resources we don't want to save."""
    path = urlparse(url).path.lower()
    _, ext = os.path.splitext(path)
    return ext in SKIP_EXTENSIONS


def extract_content(html: str, url: str) -> dict:
    """Parse HTML and return structured content."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove script/style noise
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else "No title"
    text = soup.get_text(separator="\n", strip=True)

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http"):
            links.append({"text": a.get_text(strip=True), "href": href})

    headings = [h.get_text(strip=True) for h in soup.find_all(["h1", "h2", "h3"])]

    return {
        "url": url,
        "title": title,
        "scraped_at": datetime.now().isoformat(),
        "headings": headings,
        "links": links[:50],          # cap at 50 links
        "text_preview": text[:500],   # first 500 chars preview
        "full_text": text,
    }


def save_page(url: str, html: str):
    """Save HTML, text, and JSON versions of the page."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{timestamp}_{sanitize_filename(url)}"
    base_path = os.path.join(OUTPUT_DIR, base_name)

    content = extract_content(html, url)

    if SAVE_HTML:
        with open(base_path + ".html", "w", encoding="utf-8", errors="replace") as f:
            f.write(html)

    if SAVE_TEXT:
        with open(base_path + ".txt", "w", encoding="utf-8", errors="replace") as f:
            f.write(f"URL: {url}\n")
            f.write(f"Title: {content['title']}\n")
            f.write(f"Scraped: {content['scraped_at']}\n")
            f.write("=" * 60 + "\n\n")
            f.write(content["full_text"])

    if SAVE_JSON:
        with open(base_path + ".json", "w", encoding="utf-8", errors="replace") as f:
            # Don't include full_text in JSON to keep it readable
            summary = {k: v for k, v in content.items() if k != "full_text"}
            json.dump(summary, f, indent=2, ensure_ascii=False)

    # Append to URL log
    with open(URL_LOG, "a", encoding="utf-8") as f:
        f.write(f"{content['scraped_at']} | {content['title'][:50]:<50} | {url}\n")

    print(f"[SAVED] {content['title'][:60]} → {base_name}.*")


# ── mitmproxy addon ──────────────────────────────────────────────

class ProxyScraper:
    """mitmproxy addon: intercepts responses and saves HTML pages."""

    def response(self, flow: http.HTTPFlow):
        url = flow.request.pretty_url

        # Only process HTML responses
        content_type = flow.response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return

        if should_skip(url):
            return

        # Decode response body
        try:
            html = flow.response.get_text(strict=False)
        except Exception:
            return

        if not html or len(html) < 200:  # skip tiny/empty pages
            return

        try:
            save_page(url, html)
        except Exception as e:
            print(f"[ERROR] Could not save {url}: {e}")


# ── entry point ──────────────────────────────────────────────────

addons = [ProxyScraper()]

if __name__ == "__main__":
    # Allow running directly with `python proxy_scraper.py`
    # which starts mitmproxy with this script as an addon
    import subprocess
    import sys

    print("Starting proxy on 127.0.0.1:8080 ...")
    print("Configure your browser to use this proxy.")
    print("Visit http://mitm.it to install the HTTPS certificate.")
    print(f"Scraped pages will be saved to: {os.path.abspath(OUTPUT_DIR)}/")
    print("Press Ctrl+C to stop.\n")

    import shutil
    mitmdump = shutil.which("mitmdump")
    if not mitmdump:
        print("ERROR: mitmdump not found. Make sure your venv is active.")
        sys.exit(1)

    subprocess.run([
        mitmdump,
        "--listen-host", "127.0.0.1",
        "--listen-port", "8080",
        "-s", __file__
    ])
