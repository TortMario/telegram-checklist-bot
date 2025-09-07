import os
import json
import logging
from datetime import datetime, timedelta
import re
import redis
from groq import Groq
from http.server import BaseHTTPRequestHandler
import urllib.parse

logging.basicConfig(level=logging.INFO)

class ChecklistBot:
    def __init__(self, telegram_token, groq_api_key):
        self.token = telegram_token
        self.base_url = f'https://api.telegram.org/bot{telegram_token}'
        self.groq_client = Groq(api_key=groq_api_key)
        redis_url = os.getenv('KV_URL') or os.getenv('REDIS_URL')
        if redis_url:
            self.redis_client = redis.from_url(redis_url)
        else:
            self.redis_client = None
            logging.warning("KV_URL or REDIS_URL not found. Database functionality will be disabled.")

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

    def parse_date(self, date_str):
        if not date_str or date_str.lower() == 'нет': return None
        current_date = datetime.now()
        date_str_lower = date_str.lower()
        if 'tomorrow' in date_str_lower: return current_date + timedelta(days=1)
        if 'today' in date_str_lower: return current_date
        if 'next week' in date_str_lower: return current_date + timedelta(days=7)
        return None

    def analyze_with_ai(self, message_text, prompt_template):
        """General purpose AI analysis method."""
        prompt = prompt_template.replace("[вставь свою]", message_text)
        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "Ты — полезный ассистENT, который извлекает ключевую информацию из сообщений или выполняет задачи по шаблону."},
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

    def load_checklist(self, chat_id):
        if not self.redis_client: return {}
        try:
            data = self.redis_client.get(f"checklist:{chat_id}")
            if data: return json.loads(data)
        except Exception as e:
            logging.error(f"Error loading checklist from Redis for chat {chat_id}: {e}")
        return {}

    def save_checklist(self, chat_id, checklist):
        if not self.redis_client: return
        try:
            self.redis_client.set(f"checklist:{chat_id}", json.dumps(checklist, ensure_ascii=False))
        except Exception as e:
            logging.error(f"Error saving checklist to Redis for chat {chat_id}: {e}")

    def clean_expired_items(self, checklist):
        current_time = datetime.now()
        items_to_remove = [k for k, v in checklist.items() if v.get('deadline_date') and datetime.fromisoformat(v['deadline_date']) < current_time]
        for item_id in items_to_remove:
            checklist.pop(item_id, None)
        return len(items_to_remove)

    def add_to_checklist(self, checklist, summary, deadline, actions):
        deadline_date = self.parse_date(deadline) if deadline else None
        item_id = str(int(datetime.now().timestamp() * 1000))
        checklist[item_id] = {
            'summary': summary, 'deadline': deadline,
            'deadline_date': deadline_date.isoformat() if deadline_date else None,
            'actions': actions, 'completed': False, 'created_at': datetime.now().isoformat()
        }
        return item_id

    def get_checklist_display(self, chat_id):
        checklist = self.load_checklist(chat_id)
        expired_count = self.clean_expired_items(checklist)
        if expired_count > 0: self.save_checklist(chat_id, checklist)
        if not checklist:
            return "📝 Ваш список задач пуст!" + (f"\n\n🗑️ Удалено {expired_count} просроченных задач" if expired_count > 0 else "")
        response = "📋 <b>Ваш список задач:</b>\n\n"
        if expired_count > 0: response += f"🗑️ <i>Удалено {expired_count} просроченных задач</i>\n\n"
        for item_id, item in checklist.items():
            status = "✅" if item.get('completed') else "⏳"
            summary = item.get('summary', 'Без названия')
            response += f"{status} <b>{summary[:50]}{'...' if len(summary) > 50 else ''}</b>\n"
            if item.get('deadline') and item['deadline'].lower() != 'нет': response += f"   ⏰ Срок: {item['deadline']}\n"
            if item.get('actions') and item['actions'].lower() != 'нет': response += f"   📝 Действия: {item['actions']}\n"
            response += f"   🆔 ID: <code>{item_id[-6:]}</code>\n\n"
        response += "\n<b>Команды:</b>\n"
        response += "• <code>/checklist</code> - Показать список\n"
        response += "• <code>/complete [ID]</code> - Отметить как выполненное\n"
        response += "• <code>/delete [ID]</code> - Удалить задачу\n"
        response += "• <code>/clear</code> - Удалить все выполненные\n"
        response += "• <code>/simplify</code> - Упростить задачу"
        return response

    def send_message(self, chat_id, text):
        import requests
        url = f"{self.base_url}/sendMessage"
        data = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
        try:
            requests.post(url, data=data, timeout=10)
        except Exception as e:
            logging.error(f"Error sending message to {chat_id}: {e}")

    def handle_command(self, chat_id, command):
        cmd_parts = command.split()
        cmd = cmd_parts[0].lower()
        if cmd == '/start':
            welcome = "🤖 <b>Добро пожаловать в AI Checklist Bot!</b>\n\n..." # Truncated for brevity
            self.send_message(chat_id, welcome)
            return
        elif cmd == '/checklist':
            self.send_message(chat_id, self.get_checklist_display(chat_id))
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

    def handle_message(self, message_data):
        chat_id = message_data['chat']['id']
        text = message_data.get('text', '').strip()
        if not text: return

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
                # We can make the parsing more robust later if the AI gives more structured output
                self.add_to_checklist(checklist, step_summary, "Нет", "Нет")

            self.save_checklist(chat_id, checklist)
            self.clear_user_state(chat_id)

            confirmation_message = "✅ Задача разбита на шаги и добавлена в ваш список!\n\n"
            confirmation_message += self.get_checklist_display(chat_id)
            self.send_message(chat_id, confirmation_message)
            return

        # Original message analysis logic
        if 'forward_date' in message_data: message_text = f"[ПЕРЕСЛАНО] {text}"
        else: message_text = text
        if not message_text.strip():
            self.send_message(chat_id, "Пожалуйста, отправьте сообщение с текстом для анализа.")
            return

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
        if deadline and deadline.lower() != 'нет': response += f"⏰ <b>Срок:</b> {deadline}\n"
        if actions and actions.lower() != 'нет': response += f"📋 <b>Действия:</b> {actions}\n"
        if added_to_checklist:
            response += f"\n✅ <b>Добавлено в список задач!</b> Используйте /checklist, чтобы посмотреть все задачи."
        else:
            response += f"\n💡 <i>Не найдено задач для добавления в список.</i>"
        self.send_message(chat_id, response)

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
            groq_api_key = os.getenv('GROQ_API_KEY')
            if not telegram_token or not groq_api_key:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'Missing API keys')
                return
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            webhook_data = json.loads(body.decode('utf-8'))
            bot = ChecklistBot(telegram_token, groq_api_key)
            if 'message' in webhook_data:
                bot.handle_message(webhook_data['message'])
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
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'Bot is running!'}).encode('utf-8'))