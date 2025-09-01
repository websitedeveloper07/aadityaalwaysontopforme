import aiohttp

HANDYAPI_URL = "https://data.handyapi.com/bin/{}"

async def get_bin_info(bin_number: str) -> dict:
    """
    Fetch BIN data using HandyAPI (no API key required).
    """
    if not bin_number.isdigit() or len(bin_number) < 6:
        return {"error": "Invalid BIN. Must be at least 6 digits."}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(HANDYAPI_URL.format(bin_number)) as resp:
                if resp.status != 200:
                    return {"error": f"API request failed (status {resp.status})"}

                data = await resp.json()

                if data.get("Status") != "SUCCESS":
                    return {"error": "BIN not found or API returned failure."}

                # Build clean dictionary
                return {
                    "bin": bin_number,
                    "scheme": data.get("Scheme", "N/A"),
                    "type": data.get("Type", "N/A"),
                    "brand": data.get("CardTier", "N/A"),
                    "bank": data.get("Issuer", "N/A"),
                    "country": data.get("Country", {}).get("Name", "N/A"),
                    "country_alpha2": data.get("Country", {}).get("A2", "N/A"),
                    "country_alpha3": data.get("Country", {}).get("A3", "N/A"),
                    "country_numeric": data.get("Country", {}).get("N3", "N/A"),
                    "isd_code": data.get("Country", {}).get("ISD", "N/A"),
                    "continent": data.get("Country", {}).get("Cont", "N/A"),
                    "luhn": "✅ Valid" if data.get("Luhn") else "❌ Invalid",
                }
        except Exception as e:
            return {"error": f"Exception: {e}"}
