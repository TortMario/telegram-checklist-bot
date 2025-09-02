# Telegram Checklist Bot for Vercel

AI-powered Telegram bot that analyzes forwarded messages and creates smart checklists with deadlines and action items.

## Features

- 🤖 **AI Analysis**: Automatically extracts summaries, deadlines, and action items from messages
- 📋 **Smart Checklists**: Organizes tasks with deadlines and completion tracking
- 🗑️ **Auto-cleanup**: Removes expired items automatically
- ⚡ **Serverless**: Optimized for Vercel deployment with webhook architecture

## Quick Deploy

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/yourusername/telegram-checklist-bot)

## Setup

1. **Clone and install:**
   ```bash
   git clone <your-repo>
   cd telegram-checklist-bot
   pip install -r requirements.txt
   ```

2. **Set environment variables in Vercel:**
   - `TELEGRAM_BOT_TOKEN`: Get from [@BotFather](https://t.me/botfather)
   - `GROQ_API_KEY`: Get from [Groq Console](https://console.groq.com/)

3. **Deploy to Vercel:**
   ```bash
   vercel --prod
   ```

4. **Set webhook:**
   After deployment, visit: `https://your-app.vercel.app/api/set_webhook`

## Usage

### Commands:
- `/start` - Welcome message and help
- `/checklist` - View your current checklist
- `/complete [ID]` - Mark task as complete
- `/delete [ID]` - Remove task
- `/clear` - Remove all completed tasks

### Message Analysis:
- **Forward any message** → Bot analyzes and adds to checklist
- **Send/copy text** → Bot extracts tasks and deadlines
- **Automatic cleanup** → Expired items removed automatically

## API Endpoints

- `POST /api/webhook` - Telegram webhook receiver
- `GET /api/set_webhook` - View current webhook info
- `POST /api/set_webhook` - Set new webhook URL

## Storage Note

Current implementation uses in-memory storage. For production, integrate with:
- Redis (recommended for Vercel)
- MongoDB Atlas
- PostgreSQL with connection pooling

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your tokens

# For local testing, you can still use the polling version:
python checklist_bot.py
```