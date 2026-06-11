#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import smtplib
from email.mime.text import MIMEText
import time
from datetime import datetime
import subprocess
import sys
import os

sys.stdout.recoding = 'utf-8'

MAIL_SERVER = "YOUR_SERVER_IP"
RECIPIENT = "user@your-domain.com"

def send_test_email(test_num):
    """Send test email via SMTP"""
    try:
        sender = f"test{test_num}@external.com"
        subject = f"Test Mail #{test_num} - {datetime.now().strftime('%H:%M:%S')}"
        body = f"Test email number {test_num}\nSent: {datetime.now().isoformat()}"

        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = RECIPIENT

        server = smtplib.SMTP(MAIL_SERVER, 25, timeout=10)
        server.send_message(msg)
        server.quit()

        print(f"[OK] Test {test_num}: Sent from {sender}")
        return True
    except Exception as e:
        print(f"[ERROR] Test {test_num}: {e}")
        return False

def check_delivered():
    """Check Postfix logs for delivery"""
    try:
        cmd = 'ssh -o StrictHostKeyChecking=no -i "~/.ssh/id_ed25519" root@YOUR_SERVER_IP "grep delivered /var/log/mail.log | grep ' + RECIPIENT + ' | tail -1"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return len(result.stdout.strip()) > 0
    except:
        return False

print("\n" + "="*60)
print("MAIL DELIVERY TEST - 10 ITERATIONS")
print(f"Target: {RECIPIENT}")
print("="*60 + "\n")

delivered = 0
for i in range(1, 11):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Test {i}/10")

    if send_test_email(i):
        time.sleep(1)
        if check_delivered():
            print("       -> DELIVERED")
            delivered += 1
        else:
            print("       -> PENDING")

    if i < 10:
        print(f"Wait 60 seconds...\n")
        time.sleep(60)

print("\n" + "="*60)
print(f"RESULT: {delivered}/10 delivered")
print("="*60)
