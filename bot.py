import telebot
import schedule
import time
from datetime import datetime
from logic import DBManager, get_data_raw, evaluate_strategy_full, generate_portfolio_advice, AUTO_SCAN_TICKERS, TELEGRAM_BOT_TOKEN

# Inizializza il bot (Globale, così è accessibile quando importato)
# Se il token manca (es. build time), evito il crash immediato
if TELEGRAM_BOT_TOKEN:
    bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
else:
    bot = None
    print("⚠️ WARNING: Telegram Token non trovato. Il bot non partirà.")

db = DBManager()

# --- FUNZIONI LOGICA ---

def get_market_data_for_user(username):
    pf, _ = db.get_portfolio_summary(username)
    tickers = set(AUTO_SCAN_TICKERS)
    tickers.update(pf.keys())
    return get_data_raw(list(tickers)), pf

# --- FUNZIONI COMANDI BOT (Decorators) ---
# I decorator funzionano solo se 'bot' esiste.
if bot:
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        chat_id = str(message.chat.id)
        username = message.from_user.username
        if username and db.save_chat_id(username, chat_id):
            bot.reply_to(message, f"Benvenuto {username}! Chat ID salvato.")
        else:
            bot.reply_to(message, "Ciao! Assicurati di avere un username Telegram e di esserti registrato sul sito.")

    @bot.message_handler(commands=['portafoglio'])
    def send_portfolio(message):
        username = message.from_user.username
        chat_id = message.chat.id
        if not username: return
        
        bot.send_message(chat_id, "⏳ Analisi portafoglio...")
        market_data, pf = get_market_data_for_user(username)
        
        if not pf:
            bot.send_message(chat_id, "Portafoglio vuoto.")
            return

        msgs = []
        for t, data in pf.items():
            if t in market_data:
                cur = market_data[t]['Close'].iloc[-1]
                tit, adv, _ = generate_portfolio_advice(market_data[t], data['avg_price'], cur)
                _, _, _, _, _, _, _, tgt, pot, _, risk_pot = evaluate_strategy_full(market_data[t])
                pnl = ((cur - data['avg_price']) / data['avg_price']) * 100
                
                emoji = "🟢" if pnl > 0 else "🔴"
                msg = f"{emoji} <b>{t}</b>: {pnl:+.1f}%\n📢 <b>{tit}</b>\n🎯 Tgt: ${tgt:.2f} (+{pot:.1f}%) | 🔻 Risk: {risk_pot:.1f}%\n<i>{adv}</i>"
                msgs.append(msg)
        
        if msgs:
            bot.send_message(chat_id, "💼 <b>PORTAFOGLIO</b>\n\n" + "\n\n".join(msgs), parse_mode="HTML")

    @bot.message_handler(commands=['mercato'])
    def send_market_scan(message):
        chat_id = message.chat.id
        bot.send_message(chat_id, "🔎 Scansione mercato...")
        market_data = get_data_raw(AUTO_SCAN_TICKERS)
        opps = []
        for t in AUTO_SCAN_TICKERS:
            if t in market_data:
                _, act, _, pr, rsi, _, reason, tgt, pot, _, risk_pot = evaluate_strategy_full(market_data[t])
                if "ORO" in act or "ACQUISTA" in act:
                    icon = "💎" if "ORO" in act else "🟢"
                    msg = f"{icon} <b>{t}</b>: {act}\nPrice: ${pr:.2f} | RSI: {rsi:.0f}\n🎯 Tgt: ${tgt:.2f} (+{pot:.1f}%) | 🔻 Risk: {risk_pot:.1f}%\n<i>{reason}</i>"
                    opps.append(msg)
        
        if opps:
            bot.send_message(chat_id, "🚀 <b>OCCASIONI</b>\n\n" + "\n\n".join(opps), parse_mode="HTML")
        else:
            bot.send_message(chat_id, "Nessuna occasione rilevante.")

# --- FUNZIONI DI AVVIO (Richiamate da app.py) ---

def send_daily_report():
    if not bot: return
    print(f"--- Report Giornaliero: {datetime.now()} ---")
    users = db.get_users_with_telegram()
    
    all_tickers = set(AUTO_SCAN_TICKERS)
    for u, _ in users:
        pf, _ = db.get_portfolio_summary(u)
        all_tickers.update(pf.keys())
    
    market_data = get_data_raw(list(all_tickers))
    
    for username, chat_id in users:
        msgs = []
        pf, _ = db.get_portfolio_summary(username)
        
        # 1. Portafoglio Urgenti
        if pf:
            for t, data in pf.items():
                if t in market_data:
                    cur = market_data[t]['Close'].iloc[-1]
                    tit, adv, _ = generate_portfolio_advice(market_data[t], data['avg_price'], cur)
                    if any(k in tit for k in ["VENDI", "INCASSA", "PROTEGGI", "VALUTA", "MEDIA", "MOONBAG"]):
                         pnl = ((cur - data['avg_price']) / data['avg_price']) * 100
                         emoji = "🚀" if "MOONBAG" in tit or "INCASSA" in tit else "⚠️"
                         msgs.append(f"{emoji} <b>{t}</b> ({pnl:+.1f}%): {tit}")

        # 2. Mercato
        for t in AUTO_SCAN_TICKERS:
            if t in market_data and (not pf or t not in pf):
                _, act, _, _, _, _, _, _, pot, _, _ = evaluate_strategy_full(market_data[t])
                if "ORO" in act: msgs.append(f"💎 <b>{t} - GOLDEN!</b> (+{pot:.1f}%)")
                elif "ACQUISTA" in act: msgs.append(f"🟢 <b>{t}</b>: {act} (+{pot:.1f}%)")
        
        if msgs:
            try:
                bot.send_message(chat_id, f"🌅 <b>Report {username}</b>\n\n" + "\n".join(msgs), parse_mode="HTML")
            except: pass

def run_scheduler():
    """Funzione che verrà lanciata in un thread separato"""
    schedule.every().day.at("08:00").do(send_daily_report)
    while True:
        schedule.run_pending()
        time.sleep(60)

def start_bot_polling():
    """Funzione wrapper per avviare il bot"""
    if bot:
        try:
            print("🤖 Bot Polling Started...")
            bot.infinity_polling()
        except Exception as e:
            print(f"❌ Errore Bot Polling: {e}")
