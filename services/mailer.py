import os
import smtplib
from email.mime.text import MIMEText

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")


def send_verification_email(to_email, verify_link):
    subject = "Verify your Not Movies account"
    body = f"""Hi,

Thanks for signing up for Not Movies! Click the link below to verify your account:

{verify_link}

This link will expire in 10 minutes.

If you didn't sign up for Not Movies, you can safely ignore this email.
"""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_email

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        server.send_message(msg)