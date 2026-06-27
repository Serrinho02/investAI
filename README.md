# InvestAI v2.0 — Assistente Finanziario Personale

> ⚠️ **Disclaimer:** InvestAI è uno strumento informativo e **non costituisce consulenza finanziaria**.
> Le analisi si basano su indicatori tecnici storici. I rendimenti passati non garantiscono risultati futuri.

---

## Struttura del Progetto

```
investai/
├── app.py                  ← Applicazione Streamlit (entry point)
├── requirements.txt
├── data/                   ← Storage locale JSON (persistenza offline)
│   ├── transactions.json   ← Transazioni del portafoglio
│   ├── watchlist.json      ← Lista asset personalizzata
│   └── settings.json       ← Impostazioni (telegram chat_id, ecc.)
├── core/                   ← Layer infrastrutturale
│   ├── storage.py          ← Persistenza JSON atomica
│   ├── market_data.py      ← Download dati yfinance (cache + retry)
│   ├── portfolio.py        ← Calcolo portafoglio e storico
│   ├── assets.py           ← Catalogo asset e classificazione tipo
│   └── excel_report.py     ← Generatore report Excel
├── engine/                 ← Motore di analisi finanziaria
│   ├── indicators.py       ← Calcolo indicatori tecnici (20+)
│   └── scoring.py          ← Sistema di scoring multi-dimensionale
└── telegram/               ← Bot Telegram (opzionale)
    └── bot.py
```

---

## Installazione

```bash
pip install -r requirements.txt
```

## Avvio

```bash
streamlit run app.py
```

## Telegram (opzionale)

Il bot Telegram è completamente opzionale e **non rompe l'app** se non configurato.

Per abilitarlo:
1. Crea un bot su [@BotFather](https://t.me/botfather) e copia il token
2. Imposta la variabile d'ambiente:
   ```bash
   export TELEGRAM_TOKEN="il-tuo-token"
   ```
3. Avvia l'app, vai su **Impostazioni → Telegram** e salva il tuo Chat ID
   (ottienilo da [@userinfobot](https://t.me/userinfobot))

**Comandi disponibili:**
- `/start` — attiva le notifiche e salva il chat_id
- `/stop` — disattiva le notifiche
- `/portafoglio` — analisi istantanea del portafoglio
- `/mercato` — scansione opportunità
- `/help` — lista comandi

---

## Motore di Analisi

### Indicatori calcolati

| Categoria   | Indicatori |
|-------------|------------|
| Trend       | SMA200, SMA50, EMA21, EMA9, ADX, Golden/Death Cross |
| Momentum    | RSI, MACD, Stochastic RSI, ROC10, ROC20 |
| Volatilità  | ATR, Bollinger Bands, Volatilità Storica Ann. |
| Volume      | OBV, MFI, VWAP rolling, Volume vs Mediana |
| Livelli     | Supporti/Resistenze 20g/50g, Max/Min 52W, Pivot |

### Sistema di Scoring (0–100)

Ogni opportunità produce 5 score componenti:

| Score | Peso | Descrizione |
|-------|------|-------------|
| Trend Score | 35% | Forza del trend primario (SMA, ADX, cross) |
| Momentum Score | 25% | Qualità del momentum (MACD, RSI, StochRSI, ROC) |
| Value Score | 20% | Posizione relativa (Bollinger, RSI) |
| Volume Score | 20% | Conferma volumetrica (OBV, MFI, volume vs mediana) |
| Risk Score | — | 0=basso rischio, 100=altissimo (ATR, drawdown, vol. storica) |

Il **Confidence Score** parte dall'Opportunity Score e viene penalizzato da:
- Conflitti tra indicatori (warnings > reasons)
- Trend ribassista (-15 punti)
- ADX < 20 (mercato senza direzionalità)
- Risk Score elevato
- Backtest con win rate < 40%

### Backtest

Il backtest misura cosa è successo storicamente dopo segnali simili (trend bull + RSI < 40).
- Evita look-ahead bias
- Campioni < 15 segnali vengono regressati verso il 50% (ridge estimator)
- Mostra win rate e P&L medio a 30/60/90 giorni

---

## Storage Locale

Tutte le scritture su JSON sono **atomiche** (write-then-rename).
Non c'è nessun database esterno, nessuna autenticazione, nessuna connessione remota richiesta.

I file in `data/` possono essere backuppati manualmente o sincronizzati tramite cloud storage.

---

## Dipendenze rimosse rispetto alla v1

| Dipendenza | Motivo rimozione |
|------------|-----------------|
| supabase | Sostituita con storage JSON locale |
| psycopg2-binary | Nessun PostgreSQL remoto |
| st-supabase-connection | Nessun Supabase |
| passlib / bcrypt | Nessuna autenticazione utenti |
| requests | Non necessario |
| schedule | Mantenuto (usato dallo scheduler Telegram) |
