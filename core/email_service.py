import aiosmtplib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List
from jinja2 import Template
from core.config import settings
import logging

logger = logging.getLogger(__name__)


class EmailService:
    """Email service for sending verification and notification emails"""
    
    def __init__(self):
        """Initialize email service with SMTP configuration"""
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.username = settings.SMTP_USERNAME
        self.password = settings.SMTP_PASSWORD
        self.use_tls = settings.SMTP_USE_TLS
        self.use_ssl = settings.SMTP_USE_SSL
        self.from_email = settings.FROM_EMAIL or settings.SMTP_USERNAME
        self.from_name = settings.FROM_NAME
    
    def _create_message(
        self, 
        to_email: str, 
        subject: str, 
        html_body: str, 
        text_body: Optional[str] = None
    ) -> MIMEMultipart:
        """Create email message with HTML and optional text body"""
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"{self.from_name} <{self.from_email}>"
        message["To"] = to_email
        
        # Add text version if provided
        if text_body:
            text_part = MIMEText(text_body, "plain")
            message.attach(text_part)
        
        # Add HTML version
        html_part = MIMEText(html_body, "html")
        message.attach(html_part)
        
        return message
    
    async def send_email_async(
        self, 
        to_email: str, 
        subject: str, 
        html_body: str, 
        text_body: Optional[str] = None
    ) -> bool:
        """Send email asynchronously"""
        try:
            message = self._create_message(to_email, subject, html_body, text_body)
            
            # Configure SMTP connection
            if self.use_ssl:
                smtp = aiosmtplib.SMTP(hostname=self.smtp_host, port=self.smtp_port, use_tls=False)
                await smtp.connect()
                await smtp.starttls()
            else:
                smtp = aiosmtplib.SMTP(hostname=self.smtp_host, port=self.smtp_port, use_tls=self.use_tls)
                await smtp.connect()
            
            if self.username and self.password:
                await smtp.login(self.username, self.password)
            
            await smtp.send_message(message)
            await smtp.quit()
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False
    
    def send_email_sync(
        self, 
        to_email: str, 
        subject: str, 
        html_body: str, 
        text_body: Optional[str] = None
    ) -> bool:
        """Send email synchronously (for use in Celery tasks)"""
        try:
            message = self._create_message(to_email, subject, html_body, text_body)
            
            # Configure SMTP connection
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                if self.use_tls:
                    server.starttls()
            
            if self.username and self.password:
                server.login(self.username, self.password)
            
            server.send_message(message)
            server.quit()
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False
    
    def render_verification_email(self, user_name: str, verification_code: str) -> tuple[str, str]:
        """Render email verification email template"""
        
        # HTML template
        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Email Verification - {{ app_name }}</title>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background-color: #4CAF50; color: white; padding: 20px; text-align: center; }
                .content { padding: 30px 20px; background-color: #f9f9f9; }
                .code-box { 
                    background-color: #fff; 
                    border: 2px solid #4CAF50; 
                    padding: 20px; 
                    text-align: center; 
                    margin: 20px 0;
                    border-radius: 5px;
                }
                .verification-code { 
                    font-size: 32px; 
                    font-weight: bold; 
                    letter-spacing: 8px; 
                    color: #4CAF50; 
                }
                .footer { padding: 20px; text-align: center; color: #666; font-size: 14px; }
                .warning { color: #e74c3c; font-size: 14px; margin-top: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{{ app_name }}</h1>
                    <h2>Email Verification</h2>
                </div>
                <div class="content">
                    <h3>Hello {{ user_name }},</h3>
                    <p>Thank you for registering with {{ app_name }}! To complete your registration, please verify your email address using the verification code below:</p>
                    
                    <div class="code-box">
                        <div class="verification-code">{{ verification_code }}</div>
                    </div>
                    
                    <p>Enter this code on the verification page to activate your account.</p>
                    
                    <div class="warning">
                        <strong>Important:</strong>
                        <ul>
                            <li>This code will expire in {{ expire_minutes }} minutes</li>
                            <li>Do not share this code with anyone</li>
                            <li>If you didn't request this verification, please ignore this email</li>
                        </ul>
                    </div>
                </div>
                <div class="footer">
                    <p>© {{ app_name }} - Secure Email Verification</p>
                    <p>If you have any questions, please contact our support team.</p>
                </div>
            </div>
        </body>
        </html>
        """)
        
        # Text template
        text_template = Template("""
        {{ app_name }} - Email Verification
        
        Hello {{ user_name }},
        
        Thank you for registering with {{ app_name }}! To complete your registration, please verify your email address using the verification code below:
        
        Verification Code: {{ verification_code }}
        
        Enter this code on the verification page to activate your account.
        
        IMPORTANT:
        - This code will expire in {{ expire_minutes }} minutes
        - Do not share this code with anyone
        - If you didn't request this verification, please ignore this email
        
        © {{ app_name }}
        """)
        
        context = {
            'app_name': settings.PROJECT_NAME,
            'user_name': user_name,
            'verification_code': verification_code,
            'expire_minutes': settings.EMAIL_VERIFICATION_EXPIRE_MINUTES
        }
        
        html_body = html_template.render(**context)
        text_body = text_template.render(**context)
        
        return html_body, text_body
    
    def render_password_reset_email(self, user_name: str, reset_code: str) -> tuple[str, str]:
        """Render password reset email template"""
        
        # HTML template
        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Password Reset - {{ app_name }}</title>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background-color: #e74c3c; color: white; padding: 20px; text-align: center; }
                .content { padding: 30px 20px; background-color: #f9f9f9; }
                .code-box { 
                    background-color: #fff; 
                    border: 2px solid #e74c3c; 
                    padding: 20px; 
                    text-align: center; 
                    margin: 20px 0;
                    border-radius: 5px;
                }
                .reset-code { 
                    font-size: 32px; 
                    font-weight: bold; 
                    letter-spacing: 8px; 
                    color: #e74c3c; 
                }
                .footer { padding: 20px; text-align: center; color: #666; font-size: 14px; }
                .warning { color: #e74c3c; font-size: 14px; margin-top: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{{ app_name }}</h1>
                    <h2>Password Reset</h2>
                </div>
                <div class="content">
                    <h3>Hello {{ user_name }},</h3>
                    <p>We received a request to reset your password. Use the verification code below to proceed with resetting your password:</p>
                    
                    <div class="code-box">
                        <div class="reset-code">{{ reset_code }}</div>
                    </div>
                    
                    <p>Enter this code on the password reset page to create a new password.</p>
                    
                    <div class="warning">
                        <strong>Important:</strong>
                        <ul>
                            <li>This code will expire in {{ expire_minutes }} minutes</li>
                            <li>Do not share this code with anyone</li>
                            <li>If you didn't request a password reset, please ignore this email</li>
                            <li>Your current password remains unchanged until you complete the reset process</li>
                        </ul>
                    </div>
                </div>
                <div class="footer">
                    <p>© {{ app_name }} - Secure Password Reset</p>
                    <p>If you have any questions, please contact our support team.</p>
                </div>
            </div>
        </body>
        </html>
        """)
        
        # Text template
        text_template = Template("""
        {{ app_name }} - Password Reset
        
        Hello {{ user_name }},
        
        We received a request to reset your password. Use the verification code below to proceed with resetting your password:
        
        Reset Code: {{ reset_code }}
        
        Enter this code on the password reset page to create a new password.
        
        IMPORTANT:
        - This code will expire in {{ expire_minutes }} minutes
        - Do not share this code with anyone
        - If you didn't request a password reset, please ignore this email
        - Your current password remains unchanged until you complete the reset process
        
        © {{ app_name }}
        """)
        
        context = {
            'app_name': settings.PROJECT_NAME,
            'user_name': user_name,
            'reset_code': reset_code,
            'expire_minutes': settings.PASSWORD_RESET_EXPIRE_MINUTES
        }
        
        html_body = html_template.render(**context)
        text_body = text_template.render(**context)
        
        return html_body, text_body


# Global email service instance
email_service = EmailService()