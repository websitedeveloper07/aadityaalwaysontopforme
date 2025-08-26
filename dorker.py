def run_dork(query: str) -> str:

import logging
import os
import time
import socket
import requests
import subprocess
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    filters,
    MessageHandler,
)

# For Selenium / stealth: - @Mod_By_Kamal
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.common.exceptions import WebDriverException, NoSuchElementException, ElementClickInterceptedException
from selenium_stealth import stealth

# ----------------------------------------------------------------------------------
# LOGGING @Mod_By_Kamal
# ----------------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------------
# GLOBALS @Mod_By_Kamal
# ----------------------------------------------------------------------------------

BOT_TOKEN = ""
ADMIN_ID = 5248903529  # The admin's Telegram user ID - @Mod_By_Kamal
REGISTERED_USERS_FILE = "registered_users.json"

PAYMENT_GATEWAYS = [
    "paypal", "stripe", "braintree", "square", "magento", "avs", "convergepay",
    "paysimple", "oceanpayments", "eprocessing", "hipay", "worldpay", "cybersource",
    "payjunction", "authorize.net", "2checkout", "adyen", "checkout.com", "payflow",
    "payeezy", "usaepay", "creo", "squareup", "authnet", "ebizcharge", "cpay",
    "moneris", "recurly", "cardknox", "chargify", "paytrace", "hostedpayments",
    "securepay", "eway", "blackbaud", "lawpay", "clover", "cardconnect", "bluepay",
    "fluidpay", "rocketgateway", "rocketgate", "shopify", "woocommerce",
    "bigcommerce", "opencart", "prestashop", "razorpay"
]
FRONTEND_FRAMEWORKS = ["react", "angular", "vue", "svelte"]
BACKEND_FRAMEWORKS = [
    "wordpress", "laravel", "django", "node.js", "express", "ruby on rails",
    "flask", "php", "asp.net", "spring"
]
DESIGN_LIBRARIES = ["bootstrap", "tailwind", "bulma", "foundation", "materialize"]

# ----------------------------------------------------------------------------------
# CHROMEDRIVER SETUP (OPTIONAL AUTO-INSTALL) => @Mod_By_Kamal
# ----------------------------------------------------------------------------------

def setup_chrome_driver():
    """
    Attempt to install ChromeDriver (131.0.6778.108) on Ubuntu.
    Comment out if you prefer to manage ChromeDriver manually.
    """
    try:
        logger.info("Setting up ChromeDriver automatically...")
        subprocess.run(['apt-get', 'update'], check=True)
        subprocess.run(['apt-get', 'install', '-y', 'wget', 'unzip'], check=True)

        chromedriver_url = (
            "https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/"
            "131.0.6778.108/linux64/chromedriver-linux64.zip"
        )
        subprocess.run(['wget', chromedriver_url, '-O', 'chromedriver_linux64.zip'], check=True)
        subprocess.run(['unzip', '-o', 'chromedriver_linux64.zip'], check=True)
        subprocess.run(['mv', 'chromedriver-linux64/chromedriver', '/usr/local/bin/chromedriver'], check=True)
        subprocess.run(['chmod', '+x', '/usr/local/bin/chromedriver'], check=True)

        # Cleanup @Mod_By_Kamal
        subprocess.run(['rm', '-rf', 'chromedriver_linux64.zip', 'chromedriver-linux64'], check=True)
        logger.info("ChromeDriver setup completed successfully.")
    except Exception as e:
        logger.error(f"Error setting up ChromeDriver: {e}")
        # If it fails, you can comment out `raise` if you want to try using a pre-installed driver => @Mod_By_Kamal
        raise

# ----------------------------------------------------------------------------------
# JSON UTILS => @Mod_By_Kamal
# ----------------------------------------------------------------------------------

def load_registered_users():
    """
    Load the list of registered user IDs from JSON.
    Returns a Python list of user IDs.
    """
    if not os.path.exists(REGISTERED_USERS_FILE):
        return []
    try:
        with open(REGISTERED_USERS_FILE, "r") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            else:
                return []
    except:
        return []

def save_registered_users(user_ids):
    """
    Save the list of registered user IDs to JSON.
    """
    with open(REGISTERED_USERS_FILE, "w") as f:
        json.dump(user_ids, f)

def is_user_registered(user_id):
    """Check if the given user_id is in the registered list."""
    registered = load_registered_users()
    return (user_id in registered)

def register_user(user_id):
    """Add the user_id to the JSON file if not already present."""
    registered = load_registered_users()
    if user_id not in registered:
        registered.append(user_id)
        save_registered_users(registered)

# ----------------------------------------------------------------------------------
# CREATE A NEW DRIVER FOR EACH PAGE => @Mod_By_Kamal
# ----------------------------------------------------------------------------------

def create_local_driver():
    """
    Create and return a new headless Chrome Selenium driver with stealth settings.
    """
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--disable-dev-tools")
    chrome_options.add_argument("--disable-software-rasterizer")

    # Make the language explicitly English, helps reduce local disclaimers => @Mod_By_Kamal
    chrome_options.add_argument("--lang=en-US")

    # Prevent some automated detection => @Mod_By_Kamal
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    # Make sure Chrome is installed at this path: => @Mod_By_Kamal
    chrome_options.binary_location = "/usr/bin/google-chrome"

    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = ChromeService(executable_path='/usr/local/bin/chromedriver')
    local_driver = webdriver.Chrome(service=service, options=chrome_options)

    # Apply stealth settings => @Mod_By_Kamal
    stealth(
        local_driver,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/110.0.5481.105 Safari/537.36"
        ),
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True,
    )

    local_driver.set_page_load_timeout(20)
    return local_driver

def click_google_consent_if_needed(driver, wait_seconds=2):
    """
    Attempts to click 'I agree' or 'Accept all' on Google's consent screen.
    Sometimes the ID is #L2AGLb or #W0wltc. If not found, it does nothing.
    """
    time.sleep(wait_seconds)
    possible_selectors = [
        "button#L2AGLb",        # Common "I Agree" button => @Mod_By_Kamal
        "button#W0wltc",        # Another variant => @Mod_By_Kamal
        "div[role='none'] button:nth-of-type(2)",  # fallback pattern => @Mod_By_Kamal
    ]
    for sel in possible_selectors:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, sel)
            btn.click()
            logger.info(f"Clicked Google consent button: {sel}")
            time.sleep(1.5)  # Let the page reload => @Mod_By_Kamal
            return
        except (NoSuchElementException, ElementClickInterceptedException):
            pass

# ----------------------------------------------------------------------------------
# GOOGLE SEARCH WITH PAGINATION (UPDATED SELECTOR + CONSENT HANDLER) => @Mod_By_Kamal
# ----------------------------------------------------------------------------------

def google_search(query: str, limit: int = 10, offset: int = 0):
    """
    Paginate Google search in increments of 100 results per page.
    Return up to 'limit' unique result URLs (starting from 'offset').

    We also try to handle Google's cookie consent screen by clicking the "I agree" button.
    We'll use the updated selector: <div.yuRUbf> <a> for links.

    Additionally, we append `hl=en&gl=us` to help standardize the interface.
    """
    all_links = []
    seen = set()

    pages_needed = (limit // 100) + (1 if limit % 100 != 0 else 0)
    max_pages = min(pages_needed, 10)

    logger.info(f"[google_search] Query='{query}', limit={limit}, offset={offset}")
    logger.info(f"Starting multi-page scrape: need {limit} results, up to {max_pages} pages")

    for page_index in range(max_pages):
        start_val = offset + (page_index * 100)
        driver = create_local_driver()
        try:
            # Add hl=en & gl=us to standardize => @Mod_By_Kamal
            url = (
                f"https://www.google.com/search?q={query}"
                f"&num=100"
                f"&start={start_val}"
                f"&hl=en&gl=us"
            )
            logger.info(f"Navigating to: {url}")
            driver.get(url)

            # Attempt to click "I agree" if it shows up => @Mod_By_Kamal
            click_google_consent_if_needed(driver)

            time.sleep(2)  # Let the page load a bit => @Mod_By_Kamal

            a_elements = driver.find_elements(By.CSS_SELECTOR, "div.yuRUbf > a")
            if not a_elements:
                logger.info(f"No results found on page_index={page_index} => stopping.")
                break

            page_links = []
            for a_tag in a_elements:
                href = a_tag.get_attribute("href")
                if href and href.startswith("http"):
                    page_links.append(href)

            for link in page_links:
                if link not in seen:
                    seen.add(link)
                    all_links.append(link)
                if len(all_links) >= limit:
                    break

            logger.info(
                f"Found {len(page_links)} links on this page. "
                f"Accumulated so far: {len(all_links)}"
            )

            if len(all_links) >= limit:
                break

        except WebDriverException as e:
            logger.error(f"Error scraping Google on page {page_index}: {e}")
            break
        finally:
            driver.quit()

        time.sleep(3)  # Avoid hammering Google => @Mod_By_Kamal

    return all_links[:limit]

# ----------------------------------------------------------------------------------
# DETECT TECH STACK
# ----------------------------------------------------------------------------------

def detect_tech_stack(html_text: str):
    txt_lower = html_text.lower()

    front_found = []
    for fw in FRONTEND_FRAMEWORKS:
        if fw in txt_lower:
            front_found.append(fw)

    back_found = []
    for bw in BACKEND_FRAMEWORKS:
        if bw in txt_lower:
            back_found.append(bw)

    design_found = []
    for ds in DESIGN_LIBRARIES:
        if ds in txt_lower:
            design_found.append(ds)

    return {
        "front_end": ", ".join(set(front_found)) if front_found else "None",
        "back_end": ", ".join(set(back_found)) if back_found else "None",
        "design": ", ".join(set(design_found)) if design_found else "None",
    }

# ----------------------------------------------------------------------------------
# SITE DETAILS CHECK => @Mod_By_Kamal
# ----------------------------------------------------------------------------------

def check_site_details(url: str):
    details = {
        "url": url,
        "dns": "N/A",
        "ssl": "N/A",
        "status_code": 0,
        "cloudflare": "NO",
        "captcha": "NO",
        "gateways": "",
        "graphql": "NO",
        "language": "N/A",
        "front_end": "None",
        "back_end": "None",
        "design": "None",
    }

    domain = extract_domain(url)
    if domain:
        try:
            socket.gethostbyname(domain)
            details["dns"] = "resolvable"
        except:
            details["dns"] = "unresolvable"

    try:
        resp = requests.get(url, timeout=10, verify=True)
        details["ssl"] = "valid"
        details["status_code"] = resp.status_code
        txt_lower = resp.text.lower()

        # Cloudflare
        if any("cloudflare" in k.lower() for k in resp.headers.keys()) or \
           any("cloudflare" in v.lower() for v in resp.headers.values()):
            details["cloudflare"] = "YES"
        # Captcha
        if "captcha" in txt_lower or "recaptcha" in txt_lower:
            details["captcha"] = "YES"
        # GraphQL
        if "graphql" in txt_lower:
            details["graphql"] = "YES"
        # Language
        lang = extract_language(resp.text)
        if lang:
            details["language"] = lang

        # Payment Gateways
        found_gw = []
        for gw in PAYMENT_GATEWAYS:
            if gw.lower() in txt_lower:
                found_gw.append(gw)
        if found_gw:
            details["gateways"] = ", ".join(set(found_gw))
        else:
            details["gateways"] = "None"

        # Tech stack
        stack = detect_tech_stack(resp.text)
        details["front_end"] = stack["front_end"]
        details["back_end"] = stack["back_end"]
        details["design"] = stack["design"]

    except requests.exceptions.SSLError:
        # SSL invalid
        details["ssl"] = "invalid"
        try:
            # Try again with verify=False
            resp = requests.get(url, timeout=10, verify=False)
            details["status_code"] = resp.status_code
            txt_lower = resp.text.lower()

            if any("cloudflare" in k.lower() for k in resp.headers.keys()) or \
               any("cloudflare" in v.lower() for v in resp.headers.values()):
                details["cloudflare"] = "YES"
            if "captcha" in txt_lower or "recaptcha" in txt_lower:
                details["captcha"] = "YES"
            if "graphql" in txt_lower:
                details["graphql"] = "YES"
            lang = extract_language(resp.text)
            if lang:
                details["language"] = lang

            found_gw = []
            for gw in PAYMENT_GATEWAYS:
                if gw.lower() in txt_lower:
                    found_gw.append(gw)
            if found_gw:
                details["gateways"] = ", ".join(set(found_gw))
            else:
                details["gateways"] = "None"

            stack = detect_tech_stack(resp.text)
            details["front_end"] = stack["front_end"]
            details["back_end"] = stack["back_end"]
            details["design"] = stack["design"]
        except:
            pass

    except Exception as e:
        logger.error(f"Error checking {url}: {e}")

    # Make captcha/cloudflare more readable => @Mod_By_Kamal
    if details["captcha"] == "YES":
        details["captcha"] = "✅ YES"
    else:
        details["captcha"] = "🔥 NO"

    if details["cloudflare"] == "YES":
        details["cloudflare"] = "✅ YES"
    else:
        details["cloudflare"] = "🔥 NO"

    return details

def extract_domain(url: str):
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.netloc:
        return parsed.netloc
    return None

def extract_language(html: str):
    import re
    match = re.search(r"<html[^>]*\slang=['\"]([^'\"]+)['\"]", html, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

# ----------------------------------------------------------------------------------
# ASYNC WRAPPERS FOR CONCURRENCY => @Mod_By_Kamal
# ----------------------------------------------------------------------------------

executor = ThreadPoolExecutor(max_workers=5)

async def async_google_search(query: str, limit: int, offset: int):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        executor, google_search, query, limit, offset
    )

async def async_check_site_details(url: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        executor, check_site_details, url
    )

# ----------------------------------------------------------------------------------
# BOT COMMAND HANDLERS => @Mod_By_Kamal
# ----------------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_user_registered(user_id):
        await update.message.reply_text(
            "You are not registered yet. Please type /register first."
        )
    else:
        await update.message.reply_text(
            "Welcome back! Type /cmds to see how to use this bot."
        )

async def cmd_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_user_registered(user_id):
        await update.message.reply_text("You are already registered!")
    else:
        register_user(user_id)
        await update.message.reply_text(
            "You have been registered successfully! Now you can use /cmds."
        )

async def cmd_cmds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_registered(user_id):
        await update.message.reply_text("You must /register before using any commands.")
        return

    text = (
        "Commands:\n"
        "  /dork <query> <count>\n"
        "    Example:\n"
        '      /dork intext:"shoes"+"powered by shopify"+"2025" 100\n'
        "    This will dork 100 sites for that query.\n\n"
        "For Admins Only:\n"
        "  /bord <message>\n"
        "    Broadcast the message to all registered users.\n"
    )
    await update.message.reply_text(text)

async def cmd_dork(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Parse the query by splitting from the right so that the
    last space-separated token is the count. Everything before is the query.
    """
    user_id = update.effective_user.id
    if not is_user_registered(user_id):
        await update.message.reply_text("You must /register before using /dork.")
        return

    # Example usage:
    # /dork intext:"shoes"+"powered by shopify"+"2025" 100
    raw_text = update.message.text.strip()

    # Remove the leading command "/dork"
    just_args = raw_text[len("/dork"):].strip()
    if not just_args:
        await update.message.reply_text("Usage: /dork <query> <count>")
        return

    # Right-split once to separate the query from the count
    if " " not in just_args:
        await update.message.reply_text("Usage: /dork <query> <count>")
        return

    query_part, count_str = just_args.rsplit(" ", 1)
    query_part = query_part.strip()
    count_str = count_str.strip()

    # Validate the count
    if not count_str.isdigit():
        await update.message.reply_text("Please provide a valid integer for <count>.")
        return
    # @Mod_By_Kamal

    limit = int(count_str)
    if limit < 1:
        limit = 1
    elif limit > 300:
        limit = 300

    await update.message.reply_text(
        f"Searching for up to {limit} results for:\n{query_part}\nPlease wait..."
    )
    # @Mod_By_Kamal

    try:
        results = await async_google_search(query_part, limit, 0)
    except Exception as e:
        logger.error(f"Error scraping Google: {e}")
        await update.message.reply_text(f"Error scraping Google: {e}")
        return
    # @Mod_By_Kamal

    if not results:
        await update.message.reply_text("No results found or something went wrong (possible Google block?).")
        return
    # @Mod_By_Kamal

    # Check site details concurrently
    details_list = []
    for url in results:
        d = await async_check_site_details(url)
        details_list.append(d)

    # Prepare a text file
    timestamp = int(time.time())
    filename = f"results_{timestamp}.txt"
    # @Mod_By_Kamal

    lines = []
    for d in details_list:
        lines.append(
            f"URL: {d['url']}\n"
            f"DNS: {d['dns']}\n"
            f"SSL: {d['ssl']}\n"
            f"Status: {d['status_code']}\n"
            f"Cloudflare: {d['cloudflare']}\n"
            f"Captcha: {d['captcha']}\n"
            f"Gateways: {d['gateways']}\n"
            f"GraphQL: {d['graphql']}\n"
            f"Language: {d['language']}\n"
            f"Front-end: {d['front_end']}\n"
            f"Back-end: {d['back_end']}\n"
            f"Design: {d['design']}\n"
            "\n"
            "⚡ @Mod_By_Kamal ⚡\n"
            "🌩️ Bot: @ManualDorkerBot 🌩️\n"
            "----------------------------------------\n"
        )
    # @Mod_By_Kamal

    with open(filename, "w", encoding="utf-8") as f:
        f.writelines(lines)

    # Send the file
    # @Mod_By_Kamal
    try:
        with open(filename, "rb") as file_data:
            doc = InputFile(file_data, filename=filename)
            await update.message.reply_document(
                document=doc,
                caption="Here are your results."
            )
    except Exception as e:
        logger.error(f"Error sending file: {e}")
        await update.message.reply_text(f"Error sending file: {e}")

    # Clean up the file @Mod_By_Kamal
    try:
        os.remove(filename)
    except Exception as e:
        logger.error(f"Error deleting file {filename}: {e}")

async def cmd_bord(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Only admin can broadcast @Mod_By_Kamal
    if user_id != ADMIN_ID:
        await update.message.reply_text("You are not authorized to use /bord.")
        return

    text = update.message.text.strip()
    parts = text.split(" ", maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("Usage: /bord <message>")
        return

    message_to_broadcast = parts[1].strip()

    registered_users = load_registered_users()
    count_sent = 0
    for uid in registered_users:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"[Broadcast]\n{message_to_broadcast}"
            )
            count_sent += 1
            await asyncio.sleep(0.2)
        except Exception as e:
            logger.error(f"Could not send broadcast to {uid}: {e}")

    await update.message.reply_text(f"Broadcast sent to {count_sent} registered users.")

    return f"Results for {query}..."
