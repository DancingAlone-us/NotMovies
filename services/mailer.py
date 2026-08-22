import os
import resend

resend.api_key = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL") 


def send_verification_email(to_email, verify_link):
    subject = "Verify your Not Movies account"
    body = f"""Hi,

Thanks for signing up for Not Movies! Click the link below to verify your account:

{verify_link}

This link will expire in 10 minutes.

If you didn't sign up for Not Movies, you can safely ignore this email.
"""
    params = {
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    resend.Emails.send(params)