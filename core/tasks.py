from core.notifications_service import create_notification
from db.session import get_db
from celery import current_task
from core.celery_app import celery_app
from core.email_service import email_service
from core.redis_client import verification_manager
import logging

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name='core.tasks.send_verification_email')
def send_verification_email(self, user_email: str, user_name: str):
    """
    Celery task to send email verification code
    
    Args:
        user_email: User's email address
        user_name: User's display name
    
    Returns:
        dict: Task result with success status and details
    """
    try:
        # Generate verification code
        verification_code = verification_manager.generate_verification_code(
            user_email, code_type="verification"
        )
        
        # Render email template
        html_body, text_body = email_service.render_verification_email(
            user_name, verification_code
        )
        
        # Send email
        success = email_service.send_email_sync(
            to_email=user_email,
            subject=f"Verify your email - {email_service.from_name}",
            html_body=html_body,
            text_body=text_body
        )
        
        if success:
            logger.info(f"Verification email sent successfully to {user_email}")
            return {
                "success": True,
                "message": f"Verification email sent to {user_email}",
                "task_id": self.request.id,
                "user_email": user_email
            }
        else:
            logger.error(f"Failed to send verification email to {user_email}")
            # Retry the task
            raise self.retry(countdown=60, max_retries=3)
            
    except Exception as exc:
        logger.error(f"Error sending verification email to {user_email}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True, name='core.tasks.send_password_reset_email')
def send_password_reset_email(self, user_email: str, user_name: str):
    """
    Celery task to send password reset code
    
    Args:
        user_email: User's email address
        user_name: User's display name
    
    Returns:
        dict: Task result with success status and details
    """
    try:
        # Generate password reset code
        reset_code = verification_manager.generate_verification_code(
            user_email, code_type="password_reset"
        )
        
        # Render email template
        html_body, text_body = email_service.render_password_reset_email(
            user_name, reset_code
        )
        
        # Send email
        success = email_service.send_email_sync(
            to_email=user_email,
            subject=f"Password Reset - {email_service.from_name}",
            html_body=html_body,
            text_body=text_body
        )
        
        if success:
            logger.info(f"Password reset email sent successfully to {user_email}")
            return {
                "success": True,
                "message": f"Password reset email sent to {user_email}",
                "task_id": self.request.id,
                "user_email": user_email
            }
        else:
            logger.error(f"Failed to send password reset email to {user_email}")
            # Retry the task
            raise self.retry(countdown=60, max_retries=3)
            
    except Exception as exc:
        logger.error(f"Error sending password reset email to {user_email}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True, name='core.tasks.send_welcome_email')
def send_welcome_email(self, user_email: str, user_name: str):
    """
    Celery task to send welcome email after successful verification
    
    Args:
        user_email: User's email address
        user_name: User's display name
    
    Returns:
        dict: Task result with success status and details
    """
    try:
        # Welcome email template with Black & Gold theme
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Welcome to {email_service.from_name}</title>
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
                    background: linear-gradient(135deg, #FFD700, #FFA500); 
                    color: #000000; 
                    padding: 30px 20px; 
                    text-align: center; 
                    border-radius: 12px 12px 0 0;
                    box-shadow: 0 4px 20px rgba(255, 215, 0, 0.3);
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
                    color: #FFD700;
                    margin-bottom: 20px;
                    font-size: 24px;
                }}
                .content p {{
                    color: #e0e0e0;
                    margin-bottom: 20px;
                    font-size: 16px;
                }}
                .welcome-box {{
                    background: linear-gradient(135deg, #1a1a1a, #0f0f0f);
                    border: 2px solid #FFD700;
                    padding: 30px;
                    text-align: center;
                    margin: 30px 0;
                    border-radius: 12px;
                    box-shadow: 0 0 20px rgba(255, 215, 0, 0.2);
                }}
                .welcome-icon {{
                    font-size: 48px;
                    color: #FFD700;
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
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{email_service.from_name}</h1>
                    <h2>Welcome!</h2>
                </div>
                <div class="content">
                    <h3>Hello {user_name},</h3>
                    <p>Welcome to {email_service.from_name}! Your email has been successfully verified and your account is now active.</p>
                    
                    <div class="welcome-box">
                        <div class="welcome-icon">🎉</div>
                        <p style="color: #FFD700; font-size: 18px; margin: 0;">Your account is now ready!</p>
                    </div>
                    
                    <p>You can now enjoy all the features of our platform. Thank you for joining our community!</p>
                    <p>If you have any questions, please don't hesitate to contact our support team.</p>
                </div>
                <div class="footer">
                    <p>© {email_service.from_name} - Welcome to the community!</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_body = f"""
        Welcome to {email_service.from_name}!
        
        Hello {user_name},
        
        Welcome to {email_service.from_name}! Your email has been successfully verified and your account is now active.
        
        You can now enjoy all the features of our platform. Thank you for joining our community!
        
        If you have any questions, please don't hesitate to contact our support team.
        
        © {email_service.from_name}
        """
        
        # Send email
        success = email_service.send_email_sync(
            to_email=user_email,
            subject=f"Welcome to {email_service.from_name}!",
            html_body=html_body,
            text_body=text_body
        )
        
        if success:
            logger.info(f"Welcome email sent successfully to {user_email}")
            return {
                "success": True,
                "message": f"Welcome email sent to {user_email}",
                "task_id": self.request.id,
                "user_email": user_email
            }
        else:
            logger.error(f"Failed to send welcome email to {user_email}")
            # Don't retry welcome emails - not critical
            return {
                "success": False,
                "message": f"Failed to send welcome email to {user_email}",
                "task_id": self.request.id,
                "user_email": user_email
            }
            
    except Exception as exc:
        logger.error(f"Error sending welcome email to {user_email}: {str(exc)}")
        return {
            "success": False,
            "message": f"Error sending welcome email: {str(exc)}",
            "task_id": self.request.id,
            "user_email": user_email
        }


@celery_app.task(name='core.tasks.cleanup_expired_codes')
def cleanup_expired_codes():
    """
    Periodic task to clean up expired verification codes
    This can be run as a periodic task using Celery Beat
    """
    try:
        from core.redis_client import redis_client
        
        # Get all verification and password reset keys
        verification_keys = redis_client.keys("email_verify:*")
        password_reset_keys = redis_client.keys("password_reset:*")
        rate_limit_keys = redis_client.keys("email_rate:*")
        
        expired_count = 0
        all_keys = verification_keys + password_reset_keys + rate_limit_keys
        
        for key in all_keys:
            ttl = redis_client.ttl(key)
            if ttl == -1:  # Key exists but has no expiration
                redis_client.delete(key)
                expired_count += 1
        
        logger.info(f"Cleaned up {expired_count} expired verification codes")
        return {
            "success": True,
            "cleaned_count": expired_count,
            "total_keys_checked": len(all_keys)
        }
        
    except Exception as exc:
        logger.error(f"Error during cleanup task: {str(exc)}")
        return {
            "success": False,
            "error": str(exc)
        }


@celery_app.task(bind=True, name='core.tasks.send_notification_email')
def send_notification_email(self, to_email: str, subject: str, html_body: str, text_body: str | None = None):
    """
    Generic notification email sender.
    """
    try:
        success = email_service.send_email_sync(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body or html_body,
        )
        if success:
            logger.info(f"Notification email sent to {to_email}")
            return {"success": True}
        else:
            logger.error(f"Failed to send notification email to {to_email}")
            raise self.retry(countdown=60, max_retries=3)
    except Exception as exc:
        logger.error(f"Error sending notification email to {to_email}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True, name='core.tasks.send_notification')
def send_notification(self, user_id: str, notification_type: str, title: str, message: str, data: dict = None, priority: str = "medium", channels: list = None):
    """
    Generic Celery task to send notifications
    
    Args:
        user_id: User ID to send notification to
        notification_type: Type of notification (order_processing, order_shipped, payment_successful, etc.)
        title: Notification title
        message: Notification message
        data: Additional notification data
        priority: Notification priority (low, medium, high)
        channels: Notification channels (in_app, email, sms, push)
    
    Returns:
        dict: Task result with success status and details
    """
    try:
        
        # Note: Celery tasks run in separate processes, so we need a new DB session
        # This is necessary for process isolation and reliability
        db = next(get_db())
        try:
            # Prepare notification payload
            notification_payload = {
                "user_id": user_id,
                "type": notification_type,
                "title": title,
                "message": message,
                "priority": priority,
                "channels": channels or ["in_app", "email"],
                "data": data
            }
            
            # Send notification
            create_notification(db, notification_payload)
            db.commit()
            
            logger.info(f"Notification sent to user {user_id} for {notification_type}")
            return {
                "success": True,
                "message": f"Notification sent to user {user_id}",
                "task_id": self.request.id,
                "user_id": user_id,
                "notification_type": notification_type
            }
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()
    except Exception as exc:
        logger.error(f"Error sending notification to user {user_id}: {str(exc)}")
        # Retry the task with exponential backoff
        raise self.retry(exc=exc, countdown=60, max_retries=3)