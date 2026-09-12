import smtplib, ssl
from email.message import EmailMessage
from pathlib import Path

env = {}
for line in Path(__file__).resolve().parent.parent / '.env'.read_text().splitlines():
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        env[k] = v

msg = EmailMessage()
msg['Subject'] = 'jobbot SMTP test'
msg['From'] = env['MAIL_ADDRESS']
msg['To'] = env['REPORT_TO']
msg.set_content('If you are reading this, the nightly report can reach you.')

s = smtplib.SMTP_SSL(env['MAIL_SMTP_HOST'], int(env['MAIL_SMTP_PORT']),
                     context=ssl.create_default_context())
s.login(env['MAIL_ADDRESS'], env['MAIL_PASSWORD'])
s.send_message(msg)
s.quit()
print('SMTP OK — check your inbox')
