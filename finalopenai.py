"""
selenium_openai_pagination.py

Scrapes multiple pages of OpenAI forum (https://community.openai.com/latest) 
using Selenium, collecting threads/comments with security keywords.

Ensure you replace 'DRIVER_PATH' with the real path to your chromedriver.exe,
the same one that worked before, e.g.,
  r"C:\\Users\\monik\\OneDrive\\Desktop\\THESIS\\chromedriver-win64\\chromedriver.exe"

Usage:
    python selenium_openai_pagination.py
"""

import time
import json
import re

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# Security keywords
SECURITY_KEYWORDS = [
    "security",
    "vulnerability",
    "encryption",
    "authentication",
    "xss",
    "csrf",
    "token",
    "cybersecurity",
    "rce",
    "sql injection",
    "https",
    "ssl",
    "certificate",
    "secrets",
    "api keys",
    "firewall",
    "zero-day",
    "exploit",
    "copilot",
    "generative ai",
    "llm",
    "code completion",
    "secure coding",
    "code injection",
    "github copilot",
    "gpt",
    "prompt injection",
    "pen testing",
    "cwe",
    "oauth",
    "jwt",
    "gpt code",
    "ai code generation",
    "cryptography",
    "privacy",
    "ai security",
    "auto pilot", 
    "pair programming ai",
    "data leak", 
    "exposed secrets", 
    "license compliance"
]

def contains_security_keyword(text: str) -> bool:
    """Check if any SECURITY_KEYWORDS appear in 'text' (case-insensitive)."""
    if not text:
        return False
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in SECURITY_KEYWORDS)

def scrape_openai_forum_paged(
    driver,
    base_url="https://community.openai.com",
    start_page=1,
    max_pages=3
) -> list:
    """
    Load multiple pages of the forum (e.g. /latest?page=N) with Selenium in a SINGLE driver.
    Gather threads whose titles have security keywords, then load each thread to find comments.
    Returns a list of discussion dictionaries.
    """
    all_discussions = []
    visited_ids = set()  # track visited thread IDs to avoid duplicates

    for page_num in range(start_page, start_page + max_pages):
        page_url = f"{base_url}/latest?page={page_num}"
        print(f"[INFO] Loading page #{page_num}: {page_url}")

        driver.get(page_url)
        time.sleep(3)  # wait for content to load

        soup = BeautifulSoup(driver.page_source, "html.parser")
        # Discourse typically has threads in <a class="title raw-topic-link">
        topic_links = soup.select("a.title.raw-topic-link")
        if not topic_links:
            topic_links = soup.select("a.title")  # fallback

        print(f"[DEBUG] Found {len(topic_links)} threads on page {page_num}.")

        for link in topic_links:
            title = link.get_text(strip=True)
            href = link.get("href", "")
            if href.startswith("http"):
                thread_url = href
            else:
                thread_url = base_url + href

            # Extract numeric thread ID if present
            thread_id = None
            match = re.search(r'/t/[^/]+/(\d+)', href)
            if match:
                thread_id = match.group(1)

            # Avoid re-processing the same thread ID across pages
            if thread_id and thread_id in visited_ids:
                continue

            # If the thread title has a security keyword, check it out
            if contains_security_keyword(title):
                disc_data = {
                    "source": "OpenAI Forum",
                    "thread_id": thread_id,
                    "title": title,
                    "url": thread_url,
                    "comments": []
                }

                # Load the thread page in the SAME driver
                try:
                    driver.get(thread_url)
                    time.sleep(2)  # wait for the thread's posts to load

                    thread_soup = BeautifulSoup(driver.page_source, "html.parser")
                    post_divs = thread_soup.select("div.topic-post div.cooked")
                    print(f"[DEBUG] Found {len(post_divs)} posts in thread: {title}")

                    for post in post_divs:
                        post_text = post.get_text(separator=" ", strip=True)
                        if contains_security_keyword(post_text):
                            disc_data["comments"].append(post_text)

                except Exception as e:
                    print(f"[ERROR] Could not load thread {thread_url}: {e}")

                if disc_data["comments"]:
                    all_discussions.append(disc_data)

            if thread_id:
                visited_ids.add(thread_id)

    return all_discussions

def main():
    print("[INFO] Starting Selenium-based scraper with pagination (single driver)...")
    start_time = time.time()

    # ----------------------------------------------------------------------------
    # UPDATE HERE: Use the SAME PATH that worked for you before.
    driver_path = r"C:\\Users\\monik\\OneDrive\\Desktop\\THESIS\\chromedriver-win64\\chromedriver.exe"
    # ----------------------------------------------------------------------------

    # If your Chrome is in a special location, you might also need:
    # chrome_options.binary_location = r"C:\Path\to\chrome.exe"

    chrome_options = Options()
    chrome_options.add_argument("--headless")

    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        # We want to scrape, say, 5 pages. Increase if you want more.
        discussions = scrape_openai_forum_paged(
            driver=driver,
            base_url="https://community.openai.com",
            start_page=1,   # start from page=1
            max_pages=500     # scrape 50 pages
        )
    finally:
        driver.quit()

    print(f"[INFO] Collected {len(discussions)} discussions with security keywords.")
    output_file = "finalopenai.json"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(discussions, f, indent=2, ensure_ascii=False)
        print(f"[INFO] Saved results to {output_file}")
    except Exception as e:
        print(f"[ERROR] Could not write to {output_file}: {e}")

    elapsed = time.time() - start_time
    print(f"[INFO] Extraction completed in {elapsed:.2f} seconds.")

if __name__ == "__main__":
    main()

