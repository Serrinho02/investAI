"""
Asset Catalogue — InvestAI
Lista asset predefiniti e riconoscimento automatico del tipo di strumento.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Lista asset predefiniti (nome → ticker)
# ---------------------------------------------------------------------------
POPULAR_ASSETS: dict[str, str] = {
    # --- INDICI / ETF GLOBALI ---
    "S&P 500 (USA)":           "SPY",
    "Nasdaq 100 (Tech)":       "QQQ",
    "Russell 2000 (Small Cap)":"IWM",
    "Dow Jones":               "DIA",
    "All-World":               "VWCE.DE",
    "Emerging Markets":        "EEM",
    "Europe Stoxx 50":         "FEZ",
    "China Large Cap":         "FXI",
    "China Internet":          "KWEB",
    "India":                   "INDA",
    "Brazil":                  "4BRZ.DE",
    "Japan":                   "EWJ",
    "UK (FTSE 100)":           "EWU",
    "Germany (DAX)":           "EWG",
    # --- MATERIE PRIME ---
    "Gold":                    "GLD",
    "Silver":                  "SLV",
    "Oil (WTI)":               "USO",
    "Natural Gas":             "UNG",
    "Copper (Miners)":         "COPX",
    "Uranium":                 "URA",
    "Agriculture":             "DBA",
    # --- REAL ESTATE & BOND ---
    "Real Estate (US)":        "VNQ",
    "US Treasury 20Y+":        "TLT",
    "US Treasury 1-3Y":        "SHY",
    "Corporate Bonds":         "LQD",
    # --- SETTORI USA ---
    "Semiconductors":          "SMH",
    "Technology":              "XLK",
    "Healthcare":              "XLV",
    "Financials":              "XLF",
    "Energy":                  "XLE",
    "Materials":               "XLB",
    "Industrials":             "XLI",
    "Consumer Discretionary":  "XLY",
    "Consumer Staples":        "XLP",
    "Utilities":               "XLU",
    "Clean Energy":            "ICLN",
    "Cybersecurity":           "CIBR.MI",
    "Robotics & AI":           "BOTZ",
    "Defense & Aerospace":     "ITA",
    "Biotech":                 "XBI",
    # --- CRYPTO ---
    "Bitcoin":                 "BTC-USD",
    "Ethereum":                "ETH-USD",
    "Solana":                  "SOL-USD",
    "Ripple":                  "XRP-USD",
    "Binance Coin":            "BNB-USD",
    "Cardano":                 "ADA-USD",
    "Dogecoin":                "DOGE-USD",
    "Chainlink":               "LINK-USD",
    "Polkadot":                "DOT-USD",
    # --- BIG TECH USA ---
    "Nvidia":                  "NVDA",
    "Apple":                   "AAPL",
    "Microsoft":               "MSFT",
    "Tesla":                   "TSLA",
    "Amazon":                  "AMZN",
    "Meta":                    "META",
    "Alphabet (Google)":       "GOOGL",
    "Oracle":                  "ORCL",
    "Netflix":                 "NFLX",
    "AMD":                     "AMD.F",
    "Palantir":                "PLTR",
    "Coinbase":                "COIN",
    "monday.com":              "MNDY",
    "Arista Networks":         "ANET",
    "Duolingo":                "DUOL",
    "The Trade Desk":          "TTD",
    "Axon Enterprise":         "AXON",
    "BigBear.ai":              "BBAI",
    # --- EUROPA ---
    "ASML":                    "ASML",
    "LVMH":                    "MC.PA",
    "Novo Nordisk":            "NVO",
    "SAP":                     "SAP",
    "Easyjet":                 "EJT1.F",
    # --- ITALIA ---
    "Ferrari":                 "RACE.MI",
    "Intesa Sanpaolo":         "ISP.MI",
    "UniCredit":               "UCG.MI",
    "Enel":                    "ENEL.MI",
    "Eni":                     "ENI.MI",
    "Stellantis":              "STLAM.MI",
    "Leonardo":                "LDO.MI",
    "Generali":                "G.MI",
    "Moncler":                 "MONC.MI",
    "Poste Italiane":          "PST.MI",
    "Terna":                   "TRN.MI",
    "Snam":                    "SRG.MI",
    "Mediobanca":              "MB.MI",
    "Prysmian":                "PRY.MI",
    "Fincantieri":             "FCT.MI",
    "Banca MPS":               "BMPSM.XD",
    "Banca Pop. Sondrio":      "BPSOM.XD",
}

AUTO_SCAN_TICKERS: list[str] = list(POPULAR_ASSETS.values())

# ---------------------------------------------------------------------------
# Lookup nome dall'ticker
# ---------------------------------------------------------------------------
_REVERSED: dict[str, str] = {v: k for k, v in POPULAR_ASSETS.items()}


def get_asset_name(ticker: str) -> str:
    return _REVERSED.get(ticker.upper(), ticker.upper())


# ---------------------------------------------------------------------------
# Classificazione tipo asset
# ---------------------------------------------------------------------------

# Pattern per le crypto (ticker che finisce in -USD o -BTC ecc.)
_CRYPTO_PATTERN = re.compile(r"[-/](USD|BTC|ETH|USDT|USDC|EUR)$", re.IGNORECASE)

# ETF noti (ticker nell'apposita lista predefinita)
_ETF_TICKERS: set[str] = {
    "SPY","QQQ","IWM","DIA","VWCE.DE","EEM","FEZ","FXI","KWEB","INDA",
    "4BRZ.DE","EWJ","EWU","EWG","GLD","SLV","USO","UNG","COPX","URA",
    "DBA","VNQ","TLT","SHY","LQD","SMH","XLK","XLV","XLF","XLE","XLB",
    "XLI","XLY","XLP","XLU","ICLN","CIBR.MI","BOTZ","ITA","XBI",
}

# REIT noti
_REIT_TICKERS: set[str] = {"VNQ"}

# Bond ETF noti
_BOND_TICKERS: set[str] = {"TLT","SHY","LQD","AGG","BND"}


class AssetType:
    CRYPTO    = "Crypto"
    ETF       = "ETF"
    REIT      = "REIT"
    BOND      = "Bond"
    INDEX_ETF = "Index ETF"
    STOCK     = "Azione"
    UNKNOWN   = "Sconosciuto"


def classify_asset(ticker: str) -> str:
    """Classifica il tipo di asset dato il ticker."""
    t = ticker.upper()

    if _CRYPTO_PATTERN.search(t):
        return AssetType.CRYPTO
    if t in _REIT_TICKERS:
        return AssetType.REIT
    if t in _BOND_TICKERS:
        return AssetType.BOND
    if t in _ETF_TICKERS:
        return AssetType.ETF
    # Azioni italiane (es. RACE.MI, UCG.MI)
    if t.endswith(".MI") or t.endswith(".PA") or t.endswith(".F") or t.endswith(".DE"):
        return AssetType.STOCK
    # Default: azione americana
    if re.match(r"^[A-Z]{1,5}$", t):
        return AssetType.STOCK
    return AssetType.UNKNOWN
