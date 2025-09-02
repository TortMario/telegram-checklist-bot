import os
import requests
import time
import logging
import json
from datetime import datetime, timedelta
import re
from groq import Groq
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ChecklistBot:
    def __init__(self, telegram_token, groq_api_key):
        self.token = telegram_token
        self.base_url = f'https://api.telegram.org/bot{telegram_token}'
        self.groq_client = Groq(api_key=groq_api_key)
        self.offset = 0
        self.checklist_file = 'data/checklist.json'
        self.load_checklist()

    def load_checklist(self):
        """Load checklist from file"""
        try:
            if os.path.exists(self.checklist_file):
                with open(self.checklist_file, 'r', encoding='utf-8') as f:
                    self.checklist = json.load(f)
            else:
                self.checklist = {}
        except Exception as e:
            logging.error(f"Error loading checklist: {e}")
            self.checklist = {}

    def save_checklist(self):
        """Save checklist to file"""
        try:
            with open(self.checklist_file, 'w', encoding='utf-8') as f:
                json.dump(self.checklist, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Error saving checklist: {e}")

    def clean_expired_items(self, chat_id):
        """Remove items with past deadlines"""
        if str(chat_id) not in self.checklist:
            return 0
        
        current_time = datetime.now()
        items_to_remove = []
        
        for item_id, item in self.checklist[str(chat_id)].items():
            if item.get('deadline_date'):
                try:
                    deadline = datetime.fromisoformat(item['deadline_date'])
                    if deadline < current_time:
                        items_to_remove.append(item_id)
                except:
                    pass
        
        for item_id in items_to_remove:
            del self.checklist[str(chat_id)][item_id]
        
        if items_to_remove:
            self.save_checklist()
            logging.info(f"Removed {len(items_to_remove)} expired items for chat {chat_id}")
        
        return len(items_to_remove)

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
            return response.json()
        except Exception as e:
            logging.error(f"Error sending message: {e}")
            return None

    def get_updates(self):
        """Get updates from Telegram"""
        url = f"{self.base_url}/getUpdates"
        params = {
            'offset': self.offset,
            'timeout': 30
        }
        try:
            response = requests.get(url, params=params, timeout=35)
            return response.json()
        except Exception as e:
            logging.error(f"Error getting updates: {e}")
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

    def add_to_checklist(self, chat_id, summary, deadline, actions):
        """Add items to checklist"""
        if str(chat_id) not in self.checklist:
            self.checklist[str(chat_id)] = {}
        
        # Parse deadline
        deadline_date = self.parse_date(deadline) if deadline else None
        
        # Create item
        item_id = str(int(time.time() * 1000))  # More unique ID
        item = {
            'summary': summary,
            'deadline': deadline,
            'deadline_date': deadline_date.isoformat() if deadline_date else None,
            'actions': actions,
            'completed': False,
            'created_at': datetime.now().isoformat()
        }
        
        self.checklist[str(chat_id)][item_id] = item
        self.save_checklist()
        return item_id
        
    def get_checklist_display(self, chat_id):
        """Get formatted checklist for display"""
        expired_count = self.clean_expired_items(chat_id)
        
        if str(chat_id) not in self.checklist or not self.checklist[str(chat_id)]:
            msg = "📝 Your checklist is empty!"
            if expired_count > 0:
                msg += f"\n\n🗑️ Removed {expired_count} expired items"
            return msg
        
        items = self.checklist[str(chat_id)]
        if not items:
            msg = "📝 Your checklist is empty!"
            if expired_count > 0:
                msg += f"\n\n🗑️ Removed {expired_count} expired items"
            return msg
        
        response = "📋 <b>Your Checklist:</b>\n\n"
        
        if expired_count > 0:
            response += f"🗑️ <i>Removed {expired_count} expired items</i>\n\n"
        
        for item_id, item in items.items():
            status = "✅" if item['completed'] else "⏳"
            summary = item['summary'][:50] + "..." if len(item['summary']) > 50 else item['summary']
            
            response += f"{status} <b>{summary}</b>\n"
            
            if item['deadline'] and item['deadline'].lower() != 'none':
                response += f"   ⏰ Deadline: {item['deadline']}\n"
            
            if item['actions'] and item['actions'].lower() != 'none':
                response += f"   📝 Actions: {item['actions']}\n"
            
            response += f"   🆔 ID: <code>{item_id[-6:]}</code>\n\n"  # Show last 6 digits
        
        response += "\n<b>Commands:</b>\n"
        response += "• <code>/checklist</code> - View checklist\n"
        response += "• <code>/complete [ID]</code> - Mark as complete\n"
        response += "• <code>/delete [ID]</code> - Remove item\n"
        response += "• <code>/clear</code> - Clear all completed items"
        
        return response

    def handle_command(self, chat_id, command):
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
            self.send_message(chat_id, welcome)
            
        elif cmd == '/checklist':
            checklist = self.get_checklist_display(chat_id)
            self.send_message(chat_id, checklist)
            
        elif cmd == '/complete' and len(cmd_parts) > 1:
            item_id_partial = cmd_parts[1]
            found = False
            
            if str(chat_id) in self.checklist:
                for full_id, item in self.checklist[str(chat_id)].items():
                    if full_id.endswith(item_id_partial):
                        self.checklist[str(chat_id)][full_id]['completed'] = True
                        self.save_checklist()
                        self.send_message(chat_id, "✅ Task marked as complete!")
                        found = True
                        break
            
            if not found:
                self.send_message(chat_id, "❌ Task ID not found.")
                
        elif cmd == '/delete' and len(cmd_parts) > 1:
            item_id_partial = cmd_parts[1]
            found = False
            
            if str(chat_id) in self.checklist:
                for full_id in list(self.checklist[str(chat_id)].keys()):
                    if full_id.endswith(item_id_partial):
                        del self.checklist[str(chat_id)][full_id]
                        self.save_checklist()
                        self.send_message(chat_id, "🗑️ Task deleted!")
                        found = True
                        break
            
            if not found:
                self.send_message(chat_id, "❌ Task ID not found.")
                
        elif cmd == '/clear':
            if str(chat_id) in self.checklist:
                completed_count = 0
                items_to_remove = []
                
                for item_id, item in self.checklist[str(chat_id)].items():
                    if item.get('completed', False):
                        items_to_remove.append(item_id)
                        completed_count += 1
                
                for item_id in items_to_remove:
                    del self.checklist[str(chat_id)][item_id]
                
                self.save_checklist()
                self.send_message(chat_id, f"🗑️ Cleared {completed_count} completed tasks!")
            else:
                self.send_message(chat_id, "No tasks to clear.")
                
        else:
            self.send_message(chat_id, "Unknown command. Use /start for help.")

    def handle_message(self, message):
        """Process incoming message"""
        chat_id = message['chat']['id']
        text = message.get('text', '').strip()
        
        # Handle commands
        if text.startswith('/'):
            self.handle_command(chat_id, text)
            return
            
        # Get forwarded message text or regular text
        if 'forward_date' in message:
            message_text = f"[FORWARDED] {text}"
        else:
            message_text = text

        if not message_text.strip():
            self.send_message(chat_id, "Please send a message with text to analyze.")
            return

        # Send typing indicator
        requests.post(f"{self.base_url}/sendChatAction", 
                     data={'chat_id': chat_id, 'action': 'typing'})

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
            item_id = self.add_to_checklist(chat_id, summary, deadline, actions)
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
        
        logging.info(f"Processed message from chat {chat_id}")

    def run(self):
        """Start the bot"""
        print("🚀 AI Checklist Bot started!")
        print("Forward messages to analyze and add to checklist.")
        print("Expired items are automatically removed.")
        print("Press Ctrl+C to stop\n")

        while True:
            try:
                updates = self.get_updates()
                
                if updates and updates.get('ok'):
                    for update in updates['result']:
                        self.offset = update['update_id'] + 1
                        
                        if 'message' in update:
                            self.handle_message(update['message'])

                time.sleep(1)

            except KeyboardInterrupt:
                print("\n👋 Bot stopped")
                break
            except Exception as e:
                logging.error(f"Main loop error: {e}")
                time.sleep(5)

def main():
    # Get API keys from environment
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    groq_api_key = os.getenv('GROQ_API_KEY')

    if not telegram_token or not groq_api_key:
        print("❌ Missing API keys! Check your .env file.")
        print("Need: TELEGRAM_BOT_TOKEN and GROQ_API_KEY")
        return

    # Start bot
    bot = ChecklistBot(telegram_token, groq_api_key)
    bot.run()

if __name__ == '__main__':
    main()