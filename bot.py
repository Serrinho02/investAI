import telebot
import schedule
import time
import threading
from datetime import datetime
import pandas as pd

# Importiamo il Token e le funzioni dal "Cervello" (logic.py)
from logic import (
    DBManager, 
    get_data_raw, 
    evaluate_strategy_full, 
    generate_portfolio_advice, 
    AUTO_SCAN_TICKERS, 
    TELEGRAM_BOT_TOKEN
)

# Inizializza il bot con il token importato da logic.py
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
db = DBManager()

print("🤖 InvestAI Bot inizializzato (Attendere avvio thread in app.py)...")

# --- FUNZIONI DI UTILITÀ ---

def get_market_data_for_user(username):
    """Scarica i dati necessari per un utente specifico"""
    pf, _ = db.get_portfolio_summary(username)
    # Uniamo i ticker del portafoglio con quelli della scansione automatica
    tickers = set(AUTO_SCAN_TICKERS)
    if pf:
        tickers.update(pf.keys())
    return get_data_raw(list(tickers)), pf

# --- COMANDI INTERATTIVI ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = str(message.chat.id)
    username = message.from_user.username
    
    if not username:
        bot.reply_to(message, "⚠️ Errore: Non hai un username impostato su Telegram. Impostalo nelle opzioni di Telegram e riprova.")
        return
    
    # Salviamo l'ID se l'utente esiste nel DB
    # Nota: L'utente deve essersi prima registrato sul sito Streamlit!
    if db.save_chat_id(username, chat_id):
        bot.reply_to(message, f"✅ Benvenuto {username}! Chat ID salvato correttamente.\n\nRiceverai i report giornalieri alle 08:00.\nUsa:\n/portafoglio - Analisi tuoi asset\n/mercato - Scansione nuove opportunità")
    else:
        bot.reply_to(message, f"❌ Ciao {username}! Non ho trovato questo username nel Database.\n\nPrima registrati sul sito web InvestAI, poi torna qui e digita /start.")

@bot.message_handler(commands=['portafoglio'])
def send_portfolio(message):
    username = message.from_user.username
    chat_id = message.chat.id
    
    if not username:
        bot.send_message(chat_id, "Errore: Username Telegram mancante.")
        return

    bot.send_message(chat_id, "⏳ Analisi portafoglio in corso...")
    
    market_data, pf = get_market_data_for_user(username)
    
    if not pf:
        bot.send_message(chat_id, "Il tuo portafoglio è vuoto o non hai ancora registrato transazioni sul sito.")
        return

    msgs = []
    for t, data in pf.items():
        if t in market_data:
            cur_price = market_data[t]['Close'].iloc[-1]
            
            # 1. Analisi Strategica Portfolio (P&L)
            tit, adv, _ = generate_portfolio_advice(market_data[t], data['avg_price'], cur_price)
            
            # 2. Analisi Tecnica Completa (11 Valori)
            tl, act, col, pr, rsi, dd, reason, tgt, pot, risk_pr, risk_pot = evaluate_strategy_full(market_data[t])
            
            pnl = ((cur_price - data['avg_price']) / data['avg_price']) * 100
            
            # Emoji stato P&L
            emoji = "🟢" if pnl > 0 else "🔴"
            
            # Formattazione stringhe
            pot_str = f"+{pot:.1f}%" if pot > 0 else f"{pot:.1f}%"
            
            msg = (f"{emoji} <b>{t}</b>: {pnl:+.1f}%\n"
                   f"📢 <b>{tit}</b>\n"
                   f"🎯 Tgt: ${tgt:.2f} (<b>{pot_str}</b>)\n"
                   f"🔻 Risk: {risk_pot:.1f}%\n"
                   f"<i>{adv}</i>")
            msgs.append(msg)
            
    if msgs:
        full_msg = "💼 <b>STATO PORTAFOGLIO</b>\n\n" + "\n\n".join(msgs)
        # Telegram ha un limite di 4096 caratteri, se il messaggio è lungo potremmo doverlo spezzare, 
        # ma per ora assumiamo portafogli ragionevoli.
        try:
            bot.send_message(chat_id, full_msg, parse_mode="HTML")
        except Exception as e:
            bot.send_message(chat_id, f"Errore invio dati: {e}")
    else:
        bot.send_message(chat_id, "Impossibile scaricare i dati di mercato aggiornati per i tuoi asset.")

@bot.message_handler(commands=['mercato'])
def send_market_scan(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🔎 Scansione completa del mercato in corso... (richiede qualche secondo)")
    
    market_data = get_data_raw(AUTO_SCAN_TICKERS)
    opportunities = []
    
    for t in AUTO_SCAN_TICKERS:
        if t in market_data:
            # FIX: Estraiamo tutti e 11 i valori ritornati dalla nuova logic.py
            tl, act, col, pr, rsi, dd, reason, tgt, pot, risk_pr, risk_pot = evaluate_strategy_full(market_data[t])
            
            # Filtriamo solo segnali interessanti per non intasare la chat
            if "ORO" in act or "ACQUISTA" in act:
                icon = "💎" if "ORO" in act else "🟢"
                pot_str = f"+{pot:.1f}%"
                
                msg = (f"{icon} <b>{t}</b>: {act}\n"
                       f"Prezzo: ${pr:.2f} | RSI: {rsi:.0f}\n"
                       f"🎯 Target: ${tgt:.2f} (<b>{pot_str}</b>)\n"
                       f"🔻 Rischio: {risk_pot:.1f}%\n"
                       f"<i>{reason}</i>")
                opportunities.append(msg)
    
    if opportunities:
        full_msg = "🚀 <b>OCCASIONI DI MERCATO RILEVATE</b>\n\n" + "\n\n".join(opportunities)
        try:
            bot.send_message(chat_id, full_msg, parse_mode="HTML")
        except Exception as e:
            bot.send_message(chat_id, "Errore formattazione messaggio Telegram.")
    else:
        bot.send_message(chat_id, "😴 Il mercato dorme. Nessuna occasione 'Strong Buy' o 'Golden' rilevata al momento.")

# --- JOB GIORNALIERO (REPORT MATTUTINO) ---

def send_daily_report():
    print(f"--- ⏰ Avvio Job Report Giornaliero: {datetime.now()} ---")
    
    # Riconnessione sicura al DB per ottenere gli utenti
    try:
        users = db.get_users_with_telegram()
    except Exception as e:
        print(f"Errore DB nel job scheduler: {e}")
        return
    
    if not users:
        print("Nessun utente con Telegram configurato.")
        return

    # Ottimizzazione: Scarica dati per tutti i ticker unici in una volta sola
    all_tickers = set(AUTO_SCAN_TICKERS)
    user_map = {} # Cache per non ricaricare il pf due volte
    
    for u, chat_id in users:
        pf, _ = db.get_portfolio_summary(u)
        user_map[u] = pf
        if pf:
            all_tickers.update(pf.keys())
    
    print(f"Scaricamento dati per {len(all_tickers)} asset...")
    market_data = get_data_raw(list(all_tickers))
    
    for username, chat_id in users:
        messages = []
        pf = user_map.get(username, {})
        
        # 1. Analisi Portafoglio (Solo messaggi urgenti per la notifica push)
        if pf:
            for t, data in pf.items():
                if t in market_data:
                    cur_price = market_data[t]['Close'].iloc[-1]
                    tit, adv, _ = generate_portfolio_advice(market_data[t], data['avg_price'], cur_price)
                    
                    # Keywords che meritano una notifica mattutina
                    keywords_urgenti = ["VENDI", "INCASSA", "PROTEGGI", "VALUTA", "MEDIA", "ATTENZIONE", "MOONBAG"]
                    
                    if any(k in tit for k in keywords_urgenti):
                         pnl = ((cur_price - data['avg_price']) / data['avg_price']) * 100
                         emoji = "🚀" if "MOONBAG" in tit or "INCASSA" in tit else "⚠️"
                         messages.append(f"{emoji} <b>{t}</b> ({pnl:+.1f}%): {tit}")

        # 2. Analisi Mercato (Solo Oro e Acquisti forti per chi non ce l'ha in portafoglio)
        for t in AUTO_SCAN_TICKERS:
            if t in market_data and (not pf or t not in pf):
                # FIX: 11 Valori
                _, act, _, pr, rsi, _, _, tgt, pot, _, _ = evaluate_strategy_full(market_data[t])
                
                if "ORO" in act:
                    messages.append(f"💎 <b>{t} - GOLDEN OPPORTUNITY!</b> (+{pot:.1f}%)")
                elif "ACQUISTA" in act:
                    messages.append(f"🟢 <b>{t}</b>: {act} (+{pot:.1f}%)")
        
        if messages:
            full_msg = f"🌅 <b>Report Mattutino per {username}</b>\n\n" + "\n".join(messages)
            try:
                bot.send_message(chat_id, full_msg, parse_mode="HTML")
                print(f"-> Report inviato a {username}")
            except Exception as e:
                print(f"-> Errore invio a {username}: {e}")
        else:
            print(f"-> Nessuna novità urgente per {username}")

# --- GESTIONE THREADS ---

def run_scheduler():
    # Imposta l'orario del report automatico (Orario del Server, solitamente UTC)
    # Se sei in Italia e il server è UTC, le 08:00 UTC sono le 09:00/10:00 Italia.
    # Puoi aggiungere più orari se vuoi.
    schedule.every().day.at("08:00").do(send_daily_report) 
    
    print("🕒 Scheduler avviato. Report programmato per le 08:00 UTC.")
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except Exception as e:
            print(f"Errore nello scheduler loop: {e}")
            time.sleep(60)
