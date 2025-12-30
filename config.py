import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'azazelik-code-store-codelaft'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///database.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    # Telegram settings
    TELEGRAM_BOT_TOKEN = '8453591011:AAFVDeAyQfzXkWAVo4AH7JC7cWpu8WaeJQQ'
    TELEGRAM_CHAT_ID = '564049757'
    
    # Crypto settings
    CRYPTO_WALLET = 'TUgx6uehAb6wi2i798CetNgu1JHyhGCJxh'
    TRON_API_URL = 'https://api.trongrid.io'  # Основной API
    TRON_API_URL_2 = 'https://api.shasta.trongrid.io'  # Резервный API
    
    # TRON API Keys (бесплатные)
    TRON_API_KEY = 'f7b2147a-30e4-4e11-9e98-9c441c0e7b6e'
    TRONSCAN_API = 'https://apilist.tronscanapi.com/api'
    
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'zip', 'rar'}
    
    # Session settings
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
    # Payment verification
    PAYMENT_TIMEOUT = 1800  # 30 минут в секундах
    PAYMENT_CHECK_INTERVAL = 30  # Проверка каждые 30 секунд
    REQUIRED_CONFIRMATIONS = 1  # Требуемое количество подтверждений