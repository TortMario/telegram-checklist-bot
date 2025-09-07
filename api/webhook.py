import os
import json
import logging
from datetime import datetime, timedelta
import re
from groq import Groq
from http.server import BaseHTTPRequestHandler
import urllib.parse

# Set up logging for Vercel
logging.basicConfig(level=logging.INFO)

class ChecklistBot:
    def __init__(self, telegram_token, groq_api_key):
        self.token = telegram_token
        self.base_url = f'https://api.telegram.org/bot{telegram_token}'
        self.groq_client = Groq(api_key=groq_api_key)
        
    def parse_date(self, date_str):
        """Parse date from various formats"""
        if not date_str or date_str.lower() == 'none':
            return None
        
        current_date = datetime.now()
        date_str_lower = date_str.lower()
        
        # Handle relative dates
        if 'tomorrow' in date_str_lower:
            return current_date + timedelta(days=1)
        elif 'today' in date_str_lower:
            return current_date
        elif 'next week' in date_str_lower:
            return current_date + timedelta(days=7)
        
        # Handle specific date patterns
        patterns = [
            r'(\d{1,2})/(\d{1,2})/(\d{4})',  # MM/DD/YYYY
            r'(\d{1,2})-(\d{1,2})-(\d{4})',  # MM-DD-YYYY
            r'(\d{4})-(\d{1,2})-(\d{1,2})',  # YYYY-MM-DD
            r'(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)',  # DD Month
        ]
        
        months = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }
        
        for pattern in patterns:
            match = re.search(pattern, date_str_lower)
            if match:
                try:
                    groups = match.groups()
                    if len(groups) == 3:
                        if groups[0].isdigit() and len(groups[0]) == 4:
                            # YYYY-MM-DD
                            return datetime(int(groups[0]), int(groups[1]), int(groups[2]))
                        else:
                            # MM/DD/YYYY or MM-DD-YYYY
                            return datetime(int(groups[2]), int(groups[0]), int(groups[1]))
                    elif len(groups) == 2 and groups[1] in months:
                        # DD Month format
                        return datetime(current_date.year, months[groups[1]], int(groups[0]))
                except:
                    continue
        
        return None

    def analyze_with_ai(self, message_text):
        """Use AI to analyze message for summary and deadlines"""
        prompt = f"""Analyze this message and extract:
1. Brief summary (1-2 sentences)
2. Any specific dates, deadlines, or time-sensitive information
3. Action items or tasks that need to be done

Format your response exactly as:
SUMMARY: [brief summary]
DEADLINE: [specific date/time or "None"]
ACTIONS: [comma-separated list of tasks or "None"]

Message: {message_text}"""

        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that extracts key information from messages. Be specific with dates and concise with summaries."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200,
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.error(f"AI analysis error: {e}")
            return "❌ Could not analyze message"

    def load_checklist(self, chat_id):
        """Load checklist from environment or return empty"""
        # In serverless, we'll use a database or external storage
        # For now, return empty dict (will be replaced with proper storage)
        return {}

    def save_checklist(self, chat_id, checklist):
        """Save checklist - placeholder for database integration"""
        # TODO: Implement database storage (Redis, MongoDB, etc.)
        pass

    def clean_expired_items(self, checklist, chat_id):
        """Remove items with past deadlines"""
        current_time = datetime.now()
        items_to_remove = []
        
        chat_checklist = checklist.get(str(chat_id), {})
        for item_id, item in chat_checklist.items():
            if item.get('deadline_date'):
                try:
                    deadline = datetime.fromisoformat(item['deadline_date'])
                    if deadline < current_time:
                        items_to_remove.append(item_id)
                except:
                    pass
        
        for item_id in items_to_remove:
            if str(chat_id) in checklist:
                checklist[str(chat_id)].pop(item_id, None)
        
        return len(items_to_remove)

    def add_to_checklist(self, checklist, chat_id, summary, deadline, actions):
        """Add items to checklist"""
        if str(chat_id) not in checklist:
            checklist[str(chat_id)] = {}
        
        # Parse deadline
        deadline_date = self.parse_date(deadline) if deadline else None
        
        # Create item
        item_id = str(int(datetime.now().timestamp() * 1000))
        item = {
            'summary': summary,
            'deadline': deadline,
            'deadline_date': deadline_date.isoformat() if deadline_date else None,
            'actions': actions,
            'completed': False,
            'created_at': datetime.now().isoformat()
        }
        
        checklist[str(chat_id)][item_id] = item
        return item_id
        
    def get_checklist_display(self, checklist, chat_id):
        """Get formatted checklist for display"""
        expired_count = self.clean_expired_items(checklist, chat_id)
        
        chat_checklist = checklist.get(str(chat_id), {})
        if not chat_checklist:
            msg = "📝 Your checklist is empty!"
            if expired_count > 0:
                msg += f"\n\n🗑️ Removed {expired_count} expired items"
            return msg
        
        response = "📋 <b>Your Checklist:</b>\n\n"
        
        if expired_count > 0:
            response += f"🗑️ <i>Removed {expired_count} expired items</i>\n\n"
        
        for item_id, item in chat_checklist.items():
            status = "✅" if item['completed'] else "⏳"
            summary = item['summary'][:50] + "..." if len(item['summary']) > 50 else item['summary']
            
            response += f"{status} <b>{summary}</b>\n"
            
            if item['deadline'] and item['deadline'].lower() != 'none':
                response += f"   ⏰ Deadline: {item['deadline']}\n"
            
            if item['actions'] and item['actions'].lower() != 'none':
                response += f"   📝 Actions: {item['actions']}\n"
            
            response += f"   🆔 ID: <code>{item_id[-6:]}</code>\n\n"
        
        response += "\n<b>Commands:</b>\n"
        response += "• <code>/checklist</code> - View checklist\n"
        response += "• <code>/complete [ID]</code> - Mark as complete\n"
        response += "• <code>/delete [ID]</code> - Remove item\n"
        response += "• <code>/clear</code> - Clear all completed items"
        
        return response

    def send_message(self, chat_id, text):
        """Send message to Telegram chat"""
        import requests
        
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        try:
            response = requests.post(url, data=data, timeout=30)
            return response.json()
        except Exception as e:
            logging.error(f"Error sending message: {e}")
            return None

    def handle_command(self, checklist, chat_id, command):
        """Handle bot commands"""
        cmd_parts = command.split()
        cmd = cmd_parts[0].lower()
        
        if cmd == '/start':
            welcome = "🤖 <b>Welcome to AI Checklist Bot!</b>\n\n"
            welcome += "Forward me any message and I'll:\n"
            welcome += "• Summarize it\n"
            welcome += "• Extract deadlines\n"
            welcome += "• Find action items\n"
            welcome += "• Add them to your checklist\n"
            welcome += "• Auto-remove expired items\n\n"
            welcome += "<b>Commands:</b>\n"
            welcome += "• /checklist - View your tasks\n"
            welcome += "• /complete [ID] - Mark task done\n"
            welcome += "• /delete [ID] - Remove task\n"
            welcome += "• /clear - Remove completed items"
            return welcome
            
        elif cmd == '/checklist':
            return self.get_checklist_display(checklist, chat_id)
            
        elif cmd == '/complete' and len(cmd_parts) > 1:
            item_id_partial = cmd_parts[1]
            found = False
            
            chat_checklist = checklist.get(str(chat_id), {})
            for full_id, item in chat_checklist.items():
                if full_id.endswith(item_id_partial):
                    checklist[str(chat_id)][full_id]['completed'] = True
                    found = True
                    break
            
            return "✅ Task marked as complete!" if found else "❌ Task ID not found."
                
        elif cmd == '/delete' and len(cmd_parts) > 1:
            item_id_partial = cmd_parts[1]
            found = False
            
            chat_checklist = checklist.get(str(chat_id), {})
            for full_id in list(chat_checklist.keys()):
                if full_id.endswith(item_id_partial):
                    checklist[str(chat_id)].pop(full_id, None)
                    found = True
                    break
            
            return "🗑️ Task deleted!" if found else "❌ Task ID not found."
                
        elif cmd == '/clear':
            chat_checklist = checklist.get(str(chat_id), {})
            completed_count = 0
            items_to_remove = []
            
            for item_id, item in chat_checklist.items():
                if item.get('completed', False):
                    items_to_remove.append(item_id)
                    completed_count += 1
            
            for item_id in items_to_remove:
                checklist[str(chat_id)].pop(item_id, None)
            
            return f"🗑️ Cleared {completed_count} completed tasks!" if completed_count > 0 else "No tasks to clear."
                
        else:
            return "Unknown command. Use /start for help."

    def handle_message(self, message_data):
        """Process incoming message"""
        chat_id = message_data['chat']['id']
        text = message_data.get('text', '').strip()
        
        # Load checklist (in production, this would be from database)
        checklist = self.load_checklist(chat_id)
        
        # Handle commands
        if text.startswith('/'):
            response = self.handle_command(checklist, chat_id, text)
            self.send_message(chat_id, response)
            self.save_checklist(chat_id, checklist)
            return
            
        # Get forwarded message text or regular text
        if 'forward_date' in message_data:
            message_text = f"[FORWARDED] {text}"
        else:
            message_text = text

        if not message_text.strip():
            self.send_message(chat_id, "Please send a message with text to analyze.")
            return

        # Analyze message
        analysis = self.analyze_with_ai(message_text)
        
        # Parse analysis
        summary = "No summary"
        deadline = "None"
        actions = "None"
        
        lines = analysis.split('\n')
        for line in lines:
            if line.startswith('SUMMARY:'):
                summary = line.replace('SUMMARY:', '').strip()
            elif line.startswith('DEADLINE:'):
                deadline = line.replace('DEADLINE:', '').strip()
            elif line.startswith('ACTIONS:'):
                actions = line.replace('ACTIONS:', '').strip()
        
        # Add to checklist if there are actions or deadlines
        added_to_checklist = False
        if (actions and actions.lower() != 'none') or (deadline and deadline.lower() != 'none'):
            item_id = self.add_to_checklist(checklist, chat_id, summary, deadline, actions)
            added_to_checklist = True
        
        # Send result
        response = f"🤖 <b>AI Analysis</b>\n\n"
        response += f"📝 <b>Summary:</b> {summary}\n"
        
        if deadline and deadline.lower() != 'none':
            response += f"⏰ <b>Deadline:</b> {deadline}\n"
        
        if actions and actions.lower() != 'none':
            response += f"📋 <b>Actions:</b> {actions}\n"
        
        if added_to_checklist:
            response += f"\n✅ <b>Added to checklist!</b> Use /checklist to view all items."
        else:
            response += f"\n💡 <i>No actionable items found to add to checklist.</i>"
        
        self.send_message(chat_id, response)
        self.save_checklist(chat_id, checklist)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # Get environment variables
            telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
            groq_api_key = os.getenv('GROQ_API_KEY')
            
            if not telegram_token or not groq_api_key:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'Missing API keys')
                return
            
            # Read the request body
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            
            # Parse the JSON data from Telegram
            webhook_data = json.loads(body.decode('utf-8'))
            
            # Initialize bot
            bot = ChecklistBot(telegram_token, groq_api_key)
            
            # Process the message
            if 'message' in webhook_data:
                bot.handle_message(webhook_data['message'])
            
            # Send success response
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode('utf-8'))
            
        except Exception as e:
            logging.error(f"Webhook error: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f'Error: {str(e)}'.encode('utf-8'))
    
    def do_GET(self):
        # Health check endpoint
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'Bot is running!'}).encode('utf-8'))