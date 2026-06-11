# StarCraft Mail

Self-hosted почтовый сервер с веб-интерфейсом в стиле StarCraft. Postfix + Dovecot + Flask API + ретро-фронтенд на чистом HTML/CSS/JS.

## Возможности

- 📬 Веб-почта: входящие, чтение, отправка, удаление писем
- 🎮 Ретро-интерфейс в стиле StarCraft (пиксельный шрифт Press Start 2P)
- 👤 Регистрация почтовых ящиков через веб
- 🛡 Админ-панель: управление ящиками, смена паролей, логи
- 🔤 Корректное декодирование MIME-заголовков (русские темы и имена отправителей)
- 📡 REST API поверх IMAP/SMTP

## Стек

- **Backend:** Python 3, Flask, imaplib/smtplib
- **Почта:** Postfix (SMTP) + Dovecot (IMAP/POP3, passwd-file)
- **Frontend:** чистый HTML/CSS/JS, без фреймворков

## Структура

| Файл | Назначение |
|------|-----------|
| `mail_api_deployed.py` | Актуальная версия Flask API (веб-почта + админка) |
| `webmail.html` | Интерфейс почтового ящика |
| `webmail_login.html` | Страница входа |
| `sc_registration.html` | Регистрация ящика |
| `sc_admin_login.html`, `sc_admin_panel.html` | Админка |
| `test_mail.py` | Тесты почтового стека |

## Установка

1. Настройте Postfix с virtual mailboxes (`virtual_mailbox_domains`, `virtual_mailbox_maps`) и Dovecot с passdb `passwd-file`.
2. Скопируйте API на сервер:
   ```bash
   scp mail_api_deployed.py root@YOUR_SERVER_IP:/opt/mail-api/mail_api.py
   ```
3. Запустите как systemd-сервис (порт 5001 по умолчанию).
4. Откройте `http://YOUR_SERVER_IP:5001/login`.

### Добавление ящика вручную

```bash
# /etc/dovecot/users
user@your-domain.com:{PLAIN}YOUR_PASSWORD_HERE:5000:8::/var/mail/vhosts/your-domain.com/user::

# /etc/postfix/virtual
user@your-domain.com your-domain.com/user/
# затем: postmap /etc/postfix/virtual

# права на ящик
mkdir -p /var/mail/vhosts/your-domain.com/user
chown -R vmail:mail /var/mail/vhosts/your-domain.com/user
```

### DNS

- `A`: mail → YOUR_SERVER_IP
- `MX`: @ → mail.your-domain.com (priority 10)
- `TXT` (SPF): `v=spf1 ip4:YOUR_SERVER_IP ~all`

## Лицензия

MIT
