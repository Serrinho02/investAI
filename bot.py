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

# Inizializza il bot
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
db = DBManager()

print("🤖 InvestAI Bot inizializzato (Attendere avvio thread in app.py)...")

# --- FUNZIONI DI UTILITÀ ---

def get_verified_user(message):
    """
    Verifica se chi scrive ha configurato il Chat ID sul sito.
    Ritorna: (username_sito, chat_id) oppure (None, chat_id)
    """
    chat_id = str(message.chat.id)
    # Cerca nel DB chi ha questo chat_id
    website_username = db.get_user_by_chat_id(chat_id)
    return website_username, chat_id

def get_market_data_for_user(username):
    """Scarica i dati necessari per un utente specifico"""
    pf, _ = db.get_portfolio_summary(username)
    tickers = set(AUTO_SCAN_TICKERS)
    if pf:
        tickers.update(pf.keys())
    return get_data_raw(list(tickers)), pf

# --- COMANDI INTERATTIVI ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    # 1. Recupera l'utente VERO dal DB usando l'ID
    website_user, chat_id = get_verified_user(message)
    
    if website_user:
        # CASO 1: Utente già configurato sul sito
        bot.reply_to(message, f"✅ **Riconosciuto!**\n\nCiao **{website_user}**, sei correttamente collegato al database.\n\nPuoi usare:\n/portafoglio - Vedi i tuoi asset\n/mercato - Vedi occasioni generali", parse_mode="Markdown")
    else:
        # CASO 2: Utente non ancora configurato
        bot.reply_to(message, f"⛔ **Utente non riconosciuto**\n\nIl tuo Telegram Chat ID è: `{chat_id}`\n\n1. Copia questo numero.\n2. Vai sul sito InvestAI > Impostazioni.\n3. Incolla il numero e salva.\n4. Torna qui e scrivi /start.", parse_mode="Markdown")

@bot.message_handler(commands=['portafoglio'])
def send_portfolio(message):
    # 1. Identifica l'utente dal Chat ID
    username, chat_id = get_verified_user(message)
    
    if not username:
        bot.send_message(chat_id, f"⚠️ Non sei configurato. Il tuo ID è `{chat_id}`. Inseriscilo nelle impostazioni del sito.", parse_mode="Markdown")
        return

    bot.send_message(chat_id, f"⏳ Analisi portafoglio di **{username}** in corso...", parse_mode="Markdown")
    
    market_data, pf = get_market_data_for_user(username)
    
    if not pf:
        bot.send_message(chat_id, "Il tuo portafoglio è vuoto sul sito.")
        return

    msgs = []
    for t, data in pf.items():
        if t in market_data:
            cur_price = market_data[t]['Close'].iloc[-1]
            
            # Analisi
            tit, adv, _ = generate_portfolio_advice(market_data[t], data['avg_price'], cur_price)
            tl, act, col, pr, rsi, dd, reason, tgt, pot, risk_pr, risk_pot = evaluate_strategy_full(market_data[t])
            
            pnl = ((cur_price - data['avg_price']) / data['avg_price']) * 100
            emoji = "🟢" if pnl > 0 else "🔴"
            pot_str = f"+{pot:.1f}%" if pot > 0 else f"{pot:.1f}%"
            
            msg = (f"{emoji} <b>{t}</b>: {pnl:+.1f}%\n"
                   f"📢 <b>{tit}</b>\n"
                   f"🎯 Tgt: ${tgt:.2f} (<b>{pot_str}</b>)\n"
                   f"🔻 Risk: {risk_pot:.1f}%\n"
                   f"<i>{adv}</i>")
            msgs.append(msg)
            
    if msgs:
        full_msg = f"💼 <b>PORTAFOGLIO DI {username.upper()}</b>\n\n" + "\n\n".join(msgs)
        try:
            bot.send_message(chat_id, full_msg, parse_mode="HTML")
        except:
            bot.send_message(chat_id, "Errore invio dati.")
    else:
        bot.send_message(chat_id, "Impossibile scaricare dati aggiornati.")

@bot.message_handler(commands=['mercato'])
def send_market_scan(message):
    # Anche per il mercato controlliamo se è un utente autorizzato (opzionale, ma meglio per sicurezza)
    username, chat_id = get_verified_user(message)
    
    bot.send_message(chat_id, "🔎 Scansione mercato in corso...")
    
    market_data = get_data_raw(AUTO_SCAN_TICKERS)
    opportunities = []
    
    for t in AUTO_SCAN_TICKERS:
        if t in market_data:
            tl, act, col, pr, rsi, dd, reason, tgt, pot, risk_pr, risk_pot = evaluate_strategy_full(market_data[t])
            
            if "ORO" in act or "ACQUISTA" in act:
                icon = "💎" if "ORO" in act else "🟢"
                pot_str = f"+{pot:.1f}%"
                msg = (f"{icon} <b>{t}</b>: {act}\n"
                       f"Prezzo: ${pr:.2f} | RSI: {rsi:.0f}\n"
                       f"🎯 Upside: <b>{pot_str}</b>\n"
                       f"<i>{reason}</i>")
                opportunities.append(msg)
    
    if opportunities:
        full_msg = "🚀 <b>OCCASIONI RILEVATE</b>\n\n" + "\n\n".join(opportunities)
        bot.send_message(chat_id, full_msg, parse_mode="HTML")
    else:
        bot.send_message(chat_id, "Nessuna occasione evidente al momento.")

# --- JOB GIORNALIERO ---

def send_daily_report():
    print(f"--- ⏰ Report Giornaliero: {datetime.now()} ---")
    
    try:
        # Questa funzione ritorna (username, chat_id)
        users = db.get_users_with_telegram()
    except Exception as e:
        print(f"Errore DB: {e}")
        return
    
    if not users: return

    # Scarica dati unici
    all_tickers = set(AUTO_SCAN_TICKERS)
    user_map = {} 
    
    for u, chat_id in users:
        pf, _ = db.get_portfolio_summary(u)
        user_map[u] = pf
        if pf: all_tickers.update(pf.keys())
    
    market_data = get_data_raw(list(all_tickers))
    
    for username, chat_id in users:
        messages = []
        pf = user_map.get(username, {})
        
        # 1. Notifiche Portafoglio Urgenti
        if pf:
            for t, data in pf.items():
                if t in market_data:
                    cur_price = market_data[t]['Close'].iloc[-1]
                    tit, adv, _ = generate_portfolio_advice(market_data[t], data['avg_price'], cur_price)
                    
                    keywords_urgenti = ["VENDI", "INCASSA", "PROTEGGI", "MOONBAG"]
                    if any(k in tit for k in keywords_urgenti):
                         pnl = ((cur_price - data['avg_price']) / data['avg_price']) * 100
                         messages.append(f"🚨 <b>{t}</b> ({pnl:+.1f}%): {tit}")

        # 2. Notifiche Mercato (Solo ORO)
        for t in AUTO_SCAN_TICKERS:
            if t in market_data and (not pf or t not in pf):
                _, act, _, _, _, _, _, _, pot, _, _ = evaluate_strategy_full(market_data[t])
                if "ORO" in act:
                    messages.append(f"💎 <b>{t} - GOLDEN!</b> (+{pot:.1f}%)")
        
        if messages:
            full_msg = f"🌅 <b>Buongiorno {username}!</b>\n\n" + "\n".join(messages)
            try:
                bot.send_message(chat_id, full_msg, parse_mode="HTML")
            except: pass

# --- SCHEDULER ---

def run_scheduler():
    schedule.every().day.at("08:00").do(send_daily_report) 
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except: time.sleep(60)
