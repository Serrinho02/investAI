import telebot
import schedule
import time
import threading
from datetime import datetime
from logic import DBManager, get_data_raw, evaluate_strategy_full, generate_portfolio_advice, AUTO_SCAN_TICKERS, TELEGRAM_BOT_TOKEN

# Inizializza il bot con la libreria telebot
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
db = DBManager()

print("🤖 InvestAI Bot avviato e in ascolto...")

# --- FUNZIONI DI UTILITÀ ---

def get_market_data_for_user(username):
    """Scarica i dati necessari per un utente specifico"""
    pf, _ = db.get_portfolio_summary(username)
    tickers = set(AUTO_SCAN_TICKERS)
    tickers.update(pf.keys())
    return get_data_raw(list(tickers)), pf

# --- COMANDI INTERATTIVI ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = str(message.chat.id)
    username = message.from_user.username
    
    # Salviamo l'ID se l'utente esiste nel DB
    # Nota: Assumiamo che l'username Telegram corrisponda a quello del DB
    if username and db.save_chat_id(username, chat_id):
        bot.reply_to(message, f"Benvenuto {username}! Chat ID salvato. Riceverai i report giornalieri.\nUsa /portafoglio o /mercato per analisi istantanee.")
    else:
        bot.reply_to(message, "Ciao! Non ho trovato il tuo username nel Database o non hai un username Telegram impostato.\nAssicurati di registrarti sul sito con lo stesso username.")

@bot.message_handler(commands=['portafoglio'])
def send_portfolio(message):
    username = message.from_user.username
    chat_id = message.chat.id
    
    if not username:
        bot.send_message(chat_id, "Errore: Non hai un username Telegram impostato.")
        return

    bot.send_message(chat_id, "⏳ Analisi portafoglio in corso...")
    
    market_data, pf = get_market_data_for_user(username)
    
    if not pf:
        bot.send_message(chat_id, "Il tuo portafoglio è vuoto.")
        return

    msgs = []
    for t, data in pf.items():
        if t in market_data:
            cur_price = market_data[t]['Close'].iloc[-1]
            # 1. Analisi Portfolio (P&L)
            tit, adv, _ = generate_portfolio_advice(market_data[t], data['avg_price'], cur_price)
            
            # 2. Analisi Tecnica (Target & Rischio) - Estraiamo 11 valori
            _, _, _, _, _, _, _, tgt, pot, risk_pr, risk_pot = evaluate_strategy_full(market_data[t])
            
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
        bot.send_message(chat_id, full_msg, parse_mode="HTML")
    else:
        bot.send_message(chat_id, "Impossibile scaricare i dati aggiornati.")

@bot.message_handler(commands=['mercato'])
def send_market_scan(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "🔎 Scansione mercato in corso... attendere prego.")
    
    market_data = get_data_raw(AUTO_SCAN_TICKERS)
    opportunities = []
    
    for t in AUTO_SCAN_TICKERS:
        if t in market_data:
            # FIX: Estraiamo 11 valori
            tl, act, col, pr, rsi, dd, reason, tgt, pot, risk_pr, risk_pot = evaluate_strategy_full(market_data[t])
            
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
        full_msg = "🚀 <b>OCCASIONI DI MERCATO</b>\n\n" + "\n\n".join(opportunities)
        bot.send_message(chat_id, full_msg, parse_mode="HTML")
    else:
        bot.send_message(chat_id, "Nessuna occasione evidente al momento.")

# --- JOB GIORNALIERO (REPORT) ---

def send_daily_report():
    print(f"--- Invio Report Giornaliero: {datetime.now()} ---")
    users = db.get_users_with_telegram()
    
    # Scarica dati per tutti (ottimizzazione)
    all_tickers = set(AUTO_SCAN_TICKERS)
    for u, _ in users:
        pf, _ = db.get_portfolio_summary(u)
        all_tickers.update(pf.keys())
    
    market_data = get_data_raw(list(all_tickers))
    
    for username, chat_id in users:
        messages = []
        pf, _ = db.get_portfolio_summary(username)
        
        # 1. Analisi Portafoglio (Solo Urgenze)
        if pf:
            for t, data in pf.items():
                if t in market_data:
                    cur_price = market_data[t]['Close'].iloc[-1]
                    tit, adv, _ = generate_portfolio_advice(market_data[t], data['avg_price'], cur_price)
                    
                    keywords_urgenti = ["VENDI", "INCASSA", "PROTEGGI", "VALUTA", "MEDIA", "ATTENZIONE", "MOONBAG"]
                    if any(k in tit for k in keywords_urgenti):
                         pnl = ((cur_price - data['avg_price']) / data['avg_price']) * 100
                         emoji = "🚀" if "MOONBAG" in tit or "INCASSA" in tit else "⚠️"
                         messages.append(f"{emoji} <b>{t}</b> ({pnl:+.1f}%): {tit}")

        # 2. Analisi Mercato (Solo Oro e Acquisti)
        for t in AUTO_SCAN_TICKERS:
            if t in market_data and (not pf or t not in pf):
                # FIX: Estraiamo 11 valori
                _, act, _, pr, rsi, _, _, tgt, pot, _, _ = evaluate_strategy_full(market_data[t])
                
                if "ORO" in act:
                    messages.append(f"💎 <b>{t} - GOLDEN OPPORTUNITY!</b> (+{pot:.1f}%)")
                elif "ACQUISTA" in act:
                    messages.append(f"🟢 <b>{t}</b>: {act} (+{pot:.1f}%)")
        
        if messages:
            full_msg = f"🌅 <b>Report Mattutino per {username}</b>\n\n" + "\n".join(messages)
            try:
                bot.send_message(chat_id, full_msg, parse_mode="HTML")
                print(f"-> Inviato a {username}")
            except:
                print(f"-> Errore invio a {username}")

# --- GESTIONE THREADS ---

def run_scheduler():
    # Imposta l'orario del report automatico
    schedule.every().day.at("08:00").do(send_daily_report) # Orario Server
    while True:
        schedule.run_pending()
        time.sleep(60)

