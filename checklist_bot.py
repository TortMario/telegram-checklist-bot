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

import redis

class ChecklistBot:
    def __init__(self, telegram_token, groq_api_key):
        self.token = telegram_token
        self.base_url = f'https://api.telegram.org/bot{telegram_token}'
        self.groq_client = Groq(api_key=groq_api_key)
        self.offset = 0

        # Set up Redis connection
        redis_url = os.getenv('REDIS_URL')
        if redis_url:
            self.redis_client = redis.from_url(redis_url)
        else:
            self.redis_client = None
            logging.warning("REDIS_URL not found. Database functionality will be disabled.")

    def set_user_state(self, chat_id, state):
        if not self.redis_client: return
        self.redis_client.set(f"state:{chat_id}", state, ex=600)

    def get_user_state(self, chat_id):
        if not self.redis_client: return None
        state_bytes = self.redis_client.get(f"state:{chat_id}")
        if state_bytes:
            return state_bytes.decode('utf-8')
        return None

    def clear_user_state(self, chat_id):
        if not self.redis_client: return
        self.redis_client.delete(f"state:{chat_id}")

    def load_checklist(self, chat_id):
        """Load checklist from Redis"""
        if not self.redis_client:
            return {}
        try:
            data = self.redis_client.get(f"checklist:{chat_id}")
            if data:
                return json.loads(data)
        except Exception as e:
            logging.error(f"Error loading checklist from Redis for chat {chat_id}: {e}")
        return {}

    def save_checklist(self, chat_id, checklist):
        """Save checklist to Redis"""
        if not self.redis_client:
            return
        try:
            self.redis_client.set(f"checklist:{chat_id}", json.dumps(checklist, ensure_ascii=False))
        except Exception as e:
            logging.error(f"Error saving checklist to Redis for chat {chat_id}: {e}")

    def clean_expired_items(self, checklist):
        """Remove items with past deadlines from a checklist dictionary"""
        current_time = datetime.now()
        items_to_remove = []
        
        for item_id, item in checklist.items():
            if item.get('deadline_date'):
                try:
                    deadline = datetime.fromisoformat(item['deadline_date'])
                    if deadline < current_time:
                        items_to_remove.append(item_id)
                except:
                    pass
        
        for item_id in items_to_remove:
            checklist.pop(item_id, None)
        
        return len(items_to_remove)

    def parse_date(self, date_str):
        """Parse date from various formats"""
        if not date_str or date_str.lower() == 'нет':
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

    def analyze_with_ai(self, message_text, prompt_template):
        """General purpose AI analysis method."""
        prompt = prompt_template.replace("[вставь свою]", message_text)
        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "Ты — полезный ассистент, который извлекает ключевую информацию из сообщений или выполняет задачи по шаблону."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1024, # Increased for potentially longer simplification steps
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.error(f"AI analysis error: {e}")
            return "❌ Ошибка при обращении к ИИ"

    def simplify_task(self, task_text):
        """Calls AI to simplify a task into steps."""
        prompt_template = "Вот задача: [вставь свою].\nРазбей её на шаги по 3–5 минут, с чётким началом и понятным концом.\nДобавь критерии, по которым я пойму, что шаг завершён."
        return self.analyze_with_ai(task_text, prompt_template)

    def add_to_checklist(self, checklist, summary, deadline, actions):
        """Add items to a checklist dictionary"""
        deadline_date = self.parse_date(deadline) if deadline else None
        item_id = str(int(time.time() * 1000))
        
        item = {
            'summary': summary,
            'deadline': deadline,
            'deadline_date': deadline_date.isoformat() if deadline_date else None,
            'actions': actions,
            'completed': False,
            'created_at': datetime.now().isoformat()
        }
        
        checklist[item_id] = item
        return item_id

    def get_checklist_display(self, chat_id):
        """Load, clean, and format checklist for display"""
        checklist = self.load_checklist(chat_id)
        expired_count = self.clean_expired_items(checklist)

        if expired_count > 0:
            self.save_checklist(chat_id, checklist)

        if not checklist:
            msg = "📝 Ваш список задач пуст!"
            if expired_count > 0:
                msg += f"\n\n🗑️ Удалено {expired_count} просроченных задач"
            return msg
        
        response = "📋 <b>Ваш список задач:</b>\n\n"
        if expired_count > 0:
            response += f"🗑️ <i>Удалено {expired_count} просроченных задач</i>\n\n"
        
        for item_id, item in checklist.items():
            status = "✅" if item.get('completed') else "⏳"
            summary = item.get('summary', 'Без названия')
            summary_short = summary[:50] + "..." if len(summary) > 50 else summary
            
            response += f"{status} <b>{summary_short}</b>\n"
            
            if item.get('deadline') and item['deadline'].lower() != 'нет':
                response += f"   ⏰ Срок: {item['deadline']}\n"
            
            if item.get('actions') and item['actions'].lower() != 'нет':
                response += f"   📝 Действия: {item['actions']}\n"
            
            response += f"   🆔 ID: <code>{item_id[-6:]}</code>\n\n"
        
        response += "\n<b>Команды:</b>\n"
        response += "• <code>/checklist</code> - Показать список\n"
        response += "• <code>/complete [ID]</code> - Отметить как выполненное\n"
        response += "• <code>/delete [ID]</code> - Удалить задачу\n"
        response += "• <code>/clear</code> - Удалить все выполненные\n"
        response += "• <code>/simplify</code> - Упростить задачу"
        
        return response

    def handle_command(self, chat_id, command):
        """Handle bot commands by loading, modifying, and saving the checklist."""
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
            welcome += "• /clear - Удалить все выполненные\n"
            welcome += "• /simplify - Упростить задачу"
            self.send_message(chat_id, welcome)
            return
            
        elif cmd == '/checklist':
            checklist_display = self.get_checklist_display(chat_id)
            self.send_message(chat_id, checklist_display)
            return

        elif cmd == '/simplify':
            self.set_user_state(chat_id, "awaiting_simplify_task")
            self.send_message(chat_id, "Пожалуйста, введите задачу, которую вы хотите упростить.")
            return

        checklist = self.load_checklist(chat_id)
        response_message = "❌ Неизвестная ошибка"
            
        if cmd == '/complete' and len(cmd_parts) > 1:
            item_id_partial = cmd_parts[1]
            found = False
            for full_id in checklist:
                if full_id.endswith(item_id_partial):
                    checklist[full_id]['completed'] = True
                    found = True
                    break
            response_message = "✅ Задача отмечена как выполненная!" if found else "❌ Задача с таким ID не найдена."
                
        elif cmd == '/delete' and len(cmd_parts) > 1:
            item_id_partial = cmd_parts[1]
            found = False
            for full_id in list(checklist.keys()):
                if full_id.endswith(item_id_partial):
                    checklist.pop(full_id, None)
                    found = True
                    break
            response_message = "🗑️ Задача удалена!" if found else "❌ Задача с таким ID не найдена."
                
        elif cmd == '/clear':
            items_to_remove = [item_id for item_id, item in checklist.items() if item.get('completed')]
            for item_id in items_to_remove:
                checklist.pop(item_id, None)
            response_message = f"🗑️ Очищено {len(items_to_remove)} выполненных задач!"
                
        else:
            response_message = "Неизвестная команда. Используйте /start для помощи."

        self.save_checklist(chat_id, checklist)
        self.send_message(chat_id, response_message)

    def handle_message(self, message):
        """Process incoming message"""
        chat_id = message['chat']['id']
        text = message.get('text', '').strip()

        if not text:
            return

        if text.startswith('/'):
            self.handle_command(chat_id, text)
            return

        user_state = self.get_user_state(chat_id)
        if user_state == "awaiting_simplify_task":
            self.send_message(chat_id, "⏳ Упрощаю задачу... Пожалуйста, подождите.")
            simplified_steps_text = self.simplify_task(text)

            # Parse the response and add to checklist
            checklist = self.load_checklist(chat_id)
            new_steps = [step.strip() for step in simplified_steps_text.split('\n') if step.strip()]

            if not new_steps:
                self.send_message(chat_id, "Не удалось разбить задачу на шаги. Попробуйте переформулировать.")
                self.clear_user_state(chat_id)
                return

            for step_summary in new_steps:
                self.add_to_checklist(checklist, step_summary, "Нет", "Нет")

            self.save_checklist(chat_id, checklist)
            self.clear_user_state(chat_id)

            confirmation_message = "✅ Задача разбита на шаги и добавлена в ваш список!\n\n"
            confirmation_message += self.get_checklist_display(chat_id)
            self.send_message(chat_id, confirmation_message)
            return
            
        if 'forward_date' in message:
            message_text = f"[ПЕРЕСЛАНО] {text}"
        else:
            message_text = text

        if not message_text.strip():
            self.send_message(chat_id, "Пожалуйста, отправьте сообщение с текстом для анализа.")
            return

        requests.post(f"{self.base_url}/sendChatAction", data={'chat_id': chat_id, 'action': 'typing'})

        original_prompt_template = """Проанализируй это сообщение и извлеки:
1. Краткое содержание (1-2 предложения)
2. Любые конкретные даты, сроки или важную по времени информацию
3. Задачи или пункты, которые нужно выполнить

Отформатируй свой ответ точно так:
SUMMARY: [краткое содержание]
DEADLINE: [конкретная дата/время или "Нет"]
ACTIONS: [список задач через запятую или "Нет"]

Сообщение: [вставь свою]"""
        analysis = self.analyze_with_ai(message_text, original_prompt_template)
        
        summary, deadline, actions = "Нет содержания", "Нет", "Нет"
        for line in analysis.split('\n'):
            if line.startswith('SUMMARY:'): summary = line.replace('SUMMARY:', '').strip()
            elif line.startswith('DEADLINE:'): deadline = line.replace('DEADLINE:', '').strip()
            elif line.startswith('ACTIONS:'): actions = line.replace('ACTIONS:', '').strip()
        
        added_to_checklist = False
        if (actions and actions.lower() != 'нет') or (deadline and deadline.lower() != 'нет'):
            checklist = self.load_checklist(chat_id)
            self.add_to_checklist(checklist, summary, deadline, actions)
            self.save_checklist(chat_id, checklist)
            added_to_checklist = True
        
        response = f"🤖 <b>Анализ ИИ</b>\n\n📝 <b>Содержание:</b> {summary}\n"
        if deadline and deadline.lower() != 'нет':
            response += f"⏰ <b>Срок:</b> {deadline}\n"
        if actions and actions.lower() != 'нет':
            response += f"📋 <b>Действия:</b> {actions}\n"
        
        if added_to_checklist:
            response += f"\n✅ <b>Добавлено в список задач!</b> Используйте /checklist, чтобы посмотреть все задачи."
        else:
            response += f"\n💡 <i>Не найдено задач для добавления в список.</i>"
        
        self.send_message(chat_id, response)
        logging.info(f"Обработано сообщение от чата {chat_id}")

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
    redis_url = os.getenv('REDIS_URL')

    if not telegram_token or not groq_api_key:
        print("❌ Отсутствуют ключи API! Проверьте ваш .env файл.")
        print("Необходимы: TELEGRAM_BOT_TOKEN и GROQ_API_KEY")
        return

    if not redis_url:
        print("❌ Отсутствует REDIS_URL! Локальная база данных не будет работать.")
        print("Пожалуйста, настройте Redis и добавьте REDIS_URL в ваш .env файл.")
        return

    # Start bot
    bot = ChecklistBot(telegram_token, groq_api_key)
    bot.run()

if __name__ == '__main__':
    main()