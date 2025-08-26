import requests
import re
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------
# Payment Gateways (expanded list)
# ---------------------------
PAYMENT_GATEWAYS = [
    "PayPal": [r"paypal\.com", r"paypalobjects", r"www\.paypal", r"paypal\.me", r"payflowlink"],
    "Stripe": [r"stripe\.com", r"stripe\.js", r"checkout\.stripe", r"api\.stripe", r"js\.stripe"],
    "Braintree": [r"braintreegateway\.com", r"braintreepayments\.com", r"client-token", r"braintree"],
    "Square": [r"squareup\.com", r"squarecdn", r"cash\.squareapp", r"api\.square", r"connect\.square"],
    "CyberSource": [r"cybersource\.com", r"secureacceptance", r"ics\.cybersource", r"api\.cybersource"],
    "Lemon Squeezy": [r"lemonsqueezy\.com", r"cdn\.lemonsqueezy", r"checkout\.lemonsqueezy"],
    "Authorize.Net": [r"authorize\.net", r"accept\.js", r"api\.authorize", r"secure2\.authorize"],
    "2Checkout": [r"2checkout\.com", r"2co\.com", r"secure\.2checkout", r"verifone\.com"],
    "Adyen": [r"adyen\.com", r"checkoutshopper", r"adyencheckout", r"live\.adyen", r"api\.adyen"],
    "Worldpay": [r"worldpay\.com", r"onlinepayments\.worldpay", r"secure\.worldpay", r"api\.worldpay"],
    "SagePay / Opayo": [r"sagepay\.com", r"opayo\.co\.uk", r"live\.sagepay", r"mms\.opayo"],
    "Checkout.com": [r"checkout\.com", r"api\.checkout", r"ckojs"],
    "Bolt": [r"bolt\.com", r"bolt-checkout", r"api\.bolt"],
    "eWAY": [r"eway\.com", r"secure\.ewaypayments", r"eway\.au"],
    "Payflow": [r"payflowlink", r"paypal\.com/payflow"],
    "Payeezy": [r"payeezy\.com", r"globalgatewaye4", r"firstdata", r"fiserv"],
    "Paddle": [r"paddle\.com", r"checkout\.paddle", r"vendors\.paddle"],
    "Mollie": [r"mollie\.com", r"api\.mollie", r"molliepay"],
    "Viva Wallet": [r"vivawallet\.com", r"api\.vivawallet", r"vivapayments"],
    "Rocketgate": [r"rocketgate\.com", r"gateway\.rocketgate", r"secure\.rocketgate", r"rocketgate"],
    "Recurly": [r"recurly\.com", r"js\.recurly", r"api\.recurly"],
    "BlueSnap": [r"bluesnap\.com", r"checkout\.bluesnap", r"api\.bluesnap"],
    "Nuvei": [r"nuvei\.com", r"safecharge", r"api\.safecharge"],
    "Worldline (Ingenico/Ogone)": [r"worldline\.com", r"ingenico\.", r"ogone\.", r"api\.(ingenico|worldline)"],
    "Global Payments": [r"globalpayments\.com", r"api\.globalpay", r"realexpayments", r"open\.globalpay"],
    "Elavon": [r"elavon\.com", r"convergepay", r"api\.convergepay", r"convergepay"],
    "Fiserv / First Data": [r"fiserv\.com", r"firstdata", r"payeezy", r"fdicr"],
    "FIS / Worldpay from FIS": [r"fisglobal\.com", r"worldpayfromfis"],
    "Chase Paymentech / Orbital": [r"chasepaymentech\.com", r"orbitalpay", r"secure\.chase"],
    "TSYS": [r"tsys\.com", r"cayan", r"genius\.cayan"],
    "Heartland": [r"heartlandpaymentsystems\.com", r"api\.heartland"],
    "EVO Payments": [r"evopayments\.com", r"evo\.io", r"api\.evopayments"],
    "NMI": [r"networkmerchants\.com", r"nmi\.com", r"secure\.networkmerchants"],
    "Spreedly": [r"spreedly\.com", r"core\.spreedly"],
    "WePay": [r"wepay\.com", r"api\.wepay"],
    "Dwolla": [r"dwolla\.com", r"api\.dwolla"],
    "Forte": [r"forte\.net", r"forte\.com", r"api\.forte"],
    "CardConnect": [r"cardconnect\.com", r"cardpointe", r"api\.cardconnect"],
    "BluePay": [r"bluepay\.com", r"api\.bluepay"],
    "FluidPay": [r"fluidpay\.com", r"api\.fluidpay"],
    "PayJunction": [r"payjunction\.com", r"api\.payjunction"],
    "PayTrace": [r"paytrace\.com", r"api\.paytrace"],
    "USAePay": [r"usaepay\.com", r"api\.usaepay"],
    "eProcessing Network": [r"eprocessingnetwork\.com", r"epn\.bz", r"api\.eprocessingnetwork"],
    "Payline": [r"payline\.com", r"api\.payline"],
    "PayLeap": [r"payleap\.com", r"api\.payleap"],
    "TransFirst": [r"transfirst\.com", r"api\.transfirst"],
    "Moneris": [r"moneris\.com", r"api\.moneris"],
    "Helcim": [r"helcim\.com", r"api\.helcim"],
    "Clover": [r"clover\.com", r"api\.clover", r"dev\.clover"],
    "LawPay": [r"lawpay\.com", r"api\.lawpay"],
    "Blackbaud": [r"blackbaud\.com", r"bbnpayments"],
    "PaySimple": [r"paysimple\.com", r"api\.paysimple"],
    "Converge": [r"convergepay\.com", r"api\.convergepay"],
    "Cardknox": [r"cardknox\.com", r"xpresspay", r"api\.cardknox"],
    "Chase Merchant Services": [r"chase\.com/business/merchant-services", r"orbital"],
    "AurusPay": [r"auruspay\.com", r"api\.auruspay"],
    "PayComet": [r"paycomet\.com", r"api\.paycomet"],
    "GeoMerchant": [r"geomerchant", r"geomerchant\.com"],
    "Realex Payments": [r"realexpayments\.com", r"api\.realexpayments", r"globalpay"],
    "Sage Payments": [r"sagepayments\.com", r"api\.sagepay"],
    "PrimePay / Payeezy Alt": [r"payeezy", r"firstdata", r"primepay"],
    "Opayo": [r"opayo\.co\.uk", r"sagepay"],
    "PayXpert": [r"payxpert\.com", r"api\.payxpert"],
    "MultiSafepay": [r"multisafepay\.com", r"api\.multisafepay"],
    "Bambora": [r"bambora\.com", r"api\.bambora"],
    "RedSys": [r"redsýs|redsys", r"redsys\.es", r"sis\.redsys"],
    "PayBox": [r"paybox\.com", r"api\.paybox"],
    "Dotpay": [r"dotpay\.pl", r"api\.dotpay"],
    "Payline (France)": [r"payline\.com", r"monext"],
    "HiPay": [r"hipay\.com", r"api\.hipay"],
    "Opn / Omise": [r"omise\.co", r"api\.omise", r"opn\.ish"],
    "PayTabs": [r"paytabs\.com", r"api\.paytabs"],
    "Telr": [r"telr\.com", r"secure\.telr"],
    "HyperPay": [r"hyperpay\.com", r"oppwa\.com", r"api\.hyperpay"],
    "Tap Payments": [r"tap.company", r"goSell", r"api\.tap"],
    "Moyasar": [r"moyasar\.com", r"api\.moyasar"],
    "Payfort / Amazon Payment Services": [r"payfort\.com", r"amazonpaymentservices", r"aps\.amazon"],
    "MyFatoorah": [r"myfatoorah\.com", r"api\.myfatoorah"],
    "Paymob": [r"paymob\.com", r"accept\.paymob"],
    "FawryPay": [r"fawry\.com", r"acceptance\.fawry"],
    "PayGate (ZA)": [r"paygate\.co\.za", r"api\.paygate"],
    "PayFast (ZA)": [r"payfast\.co\.za", r"api\.payfast"],
    "Peach Payments": [r"peachpayments\.com", r"api\.peachpayments"],
    "Yoco": [r"yoco\.com", r"api\.yoco"],
    "Interswitch": [r"interswitchgroup\.com", r"quickteller", r"verve"],
    "Remita": [r"remita\.net", r"api\.remita"],
    "DPO Group (Direct Pay Online)": [r"dpogroup\.com", r"3gdirectpay"],
    "Flutterwave": [r"flutterwave\.com", r"ravepay", r"api\.flutterwave"],
    "Paystack": [r"paystack\.com", r"api\.paystack"],
    "KongaPay": [r"kongapay\.com"],
    "M-Pesa": [r"safaricom\.co\.ke/mpesa", r"mpesa", r"vodacom\.co\.tz/mpesa"],
    "Airtel Money": [r"airtel\.com/money", r"airtelmoney"],
    "Orange Money": [r"orange\.com/en/orange-money", r"orangemoney"],
    "Pesapal": [r"pesapal\.com", r"api\.pesapal"],
    "Paga": [r"mypaga\.com", r"paga\.com"],
    "Conekta (MX)": [r"conekta\.com", r"api\.conekta"],
    "Openpay (MX)": [r"openpay\.mx", r"api\.openpay"],
    "Clip (MX)": [r"clip\.mx", r"pagos\.clip"],
    "Mercado Pago": [r"mercadopago\.com", r"api\.mercadopago"],
    "PagSeguro": [r"pagseguro\.uol\.com", r"api\.pagseguro"],
    "Kushki": [r"kushkipagos\.com", r"api\.kushkipagos"],
    "Culqi": [r"culqi\.com", r"api\.culqi"],
    "Niubiz (Peru)": [r"niubiz\.com\.pe", r"api\.niubiz"],
    "Pagar.me": [r"pagar\.me", r"api\.pagar\.me"],
    "EBANX": [r"ebanx\.com", r"api\.ebanx"],
    "DLocal": [r"dlocal\.com", r"api\.dlocal"],
    "Transbank (CL)": [r"transbank\.cl", r"webpay"],
    "Flow (CL)": [r"flow\.cl", r"api\.flow"],
    "PayU (Global/LatAm/India/EU)": [r"payu\.(in|com|lat|pl|ro)", r"secure\.payu"],
    "PayU Biz / PayUbiz": [r"payubiz\.in", r"api\.payubiz"],
    "Instamojo": [r"instamojo\.com", r"api\.instamojo"],
    "CCAvenue": [r"ccavenue\.com", r"secure\.ccavenue"],
    "BillDesk": [r"billdesk\.com", r"paymentgateway\.billdesk"],
    "Cashfree": [r"cashfree\.com", r"api\.cashfree"],
    "Razorpay": [r"razorpay\.com", r"razorpay\.js", r"api\.razorpay", r"checkout\.razorpay"],
    "Atom (India)": [r"atomtech\.in", r"api\.atom"],
    "EBS (India)": [r"ebs\.in", r"payuindia/ebs", r"api\.ebs"],
    "PayKun": [r"paykun\.com", r"api\.paykun"],
    "PhonePe": [r"phonepe\.com", r"api\.phonepe"],
    "UPI / NPCI": [r"upi://", r"npci\.org", r"bharatqr"],
    "BharatPe": [r"bharatpe\.com", r"qrcode\.bharatpe"],
    "Freecharge": [r"freecharge\.in", r"api\.freecharge"],
    "MobiKwik": [r"mobikwik\.com", r"wallet\.mobikwik"],
    "Juspay": [r"juspay\.in", r"api\.juspay"],
    "Paytm": [r"paytm\.com", r"securegw\.paytm", r"payments\.paytm"],
    "RazorpayX": [r"razorpayx", r"razorpay\.com/x"],
    "Pine Labs": [r"pinelabs\.com", r"plutus", r"qfix"],
    "PayLater (ICICI/Amazon etc.)": [r"paylater", r"pay\-later"],

    # === Southeast Asia & East Asia ===
    "Midtrans (IDN)": [r"midtrans\.com", r"veritrans", r"api\.midtrans"],
    "DOKU (IDN)": [r"doku\.com", r"api\.doku"],
    "Xendit (IDN/SEA)": [r"xendit\.co", r"api\.xendit"],
    "iPay88 (MY/SEA)": [r"ipay88\.com", r"api\.ipay88"],
    "MOLPay / Razer Merchant Services": [r"molpay\.com", r"razer\.com/payment", r"rms\.razer"],
    "eGHL (MY/SEA)": [r"eghl\.com", r"api\.eghl"],
    "PayMaya / Maya (PH)": [r"paymaya\.com", r"maya\.ph", r"api\.paymaya"],
    "Dragonpay (PH)": [r"dragonpay\.ph", r"api\.dragonpay"],
    "PayMongo (PH)": [r"paymongo\.com", r"api\.paymongo"],
    "Netbank (PH)": [r"netbank\.ph"],
    "NETS (SG)": [r"nets\.com\.sg", r"enets", r"api\.nets"],
    "PayNow (SG)": [r"paynow", r"sgqr"],
    "2C2P (SEA)": [r"2c2p\.com", r"api\.2c2p"],
    "FOMO Pay (SG/SEA)": [r"fomopay\.com", r"api\.fomopay"],
    "AsiaPay / PayDollar (HK)": [r"paydollar\.com", r"asiapay", r"pesopay"],
    "GMO Payment Gateway (JP)": [r"gmo-pg\.com", r"multipayment"],
    "SBPS SoftBank Payment Service (JP)": [r"sbpayment\.jp", r"api\.sbps"],
    "Komoju (JP/KR)": [r"komoju\.com", r"api\.komoju"],
    "Rakuten Pay (JP)": [r"rakuten\.co\.jp/pay", r"rakutenpay"],
    "Pay\.jp (JP)": [r"pay\.jp", r"api\.pay\.jp"],
    "LINE Pay (JP/TW/TH)": [r"linepay", r"pay\.line\.me"],
    "PayPay (JP)": [r"paypay\.ne\.jp"],
    "Naver Pay (KR)": [r"naverpay", r"pay\.naver\.com"],
    "KakaoPay (KR)": [r"kakaopay", r"pay\.kakao\.com"],
    "Toss Payments (KR)": [r"tosspayments\.com", r"api\.tosspayments"],

    # === Europe (additional) ===
    "Trustly": [r"trustly\.com", r"api\.trustly"],
    "iDEAL": [r"ideal\.nl", r"issuer\.ideal"],
    "Giropay": [r"giropay\.de"],
    "Sofort / Klarna Pay Now": [r"sofort\.com", r"klarna\.sofort"],
    "EPS (Austria)": [r"eps\-ueberweisung", r"eps\-payment"],
    "Przelewy24 (PL)": [r"przelewy24\.pl", r"p24\.pl"],
    "Blik (PL)": [r"blik\.pl", r"polski standard płatności", r"codeblik"],
    "Multibanco (PT)": [r"multibanco", r"sibs"],
    "Paytrail / Checkout Finland": [r"paytrail\.com", r"checkoutfinland\.fi"],
    "Swish (SE)": [r"swish\.nu", r"gets wish"],
    "Vipps (NO)": [r"vipps\.no"],
    "MobilePay (DK/FI)": [r"mobilepay\.dk|mobilepay\.fi", r"api\.mobilepay"],
    "Nets / DIBS": [r"nets\.eu", r"dibs\.eu", r"easy\.nets"],
    "Satispay (IT)": [r"satispay\.com"],
    "Nexi (IT)": [r"nexi\.it", r"xpay"],
    "Payplug (FR)": [r"payplug\.com"],
    "Lyra / PayZen (FR)": [r"payzen\.eu", r"lyra\-network"],
    "Qenta / Wirecard legacy (EU)": [r"qenta\.com", r"wirecard", r"checkoutportal"],
    "Paymill (DE)": [r"paymill\.com"],
    "Ratepay (DE)": [r"ratepay\.com"],
    "Scalapay (IT/EU BNPL)": [r"scalapay\.com"],

    # === Australia / New Zealand ===
    "Pin Payments (AU)": [r"pinpayments\.com", r"api\.pinpayments"],
    "BPOINT (AU)": [r"bpoint\.com\.au", r"api\.bpoint"],
    "Westpac PayWay (AU)": [r"payway\.com\.au"],
    "NAB Transact (AU)": [r"transact\.nab", r"nabtransact"],
    "ANZ eGate (AU/NZ)": [r"anz\.com/egate", r"egate"],
    "Windcave / DPS / Payment Express (AU/NZ)": [r"paymentexpress\.com", r"dps\.co\.nz", r"windcave\.com"],
    "POLi (AU/NZ)": [r"poliinternetbanking\.com", r"poli\.pay"],
    "Tyro (AU)": [r"tyro\.com", r"api\.tyro"],

    # === E-commerce Platforms (Hosted + Self-hosted) ===
    "Shopify": [r"shopify\.com", r"cdn\.shopify", r"checkout\.shopify", r"myshopify\.com"],
    "WooCommerce": [r"woocommerce\.com", r"wc\-ajax", r"woocommerce"],
    "BigCommerce": [r"bigcommerce\.com", r"checkout\.bigcommerce"],
    "Magento": [r"magento\.com", r"magento\.cloud", r"mage\/", r"magento2"],
    "Magento Payments": [r"payments\.magento", r"magento-payments"],
    "OpenCart": [r"opencart\.com", r"ocmod", r"opencart"],
    "PrestaShop": [r"prestashop\.com", r"ps_checkout", r"prestashop"],
    "3DCart / Shift4Shop": [r"3dcartstores", r"3dcart\.com", r"shift4shop\.com"],
    "Ecwid": [r"ecwid\.com", r"app\.ecwid", r"cdn\.ecwid"],
    "Shopware": [r"shopware\.com", r"api\.shopware", r"shopware"],
    "VirtueMart": [r"virtuemart\.net", r"com_virtuemart"],
    "CS-Cart": [r"cs-cart\.com", r"cscart"],
    "X-Cart": [r"x-cart\.com", r"xcart"],
    "LemonStand": [r"lemonstand\.com"],
    "Wix Stores": [r"wix\.com/ecommerce", r"checkout\.wix", r"staticwix"],
    "Squarespace Commerce": [r"squarespace\.com/commerce", r"checkout\.squarespace"],
    "Weebly Commerce": [r"weebly\.com/store", r"checkout\.weebly"],
    "Volusion": [r"volusion\.com", r"store\.volusion"],
    "Zoho Commerce": [r"zoho\.com/commerce", r"checkout\.zoho"],
    "Salesforce Commerce Cloud (Demandware)": [r"commercecloud\.com", r"demandware"],
    "SAP Hybris": [r"hybris\.com", r"commerce\.sap"],
    "Oracle Commerce": [r"oracle\.com/commerce"],
    "IBM WebSphere Commerce": [r"ibm\.com/websphere/commerce"],

    # === BNPL & Wallets (extra) ===
    "Zip / Quadpay": [r"zip\.co", r"quadpay\.com"],
    "Laybuy": [r"laybuy\.com"],
    "Openpay": [r"openpay\.com"],
    "Splitit": [r"splitit\.com"],
    "Perpay": [r"perpay\.com"],
    "Atome": [r"atome\.sg|atome\.ph|atome\.id|atome\.my|atome\.tw"],
    "Cashalo": [r"cashalo\.com"],
    "Hoolah": [r"hoolah\.co"],
    "ChargeAfter": [r"chargeafter\.com"],
    "Apple Pay": [r"applepay", r"apple\.com/apple-pay", r"applepaybutton"],
    "Google Pay": [r"pay\.google\.com", r"gpay", r"googlepay"],
    "Samsung Pay": [r"samsung\.com/pay", r"samsungpay"],
    "Venmo": [r"venmo\.com"],
    "Cash App": [r"cash\.app", r"squareup\.com/cash"],
    "Revolut Pay": [r"revolut\.com/pay", r"api\.revolut"],
    "Zelle": [r"zellepay\.com", r"zelle\.us"],
    "Alipay": [r"alipay\.com", r"intl\.alipay", r"alipayobjects"],
    "WeChat Pay": [r"wechatpay", r"pay\.weixin\.qq", r"wxpay"],
    "Skrill": [r"skrill\.com", r"skrillcdn"],
    "Neteller": [r"neteller\.com"],
    "WebMoney": [r"webmoney\.ru", r"wmtransfer"],
    "Payoneer": [r"payoneer\.com"],
    "Paysafe": [r"paysafe\.com", r"paysafecard"],
    "Payeer": [r"payeer\.com"],
    "GrabPay": [r"grabpay", r"grab\.com"],
    "PayMaya / Maya": [r"paymaya\.com", r"maya\.ph"],
    "MoMo (VN)": [r"momo\.vn", r"mservice"],
    "TrueMoney": [r"truemoney", r"truemoneywallet"],
    "Touch 'n Go (MY)": [r"touchngo", r"tngdigital"],
    "GoPay (ID)": [r"gopay\.co\.id"],
    "Dana (ID)": [r"dana\.id", r"dana\.co"],
    "JKOPay (TW)": [r"jkopay\.com"],
    "EasyPaisa (PK)": [r"easypaisa", r"telenorbank"],

    # === Cryptocurrency Gateways ===
    "BitPay": [r"bitpay\.com"],
    "Coinbase Commerce": [r"commerce\.coinbase\.com"],
    "CoinGate": [r"coingate\.com"],
    "CoinPayments": [r"coinpayments\.net"],
    "Crypto\.com Pay": [r"crypto\.com/pay"],
    "BTCPay Server": [r"btcpayserver", r"btcpay"],
    "NOWPayments": [r"nowpayments\.io"],
    "OpenNode": [r"opennode\.com"],
    "Utrust": [r"utrust\.com"],
    "MoonPay": [r"moonpay\.com"],
    "Binance Pay": [r"binance\.com/en/pay"],
    "CoinsPaid": [r"coinspaid\.com"],
    "BitGo": [r"bitgo\.com"],
    "Flexa": [r"flexa\.network"],
    "Circle": [r"circle\.com|circlepay"],

    # === Country Specific (extra) ===
    "Bizum (ES)": [r"bizum\.es"],
    "PayU Turkey / iyzico": [r"iyzico\.com", r"api\.iyzico"],
    "Paylike": [r"paylike\.io"],
    "Viva (GR)": [r"vivawallet\.com"],
    "Cetelem (FR)": [r"cetelem\.fr"],
    "Oney (FR/ES)": [r"oney\.com"],
    "Alma (FR BNPL)": [r"getalma\.eu"],
    "Clearhaus (DK)": [r"clearhaus\.com"],
    "Paysera (LT)": [r"paysera\.com"],
    "Pivo (FI)": [r"pivolompakko|pivo\.fi"],
    "Siirto (FI)": [r"siirto\.fi"],
    "Swedbank Pay": [r"swedbankpay\.se|swedbankpay\.no"],
    "Handelsbanken (SE)": [r"handelsbanken", r"card\.handelsbanken"],
    "Zimpler (SE)": [r"zimpler\.com"],
    "Nordea (FI/SE)": [r"nordea\.com", r"nordea pay"],
}

# ---------------------------
# Captcha & Cloudflare Detection
# ---------------------------
def find_captcha_details(content: str):
    lower = content.lower()
    details = []
    if "recaptcha" in lower:
        if "recaptcha v2" in lower:
            details.append("reCAPTCHA v2")
        elif "recaptcha v3" in lower:
            details.append("reCAPTCHA v3")
        else:
            details.append("reCAPTCHA (generic)")
    if "hcaptcha" in lower:
        details.append("hCaptcha")
    if "funcaptcha" in lower:
        details.append("FunCaptcha")
    if "arkoselabs" in lower:
        details.append("Arkose Labs")
    return details if details else ["None"]

def find_cloudflare(content: str, headers: dict):
    details = []
    if "cloudflare" in content.lower() or "cf-ray" in str(headers).lower():
        details.append("Cloudflare detected")
    if "turnstile" in content.lower():
        details.append("Cloudflare Turnstile")
    return details if details else ["None"]

# ---------------------------
# Gateway Detection (regex-based)
# ---------------------------
def find_payment_gateways(content: str):
    detected = []
    for gateway, patterns in PAYMENT_GATEWAYS.items():
        for pat in patterns:
            if re.search(pat, content, re.IGNORECASE):
                detected.append(gateway)
                break
    return list(set(detected)) if detected else ["Unknown"]

# ---------------------------
# Main Scanner
# ---------------------------
def run_gateway_scan(url: str) -> dict:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/117.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive"
        }

        session = requests.Session()
        resp = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        content = resp.text

        found_gateways = find_payment_gateways(content)

        # Also check JS/CSS assets
        assets = re.findall(r'src=["\'](.*?\.js)["\']', content)
        assets += re.findall(r'href=["\'](.*?\.css)["\']', content)

        asset_content = ""
        for a in assets[:10]:  # limit to first 10 assets
            asset_url = urljoin(url, a)
            try:
                r = session.get(asset_url, headers=headers, timeout=8)
                asset_content += r.text
            except:
                continue

        if asset_content:
            found_gateways += find_payment_gateways(asset_content)

        return {
            "url": url,
            "status_code": resp.status_code,
            "gateways": list(set(found_gateways)),
            "captcha": find_captcha_details(content),
            "cloudflare": find_cloudflare(content, resp.headers),
            "redirects": [h.url for h in resp.history],
        }
    except Exception as e:
        return {
            "url": url,
            "error": str(e),
            "gateways": ["Unknown"],
            "captcha": ["Unknown"],
            "cloudflare": ["Unknown"],
            "redirects": []
        }

# ---------------------------
# Bulk Scan
# ---------------------------
def scan_multiple(urls: list, workers: int = 5):
    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_url = {executor.submit(run_gateway_scan, u): u for u in urls}
        for future in as_completed(future_to_url):
            results.append(future.result())
    return results
