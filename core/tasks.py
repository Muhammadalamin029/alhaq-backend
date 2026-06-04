from core.notifications_service import create_notification
from db.session import get_db
from celery import current_task
from core.celery_app import celery_app
from core.email_service import email_service
from core.redis_client import verification_manager
from core.model import User, Profile, SellerProfile, GeneralInspection, GeneralAgreement, CarUnit, PropertyUnit, Order, Dispute
from core.system_settings_service import system_settings_service
from datetime import datetime, timedelta
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


@celery_app.task(bind=True, name='core.tasks.send_login_email')
def send_login_email(self, user_email: str, user_name: str,
                     login_time: str, ip_address: str = None, device: str = None):
    """Send a security notification when a user logs in."""
    try:
        html_body, text_body = email_service.render_login_email(
            user_name, login_time, ip_address, device
        )
        success = email_service.send_email_sync(
            to_email=user_email,
            subject=f"New Sign-In to {email_service.from_name}",
            html_body=html_body,
            text_body=text_body,
        )
        if success:
            logger.info(f"Login email sent to {user_email}")
            return {"success": True}
        else:
            raise self.retry(countdown=60, max_retries=2)
    except Exception as exc:
        logger.error(f"Error sending login email to {user_email}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=2)


@celery_app.task(bind=True, name='core.tasks.send_payout_requested_email')
def send_payout_requested_email(self, seller_email: str, business_name: str,
                                 amount: str, bank_name: str, account_number: str):
    """Notify a seller that their payout request was received."""
    try:
        html_body, text_body = email_service.render_payout_requested_email(
            business_name, amount, bank_name, account_number
        )
        success = email_service.send_email_sync(
            to_email=seller_email,
            subject=f"Payout Request Received — {amount}",
            html_body=html_body,
            text_body=text_body,
        )
        if success:
            logger.info(f"Payout requested email sent to {seller_email}")
            return {"success": True}
        else:
            raise self.retry(countdown=60, max_retries=2)
    except Exception as exc:
        logger.error(f"Error sending payout requested email to {seller_email}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=2)


# ──────────────────────────────────────────────────────────────────────────────
# KYC emails
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name='core.tasks.send_kyc_approved_email')
def send_kyc_approved_email(self, seller_email: str, business_name: str, approval_date: str):
    """Notify a seller their KYC verification was approved."""
    try:
        html_body, text_body = email_service.render_kyc_approved_email(business_name, approval_date)
        success = email_service.send_email_sync(
            to_email=seller_email,
            subject=f"KYC Approved — Welcome to {email_service.from_name}!",
            html_body=html_body, text_body=text_body,
        )
        if success:
            logger.info(f"KYC approved email sent to {seller_email}")
            return {"success": True}
        raise self.retry(countdown=60, max_retries=2)
    except Exception as exc:
        logger.error(f"Error sending KYC approved email to {seller_email}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=2)


@celery_app.task(bind=True, name='core.tasks.send_kyc_rejected_email')
def send_kyc_rejected_email(self, seller_email: str, business_name: str, reason: str = None):
    """Notify a seller their KYC verification was rejected."""
    try:
        html_body, text_body = email_service.render_kyc_rejected_email(business_name, reason)
        success = email_service.send_email_sync(
            to_email=seller_email,
            subject=f"KYC Verification — Action Required",
            html_body=html_body, text_body=text_body,
        )
        if success:
            logger.info(f"KYC rejected email sent to {seller_email}")
            return {"success": True}
        raise self.retry(countdown=60, max_retries=2)
    except Exception as exc:
        logger.error(f"Error sending KYC rejected email to {seller_email}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=2)


# ──────────────────────────────────────────────────────────────────────────────
# Payout emails
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name='core.tasks.send_payout_completed_email')
def send_payout_completed_email(self, seller_email: str, business_name: str,
                                 amount: str, bank_name: str, reference: str):
    """Notify a seller their payout was successfully processed."""
    try:
        html_body, text_body = email_service.render_payout_completed_email(
            business_name, amount, bank_name, reference
        )
        success = email_service.send_email_sync(
            to_email=seller_email,
            subject=f"Payout Successful — {amount} Sent",
            html_body=html_body, text_body=text_body,
        )
        if success:
            logger.info(f"Payout completed email sent to {seller_email}")
            return {"success": True}
        raise self.retry(countdown=60, max_retries=2)
    except Exception as exc:
        logger.error(f"Error sending payout completed email to {seller_email}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=2)


@celery_app.task(bind=True, name='core.tasks.send_payout_failed_email')
def send_payout_failed_email(self, seller_email: str, business_name: str,
                              amount: str, reason: str):
    """Notify a seller their payout failed and the balance was restored."""
    try:
        html_body, text_body = email_service.render_payout_failed_email(business_name, amount, reason)
        success = email_service.send_email_sync(
            to_email=seller_email,
            subject=f"Payout Failed — {amount} Returned to Balance",
            html_body=html_body, text_body=text_body,
        )
        if success:
            logger.info(f"Payout failed email sent to {seller_email}")
            return {"success": True}
        raise self.retry(countdown=60, max_retries=2)
    except Exception as exc:
        logger.error(f"Error sending payout failed email to {seller_email}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=2)


# ──────────────────────────────────────────────────────────────────────────────
# Inspection / Agreement emails
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name='core.tasks.send_inspection_confirmed_email')
def send_inspection_confirmed_email(self, user_email: str, user_name: str,
                                     asset_title: str, inspection_date: str,
                                     location: str, seller_name: str,
                                     seller_contact: str = None):
    """Notify a buyer their inspection has been confirmed by the seller."""
    try:
        html_body, text_body = email_service.render_inspection_confirmed_email(
            user_name, asset_title, inspection_date, location, seller_name, seller_contact
        )
        success = email_service.send_email_sync(
            to_email=user_email,
            subject=f"Inspection Confirmed — {asset_title}",
            html_body=html_body, text_body=text_body,
        )
        if success:
            logger.info(f"Inspection confirmed email sent to {user_email}")
            return {"success": True}
        raise self.retry(countdown=60, max_retries=2)
    except Exception as exc:
        logger.error(f"Error sending inspection confirmed email to {user_email}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=2)


@celery_app.task(bind=True, name='core.tasks.send_agreement_created_email')
def send_agreement_created_email(self, seller_email: str, seller_name: str,
                                  buyer_name: str, asset_title: str,
                                  total_price: str, deposit: str, plan_type: str,
                                  monthly: str = None, duration: str = None):
    """Notify the seller a new agreement has been created (pending their review)."""
    try:
        html_body, text_body = email_service.render_agreement_created_email(
            seller_name, buyer_name, asset_title, total_price, deposit, plan_type, monthly, duration
        )
        success = email_service.send_email_sync(
            to_email=seller_email,
            subject=f"New Agreement Awaiting Review — {asset_title}",
            html_body=html_body, text_body=text_body,
        )
        if success:
            logger.info(f"Agreement created email sent to {seller_email}")
            return {"success": True}
        raise self.retry(countdown=60, max_retries=2)
    except Exception as exc:
        logger.error(f"Error sending agreement created email to {seller_email}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=2)


@celery_app.task(bind=True, name='core.tasks.send_agreement_approved_email')
def send_agreement_approved_email(self, user_email: str, user_name: str,
                                   asset_title: str, total_price: str, remaining: str,
                                   next_due: str = None, monthly: str = None):
    """Notify the buyer their agreement is now active after deposit confirmation."""
    try:
        html_body, text_body = email_service.render_agreement_approved_email(
            user_name, asset_title, total_price, remaining, next_due, monthly
        )
        success = email_service.send_email_sync(
            to_email=user_email,
            subject=f"Agreement Active — {asset_title}",
            html_body=html_body, text_body=text_body,
        )
        if success:
            logger.info(f"Agreement approved email sent to {user_email}")
            return {"success": True}
        raise self.retry(countdown=60, max_retries=2)
    except Exception as exc:
        logger.error(f"Error sending agreement approved email to {user_email}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=2)


# ──────────────────────────────────────────────────────────────────────────────
# Dispute emails
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name='core.tasks.send_dispute_opened_email')
def send_dispute_opened_email(self, user_email: str, user_name: str,
                               dispute_title: str, reference: str,
                               order_or_agreement_id: str = None):
    """Notify the user their dispute has been received and is under review."""
    try:
        html_body, text_body = email_service.render_dispute_opened_email(
            user_name, dispute_title, reference, order_or_agreement_id
        )
        success = email_service.send_email_sync(
            to_email=user_email,
            subject=f"Dispute Received — {dispute_title}",
            html_body=html_body, text_body=text_body,
        )
        if success:
            logger.info(f"Dispute opened email sent to {user_email}")
            return {"success": True}
        raise self.retry(countdown=60, max_retries=2)
    except Exception as exc:
        logger.error(f"Error sending dispute opened email to {user_email}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=2)


@celery_app.task(bind=True, name='core.tasks.send_dispute_resolved_email')
def send_dispute_resolved_email(self, user_email: str, user_name: str,
                                 dispute_title: str, resolution: str,
                                 notes: str = None):
    """Notify the user their dispute has been resolved."""
    try:
        html_body, text_body = email_service.render_dispute_resolved_email(
            user_name, dispute_title, resolution, notes
        )
        success = email_service.send_email_sync(
            to_email=user_email,
            subject=f"Dispute Resolved — {dispute_title}",
            html_body=html_body, text_body=text_body,
        )
        if success:
            logger.info(f"Dispute resolved email sent to {user_email}")
            return {"success": True}
        raise self.retry(countdown=60, max_retries=2)
    except Exception as exc:
        logger.error(f"Error sending dispute resolved email to {user_email}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=2)


# ──────────────────────────────────────────────────────────────────────────────
# Order status emails
# ──────────────────────────────────────────────────────────────────────────────

@celery_app.task(bind=True, name='core.tasks.send_order_shipped_email')
def send_order_shipped_email(self, user_email: str, user_name: str,
                              order_id: str, items_summary: str, total: str,
                              tracking_note: str = None):
    """Notify the buyer their order has been shipped."""
    try:
        html_body, text_body = email_service.render_order_shipped_email(
            user_name, order_id, items_summary, total, tracking_note
        )
        success = email_service.send_email_sync(
            to_email=user_email,
            subject=f"Your Order Has Shipped — #{order_id[:8].upper()}",
            html_body=html_body, text_body=text_body,
        )
        if success:
            logger.info(f"Order shipped email sent to {user_email}")
            return {"success": True}
        raise self.retry(countdown=60, max_retries=2)
    except Exception as exc:
        logger.error(f"Error sending order shipped email to {user_email}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=2)


@celery_app.task(bind=True, name='core.tasks.send_order_delivered_email')
def send_order_delivered_email(self, user_email: str, user_name: str,
                                order_id: str, items_summary: str, total: str):
    """Notify the buyer their order has been delivered."""
    try:
        html_body, text_body = email_service.render_order_delivered_email(
            user_name, order_id, items_summary, total
        )
        success = email_service.send_email_sync(
            to_email=user_email,
            subject=f"Order Delivered — #{order_id[:8].upper()}",
            html_body=html_body, text_body=text_body,
        )
        if success:
            logger.info(f"Order delivered email sent to {user_email}")
            return {"success": True}
        raise self.retry(countdown=60, max_retries=2)
    except Exception as exc:
        logger.error(f"Error sending order delivered email to {user_email}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=2)


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
            # Get user's email address
            from core.model import User
            user = db.query(User).filter(User.id == user_id).first()
            user_email = user.email if user else None
            
            # Ensure email is always included if channels are provided
            final_channels = channels or ["in_app", "email"]
            if channels and "email" not in channels:
                final_channels.append("email")

            # Prepare notification payload
            notification_payload = {
                "user_id": user_id,
                "type": notification_type,
                "title": title,
                "message": message,
                "priority": priority,
                "channels": final_channels,
                "data": data,
                "to_email": user_email  # Include user's email for email sending
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


@celery_app.task(name='core.tasks.check_missed_inspections')
def check_missed_inspections():
    """
    Periodic task to check for inspections that were missed (24 hours after scheduled date).
    Marks them as rejected and notifies both parties.
    """
    try:
        db = next(get_db())
        try:
            # Find inspections that are "scheduled" or "confirmed" and have passed the configured expiry window
            expiry_hours = system_settings_service.get_missed_inspection_expiry_hours(db)
            expiry_threshold = datetime.utcnow() - timedelta(hours=expiry_hours)
            expired_inspections = db.query(GeneralInspection).filter(
                GeneralInspection.status.in_(["scheduled", "confirmed"]),
                GeneralInspection.inspection_date < expiry_threshold
            ).all()

            for inspection in expired_inspections:
                inspection.status = "rejected"
                inspection.notes = (inspection.notes or "") + "\nSystem: Automatically expired due to missed date."

                # Notify Buyer
                create_notification(db, {
                    "user_id": str(inspection.user_id),
                    "type": "order_processing", # Fallback type
                    "title": "Inspection Missed",
                    "message": f"Your scheduled inspection has expired and was rejected.",
                    "channels": ["in_app", "email"]
                })
                # Notify Seller
                create_notification(db, {
                    "user_id": str(inspection.seller_id),
                    "type": "order_processing",
                    "title": "Inspection Missed",
                    "message": f"A scheduled inspection was missed and has automatically expired.",
                    "channels": ["in_app", "email"]
                })

            if expired_inspections:
                db.commit()
                logger.info(f"Cleaned up {len(expired_inspections)} expired inspections using {expiry_hours} hour expiry.")
            
            return {"success": True, "expired_count": len(expired_inspections)}
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error checking missed inspections: {e}")
        return {"success": False, "error": str(e)}


@celery_app.task(name='core.tasks.send_installment_reminders')
def send_installment_reminders():
    """
    Periodic task to remind buyers of upcoming installment due dates.
    Sends reminders at exactly 7, 5, and 3 days before next_due_date.
    Exact-day matching ensures no duplicate sends across daily runs.
    """
    try:
        db = next(get_db())
        try:
            today = datetime.utcnow().date()

            # Define the three reminder windows with labels
            reminder_windows = [
                (7, "1 week"),
                (5, "5 days"),
                (3, "3 days"),
            ]

            total_reminded = 0

            for days_ahead, label in reminder_windows:
                target_date = today + timedelta(days=days_ahead)

                due_agreements = db.query(GeneralAgreement).filter(
                    GeneralAgreement.status == "active",
                    GeneralAgreement.next_due_date != None,
                    GeneralAgreement.next_due_date >= target_date,
                    GeneralAgreement.next_due_date < target_date + timedelta(days=1),
                ).all()

                for agreement in due_agreements:
                    create_notification(db, {
                        "user_id": str(agreement.user_id),
                        "type": "payment_reminder",
                        "title": "Upcoming Installment Reminder",
                        "message": (
                            f"Your next installment payment is due in {label} "
                            f"(on {agreement.next_due_date.strftime('%Y-%m-%d')}). "
                            f"Please ensure your account is funded to avoid a default."
                        ),
                        "channels": ["in_app", "email"]
                    })
                    total_reminded += 1

            if total_reminded > 0:
                db.commit()

            return {"success": True, "reminded_count": total_reminded}
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error sending installment reminders: {e}")
        return {"success": False, "error": str(e)}


@celery_app.task(name='core.tasks.process_installment_defaults')
def process_installment_defaults():
    """
    Periodic task to mark agreements as defaulted where the next due date 
    plus the seller's configured grace period has elapsed without payment.
    """
    try:
        db = next(get_db())
        try:
            now = datetime.utcnow()
            
            agreements = db.query(GeneralAgreement).join(SellerProfile).filter(
                GeneralAgreement.status == "active",
                GeneralAgreement.next_due_date < now
            ).all()

            default_count = 0
            for agreement in agreements:
                grace_period = agreement.seller.default_grace_period_days or 3
                if now > agreement.next_due_date + timedelta(days=grace_period):
                    agreement.status = "defaulted"
                    default_count += 1

                    # Notify Buyer
                    create_notification(db, {
                        "user_id": str(agreement.user_id),
                        "type": "installment_defaulted",
                        "title": "Agreement Defaulted",
                        "message": f"Your agreement has been defaulted due to missed payments.",
                        "channels": ["in_app", "email"]
                    })
                    # Notify Seller
                    create_notification(db, {
                        "user_id": str(agreement.seller_id),
                        "type": "installment_defaulted",
                        "title": "Agreement Defaulted",
                        "message": f"An agreement has been defaulted due to buyer missing payments past your grace period.",
                        "channels": ["in_app", "email"]
                    })

                    # Free up the unit/asset
                    if agreement.unit_id:
                        if agreement.asset_type == "automotive":
                            unit = db.query(CarUnit).filter(CarUnit.id == agreement.unit_id).first()
                            if unit: unit.status = "available"
                        elif agreement.asset_type == "property":
                            unit = db.query(PropertyUnit).filter(PropertyUnit.id == agreement.unit_id).first()
                            if unit: unit.status = "available"
            if default_count > 0:
                db.commit()
                logger.info(f"Defaulted {default_count} active agreements due to missed payments.")
                
            return {"success": True, "default_count": default_count}
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error processing installment defaults: {e}")
        return {"success": False, "error": str(e)}


@celery_app.task(name='core.tasks.send_weekly_admin_report')
def send_weekly_admin_report():
    """Send a weekly summary notification to admins when enabled in system settings."""
    try:
        db = next(get_db())
        try:
            if not system_settings_service.should_notify_admins(db, "weekly_report"):
                return {"success": True, "skipped": True}

            total_users = db.query(User).count()
            total_orders = db.query(Order).count()
            open_disputes = db.query(Dispute).filter(Dispute.status.in_(["open", "under_review"])).count()
            pending_sellers = db.query(SellerProfile).filter(SellerProfile.kyc_status == "pending").count()

            system_settings_service.notify_admins(
                db=db,
                event_key="weekly_report",
                title="Weekly Admin Report",
                message=(
                    f"Weekly summary: {total_users} users, {total_orders} orders, "
                    f"{pending_sellers} pending seller reviews, {open_disputes} open disputes."
                ),
                data={
                    "total_users": total_users,
                    "total_orders": total_orders,
                    "pending_seller_reviews": pending_sellers,
                    "open_disputes": open_disputes,
                    "generated_at": datetime.utcnow().isoformat(),
                },
                priority="medium",
            )
            db.commit()
            return {"success": True, "sent": True}
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error sending weekly admin report: {e}")
        return {"success": False, "error": str(e)}
