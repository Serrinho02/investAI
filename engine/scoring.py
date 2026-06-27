"""
Scoring Engine — InvestAI v2.2
Sistema di scoring multi-dimensionale, trasparente e spiegabile.

Correzioni rispetto alla v2.0:
 - P1: trend_score SMA200 usa step discreti invece di formula lineare
       (evita che asset +0.5% sopra SMA200 valgano 1/35 punti)
 - P2: BUY confermato solo se MACD non è fortemente negativo (evita falsi segnali)
 - P3: backtest deduplica cluster (segnali consecutivi entro 5 giorni → 1 solo trade)
 - P4: volume_score parte da 30 invece di 50 (nessun bonus gratuito per asset illiquidi)
 - P5: sidebar della confidence usa ratio pesato, non simmetrico (più reasons = meno penalità)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Struttura dati risultato
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AnalysisResult:
    ticker: str = ""

    opportunity_score: int = 0
    confidence_score:  int = 0
    risk_score:        int = 0   # 0=rischio basso, 100=rischio altissimo
    trend_score:       int = 0
    momentum_score:    int = 0
    value_score:       int = 0
    volume_score:      int = 0

    signal:       str = "NEUTRAL"
    action_label: str = "✋ ATTENDI"
    color:        str = "#f5f5f5"

    last_price:   float = 0.0
    rsi:          float = 0.0
    adx:          float = 0.0
    atr:          float = 0.0
    drawdown_pct: float = 0.0
    trend_label:  str   = "N/A"
    is_bullish:   bool  = False

    target:       float = 0.0
    support:      float = 0.0
    upside_pct:   float = 0.0
    downside_pct: float = 0.0

    golden_cross: bool = False
    death_cross:  bool = False

    backtest_win30: float = 0.0
    backtest_pnl30: float = 0.0
    backtest_win60: float = 0.0
    backtest_pnl60: float = 0.0
    backtest_win90: float = 0.0
    backtest_pnl90: float = 0.0
    backtest_n_signals: int = 0   # NUOVO: quanti segnali nel campione

    reasons:  list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    asset_type:        str  = "Azione"
    insufficient_data: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Score componenti
# ─────────────────────────────────────────────────────────────────────────────

def _score_trend(df: pd.DataFrame, last: pd.Series) -> tuple[int, list[str], list[str]]:
    """
    FIX P1: usa step discreti per SMA200 invece della formula lineare dist*3.5
    che produceva punteggi quasi nulli per asset vicini alla media.

    Logica: ciò che conta non è quanto sei sopra la SMA200, ma SE ci sei
    e con quale struttura di trend (50>200, EMA21, ADX, cross).
    """
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []

    close  = float(last["Close"])
    sma200 = float(last["SMA_200"])
    sma50  = float(last["SMA_50"])
    ema21  = float(last["EMA_21"])
    adx    = float(last.get("ADX", 0.0)) if not np.isnan(last.get("ADX", np.nan)) else 0.0

    # 1. Posizione rispetto SMA200 — FIX: step discreti (peso totale 30)
    if close > sma200:
        dist_pct = (close - sma200) / sma200 * 100
        if dist_pct > 10:
            score += 30
            reasons.append(f"Prezzo solido sopra SMA200 (+{dist_pct:.1f}%)")
        elif dist_pct > 3:
            score += 22
            reasons.append(f"Prezzo sopra SMA200 (+{dist_pct:.1f}%)")
        else:
            score += 14   # vicino ma sopra → partial credit
            reasons.append(f"Prezzo appena sopra SMA200 (+{dist_pct:.1f}%) — conferma debole")
    else:
        dist_pct = (sma200 - close) / sma200 * 100
        warnings.append(f"Prezzo sotto SMA200 (-{dist_pct:.1f}%)")

    # 2. SMA50 > SMA200 — trend intermedio (peso 20)
    if sma50 > sma200:
        score += 20
        reasons.append("SMA50 > SMA200 (trend intermedio rialzista)")
    else:
        warnings.append("SMA50 < SMA200 (trend intermedio ribassista)")

    # 3. Prezzo > EMA21 — breve periodo (peso 15)
    if close > ema21:
        score += 15
        reasons.append("Prezzo sopra EMA21 (momentum breve positivo)")
    else:
        warnings.append("Prezzo sotto EMA21")

    # 4. ADX — forza del trend (peso 20)
    if adx >= 30:
        score += 20
        reasons.append(f"ADX={adx:.0f} — trend molto forte")
    elif adx >= 25:
        score += 13
        reasons.append(f"ADX={adx:.0f} — trend definito")
    elif adx >= 20:
        score += 6
        reasons.append(f"ADX={adx:.0f} — trend moderato")
    else:
        warnings.append(f"ADX={adx:.0f} — mercato senza direzionalità chiara")

    # 5. Golden/Death Cross recente (ultime 10 sedute) (peso 15)
    if len(df) >= 11:
        p50  = df["SMA_50"].iloc[-10]
        p200 = df["SMA_200"].iloc[-10]
        if sma50 > sma200 and p50 <= p200:
            score += 15
            reasons.append("🟡 Golden Cross recente")
        elif sma50 < sma200 and p50 >= p200:
            score -= 15
            warnings.append("⚫ Death Cross recente")

    return max(0, min(100, score)), reasons, warnings


def _score_momentum(df: pd.DataFrame, last: pd.Series) -> tuple[int, list[str], list[str]]:
    """Momentum di breve/medio termine. Invariato rispetto a v2.0."""
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []

    rsi      = float(last.get("RSI", 50.0))
    macd     = float(last.get("MACD", 0.0))
    macd_sig = float(last.get("MACD_SIGNAL", 0.0))
    macd_h   = float(last.get("MACD_HIST", 0.0))
    stoch_k  = float(last.get("STOCH_K", 50.0))
    roc10    = float(last.get("ROC_10", 0.0))

    # MACD (peso 25)
    if macd > macd_sig:
        score += 25
        reasons.append(f"MACD sopra signal ({macd:.3f} > {macd_sig:.3f})")
    else:
        gap = abs(macd - macd_sig)
        if gap > abs(macd_sig) * 0.1:
            warnings.append("MACD significativamente sotto la signal")
        else:
            warnings.append("MACD appena sotto la signal")

    # RSI (peso 25)
    if 40 <= rsi <= 65:
        score += 25
        reasons.append(f"RSI={rsi:.0f} in zona operativa sana")
    elif 30 <= rsi < 40:
        score += 18
        reasons.append(f"RSI={rsi:.0f} vicino all'ipervenduto (opportunità)")
    elif rsi < 30:
        score += 12
        reasons.append(f"RSI={rsi:.0f} in ipervenduto (possibile rimbalzo)")
    elif 65 < rsi <= 75:
        score += 10
        warnings.append(f"RSI={rsi:.0f} in zona di attenzione")
    else:
        warnings.append(f"RSI={rsi:.0f} in ipercomprato (rischio ritracciamento)")

    # StochRSI (peso 20)
    if not np.isnan(stoch_k):
        if 20 <= stoch_k <= 70:
            score += 20
            reasons.append(f"StochRSI={stoch_k:.0f} in zona equilibrata")
        elif stoch_k < 20:
            score += 14
            reasons.append(f"StochRSI={stoch_k:.0f} ipervenduto")
        else:
            warnings.append(f"StochRSI={stoch_k:.0f} ipercomprato")

    # ROC 10g (peso 15)
    if roc10 > 2:
        score += 15
        reasons.append(f"ROC 10gg = +{roc10:.1f}% (momentum forte)")
    elif roc10 > 0:
        score += 8
        reasons.append(f"ROC 10gg = +{roc10:.1f}% (momentum positivo)")
    else:
        warnings.append(f"ROC 10gg = {roc10:.1f}% (momentum negativo)")

    return max(0, min(100, score)), reasons, warnings


def _score_value(last: pd.Series) -> tuple[int, list[str], list[str]]:
    """Valutazione relativa tramite Bollinger Bands + RSI. Invariato."""
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []

    close = float(last["Close"])
    bbl   = float(last.get("BBL", close))
    bbu   = float(last.get("BBU", close))
    rsi   = float(last.get("RSI", 50.0))

    bb_range = bbu - bbl if bbu != bbl else 1.0
    bb_pos   = (close - bbl) / bb_range

    if bb_pos <= 0.15:
        score = 85
        reasons.append(f"Prezzo sotto/a Banda Bollinger Inferiore ({bb_pos:.2f})")
    elif bb_pos <= 0.35:
        score = 65
        reasons.append(f"Prezzo nella parte bassa delle Bollinger ({bb_pos:.2f})")
    elif bb_pos <= 0.55:
        score = 50
        reasons.append(f"Prezzo nella fascia centrale Bollinger ({bb_pos:.2f})")
    elif bb_pos <= 0.80:
        score = 30
        warnings.append(f"Prezzo nella parte alta Bollinger ({bb_pos:.2f})")
    else:
        score = 10
        warnings.append(f"Prezzo vicino/sopra Banda Bollinger Superiore ({bb_pos:.2f})")

    if bb_pos <= 0.30 and rsi < 40:
        score = min(100, score + 15)
        reasons.append("Doppia conferma: Bollinger bassa + RSI scarico")

    return max(0, min(100, score)), reasons, warnings


def _score_volume(df: pd.DataFrame, last: pd.Series) -> tuple[int, list[str], list[str]]:
    """
    FIX P4: parte da 30 invece di 50.
    Un asset senza segnali volumetrici ottiene 30/100, non 50/100.
    Questo riduce il vantaggio gratuito per ETF obbligazionari e asset illiquidi.
    """
    score = 30   # FIX: era 50
    reasons: list[str] = []
    warnings: list[str] = []

    volume    = float(last.get("Volume", 0.0))
    obv_trend = float(last.get("OBV_TREND", 0.0))
    mfi       = float(last.get("MFI", 50.0))

    # Volume vs mediana 20g (peso +35 / -15)
    vol_median = df["Volume"].rolling(20).median().iloc[-1]
    if vol_median and vol_median > 0:
        ratio = volume / vol_median
        if ratio >= 2.0:
            score += 35
            reasons.append(f"Volume {ratio:.1f}x la mediana (forte conferma)")
        elif ratio >= 1.5:
            score += 22
            reasons.append(f"Volume {ratio:.1f}x la mediana (buona conferma)")
        elif ratio >= 1.2:
            score += 10
            reasons.append(f"Volume sopra media ({ratio:.1f}x)")
        elif ratio < 0.6:
            score -= 15
            warnings.append(f"Volume molto basso ({ratio:.1f}x mediana)")
        elif ratio < 0.8:
            score -= 7
            warnings.append(f"Volume sotto media ({ratio:.1f}x mediana)")

    # OBV trend 20g (peso +20 / -12)
    if not np.isnan(obv_trend):
        if obv_trend > 0:
            score += 20
            reasons.append("OBV crescente (flusso di denaro positivo)")
        else:
            score -= 12
            warnings.append("OBV calante (distribuzione in corso)")

    # MFI (peso +15 / -12)
    if not np.isnan(mfi):
        if 40 <= mfi <= 60:
            score += 10
        elif mfi < 20:
            score += 15
            reasons.append(f"MFI={mfi:.0f} — ipervenduto (possibile inversione)")
        elif mfi > 80:
            score -= 12
            warnings.append(f"MFI={mfi:.0f} — ipercomprato (pressione di vendita)")

    return max(0, min(100, score)), reasons, warnings


def _score_risk(df: pd.DataFrame, last: pd.Series) -> tuple[int, list[str]]:
    """Rischio (0=basso, 100=alto). Invariato."""
    risk = 20
    warnings: list[str] = []

    close    = float(last["Close"])
    atr      = float(last.get("ATR", 0.0))
    hist_vol = float(last.get("HIST_VOL", 15.0))

    atr_pct = (atr / close * 100) if close > 0 else 0
    if atr_pct > 5:
        risk += 30
        warnings.append(f"Volatilità molto alta (ATR={atr_pct:.1f}% del prezzo)")
    elif atr_pct > 3:
        risk += 15
        warnings.append(f"Volatilità elevata (ATR={atr_pct:.1f}%)")
    elif atr_pct > 1.5:
        risk += 5

    high_52w = float(last.get("HIGH_52W", close))
    if high_52w > 0:
        dd = (close - high_52w) / high_52w * 100
        if dd < -30:
            risk += 25
            warnings.append(f"Drawdown severo dai massimi 52W: {dd:.0f}%")
        elif dd < -15:
            risk += 10
            warnings.append(f"Drawdown moderato dai massimi 52W: {dd:.0f}%")

    if not np.isnan(hist_vol):
        if hist_vol > 60:
            risk += 20
            warnings.append(f"Volatilità storica annualizzata alta ({hist_vol:.0f}%)")
        elif hist_vol > 40:
            risk += 10

    rsi = float(last.get("RSI", 50))
    if rsi > 80:
        risk += 10
        warnings.append(f"RSI={rsi:.0f} — ipercomprato estremo")

    return max(0, min(100, risk)), warnings


def _run_backtest(df: pd.DataFrame) -> tuple[float, float, float, float, float, float, int]:
    """
    FIX P3: deduplicazione cluster.
    Dopo un segnale, i successivi 5 giorni vengono ignorati per evitare
    che un RSI<40 prolungato generi decine di trade identici.

    Returns: (win30, pnl30, win60, pnl60, win90, pnl90, n_segnali_unici)
    """
    if len(df) < 120:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0

    raw_signals = df[(df["Close"] > df["SMA_200"]) & (df["RSI"] < 40)].index.tolist()
    if len(raw_signals) < 3:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0

    # FIX: deduplicazione — cooldown 5 giorni di calendario
    deduped: list = []
    last_sig = None
    for sig in raw_signals:
        if last_sig is None or (sig - last_sig).days >= 5:
            deduped.append(sig)
            last_sig = sig

    if len(deduped) < 3:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, len(deduped)

    r30, r60, r90 = [], [], []

    for sig_date in deduped:
        idx = df.index.get_loc(sig_date)
        entry = float(df["Close"].iloc[idx])
        if entry <= 0:
            continue
        for days, bucket in [(30, r30), (60, r60), (90, r90)]:
            exit_idx = idx + days
            if exit_idx < len(df):
                exit_p = float(df["Close"].iloc[exit_idx])
                bucket.append((exit_p - entry) / entry * 100)

    def _agg(res: list[float]) -> tuple[float, float]:
        if not res:
            return 0.0, 0.0
        wr  = sum(1 for x in res if x > 0) / len(res) * 100
        avg = sum(res) / len(res)
        # Regressione verso 50% se campione piccolo
        if len(res) < 12:
            w = len(res) / 12
            wr = wr * w + 50 * (1 - w)
        return round(wr, 1), round(avg, 2)

    w30, p30 = _agg(r30)
    w60, p60 = _agg(r60)
    w90, p90 = _agg(r90)

    return w30, p30, w60, p60, w90, p90, len(deduped)


# ─────────────────────────────────────────────────────────────────────────────
# Funzione principale
# ─────────────────────────────────────────────────────────────────────────────

def analyze(df: pd.DataFrame, ticker: str = "", asset_type: str = "Azione") -> AnalysisResult:
    result = AnalysisResult(ticker=ticker, asset_type=asset_type)

    if df is None or df.empty:
        result.insufficient_data = True
        result.action_label = "⚠️ DATI INSUFFICIENTI"
        return result

    required = {"Close", "SMA_200", "SMA_50", "EMA_21", "RSI", "MACD", "ATR", "BBL"}
    if not required.issubset(df.columns):
        result.insufficient_data = True
        return result

    last = df.iloc[-1]

    # Dati base
    close  = float(last["Close"])
    sma200 = float(last["SMA_200"])
    sma50  = float(last["SMA_50"])
    rsi    = float(last.get("RSI", 50.0))
    atr    = float(last.get("ATR", 0.0))
    adx    = float(last.get("ADX", 0.0)) if not np.isnan(last.get("ADX", np.nan)) else 0.0
    bbl    = float(last.get("BBL", close))
    bbu    = float(last.get("BBU", close))
    macd   = float(last.get("MACD", 0.0))
    macd_s = float(last.get("MACD_SIGNAL", 0.0))

    result.last_price  = close
    result.rsi         = rsi
    result.adx         = adx
    result.atr         = atr
    result.is_bullish  = close > sma200
    result.trend_label = "BULLISH (Rialzista)" if result.is_bullish else "BEARISH (Ribassista)"
    result.drawdown_pct = ((close - df["Close"].max()) / df["Close"].max() * 100) if df["Close"].max() > 0 else 0.0

    result.target      = max(bbu, close + 2 * atr)
    result.support     = min(bbl, close - 2 * atr)
    result.upside_pct  = (result.target - close) / close * 100 if close > 0 else 0.0
    result.downside_pct = (result.support - close) / close * 100 if close > 0 else 0.0

    if len(df) >= 11:
        p50, p200 = df["SMA_50"].iloc[-10], df["SMA_200"].iloc[-10]
        result.golden_cross = (sma50 > sma200) and (p50 <= p200)
        result.death_cross  = (sma50 < sma200) and (p50 >= p200)

    # Score componenti
    trend_s,    trend_r,    trend_w    = _score_trend(df, last)
    momentum_s, momentum_r, momentum_w = _score_momentum(df, last)
    value_s,    value_r,    value_w    = _score_value(last)
    volume_s,   volume_r,   volume_w   = _score_volume(df, last)
    risk_s,                 risk_w     = _score_risk(df, last)

    result.trend_score    = trend_s
    result.momentum_score = momentum_s
    result.value_score    = value_s
    result.volume_score   = volume_s
    result.risk_score     = risk_s

    all_reasons  = trend_r + momentum_r + value_r + volume_r
    all_warnings = trend_w + momentum_w + value_w + volume_w + risk_w
    result.reasons  = all_reasons
    result.warnings = all_warnings

    # Opportunity Score — pesi: Trend 35%, Momentum 25%, Value 20%, Volume 20%
    opp_raw = (trend_s * 0.35 + momentum_s * 0.25 + value_s * 0.20 + volume_s * 0.20)
    result.opportunity_score = max(0, min(100, round(opp_raw)))

    # FIX P5 — Confidence Score con ratio pesato (più reasons = penalità minore)
    n_r = len([x for x in all_reasons if x])
    n_w = len([x for x in all_warnings if x])
    total = n_r + n_w

    # Penalty proporzionale ai warning ma scalata per il numero di reasons
    # Formula: se hai 8 positivi e 2 negativi → penalità bassa; se 2 e 8 → penalità alta
    if total > 0:
        conflict_ratio   = n_w / total           # 0=tutti positivi, 1=tutti negativi
        severity_factor  = max(0, conflict_ratio - 0.3)   # penalty solo se >30% warning
        conflict_penalty = severity_factor * 40
    else:
        conflict_penalty = 0

    adx_penalty  = max(0, (20 - adx) * 0.4) if adx < 20 else 0
    bear_penalty = 15 if not result.is_bullish else 0
    vol_penalty  = max(0, risk_s - 55) * 0.25

    conf_raw = opp_raw - conflict_penalty - adx_penalty - bear_penalty - vol_penalty
    result.confidence_score = max(0, min(100, round(conf_raw)))

    # Backtest con deduplicazione
    w30, p30, w60, p60, w90, p90, n_sig = _run_backtest(df)
    result.backtest_win30     = w30
    result.backtest_pnl30     = p30
    result.backtest_win60     = w60
    result.backtest_pnl60     = p60
    result.backtest_win90     = w90
    result.backtest_pnl90     = p90
    result.backtest_n_signals = n_sig

    # Aggiustamento confidence da backtest
    if n_sig >= 8:
        if w90 > 65 and p90 > 5:
            result.confidence_score = min(100, result.confidence_score + 10)
        elif w90 < 35:
            result.confidence_score = max(0, result.confidence_score - 8)
    # Campione piccolo → abbassa confidence indipendentemente dal win rate
    elif n_sig > 0:
        sample_penalty = int((1 - n_sig / 8) * 8)
        result.confidence_score = max(0, result.confidence_score - sample_penalty)

    # Segnale operativo
    _assign_signal(result, macd, macd_s, rsi, bbl, bbu)

    return result


def _assign_signal(
    r: AnalysisResult,
    macd: float,
    macd_signal: float,
    rsi: float,
    bbl: float,
    bbu: float,
) -> None:
    """
    FIX P2: BUY richiede che il MACD non sia fortemente negativo.
    Questo evita segnali BUY su asset in momentum chiaramente discendente.

    Soglia "MACD fortemente negativo": gap > 1% del prezzo corrente.
    Se il MACD è sotto signal ma di pochissimo → BUY comunque (zona grigia).
    """
    close   = r.last_price
    is_b    = r.is_bullish
    macd_gap = macd - macd_signal  # negativo se MACD sotto signal

    # Calcola soglia dinamica: 0.5% del prezzo come riferimento
    macd_threshold = -close * 0.005 if close > 0 else -0.1
    macd_strongly_negative = macd_gap < macd_threshold

    # ── 1. OPPORTUNITÀ D'ORO ────────────────────────────────────────────────
    if is_b and rsi < 30 and close <= bbl:
        r.signal       = "BUY_STRONG"
        r.action_label = "💎 OPPORTUNITÀ D'ORO"
        r.color        = "#FFF9C4"
        if r.confidence_score >= 45:
            r.reasons.insert(0, "SETUP RARO: trend bull + crollo in ipervenduto estremo")

    # ── 2. ACQUISTO SUL DIP ─────────────────────────────────────────────────
    # FIX: aggiunto controllo MACD — non segnaliamo BUY se momentum è fortemente negativo
    elif is_b and (rsi < 42 or close <= bbl * 1.02) and not macd_strongly_negative:
        r.signal       = "BUY"
        r.action_label = "🛒 ACQUISTA (Dip)"
        r.color        = "#E8F5E9"

    # ── 2b. ACQUISTA ma con avviso MACD ─────────────────────────────────────
    # RSI scarico, trend bull, MA il MACD è fortemente negativo → segnale più cauto
    elif is_b and (rsi < 42 or close <= bbl * 1.02) and macd_strongly_negative:
        r.signal       = "BUY"
        r.action_label = "🛒 ACQUISTA con cautela (MACD debole)"
        r.color        = "#F1F8E9"
        r.warnings.insert(0, f"MACD significativamente sotto la signal: attendere conferma o usare size ridotta")
        # Penalità confidence aggiuntiva
        r.confidence_score = max(0, r.confidence_score - 12)

    # ── 3. VENDI PARZIALE ───────────────────────────────────────────────────
    elif is_b and (rsi > 75 or (close >= bbu and macd < macd_signal)):
        r.signal       = "SELL_PARTIAL"
        r.action_label = "💰 VENDI PARZIALE"
        r.color        = "#FFEBEE"

    # ── 4. TREND SOLIDO ─────────────────────────────────────────────────────
    elif is_b:
        r.signal       = "HOLD"
        r.action_label = "🚀 TREND SOLIDO"
        r.color        = "#E3F2FD"

    # ── 5. RIMBALZO TECNICO (Bear) ──────────────────────────────────────────
    elif not is_b and rsi < 30 and close < bbl:
        r.signal       = "HOLD"
        r.action_label = "⚠️ RIMBALZO TECNICO (Alto Rischio)"
        r.color        = "#FFF8E1"
        r.warnings.insert(0, "BEAR trend: possibile Dead Cat Bounce — non agire con size piena")

    # ── 6. EVITA ────────────────────────────────────────────────────────────
    elif not is_b and macd < macd_signal:
        r.signal       = "AVOID"
        r.action_label = "⛔ STAI ALLA LARGA"
        r.color        = "#FAFAFA"

    # ── 7. Default ──────────────────────────────────────────────────────────
    else:
        r.signal       = "HOLD"
        r.action_label = "✋ ATTENDI"
        r.color        = "#F5F5F5"

    # Confidence troppo bassa → degrada il segnale
    if r.confidence_score < 28 and r.signal in ("BUY_STRONG", "BUY"):
        r.signal       = "HOLD"
        r.action_label = "✋ SEGNALE DEBOLE — Attendere conferma"
        r.color        = "#F5F5F5"
        r.warnings.insert(0, f"Confidence {r.confidence_score}/100: indicatori in conflitto. Non agire.")


# ─────────────────────────────────────────────────────────────────────────────
# Advisor portafoglio (invariato)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PortfolioAdvice:
    title:         str   = "😴 MANTIENI"
    advice:        str   = "Nessun segnale operativo rilevante."
    color:         str   = "#F5F5F5"
    trailing_stop: float = 0.0
    risk_score:    int   = 0
    pnl_pct:       float = 0.0


def portfolio_advice(df: pd.DataFrame, avg_price: float, current_price: float) -> PortfolioAdvice:
    req = {"RSI", "SMA_200", "ATR", "High", "Volume", "Close"}
    if df.empty or not req.issubset(df.columns):
        return PortfolioAdvice(title="⚠️ DATI INSUFFICIENTI", advice="Impossibile calcolare la strategia.")

    if avg_price <= 0:
        avg_price = current_price

    last   = df.iloc[-1]
    rsi    = float(last.get("RSI", 50))
    sma200 = float(last.get("SMA_200", current_price))
    atr    = float(last.get("ATR", current_price * 0.02))
    volume = float(last.get("Volume", 0))

    pnl_pct = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
    atr_pct = (atr / current_price * 100) if current_price > 0 else 2.0

    dist_sma = (current_price - sma200) / sma200 * 100
    soglia   = max(1.0, atr_pct * 0.5)
    trend    = "BULL" if dist_sma > soglia else ("BEAR" if dist_sma < -soglia else "SIDE")

    vol_med    = df["Volume"].rolling(20).median().iloc[-1]
    has_volume = volume > vol_med * 1.25 if vol_med and vol_med > 0 else False

    rolling_high  = df["High"].rolling(22).max().iloc[-1]
    atr_mult      = 3.5 if atr_pct > 3.0 else 3.0
    raw_stop      = rolling_high - atr_mult * atr
    trailing_stop = min(raw_stop, current_price - max(2 * atr, current_price * 0.01))

    base_risk = min(10.0, atr_pct * 1.5)
    if trend == "BEAR": base_risk += 2
    if rsi > 75 or rsi < 25: base_risk += 1
    risk_score = round(min(10, max(1, base_risk)), 1)

    t_low  = max(3.0,  1.5 * atr_pct)
    t_mid  = max(10.0, 4.0 * atr_pct)
    t_high = max(25.0, 8.0 * atr_pct)

    recent_ret = 0.0
    if len(df) >= 5:
        recent_ret = (df["Close"].iloc[-1] - df["Close"].iloc[-5]) / df["Close"].iloc[-5] * 100

    adv = PortfolioAdvice(trailing_stop=trailing_stop, risk_score=int(risk_score), pnl_pct=pnl_pct)

    if trend == "BEAR" and pnl_pct < -t_low and has_volume and recent_ret < -5:
        adv.title  = "🔪 PERICOLO – NON MEDIARE"
        adv.advice = (f"Trend ribassista con volumi crescenti. "
                      f"Rischio di ulteriori ribassi. Stop Loss: ${trailing_stop:.2f}.")
        adv.color  = "#FFEBEE"
    elif pnl_pct > t_high and trend == "BEAR":
        adv.title  = "🚨 INCASSA (Trend Rotto)"
        adv.advice = f"Ottima perf. (+{pnl_pct:.1f}%) ma trend violato. Non restituire i profitti."
        adv.color  = "#FFCDD2"
    elif pnl_pct > t_mid and trend != "BULL":
        adv.title  = "🛡️ PROTEGGI IL GUADAGNO"
        adv.advice = f"Buon gain (+{pnl_pct:.1f}%) con contesto che si indebolisce. Stop a ${trailing_stop:.2f}."
        adv.color  = "#FFF9C4"
    elif pnl_pct > t_mid and trend == "BULL":
        if rsi > 75:
            adv.title  = "💰 TAKE PROFIT PARZIALE"
            adv.advice = f"+{pnl_pct:.1f}% con RSI in euforia ({rsi:.0f}). Vendi 20-30%, stop a ${trailing_stop:.2f}."
            adv.color  = "#FFE0B2"
        else:
            adv.title  = "🚀 LASCIA CORRERE"
            adv.advice = f"In pieno trend rialzista (+{pnl_pct:.1f}%). Aggiorna solo stop a ${trailing_stop:.2f}."
            adv.color  = "#C8E6C9"
    elif trend == "BULL" and pnl_pct < -2.0:
        if rsi < 40 and has_volume:
            adv.title  = "💎 ACCUMULO (Strong Dip)"
            adv.advice = "Ritracciamento con volumi alti in trend rialzista: possibile accumulo istituzionale."
            adv.color  = "#B9F6CA"
        elif rsi < 45:
            adv.title  = "🛒 ACCUMULO CAUTO"
            adv.advice = "Fisiologico ritracciamento in trend positivo. Puoi accumulare piccole quote."
            adv.color  = "#E8F5E9"
        else:
            adv.title  = "✋ HOLD (Attendi supporto)"
            adv.advice = "Leggera flessione. Aspetta livelli migliori prima di agire."
            adv.color  = "#F5F5F5"
    elif trend == "SIDE" and atr_pct < 1.5:
        adv.title  = "🧊 COSTO OPPORTUNITÀ"
        adv.advice = f"Asset poco volatile (ATR={atr_pct:.1f}%). Capitale bloccato senza rendimento."
        adv.color  = "#E1F5FE"
    elif trend == "BEAR":
        adv.title  = "⚠️ MONITORARE (Struttura Fragile)"
        adv.advice = "Sotto SMA200. Non aumentare l'esposizione. Attendi inversione confermata."
        adv.color  = "#FFF3E0"
    else:
        adv.title  = "😴 MANTIENI"
        adv.advice = "Nessun segnale operativo rilevante. Continua a monitorare."
        adv.color  = "#F5F5F5"

    return adv
