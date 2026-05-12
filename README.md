# Train 22230 Daily Watcher

Runs **once a day at 5:00 PM IST** and emails you a screenshot of IRCTC's search results for:

| Field | Value |
|---|---|
| Train | **22230 (CSMT Vande Bharat)** |
| From | MADGAON (MAO) |
| To | THANE (TNA) |
| Date | 16/06/2026 |
| Class | Exec. Chair Car (EC) |
| Quota | GENERAL |

You'll get one of these emails every evening:

- `[BOOK NOW] Train 22230 bookings OPEN for 16/06/2026` — when the train is in results AND shows AVAILABLE/RAC/WL. **Action required.**
- `[Daily] Train 22230 listed but not yet bookable - DD-MMM-YYYY` — train appears but IRCTC says "BOOKING NOT STARTED" or similar.
- `[Daily] Train 22230 not in results yet - DD-MMM-YYYY` — train doesn't appear (likely because monsoon timetable hasn't been notified).
- `[Watcher ERROR] Train 22230 check failed - DD-MMM-YYYY` — something broke (IRCTC site down, selectors changed, etc.).

Every email has the full-page screenshot of IRCTC's results attached, so you can verify the bot's decision visually.

---

## Setup (one time, ~10 minutes)

### 1. Gmail App Password
1. Enable 2-Step Verification: <https://myaccount.google.com/security>
2. Create app password: <https://myaccount.google.com/apppasswords>
3. Name it "train-watcher". Copy the 16-character password.

### 2. Push to a new GitHub repo
```bash
cd train-22230-watcher
git init
git add .
git commit -m "Initial commit"
gh repo create train-22230-watcher --private --source=. --push
```

### 3. Add 3 secrets
**Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `GMAIL_USER` | the Gmail you generated the app password for |
| `GMAIL_APP_PASSWORD` | the 16-char password from step 1 |
| `ALERT_EMAIL` | `abhivdeo@gmail.com` |

### 4. Verify email setup
**Actions tab → "Daily Train 22230 Check" → Run workflow → mode = `test-email`.**

You should receive `[TEST] Train watcher email setup OK` within a minute. If not, fix credentials before relying on this.

### 5. Run once to confirm IRCTC scrape works
**Actions tab → Run workflow → mode = `daily`.**

This does a full check and emails you the result + screenshot **right now**, regardless of time of day. Open the email, look at the screenshot:
- If the screenshot shows IRCTC's search results page (whether the train is there or not) — **agent is working**, leave the cron alone.
- If the screenshot shows a half-filled form, login wall, or error popup — selectors need adjustment (see Troubleshooting).

### 6. Done
The daily 5 PM IST cron is already active. Nothing more to do.

---

## Schedule details

| Setting | Value |
|---|---|
| Cron expression | `30 11 * * *` (UTC) |
| Equivalent IST | 5:00 PM daily |
| Expected delay | 0–15 min (GitHub Actions queue under load) |
| Each run takes | ~2 min |
| Monthly Actions minutes | ~60 min (well within 2000 min free tier on private repos) |

If you want a different time, edit `.github/workflows/check.yml`. Remember GitHub Actions uses **UTC**, so subtract 5h30m from your desired IST time. Examples:
- 8 AM IST → `30 2 * * *`
- 9 PM IST → `30 15 * * *`

---

## Local testing

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# Run once, no email (for local debugging)
python check_train.py once

# Send a daily-style email right now
export GMAIL_USER=...
export GMAIL_APP_PASSWORD=...
export ALERT_EMAIL=abhivdeo@gmail.com
python check_train.py daily
```

---

## Changing target train/date/route

Edit `config.py` (all tunables in one place), commit, push. The next 5 PM run will use the new config. No other file needs editing.

---

## Troubleshooting

**You stop getting daily emails.** First check the Actions tab — recent runs should be green. If they're red, click into the latest one, download the `screenshots-N` artifact, look at the screenshot. Common causes:

- **`form_fill_failed`**: IRCTC tweaked their form selectors. Adjust `irctc_check.py` based on what the screenshot shows.
- **`results_not_rendered`**: New popup interstitial. Add a `.click()` for it in `_fill_station` / `check_irctc`.
- **`network_error`**: IRCTC was down at 5 PM that day. Just wait — tomorrow's run will likely succeed.

**Emails arriving but always say "not in results yet".** Expected behavior until Konkan Railway notifies the 2026 monsoon timetable (typically late May / first week of June). Once that happens, the train will reappear in IRCTC results and the email status will change.

**Want to stop daily emails after booking opens?** The agent doesn't auto-stop because daily was your explicit ask, but it does flip `alerted: true` in `.state.json` on the first BOOK NOW email. To stop the daily run, simply **disable the workflow**: Actions tab → "Daily Train 22230 Check" → ⋯ menu → "Disable workflow."

---

## Files

```
.
├── check_train.py        # orchestrator (daily | once | test-email | reset)
├── config.py             # tunables — train, date, route, class
├── irctc_check.py        # Playwright on IRCTC (primary, captures screenshot)
├── confirmtkt_check.py   # HTTP fallback (no screenshot)
├── notifier.py           # Gmail SMTP send with image attachment
├── state.py              # JSON state file
├── requirements.txt
├── .github/workflows/check.yml
└── screenshots/          # populated at runtime, uploaded to Actions
```
