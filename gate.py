import requests
import re
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------
# Expanded Payment Gateways
# ---------------------------
PAYMENT_GATEWAYS = [
    # Major Global & Popular Gateways
    "PayPal", "Stripe", "Braintree", "Square", "Cybersource", "lemon-squeezy",
    "Authorize.Net", "2Checkout", "Adyen", "Worldpay", "SagePay",
    "Checkout.com", "Bolt", "Eway", "PayFlow", "Payeezy",
    "Paddle", "Mollie", "Viva Wallet", "Rocketgateway", "Rocketgate",
    "Rocket", "Auth.net", "Authnet", "rocketgate.com", "Recurly",

    # E-commerce Platforms
    "Shopify", "WooCommerce", "BigCommerce", "Magento", "Magento Payments",
    "OpenCart", "PrestaShop", "3DCart", "Ecwid", "Shift4Shop",
    "Shopware", "VirtueMart", "CS-Cart", "X-Cart", "LemonStand",

    # Additional Payment Solutions
    "AVS", "Convergepay", "PaySimple", "oceanpayments", "eProcessing",
    "hipay", "cybersourse", "payjunction", "usaepay", "creo",
    "SquareUp", "ebizcharge", "cpay", "Moneris", "cardknox",
    "matt sorra", "Chargify", "Paytrace", "hostedpayments", "securepay",
    "blackbaud", "LawPay", "clover", "cardconnect", "bluepay",
    "fluidpay", "Ebiz", "chasepaymentech", "Auruspay", "sagepayments",
    "paycomet", "geomerchant", "realexpayments", "Razorpay",

    # Digital Wallets & Payment Apps
    "Apple Pay", "Google Pay", "Samsung Pay", "Venmo", "Cash App",
    "Revolut", "Zelle", "Alipay", "WeChat Pay", "PayPay", "Line Pay",
    "Skrill", "Neteller", "WebMoney", "Payoneer", "Paysafe",
    "Payeer", "GrabPay", "PayMaya", "MoMo", "TrueMoney",
    "Touch n Go", "GoPay", "Dana", "JKOPay", "EasyPaisa",

    # Regional & Country Specific
    "Paytm", "UPI", "PayU", "CCAvenue",
    "Mercado Pago", "PagSeguro", "Yandex.Checkout", "PayFort", "MyFatoorah",
    "Kushki", "DLocal", "RuPay", "BharatPe", "Midtrans", "MOLPay",
    "iPay88", "KakaoPay", "Toss Payments", "NaverPay", "OVO", "GCash",
    "Bizum", "Culqi", "Pagar.me", "Rapyd", "PayKun", "Instamojo",
    "PhonePe", "BharatQR", "Freecharge", "Mobikwik", "Atom", "BillDesk",
    "Citrus Pay", "RazorpayX", "Cashfree", "PayUbiz", "EBS",

    # Buy Now Pay Later
    "Klarna", "Affirm", "Afterpay", "Zip", "Sezzle",
    "Splitit", "Perpay", "Quadpay", "Laybuy", "Openpay",
    "Atome", "Cashalo", "Hoolah", "Pine Labs", "ChargeAfter",

    # Cryptocurrency
    "BitPay", "Coinbase Commerce", "CoinGate", "CoinPayments", "Crypto.com Pay",
    "BTCPay Server", "NOWPayments", "OpenNode", "Utrust", "MoonPay",
    "Binance Pay", "CoinsPaid", "BitGo", "Flexa", "Circle",

    # European Payment Methods
    "iDEAL", "Giropay", "Sofort", "Bancontact", "Przelewy24",
    "EPS", "Multibanco", "Trustly", "PPRO", "EcoPayz",

    # Enterprise Solutions
    "ACI Worldwide", "Bank of America Merchant Services",
    "JP Morgan Payment Services", "Wells Fargo Payment Solutions",
    "Deutsche Bank Payments", "Barclaycard", "American Express Payment Gateway",
    "Discover Network", "UnionPay", "JCB Payment Gateway",

    # New Payment Technologies
    "Plaid", "Stripe Terminal", "Square Terminal", "Adyen Terminal",
    "Toast POS", "Lightspeed Payments", "Poynt", "PAX",
    "SumUp", "iZettle", "Tyro", "Vend", "ShopKeep", "Revel",

    # Extra
    "HiPay", "Dotpay", "PayBox", "PayStack", "Flutterwave",
    "Opayo", "MultiSafepay", "PayXpert", "Bambora", "RedSys",
    "NPCI", "JazzCash", "Blik", "PagBank", "VibePay", "Mode",
    "Primer", "TrueLayer", "GoCardless", "Modulr", "Currencycloud",
    "Volt", "Form3", "Banking Circle", "Mangopay", "Checkout Finland",
    "Vipps", "Swish", "MobilePay"
]

# ---------------------------
# CAPTCHA & Cloudflare Detection
# ---------------------------
def find_captcha_details(content: str):
    details = []
    if "recaptcha" in content.lower():
        if "recaptcha v1" in content.lower():
            details.append("reCAPTCHA v1: Deprecated")
        if "recaptcha v2" in content.lower():
            details.append("reCAPTCHA v2: Checkbox/image challenges")
        if "recaptcha v3" in content.lower():
            details.append("reCAPTCHA v3: Invisible scoring")
        if "recaptcha enterprise" in content.lower():
            details.append("reCAPTCHA Enterprise: Advanced risk analysis")
    if "hcaptcha" in content.lower():
        details.append("hCaptcha: Privacy-focused image labeling")
    if "funcaptcha" in content.lower():
        details.append("FunCAPTCHA: Gamified challenges")
    if "arkoselabs" in content.lower():
        details.append("Arkose Labs: 3D puzzles, AI defense")
    if "text-based captcha" in content.lower():
        details.append("Legacy text-based CAPTCHA")

    return details if details else ["No CAPTCHA services detected"]


def find_cloudflare_services(content: str):
    services = []
    lower = content.lower()
    if "cloudflare turnstile" in lower:
        services.append("Cloudflare Turnstile: Invisible/no-interaction CAPTCHA")
    if "ddos protection" in lower:
        services.append("Cloudflare DDoS Protection")
    if "web application firewall" in lower:
        services.append("Cloudflare WAF: SQLi/XSS defense")
    if "rate limiting" in lower:
        services.append("Cloudflare Rate Limiting")
    if "bot management" in lower:
        services.append("Cloudflare Bot Management")
    if "ssl/tls encryption" in lower:
        services.append("Cloudflare SSL/TLS Encryption")
    if "zero trust security" in lower:
        services.append("Cloudflare Zero Trust Security")

    return services if services else ["No Cloudflare services detected"]

# ---------------------------
# Gateway Detection
# ---------------------------
def find_payment_gateways(content: str):
    detected = [g for g in PAYMENT_GATEWAYS if g.lower() in content.lower()]
    return detected if detected else ["Unknown"]
