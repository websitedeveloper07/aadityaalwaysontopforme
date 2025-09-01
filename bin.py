import aiohttp

BIN_API_URL = "https://lookup.binlist.net/{}"

async def get_bin_info(bin_number: str) -> dict:
    """
    Fetch BIN information from the Binlist API.

    Args:
        bin_number (str): First 6–8 digits of a card.

    Returns:
        dict: Formatted BIN details or error message.
    """
    if not bin_number.isdigit() or len(bin_number) < 6:
        return {"error": "Invalid BIN. It must be at least 6 digits."}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(BIN_API_URL.format(bin_number)) as resp:
                if resp.status != 200:
                    return {"error": f"API request failed (status {resp.status})"}

                data = await resp.json()

                # Format clean response
                return {
                    "bin": bin_number,
                    "scheme": data.get("scheme", "N/A"),
                    "type": data.get("type", "N/A"),
                    "brand": data.get("brand", "N/A"),
                    "bank": data.get("bank", {}).get("name", "N/A"),
                    "country": data.get("country", {}).get("name", "N/A"),
                    "country_emoji": data.get("country", {}).get("emoji", "N/A"),
                    "currency": data.get("country", {}).get("currency", "N/A"),
                }
        except Exception as e:
            return {"error": f"Exception: {str(e)}"}
