"""
Asset Catalogue — InvestAI
Lista asset estesa (~170 ticker) e classificazione automatica del tipo di strumento.
"""
from __future__ import annotations
import re

# ---------------------------------------------------------------------------
# Lista asset (nome → ticker) — ~170 asset su 12 categorie
# ---------------------------------------------------------------------------
POPULAR_ASSETS: dict[str, str] = {

    # ── ETF INDICI GLOBALI ──────────────────────────────────────────────────
    "S&P 500":              "SPY",
    "S&P 500 (acc.)":       "CSPX.L",
    "Nasdaq 100":           "QQQ",
    "Dow Jones":            "DIA",
    "Russell 2000":         "IWM",
    "MSCI All-World":       "VWCE.DE",
    "MSCI World":           "IWDA.AS",
    "Emerging Markets":     "EEM",
    "Europe Stoxx 50":      "FEZ",
    "MSCI Europe":          "IMEU.AS",
    "China Large Cap":      "FXI",
    "China Internet":       "KWEB",
    "India":                "INDA",
    "Japan":                "EWJ",
    "Brazil":               "EWZ",
    "Korea":                "EWY",
    "Taiwan":               "EWT",
    "Vietnam":              "VNM",
    "UK (FTSE 100)":        "EWU",
    "Germany (DAX)":        "EWG",
    "Mexico":               "EWW",
    "Saudi Arabia":         "KSA",

    # ── ETF SETTORI USA ─────────────────────────────────────────────────────
    "Semiconductors":       "SMH",
    "Technology":           "XLK",
    "Healthcare":           "XLV",
    "Financials":           "XLF",
    "Energy":               "XLE",
    "Materials":            "XLB",
    "Industrials":          "XLI",
    "Consumer Disc.":       "XLY",
    "Consumer Staples":     "XLP",
    "Utilities":            "XLU",
    "Real Estate (ETF)":    "XLRE",
    "Communication Svc":    "XLC",
    "Biotech":              "XBI",
    "Defense & Aerospace":  "ITA",
    "Cybersecurity":        "HACK",
    "Cloud Computing":      "SKYY",
    "AI & Robotics":        "BOTZ",
    "Clean Energy":         "ICLN",
    "Solar":                "TAN",
    "Nuclear/Uranium":      "URA",
    "Genomics":             "ARKG",
    "FinTech":              "FINX",
    "Space":                "UFO",
    "E-commerce":           "IBUY",
    "Copper (Miners)":      "COPX",

    # ── MATERIE PRIME ────────────────────────────────────────────────────────
    "Gold":                 "GLD",
    "Silver":               "SLV",
    "Platinum":             "PPLT",
    "Oil (WTI)":            "USO",
    "Oil (Brent)":          "BNO",
    "Natural Gas":          "UNG",
    "Agriculture":          "DBA",
    "Corn":                 "CORN",
    "Wheat":                "WEAT",
    "Lumber":               "CUT",
    "Lithium":              "LIT",
    "Rare Earths":          "REMX",

    # ── REAL ESTATE & BOND ──────────────────────────────────────────────────
    "Real Estate (US)":     "VNQ",
    "US Treasury 20Y+":     "TLT",
    "US Treasury 7-10Y":    "IEF",
    "US Treasury 1-3Y":     "SHY",
    "Corp Bonds IG":        "LQD",
    "Corp Bonds HY":        "HYG",
    "TIPS (Inflation)":     "TIP",
    "Euro Bonds":           "IBTE.L",

    # ── CRYPTO ───────────────────────────────────────────────────────────────
    "Bitcoin":              "BTC-USD",
    "Ethereum":             "ETH-USD",
    "Solana":               "SOL-USD",
    "Ripple (XRP)":         "XRP-USD",
    "BNB":                  "BNB-USD",
    "Cardano":              "ADA-USD",
    "Avalanche":            "AVAX-USD",
    "Chainlink":            "LINK-USD",
    "Polkadot":             "DOT-USD",
    "Dogecoin":             "DOGE-USD",
    "Shiba Inu":            "SHIB-USD",
    "NEAR Protocol":        "NEAR-USD",
    "Sui":                  "SUI-USD",
    "Pepe":                 "PEPE-USD",
    "Ethereum Classic":     "ETC-USD",

    # ── MEGA CAP USA ────────────────────────────────────────────────────────
    "Nvidia":               "NVDA",
    "Apple":                "AAPL",
    "Microsoft":            "MSFT",
    "Alphabet (Google)":    "GOOGL",
    "Amazon":               "AMZN",
    "Meta":                 "META",
    "Tesla":                "TSLA",
    "Berkshire B":          "BRK-B",
    "JPMorgan":             "JPM",
    "Visa":                 "V",
    "UnitedHealth":         "UNH",
    "ExxonMobil":           "XOM",
    "Eli Lilly":            "LLY",

    # ── TECH & GROWTH USA ───────────────────────────────────────────────────
    "Oracle":               "ORCL",
    "Netflix":              "NFLX",
    "AMD":                  "AMD",
    "Palantir":             "PLTR",
    "Salesforce":           "CRM",
    "ServiceNow":           "NOW",
    "Snowflake":            "SNOW",
    "Datadog":              "DDOG",
    "Cloudflare":           "NET",
    "CrowdStrike":          "CRWD",
    "Palo Alto Networks":   "PANW",
    "Fortinet":             "FTNT",
    "Zscaler":              "ZS",
    "Arista Networks":      "ANET",
    "Coinbase":             "COIN",
    "Robinhood":            "HOOD",
    "Affirm":               "AFRM",
    "Block (Square)":       "SQ",
    "Stripe":               "N/A",
    "Uber":                 "UBER",
    "Airbnb":               "ABNB",
    "Spotify":              "SPOT",
    "Shopify":              "SHOP",
    "monday.com":           "MNDY",
    "Duolingo":             "DUOL",
    "The Trade Desk":       "TTD",
    "Axon Enterprise":      "AXON",
    "Vertiv":               "VRT",
    "Vistra":               "VST",
    "GE Vernova":           "GEV",
    "Constellation Energy": "CEG",
    "Arm Holdings":         "ARM",
    "Broadcom":             "AVGO",
    "TSMC":                 "TSM",
    "Applied Materials":    "AMAT",
    "Lam Research":         "LRCX",
    "KLA Corp":             "KLAC",

    # ── DIFESA / SPAZIO USA ─────────────────────────────────────────────────
    "Lockheed Martin":      "LMT",
    "Northrop Grumman":     "NOC",
    "Raytheon":             "RTX",
    "L3Harris":             "LHX",
    "Rocket Lab":           "RKLB",
    "Intuitive Machines":   "LUNR",

    # ── PHARMA / BIOTECH USA ────────────────────────────────────────────────
    "Johnson & Johnson":    "JNJ",
    "AbbVie":               "ABBV",
    "Merck":                "MRK",
    "Pfizer":               "PFE",
    "Moderna":              "MRNA",
    "Regeneron":            "REGN",
    "Vertex Pharma":        "VRTX",
    "Gilead Sciences":      "GILD",

    # ── EUROPA ───────────────────────────────────────────────────────────────
    "ASML":                 "ASML",
    "LVMH":                 "MC.PA",
    "Novo Nordisk":         "NVO",
    "SAP":                  "SAP",
    "Hermès":               "RMS.PA",
    "Schneider Electric":   "SU.PA",
    "Air Liquide":          "AI.PA",
    "Siemens":              "SIE.DE",
    "KONE":                 "KNEBV.HE",
    "Infineon":             "IFX.DE",
    "Volkswagen":           "VOW3.DE",
    "Shell":                "SHEL",
    "AstraZeneca":          "AZN",
    "GSK":                  "GSK",

    # ── ITALIA (FTSE MIB) ────────────────────────────────────────────────────
    "Ferrari":              "RACE.MI",
    "Intesa Sanpaolo":      "ISP.MI",
    "UniCredit":            "UCG.MI",
    "Enel":                 "ENEL.MI",
    "Eni":                  "ENI.MI",
    "Stellantis":           "STLAM.MI",
    "Leonardo":             "LDO.MI",
    "Generali":             "G.MI",
    "Moncler":              "MONC.MI",
    "Poste Italiane":       "PST.MI",
    "Terna":                "TRN.MI",
    "Snam":                 "SRG.MI",
    "Mediobanca":           "MB.MI",
    "Prysmian":             "PRY.MI",
    "Campari":              "CPR.MI",
    "Diasorin":             "DIA.MI",
    "Nexi":                 "NEXI.MI",
    "Amplifon":             "AMP.MI",
    "Recordati":            "REC.MI",
    "Brunello Cucinelli":   "BC.MI",
}

# Rimuovi eventuali placeholder "N/A"
POPULAR_ASSETS = {k: v for k, v in POPULAR_ASSETS.items() if v != "N/A"}

AUTO_SCAN_TICKERS: list[str] = list(POPULAR_ASSETS.values())

# ---------------------------------------------------------------------------
# Lookup nome → ticker e ticker → nome
# ---------------------------------------------------------------------------
_REVERSED: dict[str, str] = {v: k for k, v in POPULAR_ASSETS.items()}


def get_asset_name(ticker: str) -> str:
    return _REVERSED.get(ticker.upper(), ticker.upper())


# ---------------------------------------------------------------------------
# Classificazione tipo asset
# ---------------------------------------------------------------------------
_CRYPTO_PATTERN = re.compile(r"[-/](USD|BTC|ETH|USDT|USDC|EUR)$", re.IGNORECASE)

_ETF_TICKERS: set[str] = {
    "SPY","CSPX.L","QQQ","DIA","IWM","VWCE.DE","IWDA.AS","EEM","FEZ","IMEU.AS",
    "FXI","KWEB","INDA","EWJ","EWZ","EWY","EWT","VNM","EWU","EWG","EWW","KSA",
    "SMH","XLK","XLV","XLF","XLE","XLB","XLI","XLY","XLP","XLU","XLRE","XLC",
    "XBI","ITA","HACK","SKYY","BOTZ","ICLN","TAN","URA","ARKG","FINX","UFO",
    "IBUY","COPX","REMX","LIT",
    "GLD","SLV","PPLT","USO","BNO","UNG","DBA","CORN","WEAT","CUT",
    "VNQ","TLT","IEF","SHY","LQD","HYG","TIP","IBTE.L",
}
_REIT_TICKERS: set[str] = {"VNQ","XLRE"}
_BOND_TICKERS: set[str] = {"TLT","IEF","SHY","LQD","HYG","TIP","AGG","BND","IBTE.L"}


class AssetType:
    CRYPTO = "Crypto"
    ETF    = "ETF"
    REIT   = "REIT"
    BOND   = "Bond"
    STOCK  = "Azione"
    UNKNOWN = "?"


def classify_asset(ticker: str) -> str:
    t = ticker.upper()
    if _CRYPTO_PATTERN.search(t):
        return AssetType.CRYPTO
    if t in _REIT_TICKERS:
        return AssetType.REIT
    if t in _BOND_TICKERS:
        return AssetType.BOND
    if t in _ETF_TICKERS:
        return AssetType.ETF
    if any(t.endswith(sfx) for sfx in (".MI", ".PA", ".DE", ".F", ".AS", ".L", ".HE")):
        return AssetType.STOCK
    if re.match(r"^[A-Z]{1,5}(-[A-Z])?$", t):
        return AssetType.STOCK
    return AssetType.UNKNOWN
