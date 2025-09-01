import aiohttp
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ---------------------------
# BIN Cache & Rate Limiting
# ---------------------------
bin_cache = {}  # {bin_number: {"data": bin_data, "timestamp": datetime}}
BIN_LOCK = asyncio.Lock()
LAST_BIN_CALL = 0
CACHE_EXPIRY = timedelta(hours=24)  # Cache expiry time

# ---------------------------
# Fetch BIN Details
# ---------------------------
async def get_bin_details(bin_number: str, retries: int = 3) -> dict:
    """
    Fetch BIN details from binlist.net API.
    Returns a dictionary with all relevant fields.
    Uses cache to avoid excessive API calls.
    """
    now_time = datetime.utcnow()

    # ---------------------------
    # Use cache if available and not expired
    # ---------------------------
    if bin_number in bin_cache:
        cached = bin_cache[bin_number]
        if now_time - cached["timestamp"] < CACHE_EXPIRY:
            return cached["data"]

    # Default BIN data structure
    bin_data = {
        "scheme": "N/A",
        "type": "N/A",
        "brand": "N/A",
        "bank": "N/A",
        "country_name": "N/A",
        "country_emoji": "",
        "country_alpha2": "N/A",
        "country_numeric": "N/A",
        "currency": "N/A",
        "latitude": "N/A",
        "longitude": "N/A",
        "number_length": "N/A",
        "number_luhn": "N/A",
    }

    url = f"https://lookup.binlist.net/{bin_number}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    # ---------------------------
    # Rate limiting: 1 request/sec
    # ---------------------------
    global LAST_BIN_CALL
    async with BIN_LOCK:
        now = asyncio.get_event_loop().time()
        if now - LAST_BIN_CALL < 1.0:
            await asyncio.sleep(1.0 - (now - LAST_BIN_CALL))
        LAST_BIN_CALL = asyncio.get_event_loop().time()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=7) as resp:
                    text = await resp.text()

                    if resp.status == 200:
                        data = await resp.json(content_type=None)

                        # ---------------------------
                        # Fill bin_data dictionary
                        # ---------------------------
                        bin_data["scheme"] = str(data.get("scheme", "N/A")).title()
                        bin_data["type"] = str(data.get("type", "N/A")).title()
                        bin_data["brand"] = str(data.get("brand", "N/A")).title()

                        bank = data.get("bank", {})
                        bin_data["bank"] = str(bank.get("name", "N/A")).title()

                        country = data.get("country", {})
                        bin_data["country_name"] = country.get("name", "N/A")
                        bin_data["country_emoji"] = country.get("emoji", "")
                        bin_data["country_alpha2"] = country.get("alpha2", "N/A")
                        bin_data["country_numeric"] = country.get("numeric", "N/A")
                        bin_data["currency"] = country.get("currency", "N/A")
                        bin_data["latitude"] = str(country.get("latitude", "N/A"))
                        bin_data["longitude"] = str(country.get("longitude", "N/A"))

                        number = data.get("number", {})
                        bin_data["number_length"] = str(number.get("length", "N/A"))
                        bin_data["number_luhn"] = str(number.get("luhn", "N/A"))

                        # ---------------------------
                        # Save to cache
                        # ---------------------------
                        bin_cache[bin_number] = {"data": bin_data, "timestamp": now_time}
                        return bin_data

                    elif resp.status == 429:
                        logger.warning(f"BIN API rate limited for {bin_number} → {text}")
                        if bin_number in bin_cache:
                            # Return cached value if available
                            logger.info(f"Returning cached BIN info for {bin_number} due to 429")
                            return bin_cache[bin_number]["data"]
                        elif retries > 0:
                            await asyncio.sleep(3)
                            return await get_bin_details(bin_number, retries=retries-1)
                        else:
                            logger.warning(f"Max retries reached for {bin_number}")
                            return bin_data
                    else:
                        logger.warning(f"BIN API returned {resp.status} for {bin_number} → {text}")

        except Exception as e:
            logger.warning(f"BIN API call failed for {bin_number}: {type(e).__name__} → {e}")
            if bin_number in bin_cache:
                return bin_cache[bin_number]["data"]

    return bin_data
