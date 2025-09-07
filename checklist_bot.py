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
        prompt = f"""Проанализируй это сообщение и извлеки:
1. Краткое содержание (1-2 предложения)
2. Любые конкретные даты, сроки или важную по времени информацию
3. Задачи или пункты, которые нужно выполнить

Отформатируй свой ответ точно так:
SUMMARY: [краткое содержание]
DEADLINE: [конкретная дата/время или "Нет"]
ACTIONS: [список задач через запятую или "Нет"]

Сообщение: {message_text}"""

        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "Ты — полезный ассистент, который извлекает ключевую информацию из сообщений. Указывай точные даты и будь краток в содержании."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200,
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.error(f"AI analysis error: {e}")
            return "❌ Не удалось проанализировать сообщение"

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
            msg = "📝 Ваш список задач пуст!"
            if expired_count > 0:
                msg += f"\n\n🗑️ Удалено {expired_count} просроченных задач"
            return msg
        
        items = self.checklist[str(chat_id)]
        if not items:
            msg = "📝 Ваш список задач пуст!"
            if expired_count > 0:
                msg += f"\n\n🗑️ Удалено {expired_count} просроченных задач"
            return msg
        
        response = "📋 <b>Ваш список задач:</b>\n\n"
        
        if expired_count > 0:
            response += f"🗑️ <i>Удалено {expired_count} просроченных задач</i>\n\n"
        
        for item_id, item in items.items():
            status = "✅" if item['completed'] else "⏳"
            summary = item['summary'][:50] + "..." if len(item['summary']) > 50 else item['summary']
            
            response += f"{status} <b>{summary}</b>\n"
            
            if item['deadline'] and item['deadline'].lower() != 'none':
                response += f"   ⏰ Срок: {item['deadline']}\n"
            
            if item['actions'] and item['actions'].lower() != 'none':
                response += f"   📝 Действия: {item['actions']}\n"
            
            response += f"   🆔 ID: <code>{item_id[-6:]}</code>\n\n"  # Show last 6 digits
        
        response += "\n<b>Команды:</b>\n"
        response += "• <code>/checklist</code> - Показать список\n"
        response += "• <code>/complete [ID]</code> - Отметить как выполненное\n"
        response += "• <code>/delete [ID]</code> - Удалить задачу\n"
        response += "• <code>/clear</code> - Удалить все выполненные"
        
        return response

    def handle_command(self, chat_id, command):
        """Handle bot commands"""
        cmd_parts = command.split()
        cmd = cmd_parts[0].lower()
        
        if cmd == '/start':
            welcome = "🤖 <b>Добро пожаловать в AI Checklist Bot!</b>\n\n"
            welcome += "Перешлите мне любое сообщение, и я:\n"
            welcome += "• Сделаю краткое содержание\n"
            welcome += "• Извлеку сроки выполнения\n"
            welcome += "• Найду задачи для выполнения\n"
            welcome += "• Добавлю их в ваш список задач\n"
            welcome += "• Автоматически удалю просроченные задачи\n\n"
            welcome += "<b>Команды:</b>\n"
            welcome += "• /checklist - Показать список\n"
            welcome += "• /complete [ID] - Отметить как выполненное\n"
            welcome += "• /delete [ID] - Удалить задачу\n"
            welcome += "• /clear - Удалить все выполненные"
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
                        self.send_message(chat_id, "✅ Задача отмечена как выполненная!")
                        found = True
                        break
            
            if not found:
                self.send_message(chat_id, "❌ Задача с таким ID не найдена.")
                
        elif cmd == '/delete' and len(cmd_parts) > 1:
            item_id_partial = cmd_parts[1]
            found = False
            
            if str(chat_id) in self.checklist:
                for full_id in list(self.checklist[str(chat_id)].keys()):
                    if full_id.endswith(item_id_partial):
                        del self.checklist[str(chat_id)][full_id]
                        self.save_checklist()
                        self.send_message(chat_id, "🗑️ Задача удалена!")
                        found = True
                        break
            
            if not found:
                self.send_message(chat_id, "❌ Задача с таким ID не найдена.")
                
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
                self.send_message(chat_id, f"🗑️ Очищено {completed_count} выполненных задач!")
            else:
                self.send_message(chat_id, "Нет задач для очистки.")
                
        else:
            self.send_message(chat_id, "Неизвестная команда. Используйте /start для помощи.")

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
            message_text = f"[ПЕРЕСЛАНО] {text}"
        else:
            message_text = text

        if not message_text.strip():
            self.send_message(chat_id, "Пожалуйста, отправьте сообщение с текстом для анализа.")
            return

        # Send typing indicator
        requests.post(f"{self.base_url}/sendChatAction", 
                     data={'chat_id': chat_id, 'action': 'typing'})

        # Analyze message
        analysis = self.analyze_with_ai(message_text)
        
        # Parse analysis
        summary = "Нет содержания"
        deadline = "Нет"
        actions = "Нет"
        
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
        if (actions and actions.lower() != 'нет') or (deadline and deadline.lower() != 'нет'):
            item_id = self.add_to_checklist(chat_id, summary, deadline, actions)
            added_to_checklist = True
        
        # Send result
        response = f"🤖 <b>Анализ ИИ</b>\n\n"
        response += f"📝 <b>Содержание:</b> {summary}\n"
        
        if deadline and deadline.lower() != 'нет':
            response += f"⏰ <b>Срок:</b> {deadline}\n"
        
        if actions and actions.lower() != 'нет':
            response += f"📋 <b>Действия:</b> {actions}\n"
        
        if added_to_checklist:
            response += f"\n✅ <b>Добавлено в список задач!</b> Используйте /checklist, чтобы посмотреть все задачи."
        else:
            response += f"\n💡 <i>Не найдено задач для добавления в список.</i>"
        
        self.send_message(chat_id, response)
        
        logging.info(f"Processed message from chat {chat_id}")

    def run(self):
        """Start the bot"""
        print("🚀 AI Checklist Bot запущен!")
        print("Пересылайте сообщения для анализа и добавления в список задач.")
        print("Просроченные задачи удаляются автоматически.")
        print("Нажмите Ctrl+C, чтобы остановить\n")

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
                print("\n👋 Бот остановлен")
                break
            except Exception as e:
                logging.error(f"Ошибка в главном цикле: {e}")
                time.sleep(5)

def main():
    # Get API keys from environment
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    groq_api_key = os.getenv('GROQ_API_KEY')

    if not telegram_token or not groq_api_key:
        print("❌ Отсутствуют ключи API! Проверьте ваш .env файл.")
        print("Необходимы: TELEGRAM_BOT_TOKEN и GROQ_API_KEY")
        return

    # Start bot
    bot = ChecklistBot(telegram_token, groq_api_key)
    bot.run()

if __name__ == '__main__':
    main()