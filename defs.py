import asyncio
import json

async def charge_resp(result):
    """
    Parses Stripe/API response and returns a simplified status without emojis.
    """
    try:
        # Convert non-string results to string
        if not isinstance(result, str):
            result = json.dumps(result)

        # Try to parse nested JSON if result is a JSON string
        try:
            inner = json.loads(result)
            # If it has a 'success' or 'status' key, reformat result
            if isinstance(inner, dict):
                if "success" in inner:
                    if inner.get("success") is True:
                        result = inner.get("data", {}).get("status", "Approved")
                    else:
                        result = inner.get("data", {}).get("status", "Declined")
                elif "status" in inner:
                    result = inner.get("status", "Declined")
        except json.JSONDecodeError:
            pass  # Not nested JSON, keep original string

        result_lower = result.lower()

        # Approved
        approved_keywords = [
            "succeeded",
            "payment method successfully added",
            "approved",
            "requires_capture"
        ]
        for kw in approved_keywords:
            if kw in result_lower:
                return "Approved"

        # CCN Live
        ccn_live_keys = [
            "incorrect_cvc",
            "security code is incorrect"
        ]
        for kw in ccn_live_keys:
            if kw in result_lower:
                return "CCN Live"

        # 3D / Auth Challenge
        auth_keys = [
            "requires_action",
            "three_d_secure_redirect",
            "card_error_authentication_required",
            "stripe_3ds2_fingerprint"
        ]
        for kw in auth_keys:
            if kw in result_lower:
                return "3D / Auth Challenge"

        # Declines / errors
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
                return message

        # fallback unknown
        return result.strip()

    except Exception as e:
        return f"Error parsing response: {str(e)}"
