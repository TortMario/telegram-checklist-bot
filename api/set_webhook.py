import os
import requests
import json
from http.server import BaseHTTPRequestHandler

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # Get environment variables
            telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
            
            if not telegram_token:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'Missing TELEGRAM_BOT_TOKEN')
                return
            
            # Read the request body to get the webhook URL
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                body = self.rfile.read(content_length)
                data = json.loads(body.decode('utf-8'))
                webhook_url = data.get('webhook_url')
            else:
                # Default to current domain
                host = self.headers.get('host', 'your-app.vercel.app')
                webhook_url = f"https://{host}/api/webhook"
            
            # Set the webhook
            telegram_url = f"https://api.telegram.org/bot{telegram_token}/setWebhook"
            
            response = requests.post(telegram_url, json={
                'url': webhook_url,
                'allowed_updates': ['message']
            })
            
            result = response.json()
            
            # Send response
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'status': 'success' if result.get('ok') else 'error',
                'webhook_url': webhook_url,
                'telegram_response': result
            }).encode('utf-8'))
            
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f'Error: {str(e)}'.encode('utf-8'))
    
    def do_GET(self):
        # Show current webhook info
        try:
            telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
            
            if not telegram_token:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'Missing TELEGRAM_BOT_TOKEN')
                return
            
            # Get webhook info
            telegram_url = f"https://api.telegram.org/bot{telegram_token}/getWebhookInfo"
            response = requests.get(telegram_url)
            result = response.json()
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result, indent=2).encode('utf-8'))
            
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f'Error: {str(e)}'.encode('utf-8'))