#!/usr/bin/env python3
"""
Mail Management API - управление почтовыми ящиками
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
import subprocess
import os
import re
import logging
from datetime import datetime
from pathlib import Path

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# Логирование
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

# ============================================================================
# API Endpoints
# ============================================================================

@app.route('/api/health', methods=['GET'])
def health():
    """Проверка здоровья API"""
    return jsonify({"status": "ok", "service": "mail-api"})


@app.route('/api/mailboxes', methods=['GET'])
def list_mailboxes():
    """Получить список всех ящиков"""
    try:
        with open(DOVECOT_USERS, 'r') as f:
            lines = f.readlines()

        mailboxes = []
        for line in lines:
            if line.strip() and not line.startswith('#'):
                parts = line.split(':')
                if len(parts) >= 1:
                    email = parts[0].strip()
                    mailboxes.append({
                        "email": email,
                        "domain": MAIL_DOMAIN,
                        "status": "active"
                    })

        logger.info(f"Получен список {len(mailboxes)} ящиков")
        return jsonify({"count": len(mailboxes), "mailboxes": mailboxes})
    except Exception as e:
        logger.error(f"Ошибка при получении списка: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/mailboxes', methods=['POST'])
def create_mailbox():
    """Создать новый ящик"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()

        if not username or not password:
            return jsonify({"error": "username и password обязательны"}), 400

        # Валидация имени
        if not re.match(r'^[a-zA-Z0-9._-]+$', username):
            return jsonify({"error": "Неверный формат имени ящика"}), 400

        email = f"{username}@{MAIL_DOMAIN}"

        # Проверка что ящик не существует
        with open(DOVECOT_USERS, 'r') as f:
            if email in f.read():
                return jsonify({"error": f"Ящик {email} уже существует"}), 400

        # Создаем директорию
        mailbox_path = Path(VHOST_PATH) / MAIL_DOMAIN / username
        mailbox_path.mkdir(parents=True, exist_ok=True)
        os.system(f"chown -R mail:mail {mailbox_path}")

        # Добавляем в Dovecot users
        with open(DOVECOT_USERS, 'a') as f:
            f.write(f"{email}:{{PLAIN}}{password}::::::\n")
        os.system(f"chmod 600 {DOVECOT_USERS}")

        # Добавляем в Postfix virtual
        with open(POSTFIX_VIRTUAL, 'a') as f:
            f.write(f"{email} {MAIL_DOMAIN}/{username}/\n")

        # Обновляем Postfix БД
        subprocess.run(['postmap', POSTFIX_VIRTUAL], check=True)
        subprocess.run(['systemctl', 'reload', 'postfix'], check=True)
        subprocess.run(['systemctl', 'reload', 'dovecot'], check=True)

        logger.info(f"Создан ящик: {email}")
        return jsonify({
            "status": "created",
            "email": email,
            "message": f"Ящик {email} успешно создан"
        }), 201

    except Exception as e:
        logger.error(f"Ошибка при создании ящика: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/mailboxes/<username>', methods=['DELETE'])
def delete_mailbox(username):
    """Удалить ящик"""
    try:
        email = f"{username}@{MAIL_DOMAIN}"

        # Удаляем из Dovecot users
        with open(DOVECOT_USERS, 'r') as f:
            lines = f.readlines()

        with open(DOVECOT_USERS, 'w') as f:
            for line in lines:
                if not line.startswith(email):
                    f.write(line)

        # Удаляем из Postfix virtual
        with open(POSTFIX_VIRTUAL, 'r') as f:
            lines = f.readlines()

        with open(POSTFIX_VIRTUAL, 'w') as f:
            for line in lines:
                if not line.startswith(email):
                    f.write(line)

        # Обновляем Postfix БД
        subprocess.run(['postmap', POSTFIX_VIRTUAL], check=True)
        subprocess.run(['systemctl', 'reload', 'postfix'], check=True)
        subprocess.run(['systemctl', 'reload', 'dovecot'], check=True)

        # Удаляем файлы (опционально)
        mailbox_path = Path(VHOST_PATH) / MAIL_DOMAIN / username
        if mailbox_path.exists():
            import shutil
            shutil.rmtree(mailbox_path)

        logger.info(f"Удален ящик: {email}")
        return jsonify({"status": "deleted", "email": email})

    except Exception as e:
        logger.error(f"Ошибка при удалении ящика: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/mailboxes/<username>/password', methods=['PUT'])
def change_password(username):
    """Изменить пароль ящика"""
    try:
        data = request.get_json()
        new_password = data.get('password', '').strip()

        if not new_password:
            return jsonify({"error": "password обязателен"}), 400

        email = f"{username}@{MAIL_DOMAIN}"

        # Обновляем в Dovecot users
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

        logger.info(f"Изменен пароль: {email}")
        return jsonify({"status": "updated", "email": email})

    except Exception as e:
        logger.error(f"Ошибка при изменении пароля: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Получить последние логи почты"""
    try:
        lines = int(request.args.get('lines', 50))

        result = subprocess.run(
            ['tail', '-n', str(lines), MAIL_LOG],
            capture_output=True,
            text=True
        )

        logs = result.stdout.split('\n')
        return jsonify({
            "count": len([l for l in logs if l]),
            "logs": [l for l in logs if l]
        })

    except Exception as e:
        logger.error(f"Ошибка при получении логов: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/test-email', methods=['POST'])
def send_test_email():
    """Отправить тестовое письмо"""
    try:
        data = request.get_json()
        to_email = data.get('to', '').strip()

        if not to_email:
            return jsonify({"error": "to обязателен"}), 400

        # Отправляем письмо
        test_message = f"Привет! Это тестовое письмо с почтового сервера {MAIL_DOMAIN}.\nВремя: {datetime.now()}"

        result = subprocess.run(
            f"echo \"{test_message}\" | sendmail -v {to_email}",
            shell=True,
            capture_output=True,
            text=True
        )

        logger.info(f"Отправлено тестовое письмо на {to_email}")
        return jsonify({
            "status": "sent",
            "to": to_email,
            "message": "Письмо отправлено"
        })

    except Exception as e:
        logger.error(f"Ошибка при отправке письма: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Web Interface
# ============================================================================

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html', domain=MAIL_DOMAIN)


@app.route('/static/<path:filename>')
def static_files(filename):
    """Статические файлы"""
    return send_from_directory('static', filename)


if __name__ == '__main__':
    logger.info("Запущен Mail API на порту 5001")
    app.run(host='0.0.0.0', port=5001, debug=False)
