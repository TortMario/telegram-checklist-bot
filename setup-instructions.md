# Setup Instructions for Scheduled Reminders

## 1. Deploy to Vercel

```bash
vercel --prod
```

## 2. Set Environment Variables in Vercel

Go to your Vercel dashboard → Settings → Environment Variables:

- `TELEGRAM_BOT_TOKEN`: Your bot token from @BotFather
- `GROQ_API_KEY`: Your Groq API key

## 3. Set Up GitHub Actions

### Add Secret to GitHub Repository:

1. Go to your GitHub repo → Settings → Secrets and variables → Actions
2. Add new repository secret:
   - **Name**: `VERCEL_APP_URL`
   - **Value**: `https://your-app-name.vercel.app` (your actual Vercel URL)

### Test the Workflow:

1. Go to Actions tab in your GitHub repo
2. Select "Daily Telegram Reminders"
3. Click "Run workflow" → "Run workflow" to test

## 4. Set Telegram Webhook

After deployment, visit: `https://your-app.vercel.app/api/set_webhook`

## 5. Test Daily Reminders

### Check Reminder Service:
Visit: `https://your-app.vercel.app/api/daily-reminder`

### Manual Test:
```bash
curl -X POST https://your-app.vercel.app/api/daily-reminder
```

## 6. Schedule Overview

**Automatic reminders will be sent:**
- 🌅 **8:00 AM Singapore Time** (daily)
- 🌆 **7:00 PM Singapore Time** (daily)

**Only if:**
- User has tasks due that day
- Tasks are not marked as completed

## 7. Verify Setup

1. **Webhook working**: Send a message to your bot
2. **Reminders working**: Check GitHub Actions logs
3. **Times correct**: Visit `/api/daily-reminder` to see Singapore time

## Troubleshooting

### If reminders don't work:
1. Check GitHub Actions logs for errors
2. Verify `VERCEL_APP_URL` secret is correct
3. Ensure environment variables are set in Vercel
4. Check Vercel function logs

### If timezone is wrong:
- The system uses Singapore timezone (SGT/UTC+8)
- GitHub Actions runs at UTC times (00:00 and 11:00)
- This converts to 8:00 AM and 7:00 PM Singapore time