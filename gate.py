# gate.py
import requests
import re
import os
import threading
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

PAYMENT_GATEWAYS = [
    "PayPal", "Stripe", "Braintree", "Square", "magento", "Convergepay",
    "PaySimple", "oceanpayments", "eProcessing", "hipay", "worldpay", "cybersourse",
    "payjunction", "Authorize.Net", "2Checkout", "Adyen", "Checkout.com", "PayFlow",
    "Payeezy", "usaepay", "creo", "SquareUp", "Authnet", "ebizcharge", "cpay",
    "Moneris", "recurly", "cardknox", "payeezy", "matt sorra", "ebizcharge",
    "payflow", "Chargify", "payflow", "Paytrace", "hostedpayments", "securepay",
    "eWay", "blackbaud", "LawPay", "clover", "cardconnect", "bluepay", "fluidpay",
    "Worldpay", "Ebiz", "chasepaymentech", "cardknox", "2checkout", "Auruspay",
    "sagepayments", "paycomet", "geomerchant", "realexpayments",
    "Rocketgateway", "Rocketgate", "Rocket", "Auth.net", "Authnet", "rocketgate.com",
    "Shopify", "WooCommerce", "BigCommerce", "Magento Payments",
    "OpenCart", "PrestaShop", "Razorpay"
]

# Security indicators
SECURITY_INDICATORS = {
    'captcha': ['captcha', 'protected by recaptcha', "i'm not a robot", 'recaptcha/api.js'],
    'cloudflare': ['cloudflare', 'cdnjs.cloudflare.com', 'challenges.cloudflare.com']
}



def normalize_url(url):
    if not re.match(r'^https?://', url, re.I):
        url = 'http://' + url
    return url


def find_payment_gateways(content):
    detected = set()
    for gateway in PAYMENT_GATEWAYS:
        if re.search(r'\b' + re.escape(gateway) + r'\b', content, re.I):
            detected.add(gateway)
    return list(detected)


def check_security(content):
    captcha_present = any(re.search(ind, content, re.I) for ind in SECURITY_INDICATORS['captcha'])
    cloudflare_present = any(re.search(ind, content, re.I) for ind in SECURITY_INDICATORS['cloudflare'])
    return captcha_present, cloudflare_present


def fetch_content(url, session):
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException:
        return None


def process_url(url, session, lock):
    normalized = normalize_url(url)
    content = fetch_content(normalized, session)
    if content is None:
        return None
    gateways = find_payment_gateways(content)
    captcha, cloudflare = check_security(content)

    if not gateways:
        return None

    if not captcha and not cloudflare:
        return {
            'url': normalized,
            'gateways': gateways,
            'captcha': captcha,
            'cloudflare': cloudflare
        }
    return None


def run_gateway_scan(urls: list[str]):
    """Run scan on list of URLs and return results list."""
    results = []

    lock = threading.Lock()
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    max_threads = min(32, os.cpu_count() + 4)

    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [executor.submit(process_url, url, session, lock) for url in urls]
        for future in as_completed(futures):
            entry = future.result()
            if entry:
                results.append(entry)

    return results
