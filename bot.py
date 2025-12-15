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
    Ritorna: (username_sito, chat_id)
    Funziona anche se l'utente è in stato STOP_.
    """
    chat_id = str(message.chat.id)
    # Cerca nel DB chi ha questo chat_id (anche se stoppato)
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
    website_user, chat_id = get_verified_user(message)
    
    if website_user:
        # Se l'utente esiste (anche se stoppato), lo RIATTIVIAMO
        # Riscriviamo l'ID pulito, rimuovendo eventuali STOP_
        db.save_chat_id(website_user, chat_id)
        
        msg = (f"✅ **Benvenuto {website_user}!**\n\n"
               f"Sei connesso e le **notifiche automatiche sono ATTIVE** (08:00 UTC).\n\n"
               f"**Comandi:**\n"
               f"/portafoglio - Analisi istantanea\n"
               f"/mercato - Scansione nuove opportunità\n"
               f"/stop - Disattiva SOLO il report automatico")
        bot.reply_to(message, msg, parse_mode="Markdown")
    else:
        bot.reply_to(message, f"⛔ **Utente non riconosciuto**\n\nChat ID: `{chat_id}`\n\nInseriscilo nelle impostazioni del sito per collegarti.", parse_mode="Markdown")

@bot.message_handler(commands=['stop'])
def stop_notifications(message):
    website_user, chat_id = get_verified_user(message)
    
    if website_user:
        # Usiamo la nuova funzione per mettere STOP_ davanti all'ID
        if db.disable_notifications(website_user, chat_id):
            bot.reply_to(message, "🔕 **Report giornaliero DISATTIVATO.**\n\nPuoi continuare a usare /portafoglio e /mercato manualmente.\nDigita /start per riattivare le notifiche automatiche.", parse_mode="Markdown")
        else:
            bot.reply_to(message, "Errore durante la disattivazione.")
    else:
        bot.reply_to(message, "Non sei registrato, quindi non hai notifiche attive.")

@bot.message_handler(commands=['portafoglio'])
def send_portfolio(message):
    username, chat_id = get_verified_user(message)
    
    if not username:
        bot.send_message(chat_id, f"⚠️ Non sei configurato. Vai sul sito per collegare l'account.", parse_mode="Markdown")
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
    print(f"--- ⏰ ESECUZIONE Report Giornaliero: {datetime.now()} ---")
    
    try:
        # Questa funzione ora esclude automaticamente chi ha STOP_ nell'ID
        users = db.get_users_with_telegram()
        
        if not users:
            print("-> Nessun utente telegram attivo (o tutti stoppati).")
            return
            
        print(f"-> Trovati {len(users)} utenti attivi. Inizio elaborazione...")

        # Scarica dati unici
        all_tickers = set(AUTO_SCAN_TICKERS)
        user_map = {} 
        
        for u, chat_id in users:
            pf, _ = db.get_portfolio_summary(u)
            user_map[u] = pf
            if pf: all_tickers.update(pf.keys())
        
        print(f"-> Scaricamento dati per {len(all_tickers)} asset...")
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
                    print(f"-> Inviato a {username}")
                except Exception as e:
                    print(f"-> Errore invio a {username}: {e}")
            else:
                print(f"-> Nessuna novità urgente per {username}")
                
    except Exception as e:
        print(f"ERROR CRITICAL in Daily Report: {e}")

# --- SCHEDULER ---

def run_scheduler():
    schedule.every().day.at("08:00").do(send_daily_report)
    print(f"🕒 Scheduler Attivo. Orario Server attuale: {datetime.now().strftime('%H:%M')}")
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except Exception as e:
            print(f"Scheduler Error: {e}")
            time.sleep(60)
