import logging
import os
import time
import socket
import requests
import subprocess
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.common.exceptions import WebDriverException, NoSuchElementException, ElementClickInterceptedException
from selenium_stealth import stealth

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Payment + tech stack lists
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

# ------------------------
# CHROMEDRIVER SETUP
# ------------------------
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

# ------------------------
# GOOGLE SEARCH
# ------------------------
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

from selenium import webdriver
from selenium.webdriver.chrome.service import Service

chrome_path = "/usr/bin/chromium-browser"
driver_path = "/usr/bin/chromedriver"

options = webdriver.ChromeOptions()
options.binary_location = chrome_path
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

service = Service(driver_path)
driver = webdriver.Chrome(service=service, options=options)


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


# ------------------------
# ASYNC WRAPPERS
# ------------------------
executor = ThreadPoolExecutor(max_workers=5)

async def async_google_search(query: str, limit: int, offset: int):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, google_search, query, limit, offset)

async def async_check_site_details(url: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, check_site_details, url)
