# Guida Deploy — InvestAI su GitHub + Streamlit Cloud

## ⚠️ Nota sulla sicurezza
Le credenziali (username, password, token Telegram) **NON vanno mai nel codice**.
Vivono esclusivamente in **Streamlit Cloud → App Settings → Secrets**.

---

## Passo 1 — Crea il repo su GitHub

1. Vai su [github.com/new](https://github.com/new)
2. Repository name: `investai` (o quello che preferisci)
3. Visibilità: **Private** (consigliato per dati personali)
4. **Non** aggiungere README / .gitignore (li hai già)
5. Clicca **Create repository**

---

## Passo 2 — Carica il codice su GitHub

Dalla cartella del progetto sul tuo computer:

```bash
cd /percorso/della/cartella/investai

# Inizializza git (solo la prima volta)
git init
git branch -M main

# Aggiungi tutti i file (il .gitignore esclude già secrets.toml)
git add .
git commit -m "InvestAI v2.0 — prima release"

# Collega al tuo repo GitHub (sostituisci USERNAME con il tuo)
git remote add origin https://github.com/USERNAME/investai.git

# Push
git push -u origin main
```

---

## Passo 3 — Configura Streamlit Cloud

1. Vai su [share.streamlit.io](https://share.streamlit.io) e accedi con GitHub
2. Clicca **New app**
3. Scegli il tuo repo `investai`, branch `main`, file `app.py`
4. Clicca **Advanced settings**

### Secrets (FONDAMENTALE)

Nella sezione **Secrets**, incolla **esattamente** questo:

```toml
[auth]
username = "nicola"
password_hash = "ad1cfa0eb10e2bc60f4057fb7b3e35318bcd05ab5576758670d5ccbc14a88380"

[telegram]
token = ""
```

> Il `password_hash` è SHA-256 di `Canguro22!`
> Per cambiare password in futuro, genera il nuovo hash con:
> ```bash
> python3 -c "import hashlib; print(hashlib.sha256('NuovaPassword'.encode()).hexdigest())"
> ```
> e aggiorna solo la riga `password_hash` nelle Secrets.

5. Clicca **Save** poi **Deploy**

---

## Passo 4 — Usa l'app

Streamlit Cloud ti dà un URL tipo `https://investai-xyz.streamlit.app`

Aprendo quell'URL vedrai la pagina di login:
- **Username:** `nicola`
- **Password:** `Canguro22!`

---

## Aggiornamenti futuri

Quando modifichi il codice in locale:

```bash
git add .
git commit -m "Descrizione modifica"
git push
```

Streamlit Cloud si aggiorna automaticamente.

---

## Telegram (opzionale)

Se vuoi attivare il bot Telegram:
1. Crea un bot con [@BotFather](https://t.me/botfather), copia il token
2. Nelle Secrets di Streamlit Cloud, aggiorna:
   ```toml
   [telegram]
   token = "1234567890:AABBccdd..."
   ```
3. Salva le Secrets → l'app si riavvia automaticamente
4. Apri nell'app **⚙️ Impostazioni → Telegram**, salva il tuo Chat ID
5. Manda `/start` al tuo bot su Telegram

