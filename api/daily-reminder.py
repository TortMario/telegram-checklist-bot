import os
import json
import logging
from datetime import datetime, timedelta
import pytz
import requests
from http.server import BaseHTTPRequestHandler

# Set up logging
logging.basicConfig(level=logging.INFO)

class DailyReminderBot:
    def __init__(self, telegram_token):
        self.token = telegram_token
        self.base_url = f'https://api.telegram.org/bot{telegram_token}'
        self.singapore_tz = pytz.timezone('Asia/Singapore')

    def load_all_checklists(self):
        """Load all users' checklists - placeholder for database integration"""
        # TODO: Implement database storage (Redis, MongoDB, etc.)
        # For now, return empty dict
        # In production, this would query your database for all users with active checklists
        return {}

    def get_singapore_date(self):
        """Get current date in Singapore timezone"""
        return datetime.now(self.singapore_tz).date()

    def is_due_today(self, task, singapore_date):
        """Check if task is due today"""
        if not task.get('deadline_date'):
            return False
        
        try:
            task_deadline = datetime.fromisoformat(task['deadline_date']).date()
            return task_deadline == singapore_date
        except:
            return False

    def format_reminder_message(self, due_tasks, chat_id):
        """Format reminder message for due tasks"""
        count = len(due_tasks)
        
        if count == 0:
            return None
            
        # Header
        message = f"🔔 <b>Daily Reminder</b> - {count} task{'s' if count > 1 else ''} due today:\n\n"
        
        # List tasks
        for task in due_tasks:
            status = "✅" if task.get('completed') else "⏳"
            summary = task['summary'][:60] + "..." if len(task['summary']) > 60 else task['summary']
            
            message += f"{status} <b>{summary}</b>\n"
            
            if task.get('deadline') and task['deadline'].lower() != 'none':
                message += f"   ⏰ Due: {task['deadline']}\n"
            
            if task.get('actions') and task['actions'].lower() != 'none':
                message += f"   📝 Actions: {task['actions']}\n"
            
            message += "\n"
        
        message += "📋 Use /checklist to manage your tasks."
        return message

    def send_message(self, chat_id, text):
        """Send message to Telegram chat"""
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        try:
            response = requests.post(url, data=data, timeout=30)
            result = response.json()
            if result.get('ok'):
                logging.info(f"Sent reminder to chat {chat_id}")
                return True
            else:
                logging.error(f"Failed to send reminder to {chat_id}: {result}")
                return False
        except Exception as e:
            logging.error(f"Error sending reminder to {chat_id}: {e}")
            return False

    def send_daily_reminders(self):
        """Check all users and send reminders for due tasks"""
        try:
            singapore_date = self.get_singapore_date()
            logging.info(f"Running daily reminder check for {singapore_date}")
            
            # Load all user checklists
            all_checklists = self.load_all_checklists()
            
            sent_count = 0
            total_users = len(all_checklists)
            
            # Process each user
            for chat_id, checklist in all_checklists.items():
                try:
                    # Find tasks due today
                    due_tasks = []
                    for task_id, task in checklist.items():
                        if not task.get('completed', False) and self.is_due_today(task, singapore_date):
                            due_tasks.append(task)
                    
                    # Send reminder if there are due tasks
                    if due_tasks:
                        message = self.format_reminder_message(due_tasks, chat_id)
                        if message and self.send_message(chat_id, message):
                            sent_count += 1
                            
                except Exception as e:
                    logging.error(f"Error processing reminders for chat {chat_id}: {e}")
                    continue
            
            logging.info(f"Daily reminder completed: {sent_count}/{total_users} users notified")
            
            return {
                'success': True,
                'date': str(singapore_date),
                'total_users': total_users,
                'notifications_sent': sent_count,
                'message': f'Daily reminder completed. Sent {sent_count} notifications to {total_users} users.'
            }
            
        except Exception as e:
            logging.error(f"Daily reminder failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'message': 'Daily reminder failed'
            }

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # Verify this is coming from a trusted source (optional security)
            # You can add authentication here if needed
            
            # Get environment variables
            telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
            
            if not telegram_token:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'Missing TELEGRAM_BOT_TOKEN')
                return
            
            # Initialize reminder bot
            reminder_bot = DailyReminderBot(telegram_token)
            
            # Send daily reminders
            result = reminder_bot.send_daily_reminders()
            
            # Send response
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result, indent=2).encode('utf-8'))
            
        except Exception as e:
            logging.error(f"Daily reminder endpoint error: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({
                'success': False,
                'error': str(e)
            }).encode('utf-8'))
    
    def do_GET(self):
        try:
            # Health check and info endpoint
            singapore_tz = pytz.timezone('Asia/Singapore')
            current_time = datetime.now(singapore_tz)
            
            info = {
                'status': 'Daily reminder service is running',
                'current_singapore_time': current_time.strftime('%Y-%m-%d %H:%M:%S %Z'),
                'next_8am': current_time.replace(hour=8, minute=0, second=0, microsecond=0),
                'next_7pm': current_time.replace(hour=19, minute=0, second=0, microsecond=0),
                'scheduled_times': ['08:00 SGT', '19:00 SGT'],
                'endpoint': 'POST /api/daily-reminder to trigger reminders'
            }
            
            # Convert datetime objects to strings for JSON serialization
            info['next_8am'] = info['next_8am'].strftime('%Y-%m-%d %H:%M:%S %Z')
            info['next_7pm'] = info['next_7pm'].strftime('%Y-%m-%d %H:%M:%S %Z')
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(info, indent=2).encode('utf-8'))
            
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({
                'error': str(e)
            }).encode('utf-8'))