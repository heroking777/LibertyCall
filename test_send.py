#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'email_sender'))

from scheduler_service_prod import send_email_to_recipient

recipient = {
    'email': 'iam.heroking777@gmail.com',
    'company_name': '株式会社テスト',
    'stage': 'follow1'
}

success, error = send_email_to_recipient(recipient, use_simulation=False)
print(f'Success: {success}, Error: {error}')
