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
        
        # HTML template with Black & Gold theme
        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Email Verification - {{ app_name }}</title>
            <style>
                body { 
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                    line-height: 1.6; 
                    color: #ffffff; 
                    background: linear-gradient(135deg, #000000, #0a0a0a);
                    margin: 0;
                    padding: 0;
                }
                .container { 
                    max-width: 600px; 
                    margin: 0 auto; 
                    padding: 20px; 
                    background: #000000;
                    border-radius: 12px;
                    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
                }
                .header { 
                    background: linear-gradient(135deg, #FFD700, #FFA500); 
                    color: #000000; 
                    padding: 30px 20px; 
                    text-align: center; 
                    border-radius: 12px 12px 0 0;
                    box-shadow: 0 4px 20px rgba(255, 215, 0, 0.3);
                }
                .header h1 {
                    margin: 0;
                    font-size: 28px;
                    font-weight: bold;
                    text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
                }
                .header h2 {
                    margin: 10px 0 0 0;
                    font-size: 20px;
                    font-weight: 500;
                }
                .content { 
                    padding: 40px 30px; 
                    background: #0a0a0a; 
                    border-radius: 0 0 12px 12px;
                }
                .content h3 {
                    color: #FFD700;
                    margin-bottom: 20px;
                    font-size: 24px;
                }
                .content p {
                    color: #e0e0e0;
                    margin-bottom: 20px;
                    font-size: 16px;
                }
                .code-box { 
                    background: linear-gradient(135deg, #1a1a1a, #0f0f0f); 
                    border: 2px solid #FFD700; 
                    padding: 30px; 
                    text-align: center; 
                    margin: 30px 0;
                    border-radius: 12px;
                    box-shadow: 0 0 20px rgba(255, 215, 0, 0.2);
                }
                .verification-code { 
                    font-size: 36px; 
                    font-weight: bold; 
                    letter-spacing: 10px; 
                    color: #FFD700; 
                    text-shadow: 0 0 10px rgba(255, 215, 0, 0.5);
                    font-family: 'Courier New', monospace;
                }
                .footer { 
                    padding: 30px; 
                    text-align: center; 
                    color: #888; 
                    font-size: 14px; 
                    background: #000000;
                    border-radius: 0 0 12px 12px;
                }
                .warning { 
                    color: #ff6b6b; 
                    font-size: 14px; 
                    margin-top: 25px; 
                    background: #1a0a0a;
                    padding: 20px;
                    border-radius: 8px;
                    border-left: 4px solid #ff6b6b;
                }
                .warning strong {
                    color: #ff6b6b;
                }
                .warning ul {
                    margin: 10px 0 0 20px;
                }
                .warning li {
                    margin-bottom: 8px;
                }
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
        
        # HTML template with Black & Gold theme
        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Password Reset - {{ app_name }}</title>
            <style>
                body { 
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                    line-height: 1.6; 
                    color: #ffffff; 
                    background: linear-gradient(135deg, #000000, #0a0a0a);
                    margin: 0;
                    padding: 0;
                }
                .container { 
                    max-width: 600px; 
                    margin: 0 auto; 
                    padding: 20px; 
                    background: #000000;
                    border-radius: 12px;
                    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
                }
                .header { 
                    background: linear-gradient(135deg, #ff6b6b, #ee5a24); 
                    color: #ffffff; 
                    padding: 30px 20px; 
                    text-align: center; 
                    border-radius: 12px 12px 0 0;
                    box-shadow: 0 4px 20px rgba(255, 107, 107, 0.3);
                }
                .header h1 {
                    margin: 0;
                    font-size: 28px;
                    font-weight: bold;
                    text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
                }
                .header h2 {
                    margin: 10px 0 0 0;
                    font-size: 20px;
                    font-weight: 500;
                }
                .content { 
                    padding: 40px 30px; 
                    background: #0a0a0a; 
                    border-radius: 0 0 12px 12px;
                }
                .content h3 {
                    color: #ff6b6b;
                    margin-bottom: 20px;
                    font-size: 24px;
                }
                .content p {
                    color: #e0e0e0;
                    margin-bottom: 20px;
                    font-size: 16px;
                }
                .code-box { 
                    background: linear-gradient(135deg, #1a0a0a, #0f0a0a); 
                    border: 2px solid #ff6b6b; 
                    padding: 30px; 
                    text-align: center; 
                    margin: 30px 0;
                    border-radius: 12px;
                    box-shadow: 0 0 20px rgba(255, 107, 107, 0.2);
                }
                .reset-code { 
                    font-size: 36px; 
                    font-weight: bold; 
                    letter-spacing: 10px; 
                    color: #ff6b6b; 
                    text-shadow: 0 0 10px rgba(255, 107, 107, 0.5);
                    font-family: 'Courier New', monospace;
                }
                .footer { 
                    padding: 30px; 
                    text-align: center; 
                    color: #888; 
                    font-size: 14px; 
                    background: #000000;
                    border-radius: 0 0 12px 12px;
                }
                .warning { 
                    color: #ff6b6b; 
                    font-size: 14px; 
                    margin-top: 25px; 
                    background: #1a0a0a;
                    padding: 20px;
                    border-radius: 8px;
                    border-left: 4px solid #ff6b6b;
                }
                .warning strong {
                    color: #ff6b6b;
                }
                .warning ul {
                    margin: 10px 0 0 20px;
                }
                .warning li {
                    margin-bottom: 8px;
                }
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

    def render_notification_email(self, notification_type: str, title: str, message: str, user_name: str, data: dict = None) -> tuple[str, str]:
        """Render notification email template with Black & Gold theme"""
        
        # Determine colors based on notification type
        color_schemes = {
            "payment_successful": {"primary": "#4CAF50", "secondary": "#2E7D32"},
            "order_processing": {"primary": "#FFD700", "secondary": "#FFA500"},
            "order_shipped": {"primary": "#2196F3", "secondary": "#1976D2"},
            "order_delivered": {"primary": "#4CAF50", "secondary": "#2E7D32"},
            "order_cancelled": {"primary": "#ff6b6b", "secondary": "#ee5a24"},
            "default": {"primary": "#FFD700", "secondary": "#FFA500"}
        }
        
        colors = color_schemes.get(notification_type, color_schemes["default"])
        
        # HTML template with Black & Gold theme
        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>{{ title }} - {{ app_name }}</title>
            <style>
                body {{ 
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                    line-height: 1.6; 
                    color: #ffffff; 
                    background: linear-gradient(135deg, #000000, #0a0a0a);
                    margin: 0;
                    padding: 0;
                }}
                .container {{ 
                    max-width: 600px; 
                    margin: 0 auto; 
                    padding: 20px; 
                    background: #000000;
                    border-radius: 12px;
                    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
                }}
                .header {{ 
                    background: linear-gradient(135deg, {{ primary_color }}, {{ secondary_color }}); 
                    color: #ffffff; 
                    padding: 30px 20px; 
                    text-align: center; 
                    border-radius: 12px 12px 0 0;
                    box-shadow: 0 4px 20px rgba({{ primary_rgb }}, 0.3);
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 28px;
                    font-weight: bold;
                    text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
                }}
                .header h2 {{
                    margin: 10px 0 0 0;
                    font-size: 20px;
                    font-weight: 500;
                }}
                .content {{ 
                    padding: 40px 30px; 
                    background: #0a0a0a; 
                    border-radius: 0 0 12px 12px;
                }}
                .content h3 {{
                    color: {{ primary_color }};
                    margin-bottom: 20px;
                    font-size: 24px;
                }}
                .content p {{
                    color: #e0e0e0;
                    margin-bottom: 20px;
                    font-size: 16px;
                }}
                .notification-box {{
                    background: linear-gradient(135deg, #1a1a1a, #0f0f0f);
                    border: 2px solid {{ primary_color }};
                    padding: 30px;
                    text-align: center;
                    margin: 30px 0;
                    border-radius: 12px;
                    box-shadow: 0 0 20px rgba({{ primary_rgb }}, 0.2);
                }}
                .notification-icon {{
                    font-size: 48px;
                    color: {{ primary_color }};
                    margin-bottom: 15px;
                }}
                .footer {{ 
                    padding: 30px; 
                    text-align: center; 
                    color: #888; 
                    font-size: 14px; 
                    background: #000000;
                    border-radius: 0 0 12px 12px;
                }}
                .data-info {{
                    background: #1a1a1a;
                    padding: 20px;
                    border-radius: 8px;
                    margin-top: 20px;
                    border-left: 4px solid {{ primary_color }};
                }}
                .data-info h4 {{
                    color: {{ primary_color }};
                    margin-bottom: 10px;
                }}
                .data-info p {{
                    color: #e0e0e0;
                    margin: 5px 0;
                    font-size: 14px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{{ app_name }}</h1>
                    <h2>{{ title }}</h2>
                </div>
                <div class="content">
                    <h3>Hello {{ user_name }},</h3>
                    <p>{{ message }}</p>
                    
                    <div class="notification-box">
                        <div class="notification-icon">{{ icon }}</div>
                        <p style="color: {{ primary_color }}; font-size: 18px; margin: 0;">{{ status_message }}</p>
                    </div>
                    
                    {% if data %}
                    <div class="data-info">
                        <h4>Order Details</h4>
                        {% if data.order_id %}
                        <p><strong>Order ID:</strong> #{{ data.order_id[:8] }}</p>
                        {% endif %}
                        {% if data.amount %}
                        <p><strong>Amount:</strong> ₦{{ "%.2f"|format(data.amount) }}</p>
                        {% endif %}
                        {% if data.seller_amount %}
                        <p><strong>Your Amount:</strong> ₦{{ "%.2f"|format(data.seller_amount) }}</p>
                        {% endif %}
                        {% if data.is_multi_seller %}
                        <p><strong>Multi-Seller Order:</strong> This order involves multiple sellers</p>
                        {% endif %}
                    </div>
                    {% endif %}
                </div>
                <div class="footer">
                    <p>© {{ app_name }} - {{ title }}</p>
                    <p>If you have any questions, please contact our support team.</p>
                </div>
            </div>
        </body>
        </html>
        """)
        
        # Determine icon and status message based on notification type
        notification_icons = {
            "payment_successful": "💰",
            "order_processing": "⚙️",
            "order_shipped": "🚚",
            "order_delivered": "✅",
            "order_cancelled": "❌"
        }
        
        status_messages = {
            "payment_successful": "Payment Received!",
            "order_processing": "Order Processing!",
            "order_shipped": "Order Shipped!",
            "order_delivered": "Order Delivered!",
            "order_cancelled": "Order Cancelled"
        }
        
        # Convert hex colors to RGB for rgba
        def hex_to_rgb(hex_color):
            hex_color = hex_color.lstrip('#')
            return ','.join(str(int(hex_color[i:i+2], 16)) for i in (0, 2, 4))
        
        context = {
            'app_name': settings.PROJECT_NAME,
            'user_name': user_name,
            'title': title,
            'message': message,
            'icon': notification_icons.get(notification_type, "📧"),
            'status_message': status_messages.get(notification_type, "Notification"),
            'primary_color': colors["primary"],
            'secondary_color': colors["secondary"],
            'primary_rgb': hex_to_rgb(colors["primary"]),
            'data': data
        }
        
        html_body = html_template.render(**context)
        
        # Text template
        text_template = Template("""
        {{ app_name }} - {{ title }}
        
        Hello {{ user_name }},
        
        {{ message }}
        
        {% if data %}
        Order Details:
        {% if data.order_id %}
        Order ID: #{{ data.order_id[:8] }}
        {% endif %}
        {% if data.amount %}
        Amount: ₦{{ "%.2f"|format(data.amount) }}
        {% endif %}
        {% if data.seller_amount %}
        Your Amount: ₦{{ "%.2f"|format(data.seller_amount) }}
        {% endif %}
        {% if data.is_multi_seller %}
        Multi-Seller Order: This order involves multiple sellers
        {% endif %}
        {% endif %}
        
        © {{ app_name }}
        """)
        
        text_body = text_template.render(**context)
        
        return html_body, text_body


# Global email service instance
email_service = EmailService()