#!/usr/bin/env python3
"""Mail API with Web Mail Interface - StarCraft Edition"""

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
import imaplib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.parser import Parser
import email

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

MAIL_DOMAIN = 'dgtlwhale.com'
VHOST_PATH = '/var/mail/vhosts'
DOVECOT_USERS = '/etc/dovecot/users'
POSTFIX_VIRTUAL = '/etc/postfix/virtual'
MAIL_LOG = '/var/log/mail.log'
ADMIN_FILE = '/etc/postfix/admin_credentials'

ADMIN_PASSWORD_HASH = 'admin_hash_placeholder'

# ============================================================================
# IMAP/SMTP Функции
# ============================================================================

def get_imap_connection(username, password):
    """Подключиться к IMAP"""
    try:
        mail = imaplib.IMAP4_SSL('127.0.0.1', 993)
        email_addr = f"{username}@{MAIL_DOMAIN}"
        mail.login(email_addr, password)
        return mail
    except Exception as e:
        logger.error(f"IMAP ошибка: {e}")
        return None

def get_inbox_list(mail, limit=20):
    """Получить список писем из inbox"""
    try:
        mail.select('INBOX')
        status, messages = mail.search(None, 'ALL')

        if status != 'OK':
            return []

        message_ids = messages[0].split()[-limit:]
        message_ids.reverse()

        emails = []
        for msg_id in message_ids:
            status, msg_data = mail.fetch(msg_id, '(RFC822.HEADER)')
            if status == 'OK':
                msg = email.message_from_bytes(msg_data[0][1])
                emails.append({
                    'id': msg_id.decode(),
                    'from': msg.get('From', 'Unknown'),
                    'subject': msg.get('Subject', '(No Subject)'),
                    'date': msg.get('Date', ''),
                })
        return emails
    except Exception as e:
        logger.error(f"Ошибка получения inbox: {e}")
        return []

def get_email_body(mail, msg_id):
    """Получить полное письмо"""
    try:
        status, msg_data = mail.fetch(msg_id, '(RFC822)')
        if status == 'OK':
            msg = email.message_from_bytes(msg_data[0][1])

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        break
            else:
                body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')

            return {
                'from': msg.get('From', ''),
                'to': msg.get('To', ''),
                'subject': msg.get('Subject', ''),
                'date': msg.get('Date', ''),
                'body': body
            }
    except Exception as e:
        logger.error(f"Ошибка получения письма: {e}")
    return None

def send_email(username, password, to, subject, body):
    """Отправить письмо через SMTP"""
    try:
        email_addr = f"{username}@{MAIL_DOMAIN}"

        msg = MIMEMultipart()
        msg['From'] = email_addr
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP('127.0.0.1', 25)
        server.starttls()
        server.login(email_addr, password)
        server.send_message(msg)
        server.quit()

        logger.info(f"Письмо отправлено из {email_addr} к {to}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки письма: {e}")
        return False

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
    """Защита админ-панели"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def require_user(f):
    """Защита почты пользователя"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_logged_in' not in session:
            return redirect(url_for('user_login'))
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# Маршруты - Регистрация и Админ
# ============================================================================

@app.route('/')
def index():
    """Главная страница с регистрацией"""
    return render_template('registration.html', domain=MAIL_DOMAIN)

@app.route('/api/health')
def health():
    """Проверка здоровья API"""
    return jsonify({"status": "ok"})

@app.route('/api/register', methods=['POST'])
def register():
    """Регистрация нового ящика"""
    data = request.get_json()
    username = data.get('username', '').strip().lower()
    password = data.get('password', '').strip()

    if not username or not password or len(username) < 3:
        return jsonify({"error": "Имя должно быть от 3 символов"}), 400

    email = f"{username}@{MAIL_DOMAIN}"
    vhost_dir = f"{VHOST_PATH}/{MAIL_DOMAIN}/{username}"

    try:
        os.makedirs(vhost_dir, exist_ok=True)
        os.makedirs(f"{vhost_dir}/Maildir/new", exist_ok=True)
        os.makedirs(f"{vhost_dir}/Maildir/cur", exist_ok=True)
        os.makedirs(f"{vhost_dir}/Maildir/tmp", exist_ok=True)

        subprocess.run(['chown', '-R', 'mail:mail', vhost_dir], check=True)
        subprocess.run(['chmod', '-R', '700', vhost_dir], check=True)

        with open(DOVECOT_USERS, 'a') as f:
            f.write(f"{email}:{generate_password_hash(password)}:5000:5000::{vhost_dir}::\n")

        with open(POSTFIX_VIRTUAL, 'a') as f:
            f.write(f"{email} {email}\n")

        subprocess.run(['postmap', POSTFIX_VIRTUAL], check=True)
        subprocess.run(['systemctl', 'reload', 'postfix', 'dovecot'], check=True)

        logger.info(f"Новый ящик: {email}")
        return jsonify({"status": "registered", "email": email}), 201

    except Exception as e:
        logger.error(f"Ошибка регистрации: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# Маршруты - Веб-почта
# ============================================================================

@app.route('/login')
def user_login():
    """Страница входа в почту"""
    return render_template('webmail_login.html', domain=MAIL_DOMAIN)

@app.route('/api/user/login', methods=['POST'])
def api_user_login():
    """Вход пользователя в почту"""
    data = request.get_json()
    username = data.get('username', '').strip().lower()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({"error": "Имя и пароль обязательны"}), 400

    try:
        mail = get_imap_connection(username, password)
        if mail:
            mail.logout()
            session['user_logged_in'] = True
            session['username'] = username
            session['password'] = password
            session['email'] = f"{username}@{MAIL_DOMAIN}"
            session.permanent = True
            app.permanent_session_lifetime = timedelta(hours=24)
            logger.info(f"Пользователь {username} вошел в почту")
            return jsonify({"status": "ok"})
        else:
            return jsonify({"error": "Неверные учетные данные"}), 401
    except Exception as e:
        logger.error(f"Ошибка входа: {e}")
        return jsonify({"error": "Ошибка аутентификации"}), 401

@app.route('/mail')
@require_user
def webmail():
    """Веб-почта (Inbox)"""
    return render_template('webmail.html', email=session.get('email'))

@app.route('/api/mail/inbox', methods=['GET'])
@require_user
def get_inbox():
    """API: Получить inbox"""
    username = session.get('username')

    try:
        from werkzeug.security import check_password_hash

        with open(DOVECOT_USERS, 'r') as f:
            for line in f:
                if line.startswith(session.get('email')):
                    stored_hash = line.split(':')[1]
                    break

        mail = imaplib.IMAP4_SSL('127.0.0.1', 993)
        mail.login(session.get('email'), session.get('password'))

        emails = get_inbox_list(mail, limit=50)
        mail.logout()

        return jsonify({"emails": emails})
    except Exception as e:
        logger.error(f"Ошибка получения inbox: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/mail/message/<msg_id>', methods=['GET'])
@require_user
def get_message(msg_id):
    """API: Получить письмо"""
    username = session.get('username')

    try:
        mail = get_imap_connection(username, session.get('password', ''))
        if not mail:
            return jsonify({"error": "Ошибка подключения"}), 500

        message = get_email_body(mail, msg_id.encode())
        mail.logout()

        if message:
            return jsonify(message)
        else:
            return jsonify({"error": "Письмо не найдено"}), 404
    except Exception as e:
        logger.error(f"Ошибка получения письма: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/mail/message/<msg_id>', methods=['DELETE'])
@require_user
def delete_message(msg_id):
    """API: Удалить письмо"""
    username = session.get('username')

    try:
        mail = get_imap_connection(username, session.get('password', ''))
        if not mail:
            return jsonify({"error": "Ошибка подключения"}), 500

        mail.select('INBOX')
        mail.store(msg_id.encode(), '+FLAGS', '\\Deleted')
        mail.expunge()
        mail.logout()

        logger.info(f"Письмо {msg_id} удалено для {username}")
        return jsonify({"status": "deleted"})
    except Exception as e:
        logger.error(f"Ошибка удаления письма: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/mail/send', methods=['POST'])
@require_user
def send_mail():
    """API: Отправить письмо"""
    data = request.get_json()
    to = data.get('to', '').strip()
    subject = data.get('subject', '').strip()
    body = data.get('body', '').strip()
    username = session.get('username')

    if not to or not subject:
        return jsonify({"error": "Заполните все поля"}), 400

    try:
        success = send_email(username, session.get('password', ''), to, subject, body)
        if success:
            return jsonify({"status": "sent"})
        else:
            return jsonify({"error": "Ошибка отправки"}), 500
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/user/logout')
def user_logout():
    """Выход из почты"""
    session.pop('user_logged_in', None)
    session.pop('username', None)
    session.pop('password', None)
    session.pop('email', None)
    return redirect(url_for('user_login'))

# ============================================================================
# Маршруты - Админ панель
# ============================================================================

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
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/api/admin/mailboxes', methods=['GET'])
@require_admin
def get_mailboxes():
    """Получить список всех ящиков"""
    try:
        mailboxes = []
        with open(DOVECOT_USERS, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    email = line.split(':')[0]
                    mailboxes.append({"email": email, "status": "active"})

        return jsonify({"count": len(mailboxes), "mailboxes": mailboxes})
    except Exception as e:
        logger.error(f"Ошибка получения ящиков: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/mailboxes/<username>/password', methods=['PUT'])
@require_admin
def change_password(username):
    """Изменить пароль ящика"""
    data = request.get_json()
    new_password = data.get('password', '').strip()

    if not new_password:
        return jsonify({"error": "Пароль обязателен"}), 400

    try:
        email = f"{username}@{MAIL_DOMAIN}"
        new_hash = generate_password_hash(new_password)

        with open(DOVECOT_USERS, 'r') as f:
            lines = f.readlines()

        with open(DOVECOT_USERS, 'w') as f:
            for line in lines:
                if line.startswith(email):
                    parts = line.split(':')
                    parts[1] = new_hash
                    f.write(':'.join(parts))
                else:
                    f.write(line)

        logger.info(f"Пароль изменен для {email}")
        return jsonify({"status": "ok", "email": email})
    except Exception as e:
        logger.error(f"Ошибка изменения пароля: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/mailboxes/<username>', methods=['DELETE'])
@require_admin
def delete_mailbox(username):
    """Удалить ящик"""
    try:
        email = f"{username}@{MAIL_DOMAIN}"
        vhost_dir = f"{VHOST_PATH}/{MAIL_DOMAIN}/{username}"

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
        subprocess.run(['rm', '-rf', vhost_dir], check=True)
        subprocess.run(['systemctl', 'reload', 'postfix', 'dovecot'], check=True)

        logger.info(f"Ящик удален: {email}")
        return jsonify({"status": "ok", "email": email})
    except Exception as e:
        logger.error(f"Ошибка удаления ящика: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/logs')
@require_admin
def get_logs():
    """Получить логи"""
    try:
        lines_count = request.args.get('lines', 50, type=int)
        with open('/var/log/mail-api.log', 'r') as f:
            logs = f.readlines()[-lines_count:]

        return jsonify({"logs": [log.strip() for log in logs]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================================================
# Инициализация
# ============================================================================

if __name__ == '__main__':
    init_admin()
    logger.info("Mail API v3 запущен на :5001")
    app.run(host='0.0.0.0', port=5001, debug=False)
