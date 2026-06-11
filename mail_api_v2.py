#!/usr/bin/env python3
"""Mail Management API - with authentication"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import subprocess
import os
import re
import logging
from datetime import datetime, timedelta
from pathlib import Path
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/mail-api.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация
MAIL_DOMAIN = 'dgtlwhale.com'
VHOST_PATH = '/var/mail/vhosts'
DOVECOT_USERS = '/etc/dovecot/users'
POSTFIX_VIRTUAL = '/etc/postfix/virtual'
MAIL_LOG = '/var/log/mail.log'
ADMIN_FILE = '/etc/postfix/admin_credentials'

# Админ пароль (по умолчанию: admin)
ADMIN_PASSWORD_HASH = 'admin_hash_placeholder'  # Будет обновлено скриптом

# ============================================================================
# Утилиты аутентификации
# ============================================================================

def init_admin():
    """Инициализировать админ пароль"""
    global ADMIN_PASSWORD_HASH
    try:
        with open(ADMIN_FILE, 'r') as f:
            ADMIN_PASSWORD_HASH = f.read().strip()
    except:
        ADMIN_PASSWORD_HASH = generate_password_hash('admin')
        with open(ADMIN_FILE, 'w') as f:
            f.write(ADMIN_PASSWORD_HASH)
        os.chmod(ADMIN_FILE, 0o600)

def require_admin(f):
    """Декоратор для защиты админ-панели"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# Страницы
# ============================================================================

@app.route('/')
def index():
    """Главная страница с регистрацией"""
    return render_template('registration.html', domain=MAIL_DOMAIN)

@app.route('/admin')
@require_admin
def admin_panel():
    """Админ панель"""
    return render_template('admin.html', domain=MAIL_DOMAIN)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Логин админа"""
    if request.method == 'POST':
        data = request.get_json()
        password = data.get('password', '').strip()

        if check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['admin_logged_in'] = True
            session.permanent = True
            app.permanent_session_lifetime = timedelta(hours=24)
            logger.info("Админ вошел в систему")
            return jsonify({"status": "ok"})
        else:
            logger.warning("Неверный пароль админа")
            return jsonify({"error": "Неверный пароль"}), 401

    return render_template('admin_login.html', domain=MAIL_DOMAIN)

@app.route('/admin/logout')
def admin_logout():
    """Выход админа"""
    session.clear()
    logger.info("Админ вышел из системы")
    return redirect(url_for('admin_login'))

# ============================================================================
# API - Регистрация ящиков
# ============================================================================

@app.route('/api/register', methods=['POST'])
def register_mailbox():
    """Регистрация нового ящика (публичный endpoint)"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()

        # Валидация
        if not username or not password:
            return jsonify({"error": "Нужны username и password"}), 400

        if len(username) < 3:
            return jsonify({"error": "Имя должно быть минимум 3 символа"}), 400

        if len(password) < 6:
            return jsonify({"error": "Пароль должен быть минимум 6 символов"}), 400

        if not re.match(r'^[a-zA-Z0-9._-]+$', username):
            return jsonify({"error": "Только буквы, цифры и . _ -"}), 400

        email = f"{username}@{MAIL_DOMAIN}"

        # Проверка существования
        with open(DOVECOT_USERS, 'r') as f:
            if email in f.read():
                return jsonify({"error": f"Ящик {email} уже занят"}), 400

        # Создание директории
        mailbox_path = Path(VHOST_PATH) / MAIL_DOMAIN / username
        mailbox_path.mkdir(parents=True, exist_ok=True)
        os.system(f"chown -R mail:mail {mailbox_path}")

        # Добавление в Dovecot
        with open(DOVECOT_USERS, 'a') as f:
            f.write(f"{email}:{{PLAIN}}{password}::::::\n")
        os.system(f"chmod 600 {DOVECOT_USERS}")

        # Добавление в Postfix
        with open(POSTFIX_VIRTUAL, 'a') as f:
            f.write(f"{email} {MAIL_DOMAIN}/{username}/\n")

        subprocess.run(['postmap', POSTFIX_VIRTUAL], check=True)
        subprocess.run(['systemctl', 'reload', 'postfix'], check=True)
        subprocess.run(['systemctl', 'reload', 'dovecot'], check=True)

        logger.info(f"Новый ящик: {email}")
        return jsonify({
            "status": "registered",
            "email": email,
            "message": f"Ящик {email} создан!"
        }), 201

    except Exception as e:
        logger.error(f"Ошибка регистрации: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# API - Админ управление
# ============================================================================

@app.route('/api/admin/mailboxes', methods=['GET'])
@require_admin
def admin_list_mailboxes():
    """Список всех ящиков (только для админа)"""
    try:
        with open(DOVECOT_USERS, 'r') as f:
            lines = f.readlines()

        mailboxes = []
        for line in lines:
            if line.strip() and not line.startswith('#'):
                parts = line.split(':')
                if len(parts) >= 1:
                    email = parts[0].strip()
                    mailboxes.append({"email": email, "status": "active"})

        return jsonify({"count": len(mailboxes), "mailboxes": mailboxes})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/mailboxes/<username>', methods=['DELETE'])
@require_admin
def admin_delete_mailbox(username):
    """Удалить ящик (только админ)"""
    try:
        email = f"{username}@{MAIL_DOMAIN}"

        with open(DOVECOT_USERS, 'r') as f:
            lines = f.readlines()
        with open(DOVECOT_USERS, 'w') as f:
            for line in lines:
                if not line.startswith(email):
                    f.write(line)

        with open(POSTFIX_VIRTUAL, 'r') as f:
            lines = f.readlines()
        with open(POSTFIX_VIRTUAL, 'w') as f:
            for line in lines:
                if not line.startswith(email):
                    f.write(line)

        subprocess.run(['postmap', POSTFIX_VIRTUAL], check=True)
        subprocess.run(['systemctl', 'reload', 'postfix'], check=True)
        subprocess.run(['systemctl', 'reload', 'dovecot'], check=True)

        logger.info(f"Админ удалил ящик: {email}")
        return jsonify({"status": "deleted", "email": email})

    except Exception as e:
        logger.error(f"Ошибка удаления: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/mailboxes/<username>/password', methods=['PUT'])
@require_admin
def admin_change_password(username):
    """Изменить пароль (админ)"""
    try:
        data = request.get_json()
        new_password = data.get('password', '').strip()

        if not new_password:
            return jsonify({"error": "password обязателен"}), 400

        email = f"{username}@{MAIL_DOMAIN}"

        with open(DOVECOT_USERS, 'r') as f:
            lines = f.readlines()

        with open(DOVECOT_USERS, 'w') as f:
            for line in lines:
                if line.startswith(email):
                    f.write(f"{email}:{{PLAIN}}{new_password}::::::\n")
                else:
                    f.write(line)

        os.system(f"chmod 600 {DOVECOT_USERS}")
        subprocess.run(['systemctl', 'reload', 'dovecot'], check=True)

        logger.info(f"Админ изменил пароль: {email}")
        return jsonify({"status": "updated", "email": email})

    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/logs', methods=['GET'])
@require_admin
def admin_get_logs():
    """Логи (админ)"""
    try:
        lines = int(request.args.get('lines', 50))
        result = subprocess.run(['tail', '-n', str(lines), MAIL_LOG],
                              capture_output=True, text=True)
        logs = [l for l in result.stdout.split('\n') if l]
        return jsonify({"count": len(logs), "logs": logs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    """Проверка статуса"""
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    init_admin()
    logger.info("Mail API v2 запущен на :5001")
    app.run(host='0.0.0.0', port=5001, debug=False)
