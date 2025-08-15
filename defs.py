import asyncio
import json

async def charge_resp(result):
    """
    Parses Stripe response and returns a simplified message for API.
    Categories:
    - Approved ✅
    - CCN Live ✅
    - 3D / Auth Challenge ✅
    - Declines/Errors ❌
    """
    try:
        # Ensure result is string
        if not isinstance(result, str):
            result = json.dumps(result)

        result_lower = result.lower()

        # Helper to append emoji only if missing
        def append_emoji(msg: str, emoji: str):
            msg = msg.strip()
            return msg if emoji in msg else f"{msg} {emoji}"

        # -------------------------
        # Approved responses
        # -------------------------
        approved_keywords = [
            '"status":"succeeded"',
            '"status":"suceeded"',
            "payment method successfully added"
        ]
        for keyword in approved_keywords:
            if keyword in result_lower:
                return append_emoji("Approved", "✅")

        # -------------------------
        # CCN Live responses
        # -------------------------
        ccn_live_keys = [
            "incorrect_cvc",
            "security code is incorrect"
        ]
        for key in ccn_live_keys:
            if key in result_lower:
                return append_emoji("CCN Live", "✅")

        # -------------------------
        # 3D / Authentication Challenge
        # -------------------------
        auth_keys = [
            "three_d_secure_redirect",
            "card_error_authentication_required",
            "stripe_3ds2_fingerprint"
        ]
        for key in auth_keys:
            if key in result_lower:
                return append_emoji("3D / Auth Challenge", "✅")

        # -------------------------
        # Declines / Errors
        # -------------------------
        decline_map = {
            "insufficient funds": "Insufficient Funds",
            "transaction_not_allowed": "Card Doesn't Support Purchase",
            "does not support this type of purchase": "Card Doesn't Support Purchase",
            "expired_card": "Expired Card",
            "your card has expired": "Expired Card",
            "stolen_card": "Stolen Card",
            "lost_card": "Lost Card",
            "pickup_card": "Pickup Card",
            "incorrect_number": "Incorrect Card Number",
            "your card number is incorrect": "Incorrect Card Number",
            "invalid_cvc": "Invalid CVC",
            "generic_decline": "Card Declined",
            "your card was declined": "Card Declined",
            "do not honor": "Card Declined",
            "fraudulent": "Fraudulent",
            "setup_intent_authentication_failure": "Authentication Failure",
            "invalid account": "Dead Card",
            "invalid api key": "Stripe API Key Error",
            "testmode_charges_only": "Stripe API Key Error",
            "api_key_expired": "Stripe API Key Error",
            "please update bearer token": "Token Expired Admin Notified",
            "pickup": "Pickup Card",
            "restricted_card": "Restricted Card",
            "card velocity exceeded": "Card Velocity Limit"
        }

        for key, message in decline_map.items():
            if key in result_lower:
                return append_emoji(message, "❌")

        # -------------------------
        # Fallback: Unknown response
        # -------------------------
        return append_emoji(result, "❌")

    except Exception as e:
        return append_emoji(f"Error parsing response: {str(e)}", "❌")
