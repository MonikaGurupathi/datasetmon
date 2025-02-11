import os
import re
import time
import requests
import pandas as pd
import praw

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

# ---------- CONFIG ----------
REDDIT_CLIENT_ID = "5uUMU9NUJo-k2s-3zY5Ncw"
REDDIT_CLIENT_SECRET = "VLw_f-NfFyWbT9saua4ISGr7JeEbCg"
REDDIT_USER_AGENT = "comment scraping by MindImportant8450"
STACK_EXCHANGE_API_KEY = None  # Optional
SELENIUM_DRIVER_PATH = r"/opt/homebrew/bin/chromedriver"

OUTPUT_EXCEL_FILE = "comments_dataset.xlsx"

# We'll define multiple synonyms or relevant words for security & privacy
# plus synonyms for code generation AI tools.
RELEVANT_KEYWORDS = {
    "security", "privacy", "copilot", "gemini", "codewhisperer", "malicious",
    "vulnerability", "vulnerabilities", "license compliance", "safety",
    "private code", "leak", "ip", "intellectual property", "prompt injection"
}

# We can define more robust queries
SEARCH_QUERIES = [
    "GitHub Copilot security",
    "GitHub Copilot privacy",
    "Gemini AI security",
    "Gemini AI privacy",
    "code generation AI vulnerabilities",
    "AI code generation licensing",
    "AI pair programming security"
]

def clean_text(text, max_length=10000):
    cleaned = "".join(char for char in text if char.isprintable())
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length] + " [TRUNCATED]"
    return cleaned

def is_relevant_comment(text):
    """
    Check if text contains ANY relevant keyword or synonym (case-insensitive).
    """
    lower = text.lower()
    for kw in RELEVANT_KEYWORDS:
        if kw in lower:
            return True
    return False

def save_to_excel(df, sheet_name):
    try:
        with pd.ExcelWriter(OUTPUT_EXCEL_FILE, mode="a", if_sheet_exists="replace") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    except FileNotFoundError:
        with pd.ExcelWriter(OUTPUT_EXCEL_FILE, mode="w") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)

# 1) REDDIT SCRAPING
def scrape_reddit(subreddits, queries, limit=50):
    """
    Collect more posts and comments from multiple queries in multiple subreddits.
    """
    print("[INFO] Scraping Reddit with extended queries...")
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )
    data_rows = []

    for q in queries:
        for sub in subreddits:
            try:
                subreddit = reddit.subreddit(sub)
                submissions = subreddit.search(q, limit=limit)
                for submission in submissions:
                    # Basic thread info
                    thread_title = submission.title
                    thread_url = f"https://www.reddit.com{submission.permalink}"
                    upvotes = submission.score

                    submission.comments.replace_more(limit=None)
                    for cmt in submission.comments.list():
                        cmt_body = clean_text(cmt.body)
                        if is_relevant_comment(cmt_body):
                            data_rows.append({
                                "Thread Title": thread_title,
                                "URL": thread_url,
                                "Comment": cmt_body,
                                "Engagement": upvotes,
                                "Platform": "Reddit"
                            })
            except Exception as e:
                print(f"[ERROR] r/{sub} for query '{q}': {e}")

    return pd.DataFrame(data_rows)

# 2) STACK OVERFLOW SCRAPING
def scrape_stack_overflow(queries, pagesize=30):
    """
    Use multiple queries. Also fetch answers, and do a broader check for relevant words in questions/answers.
    """
    print("[INFO] Scraping Stack Overflow with broader coverage...")
    data_rows = []
    base_url = "https://api.stackexchange.com/2.3/search"
    answers_url = "https://api.stackexchange.com/2.3/questions/{ids}/answers"

    for q in queries:
        params = {
            "order": "desc",
            "sort": "activity",
            "intitle": q,      # searching in the title
            "site": "stackoverflow",
            "pagesize": pagesize
        }
        if STACK_EXCHANGE_API_KEY:
            params["key"] = STACK_EXCHANGE_API_KEY

        try:
            resp = requests.get(base_url, params=params)
            resp.raise_for_status()
            jdata = resp.json()
            qids = []

            for item in jdata.get("items", []):
                title = item.get("title", "")
                link = item.get("link", "")
                views = item.get("view_count", 0)
                body_snippet = item.get("body", "")  # sometimes partial
                question_id = item.get("question_id")

                # Check relevance in question itself
                if not is_relevant_comment(title + " " + body_snippet):
                    continue

                data_rows.append({
                    "Thread Title": title,
                    "URL": link,
                    "Comment": "[QUESTION]",
                    "Engagement": views,
                    "Platform": "Stack Overflow"
                })
                qids.append(str(question_id))

            # Fetch answers for these questions
            if qids:
                joined_ids = ";".join(qids)
                ans_params = {
                    "order": "desc",
                    "sort": "activity",
                    "site": "stackoverflow",
                    "pagesize": 10  # top 10 answers
                }
                if STACK_EXCHANGE_API_KEY:
                    ans_params["key"] = STACK_EXCHANGE_API_KEY

                ans_resp = requests.get(answers_url.format(ids=joined_ids), params=ans_params)
                ans_resp.raise_for_status()
                ans_data = ans_resp.json()
                for ans in ans_data.get("items", []):
                    ans_body = ans.get("body_markdown", "")
                    if is_relevant_comment(ans_body):
                        question_id = ans.get("question_id", "")
                        # We can build a direct link to the question or answer
                        q_url = f"https://stackoverflow.com/questions/{question_id}"
                        clean_ans = clean_text(ans_body)
                        data_rows.append({
                            "Thread Title": f"Answer to {question_id}",
                            "URL": q_url,
                            "Comment": clean_ans,
                            "Engagement": None,
                            "Platform": "Stack Overflow"
                        })

        except Exception as e:
            print(f"[ERROR] Stack Overflow query '{q}': {e}")

    return pd.DataFrame(data_rows)

# 3) GITHUB DISCUSSIONS (Selenium)
def scrape_github_discussions(discussions_url, queries, max_threads=20):
    """
    Attempt to search each query, load multiple pages, and collect relevant comments.
    'discussions_url' could be https://github.com/orgs/github/discussions, or something similar.
    """
    print("[INFO] Scraping GitHub Discussions with deeper approach...")
    data_rows = []
    service = Service(SELENIUM_DRIVER_PATH)
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get(discussions_url)
        time.sleep(3)

        # For each query, try searching in the page's search bar if available
        for q in queries:
            # Example (depends on actual GitHub Discussions layout):
            try:
                search_input = driver.find_element(By.XPATH, "//input[@aria-label='Search all discussions']")
                search_input.clear()
                search_input.send_keys(q)
                search_input.send_keys(Keys.ENTER)
                time.sleep(3)

                # TODO: Implement pagination or scrolling if multiple pages of results
                threads = driver.find_elements(By.XPATH, "//a[contains(@href, '/discussions/')]")
                thread_urls = []
                for t in threads:
                    text = t.text.strip().lower()
                    href = t.get_attribute("href")
                    # Basic filter if query matches text/href
                    if q.lower() in text or q.lower() in href.lower():
                        thread_urls.append(href)
                    if len(thread_urls) >= max_threads:
                        break

                # Now visit each thread
                for url in thread_urls:
                    driver.get(url)
                    time.sleep(2)

                    # Scrape thread title
                    try:
                        thread_title = driver.find_element(By.XPATH, "//h1").text.strip()
                    except:
                        thread_title = "N/A"

                    # Find comment blocks (often .js-comment or .DiscussionComment)
                    comments = driver.find_elements(By.XPATH, "//div[contains(@class, 'js-comment')]")
                    for cmt in comments:
                        ctext = cmt.text.strip()
                        ctext = clean_text(ctext)
                        if is_relevant_comment(ctext):
                            data_rows.append({
                                "Thread Title": thread_title,
                                "URL": url,
                                "Comment": ctext,
                                "Engagement": None,
                                "Platform": "GitHub Discussions"
                            })

                    # TODO: If there's pagination in the discussion thread, handle it (click "Next" etc.)
            except Exception as e:
                print(f"[WARNING] Issue searching for '{q}' in GitHub Discussions: {e}")

    except Exception as e:
        print(f"[ERROR] GitHub Discussions scrape: {e}")
    finally:
        driver.quit()

    return pd.DataFrame(data_rows)

# 4) VS CODE MARKETPLACE (Selenium) - with “Load More Reviews”
def scrape_vscode_marketplace(extension_url="https://marketplace.visualstudio.com/items?itemName=GitHub.copilot"):
    print("[INFO] Scraping VS Code Marketplace for more reviews...")
    data_rows = []
    service = Service(SELENIUM_DRIVER_PATH)
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get(extension_url)
        time.sleep(5)  # wait for page to load

        # Attempt to click "Load more" until no more appear (pseudo-code)
        # The actual HTML structure may differ.
        while True:
            try:
                load_more_button = driver.find_element(By.XPATH, "//button[text()='Load more reviews']")
                load_more_button.click()
                time.sleep(3)
            except:
                # No more button or an error -> break
                break

        # Now that we (hopefully) loaded more reviews, gather them
        reviews = driver.find_elements(By.XPATH, "//div[@class='review']")
        for rev in reviews:
            try:
                rating_element = rev.find_element(By.XPATH, ".//span[contains(@class, 'rating')]")
                rating = rating_element.get_attribute("aria-label")  # e.g. "5 stars"
            except:
                rating = None

            try:
                timestamp_element = rev.find_element(By.XPATH, ".//span[contains(@class, 'timestamp')]")
                timestamp = timestamp_element.text.strip()
            except:
                timestamp = None

            try:
                comment_element = rev.find_element(By.XPATH, ".//div[contains(@class, 'description')]")
                comment_text = clean_text(comment_element.text.strip())
            except:
                comment_text = "N/A"

            # Filter relevant
            if is_relevant_comment(comment_text):
                data_rows.append({
                    "Thread Title": "GitHub Copilot Extension Review",
                    "URL": extension_url,
                    "Comment": comment_text,
                    "Engagement": rating,
                    "Timestamp": timestamp,
                    "Platform": "VS Code Marketplace"
                })

    except Exception as e:
        print(f"[ERROR] VS Code Marketplace: {e}")
    finally:
        driver.quit()

    return pd.DataFrame(data_rows)

# 5) OPENAI FORUM (Selenium) - Searching + Multiple Pages
def scrape_openai_forum(forum_url="https://community.openai.com/",
                       queries=["copilot security", "gemini ai security", "code generation privacy"],
                       max_threads=10):
    print("[INFO] Scraping OpenAI Forum with searching & multiple queries...")
    data_rows = []
    service = Service(SELENIUM_DRIVER_PATH)
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get(forum_url)
        time.sleep(4)

        # Attempt to search for each query if there's a search bar
        for q in queries:
            try:
                # The forum uses Discourse, so there's usually a search button or input
                search_button = driver.find_element(By.XPATH, "//button[@class='search-btn']")
                search_button.click()
                time.sleep(1)

                # Now find the input
                search_input = driver.find_element(By.XPATH, "//input[@placeholder='Search...']")
                search_input.clear()
                search_input.send_keys(q)
                search_input.send_keys(Keys.ENTER)
                time.sleep(3)

                # TODO: Possibly iterate multiple pages if there's pagination
                threads = driver.find_elements(By.XPATH, "//a[contains(@class, 'topic-title')]")
                thread_urls = []
                for t in threads:
                    href = t.get_attribute("href")
                    if len(thread_urls) < max_threads:
                        thread_urls.append(href)

                # Visit each thread
                for url in thread_urls:
                    driver.get(url)
                    time.sleep(3)

                    try:
                        thread_title = driver.find_element(By.XPATH, "//h1").text.strip()
                    except:
                        thread_title = "N/A"

                    # Gather post elements
                    posts = driver.find_elements(By.XPATH, "//div[contains(@class, 'post')]")
                    for post in posts:
                        ctext = post.text.strip()
                        ctext = clean_text(ctext)
                        if is_relevant_comment(ctext):
                            data_rows.append({
                                "Thread Title": thread_title,
                                "URL": url,
                                "Comment": ctext,
                                "Engagement": None,
                                "Platform": "OpenAI Forum"
                            })

            except Exception as e:
                print(f"[WARNING] OpenAI Forum search '{q}': {e}")

    except Exception as e:
        print(f"[ERROR] OpenAI Forum: {e}")
    finally:
        driver.quit()

    return pd.DataFrame(data_rows)


def main():
    # 1. Reddit
    subreddits = [
        "opensource",
        "github",
        "programming",
        "artificial",  # replaced 'ArtificialIntelligence' if it's private
        "OpenAI",
    ]
    reddit_df = scrape_reddit(subreddits, SEARCH_QUERIES, limit=50)
    save_to_excel(reddit_df, "Reddit")

    # 2. Stack Overflow
    stack_df = scrape_stack_overflow(SEARCH_QUERIES, pagesize=30)
    save_to_excel(stack_df, "StackOverflow")

    # 3. GitHub Discussions
    # Example: https://github.com/github/copilot/discussions might be more relevant
    # You can also try https://github.com/orgs/community/discussions
    github_df = scrape_github_discussions(
        discussions_url="https://github.com/github/copilot/discussions",
        queries=["copilot", "security", "privacy", "gemini"],
        max_threads=20
    )
    save_to_excel(github_df, "GitHubDiscussions")

    # 4. VS Code Marketplace
    # You could also try a different extension URL if relevant (e.g. “Copilot Labs”).
    vscode_df = scrape_vscode_marketplace(
        extension_url="https://marketplace.visualstudio.com/items?itemName=GitHub.copilot"
    )
    save_to_excel(vscode_df, "VSCodeMarketplace")

    # 5. OpenAI Forum
    # We pass multiple queries. 
    openai_df = scrape_openai_forum(
        forum_url="https://community.openai.com/",
        queries=["copilot security", "gemini ai security", "code generation privacy"],
        max_threads=10
    )
    save_to_excel(openai_df, "OpenAIForum")

    print("Done! Check", OUTPUT_EXCEL_FILE)

if __name__ == "__main__":
    main()