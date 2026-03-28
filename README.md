# BHEL Appointment Bot — Slack + Vercel + GitHub Actions

## How it works
1. You type `/book` in Slack
2. Vercel receives the command and triggers GitHub Actions
3. GitHub Actions runs the browser bot in the cloud
4. Bot opens portal, enters your mobile, clicks Send OTP
5. Slack asks you to type `/otp 123456`
6. Bot logs in, finds Dr S Kamal Kumar, selects furthest date
7. Bot checks for green slots every 1 hour
8. The moment a slot opens — bot books it and notifies Slack

---

## Setup — Step by Step

### Step 1: GitHub repo
1. Create a new GitHub repo (can be private)
2. Upload all these files keeping the folder structure intact

### Step 2: GitHub Secrets
Go to repo → Settings → Secrets and variables → Actions → New repository secret

Add these secrets:
| Secret name        | Value                              |
|--------------------|------------------------------------|
| MOBILE             | 919XXXXXXXXX (your mobile with country code) |
| DOCTOR_SEARCH      | Kamal Kumar                        |
| SLACK_WEBHOOK      | (Slack Incoming Webhook URL — see Step 4) |
| BOT_GITHUB_TOKEN   | (GitHub Personal Access Token — see Step 3) |

### Step 3: GitHub Personal Access Token
1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. Create token with access to your repo
3. Permissions needed: Actions (read/write), Variables (read/write)
4. Copy the token → add as `BOT_GITHUB_TOKEN` secret

### Step 4: Slack App setup
1. Go to api.slack.com/apps → Create New App → From scratch
2. Name it "BHEL Bot", pick your workspace

**Incoming Webhooks** (for bot → Slack messages):
- Enable Incoming Webhooks
- Add New Webhook to Workspace → pick your channel
- Copy the webhook URL → add as `SLACK_WEBHOOK` GitHub secret

**Slash Commands** (for /book and /otp):
- Create slash command `/book`
  - Request URL: `https://your-vercel-app.vercel.app/book`
  - Description: Start BHEL appointment booking
- Create slash command `/otp`
  - Request URL: `https://your-vercel-app.vercel.app/otp`
  - Description: Send OTP to booking bot

**OAuth & Permissions** — add these scopes:
- `commands`
- `chat:write`
- `incoming-webhook`

Install the app to your workspace.

### Step 5: Vercel setup
1. Go to vercel.com → New Project → Import your GitHub repo
2. Framework: Other
3. Add Environment Variables in Vercel dashboard:
   | Variable      | Value                        |
   |---------------|------------------------------|
   | GITHUB_TOKEN  | (same token from Step 3)     |
   | GITHUB_REPO   | yourusername/your-repo-name  |
4. Deploy!
5. Copy your Vercel URL (e.g. https://bhel-bot.vercel.app)
6. Update the Slack slash command URLs with your Vercel URL

### Step 6: Test it
1. Open your Slack channel
2. Type `/book`
3. Watch the bot respond!
4. When it asks for OTP, check your phone and type `/otp 583921`
5. Bot will log in and start checking for slots

---

## Slack messages you'll see

| Event                  | Message                                      |
|------------------------|----------------------------------------------|
| Bot started            | Bot is live! Opening portal...               |
| OTP needed             | OTP sent to your phone! Type /otp XXXXXX    |
| OTP received           | OTP received! Bot is logging in now...       |
| Logged in              | Logged in! Navigating to doctor's page...    |
| Polling started        | Now checking every 1 hour for slots          |
| No slot (each check)   | Check 1/2: No open slots. Next check at...   |
| Slot found + booked    | Appointment booked! Slot: 09:30 AM           |
| Timed out              | No slot found after 2 hours. Try /book again |
| Error                  | Bot crashed! [error details]                 |

---

## Files in this project
```
bhel-booking-bot/
├── api/
│   ├── book.js          ← Vercel: receives /book slash command
│   └── otp.js           ← Vercel: receives /otp from user
├── .github/
│   └── workflows/
│       └── book.yml     ← GitHub Actions: runs the browser bot
├── book_appointment.py  ← Main bot script (runs in GitHub Actions)
├── vercel.json          ← Vercel routing config
└── README.md            ← This file
```
