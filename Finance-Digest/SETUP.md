# Finance Digest Bot — Setup Guide

## Prerequisites

- Linux server with an NVIDIA GPU (8 GB VRAM recommended)
- A Discord account with a server you own
- Free API keys for Alpha Vantage and Finnhub (links below)

---

## Step 1 — Install Ollama

Ollama runs the LLM locally on your GPU.

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Start and enable Ollama as a system service:

```bash
sudo systemctl enable ollama
sudo systemctl start ollama
```

---

## Step 2 — Download a Model

Choose based on your VRAM:

| VRAM | Command | Notes |
|---|---|---|
| 8 GB | `ollama pull qwen2.5:7b` | Recommended for GTX 1070 — fits at ~4.7 GB |
| 12–16 GB | `ollama pull qwen2.5:14b` | Stronger analytical reasoning |
| 16 GB+ | `ollama pull qwen2.5:32b` | Best quality |

Test the model works:

```bash
ollama run qwen2.5:7b "What is a P/E ratio?"
```

---

## Step 3 — Verify the Ollama API

Ollama exposes an OpenAI-compatible API on port 11434. No API key needed.

```bash
# List available models
curl http://localhost:11434/v1/models

# Test a completion
curl -X POST http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen2.5:7b", "messages": [{"role": "user", "content": "What is EBITDA?"}]}'
```

---

## Step 4 — Create a Discord Bot

1. Go to [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** — give it a name (e.g. `Finance Digest`)
3. Go to **Bot** in the left sidebar → click **Reset Token** → copy the token
4. Scroll down and enable **Message Content Intent**
5. Go to **OAuth2 → URL Generator**:
   - Scopes: `bot` + `applications.commands`
   - Bot Permissions: `Send Messages`, `Read Messages/View Channels`, `Embed Links`
6. Copy the generated URL and open it in your browser to invite the bot to your server

**Get your IDs** (enable Developer Mode in Discord Settings → Advanced):
- **Server ID**: Right-click your server → Copy Server ID
- **Channel ID**: Right-click the channel for briefings → Copy Channel ID

---

## Step 5 — Get Financial API Keys

Both are free:

| API | Sign Up | Free Tier |
|---|---|---|
| Alpha Vantage | [alphavantage.co/support/#api-key](https://www.alphavantage.co/support/#api-key) | 25 requests/day |
| Finnhub | [finnhub.io/register](https://finnhub.io/register) | 60 requests/min |

---

## Step 6 — Set Up the Bot

Navigate to the project directory:

```bash
cd /srv/network-drive/projects/OpenClaw-Finance-Digest
```

Run the setup script to create the Python virtual environment:

```bash
bash setup.sh
```

Create your `.env` configuration file:

```bash
cp .env.example .env
nano .env
```

Fill in all values in `.env`:

```env
DISCORD_TOKEN=        # from Step 4
DISCORD_GUILD_ID=     # your server ID
BRIEFING_CHANNEL_ID=  # channel for morning briefings

OLLAMA_API_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen2.5:7b   # must match what you pulled in Step 2

ALPHA_VANTAGE_KEY=    # from Step 5
FINNHUB_KEY=          # from Step 5

BRIEFING_TIME=07:00
BRIEFING_TIMEZONE=America/New_York

DB_PATH=./finance_digest.db
LOG_PATH=./logs/finance_digest.log
SEC_USER_AGENT=FinanceDigestBot/1.0 your@email.com

SITE_PUBLIC_URL=    # public URL of the site-generator (e.g. https://finance.yourdomain.com)
```

---

## Step 7 — Set Up the Site Generator

The site generator is a separate Node.js server that serves the analysis pages published by the bot.

Navigate to the site-generator directory:

```bash
cd /srv/network-drive/projects/site-generator
```

Install dependencies (first time only):

```bash
npm install
```

Build any existing pages and start the server:

```bash
npm run dev
```

The server runs on `http://localhost:3000`. You can verify it's working by opening that URL in your browser — you should see the analyses index page.

**To keep it running in the background**, install it as a systemd service:

```bash
sudo nano /etc/systemd/system/site-generator.service
```

Paste the following:

```ini
[Unit]
Description=Finance Digest Site Generator
After=network.target

[Service]
WorkingDirectory=/srv/network-drive/projects/site-generator
ExecStart=/usr/bin/node src/server.js
Restart=on-failure
User=christopherpas
Environment=PORT=3000

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable site-generator
sudo systemctl start site-generator
```

Check it is running:

```bash
sudo systemctl status site-generator
```

**Add the site URL to your Finance-Digest `.env`** so the bot can include page links in Discord messages:

```env
SITE_PUBLIC_URL=https://your-cloudflare-tunnel-domain.com
```

Leave it blank if you haven't set up a domain yet — the bot will still publish pages, it just won't include the link in Discord.

---

## Step 8 — Test the Bot

Run it manually to confirm everything connects:

```bash
.venv/bin/python run.py
```

You should see output like:

```
Config loaded — briefing at 07:00 America/New_York
Database initialized at ./finance_digest.db
Ollama reachable
Logged in as Finance Digest#1234 (ID: ...)
Slash commands synced to guild ...
Scheduler started — morning briefing at 07:00 America/New_York
```

In Discord, test a command:

```
/add AAPL portfolio
/list
/analyze AAPL
```

If `/analyze` returns a multi-section breakdown, the full pipeline is working.

---

## Step 9 — Deploy as a Background Service

Install the systemd service so the bot starts automatically and restarts on failure:

```bash
sudo cp systemd/finance-digest.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable finance-digest
sudo systemctl start finance-digest
```

Check it is running:

```bash
sudo systemctl status finance-digest
```

Follow live logs:

```bash
sudo journalctl -u finance-digest -f
```

---

## Available Commands

| Command | Description |
|---|---|
| `/add TICKER [portfolio\|watchlist]` | Add a stock to track |
| `/remove TICKER` | Stop tracking a stock |
| `/list` | Show all tracked stocks |
| `/briefing` | Trigger the morning briefing now |
| `/analyze TICKER` | Full 6-step deep-dive analysis |
| `/opportunities` | Score watchlist + find best opportunities |
| `/screen` | AI suggests new tickers based on your portfolio |
| `/thesis TICKER` | View or set your investment thesis for a stock |

---

## Morning Briefing

The bot automatically posts a briefing to your configured channel at the time set in `BRIEFING_TIME`. Each briefing includes:

- **Portfolio companies** — price movement, earnings update, news, thesis integrity check
- **Watchlist companies** — short update and entry point check
- **Opportunity scores** — top watchlist picks ranked by quantitative signals
- **Weekly new ideas** — AI-suggested tickers based on your portfolio themes (once per week)

---

## Troubleshooting

**Ollama not reachable at startup**
```bash
sudo systemctl status ollama
sudo systemctl start ollama
# Confirm the model is downloaded:
ollama list
```

**Model not found error**
```bash
# Make sure OLLAMA_MODEL in .env matches exactly what ollama list shows
ollama list
ollama pull qwen2.5:7b   # re-pull if missing
```

**Slash commands not appearing in Discord**
- Commands sync on bot startup — wait ~1 minute after starting
- Make sure `DISCORD_GUILD_ID` is set to your server ID (not a channel ID)

**Alpha Vantage daily limit hit**
- Free tier is 25 requests/day — the bot tracks this automatically and skips AV once the limit is reached for the day

**Site pages not updating after `/analyze`**
```bash
# Check the site-generator service is running
sudo systemctl status site-generator

# Manually trigger a rebuild for a specific ticker
cd /srv/network-drive/projects/site-generator
node src/build.js --slug=aapl

# Check Node is installed
node --version
```

**Bot not sending page links in Discord**
- Make sure `SITE_PUBLIC_URL` is set in `.env` and the bot has been restarted
- The URL must be publicly reachable (via Cloudflare Tunnel or Railway)

---

**GPU not being used by Ollama**
```bash
# While model is running, check GPU memory usage:
nvidia-smi
# If GPU memory shows 0, reinstall Ollama:
curl -fsSL https://ollama.com/install.sh | sh
```
