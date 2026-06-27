"""
Scoring Engine — InvestAI
Sistema di scoring multi-dimensionale, trasparente e spiegabile.

Ogni score è calcolato combinando più indicatori tecnici indipendenti.
I punteggi derivano solo da dati reali — nessuna formula "magica".
Conflitti tra indicatori abbassano automaticamente il Confidence Score.

Scores prodotti (0–100):
 - trend_score       : forza e qualità del trend primario
 - momentum_score    : momentum di breve/medio termine
 - value_score       : valutazione relativa (ipercomprato/ipervenduto)
 - volume_score      : conferma volumetrica
 - risk_score        : 0=basso rischio, 100=alto rischio  ← invertito rispetto agli altri
 - opportunity_score : sintesi pesata degli score positivi
 - confidence_score  : solidità complessiva del segnale (penalizza i conflitti)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Struttura dati del risultato
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    ticker: str = ""

    # Scores (0-100)
    opportunity_score: int = 0
    confidence_score:  int = 0
    risk_score:        int = 0   # 0=basso rischio, 100=altissimo rischio
    trend_score:       int = 0
    momentum_score:    int = 0
    value_score:       int = 0
    volume_score:      int = 0

    # Segnale operativo
    signal:     str = "NEUTRAL"   # BUY_STRONG | BUY | HOLD | SELL_PARTIAL | SELL | AVOID
    action_label: str = "✋ ATTENDI"
    color:      str = "#f5f5f5"

    # Dati tecnici chiave
    last_price:   float = 0.0
    rsi:          float = 0.0
    adx:          float = 0.0
    atr:          float = 0.0
    drawdown_pct: float = 0.0
    trend_label:  str   = "N/A"
    is_bullish:   bool  = False

    # Livelli
    target:        float = 0.0
    support:       float = 0.0
    upside_pct:    float = 0.0
    downside_pct:  float = 0.0

    # Golden/Death cross
    golden_cross:  bool = False
    death_cross:   bool = False

    # Backtest
    backtest_win30: float = 0.0
    backtest_pnl30: float = 0.0
    backtest_win60: float = 0.0
    backtest_pnl60: float = 0.0
    backtest_win90: float = 0.0
    backtest_pnl90: float = 0.0

    # Spiegazione testuale
    reasons:        list[str] = field(default_factory=list)
    warnings:       list[str] = field(default_factory=list)

    # Asset type
    asset_type: str = "Azione"

    # Flag per dati insufficienti
    insufficient_data: bool = False


# ---------------------------------------------------------------------------
# Funzioni di scoring componenti
# ---------------------------------------------------------------------------

def _score_trend(df: pd.DataFrame, last: pd.Series) -> tuple[int, list[str], list[str]]:
    """
    Valuta la forza del trend primario (0-100).
    Usa SMA200, SMA50, EMA21, ADX, Golden/Death Cross.
    """
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []

    close     = last["Close"]
    sma200    = last["SMA_200"]
    sma50     = last["SMA_50"]
    ema21     = last["EMA_21"]
    adx_val   = last["ADX"] if not np.isnan(last.get("ADX", np.nan)) else 0.0

    # 1. Posizione rispetto SMA200 (peso 35)
    if close > sma200:
        dist_pct = (close - sma200) / sma200 * 100
        sub = min(35, int(dist_pct * 3.5))
        score += sub
        reasons.append(f"Prezzo sopra SMA200 (+{dist_pct:.1f}%)")
    else:
        dist_pct = (sma200 - close) / sma200 * 100
        warnings.append(f"Prezzo sotto SMA200 (-{dist_pct:.1f}%)")

    # 2. SMA50 sopra SMA200 = trend intermedio positivo (peso 20)
    if sma50 > sma200:
        score += 20
        reasons.append("SMA50 > SMA200 (trend intermedio rialzista)")
    else:
        warnings.append("SMA50 < SMA200 (trend intermedio ribassista)")

    # 3. Prezzo sopra EMA21 = trend di breve periodo (peso 15)
    if close > ema21:
        score += 15
        reasons.append("Prezzo sopra EMA21 (momentum breve positivo)")
    else:
        warnings.append("Prezzo sotto EMA21")

    # 4. ADX (forza trend — sopra 25 = trend definito) (peso 20)
    if adx_val >= 30:
        score += 20
        reasons.append(f"ADX={adx_val:.0f} (trend molto forte)")
    elif adx_val >= 25:
        score += 12
        reasons.append(f"ADX={adx_val:.0f} (trend definito)")
    elif adx_val >= 20:
        score += 6
    else:
        warnings.append(f"ADX={adx_val:.0f} (mercato senza trend chiaro)")

    # 5. Golden/Death Cross recente (ultime 10 sedute) (peso 10)
    if len(df) >= 11:
        prev_sma50  = df["SMA_50"].iloc[-10]
        prev_sma200 = df["SMA_200"].iloc[-10]
        if sma50 > sma200 and prev_sma50 <= prev_sma200:
            score += 10
            reasons.append("🟡 Golden Cross recente (SMA50 ha superato SMA200)")
        elif sma50 < sma200 and prev_sma50 >= prev_sma200:
            score -= 10
            warnings.append("⚫ Death Cross recente (SMA50 ha incrociato al ribasso SMA200)")

    return max(0, min(100, score)), reasons, warnings


def _score_momentum(df: pd.DataFrame, last: pd.Series) -> tuple[int, list[str], list[str]]:
    """
    Valuta il momentum di breve/medio termine (0-100).
    Usa MACD, RSI, StochRSI, ROC.
    """
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []

    rsi       = last.get("RSI", 50.0)
    macd      = last.get("MACD", 0.0)
    macd_sig  = last.get("MACD_SIGNAL", 0.0)
    macd_hist = last.get("MACD_HIST", 0.0)
    stoch_k   = last.get("STOCH_K", 50.0)
    roc10     = last.get("ROC_10", 0.0)
    roc20     = last.get("ROC_20", 0.0)

    # 1. MACD sopra signal (peso 25)
    if macd > macd_sig:
        sub = 25
        if macd_hist > 0:
            reasons.append(f"MACD positivo e sopra la signal ({macd:.3f} > {macd_sig:.3f})")
        score += sub
    else:
        warnings.append("MACD sotto la signal (momentum negativo)")

    # 2. RSI zona operativa (peso 25)
    if 40 <= rsi <= 65:
        score += 25
        reasons.append(f"RSI={rsi:.0f} in zona operativa sana (40-65)")
    elif 30 <= rsi < 40:
        score += 15
        reasons.append(f"RSI={rsi:.0f} vicino alla zona di ipervenduto (opportunità)")
    elif rsi < 30:
        score += 10
        reasons.append(f"RSI={rsi:.0f} in ipervenduto (possibile rimbalzo tecnico)")
    elif 65 < rsi <= 75:
        score += 10
        warnings.append(f"RSI={rsi:.0f} in zona di attenzione")
    else:
        score += 0
        warnings.append(f"RSI={rsi:.0f} in ipercomprato (rischio ritracciamento)")

    # 3. Stochastic RSI (peso 20)
    if not np.isnan(stoch_k):
        if 20 <= stoch_k <= 70:
            score += 20
            reasons.append(f"StochRSI={stoch_k:.0f} in zona equilibrata")
        elif stoch_k < 20:
            score += 15
            reasons.append(f"StochRSI={stoch_k:.0f} in ipervenduto estremo")
        else:
            warnings.append(f"StochRSI={stoch_k:.0f} in ipercomprato")

    # 4. Rate of Change (peso 15 + 15)
    if roc10 > 0:
        score += min(15, int(roc10 * 1.5))
        reasons.append(f"ROC 10gg = +{roc10:.1f}% (momentum recente positivo)")
    else:
        warnings.append(f"ROC 10gg = {roc10:.1f}% (momentum recente negativo)")

    return max(0, min(100, score)), reasons, warnings


def _score_value(last: pd.Series) -> tuple[int, list[str], list[str]]:
    """
    Valuta il valore relativo rispetto alle Bollinger Bands (0-100).
    Un prezzo vicino alla banda inferiore è un valore migliore.
    """
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []

    close = last["Close"]
    bbl   = last.get("BBL", close)
    bbm   = last.get("BBM", close)
    bbu   = last.get("BBU", close)
    rsi   = last.get("RSI", 50.0)

    bb_range = bbu - bbl if bbu != bbl else 1.0
    bb_pos   = (close - bbl) / bb_range  # 0=banda inf, 1=banda sup

    if bb_pos <= 0.15:
        score = 85
        reasons.append(f"Prezzo vicino/sotto la Banda Bollinger Inferiore (posizione={bb_pos:.2f})")
    elif bb_pos <= 0.35:
        score = 65
        reasons.append(f"Prezzo nella parte bassa delle Bollinger (posizione={bb_pos:.2f})")
    elif bb_pos <= 0.55:
        score = 50
        reasons.append(f"Prezzo nella fascia centrale delle Bollinger ({bb_pos:.2f})")
    elif bb_pos <= 0.80:
        score = 30
        warnings.append(f"Prezzo nella parte alta delle Bollinger ({bb_pos:.2f})")
    else:
        score = 10
        warnings.append(f"Prezzo vicino/sopra la Banda Bollinger Superiore ({bb_pos:.2f})")

    # Bonus: doppia conferma con RSI
    if bb_pos <= 0.30 and rsi < 40:
        score = min(100, score + 15)
        reasons.append("Doppia conferma: prezzo basso + RSI scarico")

    return max(0, min(100, score)), reasons, warnings


def _score_volume(df: pd.DataFrame, last: pd.Series) -> tuple[int, list[str], list[str]]:
    """
    Valuta la conferma volumetrica (0-100).
    Usa OBV, MFI, e confronto volume corrente con mediana mobile.
    """
    score = 50  # Neutrale di default
    reasons: list[str] = []
    warnings: list[str] = []

    volume    = last.get("Volume", 0.0)
    obv_trend = last.get("OBV_TREND", 0.0)
    mfi       = last.get("MFI", 50.0)

    # 1. Volume corrente vs mediana 20g
    vol_series = df["Volume"]
    vol_median = vol_series.rolling(20).median().iloc[-1]
    if vol_median > 0:
        vol_ratio = volume / vol_median
        if vol_ratio >= 1.5:
            score += 25
            reasons.append(f"Volume {vol_ratio:.1f}x la mediana (conferma istituzionale)")
        elif vol_ratio >= 1.2:
            score += 10
            reasons.append(f"Volume leggermente sopra media ({vol_ratio:.1f}x)")
        elif vol_ratio < 0.7:
            score -= 10
            warnings.append(f"Volume basso ({vol_ratio:.1f}x mediana) — scarsa partecipazione")

    # 2. OBV trend (ultimi 20gg)
    if not np.isnan(obv_trend):
        if obv_trend > 0:
            score += 15
            reasons.append("OBV in crescita (denaro che entra nel titolo)")
        else:
            score -= 10
            warnings.append("OBV in calo (distribuzione in corso)")

    # 3. MFI (Money Flow Index)
    if not np.isnan(mfi):
        if 40 <= mfi <= 60:
            score += 10
        elif mfi > 80:
            score -= 10
            warnings.append(f"MFI={mfi:.0f} in ipercomprato (pressione di vendita)")
        elif mfi < 20:
            score += 15
            reasons.append(f"MFI={mfi:.0f} in ipervenduto (possibile inversione)")

    return max(0, min(100, score)), reasons, warnings


def _score_risk(df: pd.DataFrame, last: pd.Series) -> tuple[int, list[str]]:
    """
    Valuta il rischio (0=basso rischio, 100=alto rischio).
    Usa ATR%, drawdown dai massimi, volatilità storica.
    """
    risk = 20  # Base: rischio basso
    warnings: list[str] = []

    close    = last["Close"]
    atr      = last.get("ATR", 0.0)
    hist_vol = last.get("HIST_VOL", 15.0)

    # 1. Volatilità relativa (ATR come % del prezzo)
    atr_pct = (atr / close * 100) if close > 0 else 0
    if atr_pct > 5:
        risk += 30
        warnings.append(f"Volatilità molto alta (ATR={atr_pct:.1f}% del prezzo)")
    elif atr_pct > 3:
        risk += 15
        warnings.append(f"Volatilità elevata (ATR={atr_pct:.1f}%)")
    elif atr_pct > 1.5:
        risk += 5

    # 2. Drawdown dai massimi annuali
    high_52w = last.get("HIGH_52W", close)
    if high_52w > 0:
        dd = (close - high_52w) / high_52w * 100
        if dd < -30:
            risk += 25
            warnings.append(f"Drawdown severo dai massimi 52W: {dd:.0f}%")
        elif dd < -15:
            risk += 10
            warnings.append(f"Drawdown moderato dai massimi 52W: {dd:.0f}%")

    # 3. Volatilità storica annualizzata
    if not np.isnan(hist_vol):
        if hist_vol > 60:
            risk += 20
            warnings.append(f"Volatilità storica annualizzata molto alta ({hist_vol:.0f}%)")
        elif hist_vol > 40:
            risk += 10
        elif hist_vol < 15:
            pass  # Bassa volatilità = rischio contenuto (già coperto dalla base)

    # 4. RSI ipercomprato
    rsi = last.get("RSI", 50)
    if rsi > 80:
        risk += 10
        warnings.append(f"RSI={rsi:.0f}: estremo ipercomprato")

    return max(0, min(100, risk)), warnings


def _run_backtest(df: pd.DataFrame) -> tuple[float, float, float, float, float, float]:
    """
    Backtest del segnale di acquisto (trend rialzista + ipervenduto).
    Evita look-ahead bias: utilizza solo dati disponibili al momento del segnale.
    Abbassa confidence se campione piccolo (< 15 segnali).

    Returns: (win30, pnl30, win60, pnl60, win90, pnl90)
    """
    if len(df) < 100:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

    # Segnale: prezzo sopra SMA200 e RSI < 40
    signals = df[(df["Close"] > df["SMA_200"]) & (df["RSI"] < 40)].index.tolist()

    if len(signals) < 5:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

    results_30: list[float] = []
    results_60: list[float] = []
    results_90: list[float] = []

    for sig_date in signals:
        entry_idx   = df.index.get_loc(sig_date)
        entry_price = df["Close"].iloc[entry_idx]
        if entry_price <= 0:
            continue

        for days, results_list in [(30, results_30), (60, results_60), (90, results_90)]:
            exit_idx = entry_idx + days
            if exit_idx < len(df):
                exit_price = df["Close"].iloc[exit_idx]
                pnl = (exit_price - entry_price) / entry_price * 100
                results_list.append(pnl)

    def _agg(res: list[float]) -> tuple[float, float]:
        if not res:
            return 0.0, 0.0
        win_rate = sum(1 for x in res if x > 0) / len(res) * 100
        avg_pnl  = sum(res) / len(res)
        # Se campione piccolo, abbassa il win_rate verso 50% (regressione verso la media)
        if len(res) < 15:
            confidence_weight = len(res) / 15
            win_rate = win_rate * confidence_weight + 50 * (1 - confidence_weight)
        return round(win_rate, 1), round(avg_pnl, 2)

    w30, p30 = _agg(results_30)
    w60, p60 = _agg(results_60)
    w90, p90 = _agg(results_90)

    return w30, p30, w60, p60, w90, p90


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

def analyze(df: pd.DataFrame, ticker: str = "", asset_type: str = "Azione") -> AnalysisResult:
    """
    Analisi tecnica completa di un asset.

    Parameters
    ----------
    df          : DataFrame con indicatori già calcolati (output di compute_indicators)
    ticker      : stringa ticker (solo per etichettatura)
    asset_type  : tipo di asset (per eventuale adattamento futuro)

    Returns
    -------
    AnalysisResult con tutti gli score e la spiegazione testuale.
    """
    result = AnalysisResult(ticker=ticker, asset_type=asset_type)

    if df is None or df.empty:
        result.insufficient_data = True
        result.action_label = "⚠️ DATI INSUFFICIENTI"
        result.confidence_score = 0
        return result

    last = df.iloc[-1]

    # Verifica che le colonne minime esistano
    required = {"Close", "SMA_200", "RSI", "MACD", "ATR", "BBL"}
    if not required.issubset(df.columns):
        result.insufficient_data = True
        return result

    # -----------------------------------------------------------------------
    # Dati tecnici base
    # -----------------------------------------------------------------------
    close   = float(last["Close"])
    sma200  = float(last["SMA_200"])
    sma50   = float(last["SMA_50"])
    rsi     = float(last.get("RSI", 50.0))
    atr     = float(last.get("ATR", 0.0))
    adx     = float(last.get("ADX", 0.0)) if not np.isnan(last.get("ADX", np.nan)) else 0.0
    bbl     = float(last.get("BBL", close))
    bbu     = float(last.get("BBU", close))
    macd    = float(last.get("MACD", 0.0))
    macd_s  = float(last.get("MACD_SIGNAL", 0.0))

    result.last_price = close
    result.rsi        = rsi
    result.adx        = adx
    result.atr        = atr
    result.is_bullish = close > sma200
    result.trend_label = "BULLISH (Rialzista)" if result.is_bullish else "BEARISH (Ribassista)"

    # Drawdown dai massimi storici (nel dataset)
    max_price = df["Close"].max()
    result.drawdown_pct = ((close - max_price) / max_price * 100) if max_price > 0 else 0.0

    # Livelli tecnici
    result.target  = max(bbu, close + 2 * atr)
    result.support = min(bbl, close - 2 * atr)
    result.upside_pct   = (result.target - close) / close * 100 if close > 0 else 0.0
    result.downside_pct = (result.support - close) / close * 100 if close > 0 else 0.0

    # Golden / Death Cross
    if len(df) >= 11:
        prev_sma50  = df["SMA_50"].iloc[-10]
        prev_sma200 = df["SMA_200"].iloc[-10]
        result.golden_cross = (sma50 > sma200) and (prev_sma50 <= prev_sma200)
        result.death_cross  = (sma50 < sma200) and (prev_sma50 >= prev_sma200)

    # -----------------------------------------------------------------------
    # Calcolo dei 5 score componenti
    # -----------------------------------------------------------------------
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

    # Aggrega reasons e warnings
    all_reasons  = trend_r + momentum_r + value_r + volume_r
    all_warnings = trend_w + momentum_w + value_w + volume_w + risk_w
    result.reasons  = all_reasons
    result.warnings = all_warnings

    # -----------------------------------------------------------------------
    # Opportunity Score (ponderato)
    # Pesi: Trend 35%, Momentum 25%, Value 20%, Volume 20%
    # -----------------------------------------------------------------------
    opp_raw = (
        trend_s    * 0.35 +
        momentum_s * 0.25 +
        value_s    * 0.20 +
        volume_s   * 0.20
    )
    result.opportunity_score = max(0, min(100, round(opp_raw)))

    # -----------------------------------------------------------------------
    # Confidence Score
    # Parte dall'opportunity score, penalizzato da:
    # 1. Conflitti tra indicatori (warnings > reasons)
    # 2. Trend ribassista
    # 3. ADX basso (mercato senza direzionalità)
    # 4. Volatilità estrema
    # -----------------------------------------------------------------------
    n_reasons  = len([r for r in all_reasons if r])
    n_warnings = len([w for w in all_warnings if w])

    conflict_ratio = n_warnings / max(n_reasons + n_warnings, 1)
    conflict_penalty = conflict_ratio * 30  # Fino a -30 per conflitti massimi

    adx_penalty = max(0, (20 - adx) * 0.5) if adx < 20 else 0  # Penalità ADX basso
    bear_penalty = 15 if not result.is_bullish else 0
    vol_penalty  = max(0, risk_s - 50) * 0.3  # Penalità per rischio elevato

    conf_raw = opp_raw - conflict_penalty - adx_penalty - bear_penalty - vol_penalty
    result.confidence_score = max(0, min(100, round(conf_raw)))

    # -----------------------------------------------------------------------
    # Backtest
    # -----------------------------------------------------------------------
    w30, p30, w60, p60, w90, p90 = _run_backtest(df)
    result.backtest_win30 = w30
    result.backtest_pnl30 = p30
    result.backtest_win60 = w60
    result.backtest_pnl60 = p60
    result.backtest_win90 = w90
    result.backtest_pnl90 = p90

    # Bonus backtest al confidence score
    if w90 > 60 and p90 > 5:
        result.confidence_score = min(100, result.confidence_score + 8)
    elif w90 < 40:
        result.confidence_score = max(0, result.confidence_score - 5)

    # -----------------------------------------------------------------------
    # Segnale operativo
    # -----------------------------------------------------------------------
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
    Assegna il segnale operativo (BUY_STRONG | BUY | HOLD | SELL_PARTIAL | SELL | AVOID)
    combinando tutti i fattori analizzati.
    """
    close = r.last_price
    is_b  = r.is_bullish

    # --- PATTERN DI SEGNALE ---

    # 1. OPPORTUNITÀ D'ORO: trend bull + RSI estremo + sotto Bollinger inferiore
    if is_b and rsi < 30 and close <= bbl:
        r.signal       = "BUY_STRONG"
        r.action_label = "💎 OPPORTUNITÀ D'ORO"
        r.color        = "#FFF9C4"  # giallo morbido
        if r.confidence_score >= 50:
            r.reasons.insert(0, "SETUP RARO: trend rialzista + crollo in ipervenduto estremo")

    # 2. ACQUISTO SUL DIP: trend bull + RSI scarico o prezzo vicino a Bollinger inf
    elif is_b and (rsi < 42 or close <= bbl * 1.02):
        r.signal       = "BUY"
        r.action_label = "🛒 ACQUISTA (Dip)"
        r.color        = "#E8F5E9"

    # 3. VENDI PARZIALE: trend bull + ipercomprato
    elif is_b and (rsi > 75 or (close >= bbu and macd < macd_signal)):
        r.signal       = "SELL_PARTIAL"
        r.action_label = "💰 VENDI PARZIALE"
        r.color        = "#FFEBEE"

    # 4. TREND SOLIDO: bull + nessun estremo
    elif is_b:
        r.signal       = "HOLD"
        r.action_label = "🚀 TREND SOLIDO"
        r.color        = "#E3F2FD"

    # 5. TENTATIVO RISCHIOSO: bear + RSI estremo (possibile rimbalzo)
    elif not is_b and rsi < 30 and close < bbl:
        r.signal       = "HOLD"
        r.action_label = "⚠️ RIMBALZO TECNICO (Alto Rischio)"
        r.color        = "#FFF8E1"
        r.warnings.insert(0, "BEAR trend: qualsiasi rialzo potrebbe essere un Dead Cat Bounce")

    # 6. EVITA: bear + momentum negativo
    elif not is_b and macd < macd_signal:
        r.signal       = "AVOID"
        r.action_label = "⛔ STAI ALLA LARGA"
        r.color        = "#FAFAFA"

    # 7. Default
    else:
        r.signal       = "HOLD"
        r.action_label = "✋ ATTENDI"
        r.color        = "#F5F5F5"

    # Se confidence troppo bassa → abbassa l'aggressività del segnale
    if r.confidence_score < 30 and r.signal in ("BUY_STRONG", "BUY"):
        r.signal       = "HOLD"
        r.action_label = "✋ SEGNALE DEBOLE (Attendere conferma)"
        r.color        = "#F5F5F5"
        r.warnings.insert(0, f"Confidence bassa ({r.confidence_score}/100): indicatori in conflitto. Non agire.")


# ---------------------------------------------------------------------------
# Advisor portafoglio
# ---------------------------------------------------------------------------

@dataclass
class PortfolioAdvice:
    title:         str   = "😴 MANTIENI"
    advice:        str   = "Nessun segnale operativo rilevante."
    color:         str   = "#F5F5F5"
    trailing_stop: float = 0.0
    risk_score:    int   = 0   # 1-10
    pnl_pct:       float = 0.0


def portfolio_advice(df: pd.DataFrame, avg_price: float, current_price: float) -> PortfolioAdvice:
    """
    Consigli operativi per una posizione già aperta.
    """
    req = {"RSI", "SMA_200", "ATR", "High", "Volume", "Close"}
    if df.empty or not req.issubset(df.columns):
        return PortfolioAdvice(title="⚠️ DATI INSUFFICIENTI", advice="Impossibile calcolare la strategia.")

    if avg_price <= 0:
        avg_price = current_price

    last    = df.iloc[-1]
    rsi     = float(last.get("RSI", 50))
    sma200  = float(last.get("SMA_200", current_price))
    atr     = float(last.get("ATR", current_price * 0.02))
    volume  = float(last.get("Volume", 0))

    pnl_pct = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
    atr_pct = (atr / current_price * 100) if current_price > 0 else 2.0

    # Trend dinamico con soglia ATR
    dist_sma_pct = (current_price - sma200) / sma200 * 100
    soglia = max(1.0, atr_pct * 0.5)
    trend  = "BULL" if dist_sma_pct > soglia else ("BEAR" if dist_sma_pct < -soglia else "SIDE")

    # Volume vs mediana 20g
    vol_med    = df["Volume"].rolling(20).median().iloc[-1]
    has_volume = volume > vol_med * 1.25 if vol_med > 0 else False

    # Trailing stop (Chandelier Exit)
    rolling_high  = df["High"].rolling(22).max().iloc[-1]
    atr_mult      = 3.5 if atr_pct > 3.0 else 3.0
    raw_stop      = rolling_high - atr_mult * atr
    trailing_stop = min(raw_stop, current_price - max(2 * atr, current_price * 0.01))

    # Risk score 1-10
    base_risk = min(10.0, atr_pct * 1.5)
    if trend == "BEAR":
        base_risk += 2
    if rsi > 75 or rsi < 25:
        base_risk += 1
    risk_score = round(min(10, max(1, base_risk)), 1)

    # Soglie dinamiche P&L
    t_low  = max(3.0, 1.5 * atr_pct)
    t_mid  = max(10.0, 4 * atr_pct)
    t_high = max(25.0, 8 * atr_pct)

    recent_ret = 0.0
    if len(df) >= 5:
        recent_ret = (df["Close"].iloc[-1] - df["Close"].iloc[-5]) / df["Close"].iloc[-5] * 100

    advice = PortfolioAdvice(trailing_stop=trailing_stop, risk_score=int(risk_score), pnl_pct=pnl_pct)

    # --- DECISION ENGINE ---
    if trend == "BEAR" and pnl_pct < -t_low and has_volume and recent_ret < -5:
        advice.title  = "🔪 PERICOLO – NON MEDIARE"
        advice.advice = (f"Trend ribassista con volumi crescenti (distribuzione istituzionale). "
                         f"Rischio elevato di ulteriori ribassi. "
                         f"Stop Loss suggerito: ${trailing_stop:.2f}.")
        advice.color  = "#FFEBEE"

    elif pnl_pct > t_high and trend == "BEAR":
        advice.title  = "🚨 INCASSA (Trend Rotto)"
        advice.advice = (f"Ottima performance (+{pnl_pct:.1f}%) ma trend di lungo periodo violato. "
                         f"Non restituire i profitti al mercato. Valuta l'uscita.")
        advice.color  = "#FFCDD2"

    elif pnl_pct > t_mid and trend != "BULL":
        advice.title  = "🛡️ PROTEGGI IL GUADAGNO"
        advice.advice = (f"Buon guadagno (+{pnl_pct:.1f}%) in un contesto che si indebolisce. "
                         f"Stringi lo stop a ${trailing_stop:.2f} o vendi parzialmente.")
        advice.color  = "#FFF9C4"

    elif pnl_pct > t_mid and trend == "BULL":
        if rsi > 75:
            advice.title  = "💰 TAKE PROFIT PARZIALE"
            advice.advice = (f"Ottima performance (+{pnl_pct:.1f}%) con RSI in zona di euforia ({rsi:.0f}). "
                             f"Vendi 20-30% e lascia il resto con stop a ${trailing_stop:.2f}.")
            advice.color  = "#FFE0B2"
        else:
            advice.title  = "🚀 LASCIA CORRERE"
            advice.advice = (f"Sei in pieno trend rialzista (+{pnl_pct:.1f}%). "
                             f"Il trend è sano. Aggiorna solo lo stop a ${trailing_stop:.2f}.")
            advice.color  = "#C8E6C9"

    elif trend == "BULL" and pnl_pct < -2.0:
        if rsi < 40 and has_volume:
            advice.title  = "💎 ACCUMULO (Strong Dip)"
            advice.advice = "Ritracciamento con volumi alti in trend rialzista: possibile accumulo istituzionale."
            advice.color  = "#B9F6CA"
        elif rsi < 45:
            advice.title  = "🛒 ACCUMULO CAUTO"
            advice.advice = "Fisiologico ritracciamento in trend positivo. Puoi accumulare piccole quote."
            advice.color  = "#E8F5E9"
        else:
            advice.title  = "✋ HOLD (Attendi supporto)"
            advice.advice = "Leggera flessione. Aspetta livelli di supporto migliori prima di agire."
            advice.color  = "#F5F5F5"

    elif trend == "SIDE" and atr_pct < 1.5:
        advice.title  = "🧊 COSTO OPPORTUNITÀ"
        advice.advice = (f"L'asset si muove poco (ATR={atr_pct:.1f}%). "
                         f"Il capitale è bloccato senza rendimento. Valuta alternative più attive.")
        advice.color  = "#E1F5FE"

    elif trend == "BEAR":
        advice.title  = "⚠️ MONITORARE (Struttura Fragile)"
        advice.advice = "Sotto SMA200. Non aumentare l'esposizione. Attendi conferma di inversione."
        advice.color  = "#FFF3E0"

    else:
        advice.title  = "😴 MANTIENI"
        advice.advice = "Nessun segnale operativo rilevante. Continua a monitorare."
        advice.color  = "#F5F5F5"

    return advice
