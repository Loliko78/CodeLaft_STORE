from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import json
import requests
import uuid
import time
import threading
from decimal import Decimal
from PIL import Image
import io
import hashlib
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Context processor to make 'now' available in all templates
@app.context_processor
def inject_now():
    return {'now': datetime.utcnow()}

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)
    original_price = db.Column(db.Float)  # Цена без скидки
    price_type = db.Column(db.String(20), nullable=False)  # 'one_time' or 'subscription' or 'trial'
    subscription_days = db.Column(db.Integer, default=30)  # For subscription products
    trial_days = db.Column(db.Integer, default=7)  # Для тестового периода
    quantity = db.Column(db.Integer, default=1)
    image_filename = db.Column(db.String(200))
    form_fields = db.Column(db.Text)  # JSON string with form fields
    is_active = db.Column(db.Boolean, default=True)
    is_trial = db.Column(db.Boolean, default=False)  # Флаг тестового товара
    max_trial_per_user = db.Column(db.Integer, default=1)  # Максимум тестовых периодов на пользователя
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Связь с отзывами
    reviews = db.relationship('Review', backref='product', lazy=True, cascade='all, delete-orphan')
    # Связь с промокодами
    promocodes = db.relationship('Promocode', backref='product', lazy=True, cascade='all, delete-orphan')

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(50), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    promocode_id = db.Column(db.Integer, db.ForeignKey('promocode.id'), nullable=True)
    quantity = db.Column(db.Integer, default=1)
    amount = db.Column(db.Float, nullable=False)
    original_amount = db.Column(db.Float)  # Сумма без скидки
    discount_amount = db.Column(db.Float, default=0)  # Сумма скидки
    payment_type = db.Column(db.String(20), nullable=False)
    form_data = db.Column(db.Text)  # JSON string with form data
    status = db.Column(db.String(20), default='pending')  # pending, paid, cancelled, expired, trial
    transaction_hash = db.Column(db.String(100))  # Хэш транзакции TRON
    expires_at = db.Column(db.DateTime)  # Для подписок и тестов
    payment_expires_at = db.Column(db.DateTime)  # Время истечения ожидания оплаты
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('orders', lazy=True))
    product = db.relationship('Product', backref=db.backref('orders', lazy=True))
    promocode = db.relationship('Promocode', backref=db.backref('orders', lazy=True))

class UserProduct(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    expires_at = db.Column(db.DateTime)  # For subscriptions and trials
    is_active = db.Column(db.Boolean, default=True)
    is_trial = db.Column(db.Boolean, default=False)  # Флаг тестового периода
    
    user = db.relationship('User', backref=db.backref('user_products', lazy=True))
    product = db.relationship('Product')
    order = db.relationship('Order')

class Promocode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_type = db.Column(db.String(20), nullable=False)  # 'percentage' or 'fixed'
    discount_value = db.Column(db.Float, nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)  # None = для всех товаров
    usage_limit = db.Column(db.Integer, default=1)  # 0 = безлимитно
    used_count = db.Column(db.Integer, default=0)
    valid_from = db.Column(db.DateTime, default=datetime.utcnow)
    valid_until = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    comment = db.Column(db.Text, nullable=False)
    is_approved = db.Column(db.Boolean, default=False)  # Модерация отзывов
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('reviews', lazy=True))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# TRON Payment Verification Functions
class TronPaymentVerifier:
    @staticmethod
    def get_wallet_transactions(wallet_address, start_timestamp=None):
        """Получить транзакции кошелька через TRONSCAN API"""
        try:
            url = f"{app.config['TRONSCAN_API']}/transaction"
            params = {
                'address': wallet_address,
                'start_timestamp': start_timestamp or int((datetime.utcnow() - timedelta(hours=1)).timestamp() * 1000),
                'end_timestamp': int(datetime.utcnow().timestamp() * 1000),
                'sort': '-timestamp',
                'count': 50
            }
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get('data', []) if isinstance(data, dict) else data
        except Exception as e:
            print(f"Error fetching transactions from TronScan: {e}")
        
        return []

    @staticmethod
    def check_transaction(transaction_hash):
        """Проверить конкретную транзакцию"""
        try:
            # Проверка через TRONGRID
            url = f"{app.config['TRON_API_URL']}/v1/transactions/{transaction_hash}"
            headers = {
                'TRON-PRO-API-KEY': app.config['TRON_API_KEY']
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data
        except Exception as e:
            print(f"Error checking transaction: {e}")
        
        return None

    @staticmethod
    def verify_payment(order, wallet_address):
        """Проверить оплату для конкретного заказа"""
        try:
            # Ищем транзакции за последний час
            start_time = int((order.created_at - timedelta(hours=1)).timestamp() * 1000)
            transactions = TronPaymentVerifier.get_wallet_transactions(wallet_address, start_time)
            
            required_amount = Decimal(str(order.amount))
            
            for tx in transactions:
                # Проверяем USDT транзакции
                if tx.get('tokenInfo', {}).get('tokenAbbr') == 'USDT':
                    amount = Decimal(str(tx.get('amount', 0))) / Decimal('1000000')  # Конвертация из SUN
                    
                    # Проверяем сумму и получателя
                    if (amount >= required_amount * Decimal('0.99') and  # Допуск 1%
                        tx.get('toAddress') == wallet_address.lower()):
                        
                        # Проверяем подтверждения
                        confirmations = tx.get('confirmed', False)
                        if confirmations:
                            return {
                                'success': True,
                                'transaction_hash': tx.get('hash'),
                                'amount': float(amount),
                                'timestamp': tx.get('timestamp', 0) / 1000
                            }
            
            return {'success': False, 'message': 'Payment not found'}
            
        except Exception as e:
            print(f"Payment verification error: {e}")
            return {'success': False, 'message': str(e)}

    @staticmethod
    def start_payment_monitor():
        """Запуск мониторинга платежей в отдельном потоке"""
        def monitor():
            while True:
                try:
                    pending_orders = Order.query.filter(
                        Order.status == 'pending',
                        Order.payment_expires_at > datetime.utcnow()
                    ).all()
                    
                    for order in pending_orders:
                        result = TronPaymentVerifier.verify_payment(
                            order, 
                            app.config['CRYPTO_WALLET']
                        )
                        
                        if result['success']:
                            # Обновляем статус заказа
                            order.status = 'paid'
                            order.transaction_hash = result['transaction_hash']
                            
                            # Добавляем товар пользователю
                            user_product = UserProduct(
                                user_id=order.user_id,
                                product_id=order.product_id,
                                order_id=order.id,
                                expires_at=order.expires_at,
                                is_active=True
                            )
                            db.session.add(user_product)
                            
                            # Обновляем количество товара
                            product = order.product
                            if product.quantity > 0:
                                product.quantity -= order.quantity
                            
                            # Обновляем счетчик промокода
                            if order.promocode_id:
                                promocode = Promocode.query.get(order.promocode_id)
                                if promocode:
                                    promocode.used_count += 1
                            
                            db.session.commit()
                            
                            # Отправляем уведомление в Telegram
                            send_telegram_message(order, order.user, product, order.form_data)
                            
                            print(f"Order {order.order_id} confirmed!")
                    
                    db.session.commit()
                    time.sleep(app.config['PAYMENT_CHECK_INTERVAL'])
                    
                except Exception as e:
                    print(f"Monitor error: {e}")
                    time.sleep(30)
        
        # Запускаем монитор в фоновом потоке
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        print("Payment monitor started")

# Telegram bot functions
def send_telegram_message(order, user, product, form_data):
    try:
        token = app.config['TELEGRAM_BOT_TOKEN']
        chat_id = app.config['TELEGRAM_CHAT_ID']
        
        # Format message
        if order.status == 'trial':
            message = f"🆓 НОВЫЙ ТЕСТОВЫЙ ПЕРИОД!\n\n"
        else:
            message = f"✅ ОПЛАЧЕН НОВЫЙ ЗАКАЗ!\n\n"
        
        message += f"📦 Товар: {product.name}\n"
        
        if order.status != 'trial':
            message += f"💰 Сумма: {order.amount} USDT"
            
            if order.discount_amount > 0:
                message += f" (скидка: -{order.discount_amount} USDT)\n"
            else:
                message += "\n"
        else:
            message += f"💰 Тип: Тестовый период ({product.trial_days} дней)\n"
            
        message += f"👤 Пользователь: {user.username} (ID: {user.id})\n"
        message += f"📧 Email: {user.email}\n"
        message += f"🆔 Заказ: {order.order_id}\n"
        
        if order.status != 'trial' and order.transaction_hash:
            message += f"🔗 Транзакция: {order.transaction_hash}\n"
        
        message += f"📅 Дата: {order.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"🔢 Количество: {order.quantity}\n"
        
        if order.promocode:
            message += f"🎫 Промокод: {order.promocode.code}\n"
        
        if form_data:
            message += "\n📝 Данные от покупателя:\n"
            form_dict = json.loads(form_data)
            for key, value in form_dict.items():
                if key != 'files':
                    message += f"{key}: {value}\n"
        
        # Send message
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, json=data)
        
        # Send files if any
        if form_data:
            form_dict = json.loads(form_data)
            files = form_dict.get('files', [])
            for file_info in files:
                if file_info.get('filename'):
                    file_url = url_for('download_file', filename=file_info['filename'], _external=True)
                    url = f"https://api.telegram.org/bot{token}/sendDocument"
                    data = {
                        "chat_id": chat_id,
                        "document": file_url,
                        "caption": f"Файл от {user.username} для заказа {order.order_id}"
                    }
                    requests.post(url, json=data)
                    
                    # Delete file after sending
                    try:
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_info['filename'])
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    except:
                        pass
        
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def save_file(file):
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        return filename
    return None

def calculate_discounted_price(price, promocode):
    """Рассчитать цену со скидкой"""
    if not promocode:
        return price
    
    if promocode.discount_type == 'percentage':
        discount = price * (promocode.discount_value / 100)
    else:  # fixed
        discount = promocode.discount_value
    
    discounted_price = price - discount
    return max(discounted_price, 0)  # Цена не может быть отрицательной

def validate_promocode(code, product_id=None, user_id=None):
    """Проверить валидность промокода"""
    promocode = Promocode.query.filter_by(code=code, is_active=True).first()
    
    if not promocode:
        return {'valid': False, 'message': 'Промокод не найден'}
    
    # Проверка срока действия
    now = datetime.utcnow()
    if promocode.valid_from and now < promocode.valid_from:
        return {'valid': False, 'message': 'Промокод еще не активен'}
    
    if promocode.valid_until and now > promocode.valid_until:
        return {'valid': False, 'message': 'Промокод истек'}
    
    # Проверка лимита использования
    if promocode.usage_limit > 0 and promocode.used_count >= promocode.usage_limit:
        return {'valid': False, 'message': 'Промокод уже использован'}
    
    # Проверка привязки к товару
    if promocode.product_id and promocode.product_id != product_id:
        return {'valid': False, 'message': 'Промокод не действителен для этого товара'}
    
    # Проверка, использовал ли пользователь уже этот промокод
    if user_id:
        used = Order.query.filter_by(
            user_id=user_id,
            promocode_id=promocode.id,
            status='paid'
        ).first()
        if used:
            return {'valid': False, 'message': 'Вы уже использовали этот промокод'}
    
    return {'valid': True, 'promocode': promocode}

def can_user_get_trial(user_id, product_id):
    """Проверить, может ли пользователь получить тестовый период"""
    # Проверяем, не использовал ли уже пользователь тестовый период для этого товара
    trial_orders = Order.query.filter(
        Order.user_id == user_id,
        Order.product_id == product_id,
        Order.status == 'trial'
    ).count()
    
    if trial_orders > 0:
        return False, 'Вы уже использовали тестовый период для этого товара'
    
    # Проверяем общее количество тестовых периодов пользователя
    product = Product.query.get(product_id)
    if product:
        user_trials = Order.query.filter(
            Order.user_id == user_id,
            Order.status == 'trial'
        ).count()
        
        if user_trials >= product.max_trial_per_user:
            return False, f'Вы использовали максимальное количество тестовых периодов ({product.max_trial_per_user})'
    
    return True, ''

# Routes
@app.route('/')
def index():
    products = Product.query.filter_by(is_active=True).all()
    
    # Добавляем информацию о скидках и тестовых периодах
    for product in products:
        # Находим активный промокод для товара
        promocode = Promocode.query.filter(
            Promocode.product_id == product.id,
            Promocode.is_active == True,
            Promocode.valid_from <= datetime.utcnow(),
            (Promocode.valid_until == None) | (Promocode.valid_until >= datetime.utcnow())
        ).first()
        
        if promocode:
            product.has_discount = True
            product.discounted_price = calculate_discounted_price(product.price, promocode)
            product.discount_percent = int(promocode.discount_value) if promocode.discount_type == 'percentage' else None
        else:
            product.has_discount = False
            product.discounted_price = product.price
        
        # Проверяем, может ли текущий пользователь получить тестовый период
        if current_user.is_authenticated and product.price_type == 'trial':
            can_trial, message = can_user_get_trial(current_user.id, product.id)
            product.can_get_trial = can_trial
            product.trial_message = message
        else:
            product.can_get_trial = False
    
    return render_template('index.html', products=products)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user, remember=True)
            flash('Вход выполнен успешно!', 'success')
            return redirect(url_for('profile'))
        else:
            flash('Неверное имя пользователя или пароль', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('Имя пользователя уже занято', 'error')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email уже зарегистрирован', 'error')
            return redirect(url_for('register'))
        
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('Регистрация прошла успешно! Теперь вы можете войти.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    user_products = UserProduct.query.filter_by(user_id=current_user.id, is_active=True).all()
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    
    # Получаем отзывы пользователя
    reviews = Review.query.filter_by(user_id=current_user.id).order_by(Review.created_at.desc()).all()
    
    return render_template('profile.html', 
                         user_products=user_products, 
                         orders=orders,
                         reviews=reviews)

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    
    # Получаем активные промокоды для товара
    promocodes = Promocode.query.filter(
        Promocode.product_id == product.id,
        Promocode.is_active == True,
        Promocode.valid_from <= datetime.utcnow(),
        (Promocode.valid_until == None) | (Promocode.valid_until >= datetime.utcnow()),
        (Promocode.usage_limit == 0) | (Promocode.used_count < Promocode.usage_limit)
    ).all()
    
    # Получаем одобренные отзывы с информацией о пользователях
    reviews = Review.query.filter_by(
        product_id=product_id,
        is_approved=True
    ).order_by(Review.created_at.desc()).all()
    
    # Рассчитываем рейтинг
    avg_rating = 0
    if reviews:
        avg_rating = sum(review.rating for review in reviews) / len(reviews)
    
    # Проверяем, оставлял ли текущий пользователь отзыв
    user_review = None
    if current_user.is_authenticated:
        user_review = Review.query.filter_by(
            user_id=current_user.id,
            product_id=product_id
        ).first()
    
    # Рассчитываем цену со скидкой, если есть активный промокод
    discounted_price = product.price
    active_promocode = None
    
    if promocodes:
        # Используем первый активный промокод
        active_promocode = promocodes[0]
        discounted_price = calculate_discounted_price(product.price, active_promocode)
    
    # Проверяем, может ли пользователь получить тестовый период
    can_get_trial = False
    trial_message = ''
    if current_user.is_authenticated and product.price_type == 'trial':
        can_get_trial, trial_message = can_user_get_trial(current_user.id, product_id)
    
    return render_template('product.html', 
                         product=product,
                         reviews=reviews,
                         avg_rating=avg_rating,
                         user_review=user_review,
                         promocodes=promocodes,
                         discounted_price=discounted_price,
                         active_promocode=active_promocode,
                         can_get_trial=can_get_trial,
                         trial_message=trial_message)

@app.route('/add_review/<int:product_id>', methods=['POST'])
@login_required
def add_review(product_id):
    product = Product.query.get_or_404(product_id)
    
    # Проверяем, покупал ли пользователь товар
    has_purchased = UserProduct.query.filter_by(
        user_id=current_user.id,
        product_id=product_id,
        is_active=True
    ).first() is not None
    
    if not has_purchased:
        flash('Вы можете оставить отзыв только после покупки товара', 'error')
        return redirect(url_for('product_detail', product_id=product_id))
    
    # Проверяем, не оставлял ли уже отзыв
    existing_review = Review.query.filter_by(
        user_id=current_user.id,
        product_id=product_id
    ).first()
    
    if existing_review:
        flash('Вы уже оставили отзыв на этот товар', 'error')
        return redirect(url_for('product_detail', product_id=product_id))
    
    rating = request.form.get('rating', type=int)
    comment = request.form.get('comment', '').strip()
    
    if not (1 <= rating <= 5):
        flash('Рейтинг должен быть от 1 до 5', 'error')
        return redirect(url_for('product_detail', product_id=product_id))
    
    if not comment or len(comment) < 10:
        flash('Отзыв должен содержать минимум 10 символов', 'error')
        return redirect(url_for('product_detail', product_id=product_id))
    
    review = Review(
        user_id=current_user.id,
        product_id=product_id,
        rating=rating,
        comment=comment,
        is_approved=False  # Требуется модерация
    )
    
    db.session.add(review)
    db.session.commit()
    
    flash('Отзыв отправлен на модерацию. Спасибо!', 'success')
    return redirect(url_for('product_detail', product_id=product_id))

@app.route('/delete_review/<int:review_id>', methods=['POST'])
@login_required
def delete_review(review_id):
    review = Review.query.get_or_404(review_id)
    
    if review.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    
    db.session.delete(review)
    db.session.commit()
    
    flash('Отзыв удален', 'success')
    return redirect(url_for('product_detail', product_id=review.product_id))

@app.route('/buy/<int:product_id>', methods=['GET', 'POST'])
@login_required
def buy_product(product_id):
    product = Product.query.get_or_404(product_id)
    
    # Если товар тестовый, создаем заказ сразу
    if product.price_type == 'trial':
        # Проверяем, может ли пользователь получить тестовый период
        can_trial, message = can_user_get_trial(current_user.id, product_id)
        if not can_trial:
            flash(message, 'error')
            return redirect(url_for('product_detail', product_id=product_id))
        
        if request.method == 'POST':
            # Handle form data for trial
            form_data = {}
            if product.form_fields:
                fields = json.loads(product.form_fields)
                for field in fields:
                    field_name = field['name']
                    if field['type'] == 'file':
                        files = []
                        file = request.files.get(field_name)
                        if file and file.filename:
                            filename = save_file(file)
                            if filename:
                                files.append({
                                    'filename': filename,
                                    'original_name': file.filename
                                })
                        form_data[field_name] = files
                    else:
                        form_data[field_name] = request.form.get(field_name, '')
            
            # Create trial order
            order_id = f"TRIAL-{uuid.uuid4().hex[:8].upper()}"
            order = Order(
                order_id=order_id,
                user_id=current_user.id,
                product_id=product.id,
                quantity=1,
                amount=0,  # Бесплатно
                original_amount=0,
                discount_amount=0,
                payment_type='trial',
                form_data=json.dumps(form_data, ensure_ascii=False),
                status='trial',
                expires_at=datetime.utcnow() + timedelta(days=product.trial_days)
            )
            
            db.session.add(order)
            db.session.commit()
            
            # Add product to user's collection
            user_product = UserProduct(
                user_id=current_user.id,
                product_id=product.id,
                order_id=order.id,
                expires_at=order.expires_at,
                is_active=True,
                is_trial=True
            )
            db.session.add(user_product)
            db.session.commit()
            
            # Send notification to Telegram
            send_telegram_message(order, current_user, product, order.form_data)
            
            flash(f'Тестовый период активирован на {product.trial_days} дней!', 'success')
            return redirect(url_for('profile'))
        
        # Display form for trial
        form_fields = json.loads(product.form_fields) if product.form_fields else []
        return render_template('buy_trial.html', 
                             product=product, 
                             form_fields=form_fields,
                             now=datetime.utcnow())
    
    # Обычный товар (покупка или подписка)
    if request.method == 'POST':
        # Проверяем промокод
        promocode_input = request.form.get('promocode', '').strip()
        promocode = None
        discount_amount = 0
        
        if promocode_input:
            validation = validate_promocode(promocode_input, product_id, current_user.id)
            if validation['valid']:
                promocode = validation['promocode']
                discount_amount = product.price - calculate_discounted_price(product.price, promocode)
            else:
                flash(validation['message'], 'error')
                return redirect(url_for('buy_product', product_id=product_id))
        
        # Handle form data
        form_data = {}
        if product.form_fields:
            fields = json.loads(product.form_fields)
            for field in fields:
                field_name = field['name']
                if field['type'] == 'file':
                    files = []
                    file = request.files.get(field_name)
                    if file and file.filename:
                        filename = save_file(file)
                        if filename:
                            files.append({
                                'filename': filename,
                                'original_name': file.filename
                            })
                    form_data[field_name] = files
                else:
                    form_data[field_name] = request.form.get(field_name, '')
        
        # Calculate final amount
        final_amount = product.price - discount_amount
        
        # Create order
        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        order = Order(
            order_id=order_id,
            user_id=current_user.id,
            product_id=product.id,
            promocode_id=promocode.id if promocode else None,
            quantity=1,
            amount=final_amount,
            original_amount=product.price,
            discount_amount=discount_amount,
            payment_type='usdt_trc20',
            form_data=json.dumps(form_data, ensure_ascii=False),
            status='pending',
            payment_expires_at=datetime.utcnow() + timedelta(seconds=app.config['PAYMENT_TIMEOUT'])
        )
        
        if product.price_type == 'subscription':
            order.expires_at = datetime.utcnow() + timedelta(days=product.subscription_days)
        
        db.session.add(order)
        db.session.commit()
        
        return render_template('payment.html', 
                             order=order, 
                             product=product,
                             wallet=app.config['CRYPTO_WALLET'],
                             promocode=promocode)
    
    # Display form
    form_fields = json.loads(product.form_fields) if product.form_fields else []
    
    # Получаем доступные промокоды
    promocodes = Promocode.query.filter(
        (Promocode.product_id == product_id) | (Promocode.product_id == None),
        Promocode.is_active == True,
        Promocode.valid_from <= datetime.utcnow(),
        (Promocode.valid_until == None) | (Promocode.valid_until >= datetime.utcnow()),
        (Promocode.usage_limit == 0) | (Promocode.used_count < Promocode.usage_limit)
    ).all()
    
    return render_template('buy.html', 
                         product=product, 
                         form_fields=form_fields,
                         promocodes=promocodes)

# Context processor to make 'now' and 'timedelta' available in all templates
@app.context_processor
def inject_now():
    return {'now': datetime.utcnow(), 'timedelta': timedelta}

@app.route('/check_payment_status/<order_id>')
@login_required
def check_payment_status(order_id):
    order = Order.query.filter_by(order_id=order_id, user_id=current_user.id).first_or_404()
    
    result = TronPaymentVerifier.verify_payment(order, app.config['CRYPTO_WALLET'])
    
    if result['success']:
        # Обновляем статус заказа
        order.status = 'paid'
        order.transaction_hash = result['transaction_hash']
        
        # Добавляем товар пользователю
        user_product = UserProduct(
            user_id=current_user.id,
            product_id=order.product_id,
            order_id=order.id,
            expires_at=order.expires_at,
            is_active=True
        )
        db.session.add(user_product)
        
        # Обновляем количество товара
        product = order.product
        if product.quantity > 0:
            product.quantity -= order.quantity
        
        # Обновляем счетчик промокода
        if order.promocode_id:
            promocode = Promocode.query.get(order.promocode_id)
            if promocode:
                promocode.used_count += 1
        
        db.session.commit()
        
        # Отправляем уведомление в Telegram
        send_telegram_message(order, current_user, product, order.form_data)
        
        return jsonify({
            'success': True,
            'redirect': url_for('profile')
        })
    
    # Проверяем не истекло ли время ожидания оплаты
    if order.payment_expires_at and datetime.utcnow() > order.payment_expires_at:
        order.status = 'expired'
        db.session.commit()
        return jsonify({
            'success': False,
            'message': 'Время оплаты истекло',
            'expired': True
        })
    
    return jsonify({
        'success': False,
        'message': 'Оплата не найдена',
        'expired': False
    })

@app.route('/download_file/<filename>')
def download_file(filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    abort(404)

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        abort(403)
    
    products = Product.query.all()
    orders = Order.query.order_by(Order.created_at.desc()).all()
    users = User.query.all()
    promocodes = Promocode.query.all()
    reviews = Review.query.order_by(Review.created_at.desc()).all()
    
    # Статистика
    total_revenue = sum(order.amount for order in orders if order.status == 'paid')
    pending_orders = sum(1 for order in orders if order.status == 'pending')
    trial_orders = sum(1 for order in orders if order.status == 'trial')
    total_users = len(users)
    
    return render_template('admin.html', 
                         products=products, 
                         orders=orders, 
                         users=users,
                         promocodes=promocodes,
                         reviews=reviews,
                         total_revenue=total_revenue,
                         pending_orders=pending_orders,
                         trial_orders=trial_orders,
                         total_users=total_users)

@app.route('/admin/add_product', methods=['GET', 'POST'])
@login_required
def add_product():
    if not current_user.is_admin:
        abort(403)
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        price = float(request.form.get('price'))
        
        # Исправление для original_price (может быть пустым)
        original_price_str = request.form.get('original_price')
        if original_price_str and original_price_str.strip():
            original_price = float(original_price_str)
        else:
            original_price = price
        
        price_type = request.form.get('price_type')
        subscription_days = int(request.form.get('subscription_days', 30))
        trial_days = int(request.form.get('trial_days', 7))
        quantity = int(request.form.get('quantity', 1))
        max_trial_per_user = int(request.form.get('max_trial_per_user', 1))
        
        # Handle image upload
        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                image_filename = save_file(file)
        
        # Handle form fields
        form_fields = []
        field_names = request.form.getlist('field_name[]')
        field_types = request.form.getlist('field_type[]')
        field_required = request.form.getlist('field_required[]')
        
        for i in range(len(field_names)):
            if field_names[i]:
                form_fields.append({
                    'name': field_names[i],
                    'type': field_types[i],
                    'required': field_required[i] == 'true',
                    'label': field_names[i].replace('_', ' ').title()
                })
        
        product = Product(
            name=name,
            description=description,
            price=price,
            original_price=original_price,
            price_type=price_type,
            subscription_days=subscription_days,
            trial_days=trial_days,
            quantity=quantity,
            image_filename=image_filename,
            form_fields=json.dumps(form_fields, ensure_ascii=False),
            is_trial=(price_type == 'trial'),
            max_trial_per_user=max_trial_per_user
        )
        
        db.session.add(product)
        db.session.commit()
        
        flash('Товар успешно добавлен!', 'success')
        return redirect(url_for('admin_panel'))
    
    return render_template('add_product.html')

@app.route('/admin/edit_product/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    if not current_user.is_admin:
        abort(403)
    
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        product.name = request.form.get('name')
        product.description = request.form.get('description')
        product.price = float(request.form.get('price'))
        
        # Исправление для original_price (может быть пустым)
        original_price_str = request.form.get('original_price')
        if original_price_str and original_price_str.strip():
            product.original_price = float(original_price_str)
        else:
            product.original_price = product.price
        
        product.price_type = request.form.get('price_type')
        product.subscription_days = int(request.form.get('subscription_days', 30))
        product.trial_days = int(request.form.get('trial_days', 7))
        product.quantity = int(request.form.get('quantity', 1))
        product.is_active = request.form.get('is_active') == 'true'
        product.is_trial = (request.form.get('price_type') == 'trial')
        product.max_trial_per_user = int(request.form.get('max_trial_per_user', 1))
        
        # Handle image upload
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                # Delete old image
                if product.image_filename:
                    old_path = os.path.join(app.config['UPLOAD_FOLDER'], product.image_filename)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                product.image_filename = save_file(file)
        
        # Handle form fields
        form_fields = []
        field_names = request.form.getlist('field_name[]')
        field_types = request.form.getlist('field_type[]')
        field_required = request.form.getlist('field_required[]')
        
        for i in range(len(field_names)):
            if field_names[i]:
                form_fields.append({
                    'name': field_names[i],
                    'type': field_types[i],
                    'required': field_required[i] == 'true',
                    'label': field_names[i].replace('_', ' ').title()
                })
        
        product.form_fields = json.dumps(form_fields, ensure_ascii=False)
        
        db.session.commit()
        flash('Товар успешно обновлен!', 'success')
        return redirect(url_for('admin_panel'))
    
    form_fields = json.loads(product.form_fields) if product.form_fields else []
    return render_template('edit_product.html', product=product, form_fields=form_fields)

@app.route('/admin/delete_product/<int:product_id>')
@login_required
def delete_product(product_id):
    if not current_user.is_admin:
        abort(403)
    
    product = Product.query.get_or_404(product_id)
    
    # Проверяем, есть ли заказы связанные с этим продуктом
    orders_with_product = Order.query.filter_by(product_id=product_id).count()
    
    if orders_with_product > 0:
        flash(f'Нельзя удалить товар, так как с ним связано {orders_with_product} заказов', 'error')
        return redirect(url_for('admin_panel'))
    
    # Delete image file
    if product.image_filename:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], product.image_filename)
        if os.path.exists(filepath):
            os.remove(filepath)
    
    db.session.delete(product)
    db.session.commit()
    
    flash('Товар удален!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/add_promocode', methods=['GET', 'POST'])
@login_required
def add_promocode():
    if not current_user.is_admin:
        abort(403)
    
    if request.method == 'POST':
        code = request.form.get('code').strip().upper()
        discount_type = request.form.get('discount_type')
        discount_value = float(request.form.get('discount_value'))
        
        # Исправление для product_id (может быть 'all')
        product_id_str = request.form.get('product_id')
        if product_id_str and product_id_str != 'all':
            product_id = int(product_id_str)
        else:
            product_id = None
        
        usage_limit = int(request.form.get('usage_limit', 1))
        
        # Parse dates
        valid_from_str = request.form.get('valid_from')
        valid_until_str = request.form.get('valid_until')
        
        valid_from = datetime.strptime(valid_from_str, '%Y-%m-%dT%H:%M') if valid_from_str else datetime.utcnow()
        valid_until = datetime.strptime(valid_until_str, '%Y-%m-%dT%H:%M') if valid_until_str else None
        
        # Check if code already exists
        if Promocode.query.filter_by(code=code).first():
            flash('Промокод с таким кодом уже существует', 'error')
            return redirect(url_for('admin_panel'))
        
        promocode = Promocode(
            code=code,
            discount_type=discount_type,
            discount_value=discount_value,
            product_id=product_id,
            usage_limit=usage_limit,
            valid_from=valid_from,
            valid_until=valid_until,
            is_active=True
        )
        
        db.session.add(promocode)
        db.session.commit()
        
        flash('Промокод успешно добавлен!', 'success')
        return redirect(url_for('admin_panel'))
    
    products = Product.query.filter_by(is_active=True).all()
    return render_template('add_promocode.html', products=products)

@app.route('/admin/edit_promocode/<int:promocode_id>', methods=['GET', 'POST'])
@login_required
def edit_promocode(promocode_id):
    if not current_user.is_admin:
        abort(403)
    
    promocode = Promocode.query.get_or_404(promocode_id)
    
    if request.method == 'POST':
        promocode.code = request.form.get('code').strip().upper()
        promocode.discount_type = request.form.get('discount_type')
        promocode.discount_value = float(request.form.get('discount_value'))
        
        # Исправление для product_id (может быть 'all')
        product_id_str = request.form.get('product_id')
        if product_id_str and product_id_str != 'all':
            promocode.product_id = int(product_id_str)
        else:
            promocode.product_id = None
        
        promocode.usage_limit = int(request.form.get('usage_limit', 1))
        promocode.is_active = request.form.get('is_active') == 'true'
        
        # Parse dates
        valid_from_str = request.form.get('valid_from')
        valid_until_str = request.form.get('valid_until')
        
        if valid_from_str:
            promocode.valid_from = datetime.strptime(valid_from_str, '%Y-%m-%dT%H:%M')
        if valid_until_str:
            promocode.valid_until = datetime.strptime(valid_until_str, '%Y-%m-%dT%H:%M')
        
        db.session.commit()
        flash('Промокод успешно обновлен!', 'success')
        return redirect(url_for('admin_panel'))
    
    products = Product.query.filter_by(is_active=True).all()
    return render_template('edit_promocode.html', promocode=promocode, products=products)

@app.route('/admin/delete_promocode/<int:promocode_id>')
@login_required
def delete_promocode(promocode_id):
    if not current_user.is_admin:
        abort(403)
    
    promocode = Promocode.query.get_or_404(promocode_id)
    db.session.delete(promocode)
    db.session.commit()
    
    flash('Промокод удален!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/toggle_review/<int:review_id>/<action>')
@login_required
def toggle_review(review_id, action):
    if not current_user.is_admin:
        abort(403)
    
    review = Review.query.get_or_404(review_id)
    
    if action == 'approve':
        review.is_approved = True
        flash('Отзыв одобрен', 'success')
    elif action == 'reject':
        review.is_approved = False
        flash('Отзыв отклонен', 'success')
    elif action == 'delete':
        db.session.delete(review)
        flash('Отзыв удален', 'success')
    
    db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin/orders')
@login_required
def admin_orders():
    if not current_user.is_admin:
        abort(403)
    
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('orders.html', orders=orders)

@app.route('/admin/order_details/<int:order_id>')
@login_required
def order_details(order_id):
    if not current_user.is_admin:
        abort(403)
    
    order = Order.query.get_or_404(order_id)
    
    # Parse form data
    form_data = {}
    if order.form_data:
        try:
            form_data = json.loads(order.form_data)
        except:
            form_data = {'error': 'Не удалось прочитать данные формы'}
    
    return render_template('order_details.html', 
                         order=order, 
                         form_data=form_data,
                         user=order.user,
                         product=order.product)

@app.route('/admin/manual_confirm/<int:order_id>')
@login_required
def manual_confirm(order_id):
    if not current_user.is_admin:
        abort(403)
    
    order = Order.query.get_or_404(order_id)
    
    if order.status == 'pending':
        # Обновляем статус заказа
        order.status = 'paid'
        order.transaction_hash = f"MANUAL-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        # Добавляем товар пользователю
        user_product = UserProduct(
            user_id=order.user_id,
            product_id=order.product_id,
            order_id=order.id,
            expires_at=order.expires_at,
            is_active=True
        )
        db.session.add(user_product)
        
        # Обновляем количество товара
        product = order.product
        if product.quantity > 0:
            product.quantity -= order.quantity
        
        # Обновляем счетчик промокода
        if order.promocode_id:
            promocode = Promocode.query.get(order.promocode_id)
            if promocode:
                promocode.used_count += 1
        
        db.session.commit()
        
        # Отправляем уведомление в Telegram
        send_telegram_message(order, order.user, product, order.form_data)
        
        flash('Заказ успешно подтвержден вручную!', 'success')
    else:
        flash('Заказ уже обработан', 'warning')
    
    return redirect(url_for('admin_orders'))

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

# API endpoints
@app.route('/api/check_promocode', methods=['POST'])
@login_required
def check_promocode():
    data = request.get_json()
    code = data.get('code', '').strip()
    product_id = data.get('product_id')
    
    validation = validate_promocode(code, product_id, current_user.id)
    
    if validation['valid']:
        promocode = validation['promocode']
        product = Product.query.get(product_id)
        
        if product:
            discounted_price = calculate_discounted_price(product.price, promocode)
            discount_amount = product.price - discounted_price
            
            return jsonify({
                'valid': True,
                'discounted_price': discounted_price,
                'discount_amount': discount_amount,
                'discount_text': f'-{promocode.discount_value}{"%" if promocode.discount_type == "percentage" else " USDT"}'
            })
    
    return jsonify({
        'valid': False,
        'message': validation.get('message', 'Неверный промокод')
    })

@app.route('/api/check_subscriptions', methods=['POST'])
def check_subscriptions():
    # This would be called by a cron job to check expired subscriptions
    expired_products = UserProduct.query.filter(
        UserProduct.expires_at < datetime.utcnow(),
        UserProduct.is_active == True
    ).all()
    
    for user_product in expired_products:
        user_product.is_active = False
        db.session.add(user_product)
    
    db.session.commit()
    return jsonify({'updated': len(expired_products)})

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(403)
def forbidden_error(error):
    return render_template('403.html'), 403

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

# Create admin user on first run
def create_admin():
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', email='admin@codelaft.store', is_admin=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("Admin user created: admin / admin123")

# Флаг для отслеживания инициализации
_monitor_started = False
@app.route('/confirm_payment/<order_id>', methods=['POST'])
@login_required
def confirm_payment(order_id):
    """Ручное подтверждение оплаты пользователем (для случаев, когда автоматическая проверка не сработала)"""
    order = Order.query.filter_by(order_id=order_id, user_id=current_user.id).first_or_404()
    
    # Проверяем оплату
    result = TronPaymentVerifier.verify_payment(order, app.config['CRYPTO_WALLET'])
    
    if result['success']:
        # Обновляем статус заказа
        order.status = 'paid'
        order.transaction_hash = result['transaction_hash']
        
        # Добавляем товар пользователю
        user_product = UserProduct(
            user_id=current_user.id,
            product_id=order.product_id,
            order_id=order.id,
            expires_at=order.expires_at,
            is_active=True
        )
        db.session.add(user_product)
        
        # Обновляем количество товара
        product = order.product
        if product.quantity > 0:
            product.quantity -= order.quantity
        
        # Обновляем счетчик промокода
        if order.promocode_id:
            promocode = Promocode.query.get(order.promocode_id)
            if promocode:
                promocode.used_count += 1
        
        db.session.commit()
        
        # Отправляем уведомление в Telegram
        send_telegram_message(order, current_user, product, order.form_data)
        
        flash('Оплата подтверждена! Товар добавлен в ваш аккаунт.', 'success')
        return redirect(url_for('profile'))
    
    # Проверяем не истекло ли время ожидания оплаты
    if order.payment_expires_at and datetime.utcnow() > order.payment_expires_at:
        order.status = 'expired'
        db.session.commit()
        flash('Время оплаты истекло. Пожалуйста, создайте новый заказ.', 'error')
        return redirect(url_for('product_detail', product_id=order.product_id))
    
    flash('Оплата не найдена. Если вы уже отправили средства, подождите несколько минут или проверьте правильность суммы и адреса.', 'warning')
    return redirect(url_for('check_payment_status', order_id=order_id))
@app.before_request
def start_payment_monitor_once():
    global _monitor_started
    if not _monitor_started:
        _monitor_started = True
        # Запускаем монитор в отдельном потоке
        monitor_thread = threading.Thread(target=TronPaymentVerifier.start_payment_monitor, daemon=True)
        monitor_thread.start()
        print("Payment monitor started")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_admin()
        # Также запускаем монитор сразу при старте
        monitor_thread = threading.Thread(target=TronPaymentVerifier.start_payment_monitor, daemon=True)
        monitor_thread.start()
    app.run(debug=True, port=5000, threaded=True)