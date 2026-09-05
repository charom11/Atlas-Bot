# 📖 Complete Guide: Running Weather-Ensemble AI 24/7 on GitHub

This guide walks you through setting up your trading bot to run **24 hours a day, 7 days a week directly in GitHub's Cloud** with **zero cost**, **zero reliance on your home computer**, and **100% automated restart**.

---

## 📋 Table of Contents
1. [Step 1: Create a Private GitHub Repository](#step-1-create-a-private-github-repository)
2. [Step 2: Push Your Code to GitHub](#step-2-push-your-code-to-github)
3. [Step 3: Add Encrypted Secrets in GitHub](#step-3-add-encrypted-secrets-in-github)
4. [Step 4: Start the 24/7 Trading Workflow](#step-4-start-the-247-trading-workflow)
5. [Step 5: Control Everything from Your Phone via Telegram](#step-5-control-everything-from-your-phone-via-telegram)

---

## Step 1: Create a Private GitHub Repository

1. Go to [https://github.com/new](https://github.com/new) and log in.
2. Under **Repository name**, enter: `crypto-quant-bot` (or any name you prefer).
3. Select **🔒 Private** (Important: Keeps your strategy and setup private).
4. Leave all other checkboxes unchecked (do NOT check Add README or .gitignore).
5. Click **Create repository**.

---

## Step 2: Push Your Code to GitHub

Open **PowerShell** or **Command Prompt** in `d:\Bot2` and run these 3 commands:

```powershell
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/crypto-quant-bot.git
git branch -M main
git push -u origin main
```
*(Replace `<YOUR_GITHUB_USERNAME>` with your real GitHub username).*

> [!NOTE]
> Your `.env` file containing local keys is automatically protected by `.gitignore` and will never be pushed publicly.

---

## Step 3: Add Encrypted Secrets in GitHub

To allow the cloud runner to trade on Binance and message your Telegram:

1. In your GitHub repository $\rightarrow$ Click **Settings** (top menu bar).
2. On the left sidebar $\rightarrow$ Click **Secrets and variables** $\rightarrow$ Click **Actions**.
3. Click the green **New repository secret** button.
4. Add the following **4 Secrets** one by one:

| Secret Name | Secret Value | Purpose |
| :--- | :--- | :--- |
| **`BINANCE_API_KEY`** | Your Binance Futures API Key | Places orders on Binance |
| **`BINANCE_API_SECRET`** | Your Binance Futures Secret Key | Authenticates orders |
| **`TELEGRAM_BOT_TOKEN`** | `8252250269:AAFnW58V_b0l0Qk2jM4L8aV9o3X_EXAMPLE` | Sends alerts & listens to commands |
| **`TELEGRAM_CHAT_ID`** | `8448744577` | Your personal Telegram Chat ID |

---

## Step 4: Start the 24/7 Trading Workflow

1. In your GitHub repository $\rightarrow$ Click the **Actions** tab at the top.
2. On the left menu, select: **`⚡ Weather-Ensemble AI 24/7 Live Trading Runner`**.
3. Click the **Run workflow** dropdown on the right.
4. Click the green **Run workflow** button.

### 🔄 How the 24/7 Automation Works:
- GitHub starts a cloud container that runs the live bot across all 19 assets.
- Every **5 hours**, the scheduled cron (`schedule: cron '0 */5 * * *'`) triggers the next session seamlessly, guaranteeing **continuous 24/7/365 market coverage**.
- You can click on the running job to watch live terminal logs in real time from any browser!

---

## Step 5: Control Everything from Your Phone via Telegram

Once running in GitHub Actions, you don't need your PC on at all. Open Telegram and send commands:

- **`/status`** $\rightarrow$ Checks wallet balance, active leverage, and live status.
- **`/positions`** $\rightarrow$ Displays open Binance Futures trades with live PnL.
- **`/tf 15m`** $\rightarrow$ Changes execution timeframe.
- **`/closeall`** $\rightarrow$ 🚨 Emergency 1-tap market close of all open positions.
- **`/circuit`** $\rightarrow$ View daily drawdown and circuit breaker health.

---

## 🛠️ Summary Checklist
- [x] Repository initialized with GitHub Actions workflow (`.github/workflows/trading_bot_24_7.yml`)
- [x] Sensitive keys secured in `.gitignore`
- [x] Multi-asset universe (19 coins) & MTF Divergences active
- [x] Real-time push alerts wired directly to Telegram
