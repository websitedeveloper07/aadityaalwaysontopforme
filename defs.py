import asyncio

async def charge_resp(result):
    """
    Parses Stripe/API response and returns concise, meaningful messages.
    Categories:
    - Approved ✅
    - CCN Live ❎
    - 3D Challenge ❎
    - Declines / Errors ❌
    """

    try:
        if not isinstance(result, str):
            result = str(result).lower()
        else:
            result = result.lower()

        # -------------------------
        # Approved
        # -------------------------
        approved_keywords = [
            '{"status":"succeeded"',
            '"status":"suceeded"',
            "payment method successfully added"
        ]
        if any(k in result for k in approved_keywords):
            return "Approved ✅"

        # -------------------------
        # CCN Live
        # -------------------------
        ccn_live_keys = [
            "incorrect_cvc",
            "security code is incorrect",
            "your card's security code is incorrect"
        ]
        if any(k in result for k in ccn_live_keys):
            return "CCN Live ❎"

        # -------------------------
        # 3D / Auth Challenge
        # -------------------------
        auth_keys = [
            "three_d_secure_redirect",
            "card_error_authentication_required",
            "stripe_3ds2_fingerprint",
            "wcpay-confirm-pi:"
        ]
        if any(k in result for k in auth_keys):
            return "3D Challenge ❎"

        # -------------------------
        # CVV Live
        # -------------------------
        if '"cvc_check": "pass"' in result:
            return "CVV Live ❎"

        # -------------------------
        # Declines / Errors
        # -------------------------
        decline_map = {
            "insufficient funds": "Insufficient Funds ❌",
            "transaction_not_allowed": "Card Doesn't Support Purchase ❌",
            "does not support this type of purchase": "Card Doesn't Support Purchase ❌",
            "generic_decline": "Card Declined ❌",
            "your card was declined": "Card Declined ❌",
            "do not honor": "Do Not Honor ❌",
            "fraudulent": "Fraudulent ❌",
            "setup_intent_authentication_failure": "Auth Failure ❌",
            "invalid cvc": "Invalid CVC ❌",
            "stolen card": "Stolen Card ❌",
            "lost_card": "Lost Card ❌",
            "pickup_card": "Pickup Card ❌",
            "pickup": "Pickup Card ❌",
            "restricted_card": "Restricted Card ❌",
            "card velocity exceeded": "Card Velocity Limit ❌",
            "incorrect_number": "Incorrect Card Number ❌",
            "your card number is incorrect": "Incorrect Card Number ❌",
            "expired_card": "Expired Card ❌",
            "your card has expired": "Expired Card ❌",
            "card is not supported": "Card Not Supported ❌",
            "invalid account": "Dead Card ❌",
            "invalid api key": "API Key Error ❌",
            "testmode_charges_only": "Test Mode Only ❌",
            "api_key_expired": "API Key Expired ❌",
            "please update bearer token": "Token Expired ❌",
            "your account cannot currently make live charges": "Account Cannot Charge ❌",
            "intent_confirmation_challenge": "Captcha ❌",
            "Your card's expiration year is invalid.": "Expiration Year Invalid ❌",
            "invalid_expiry_month": "Expiration Month Invalid ❌",
            "Your card's expiration month is invalid.": "Expiration Month Invalid ❌"
        }

        for key, message in decline_map.items():
            if key in result:
                return message

        # -------------------------
        # Fallback
        # -------------------------
        return "Declined ❌"

    except Exception:
        return "Error ❌"
