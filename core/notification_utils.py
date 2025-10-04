"""
Notification utilities for sending various types of notifications via Celery
"""

import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


def send_notification_async(
    user_id: str,
    notification_type: str,
    title: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    priority: str = "medium",
    channels: Optional[List[str]] = None
) -> Optional[str]:
    """
    Send a notification asynchronously using Celery
    
    Args:
        user_id: User ID to send notification to
        notification_type: Type of notification (order_processing, payment_successful, etc.)
        title: Notification title
        message: Notification message
        data: Additional notification data
        priority: Notification priority (low, medium, high)
        channels: Notification channels (in_app, email, sms, push)
    
    Returns:
        str: Task ID if successful, None if failed
    """
    try:
        from core.tasks import send_notification
        
        # Queue the notification task
        task = send_notification.delay(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            data=data,
            priority=priority,
            channels=channels or ["in_app", "email"]
        )
        
        logger.info(f"Queued notification task {task.id} for user {user_id}, type {notification_type}")
        return task.id
    except Exception as e:
        logger.error(f"Failed to queue notification task for user {user_id}, type {notification_type}: {e}")
        return None


def send_order_notification(
    user_id: str,
    order_id: str,
    status: str,
    message: str,
    is_seller: bool = False,
    order_data: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Send order-related notification
    
    Args:
        user_id: User ID to send notification to
        order_id: Order ID
        status: Order status (processing, shipped, delivered, etc.)
        message: Notification message
        is_seller: Whether this is a seller notification
        order_data: Additional order data
    
    Returns:
        str: Task ID if successful, None if failed
    """
    # Map status to notification type
    status_to_notification = {
        "processing": "order_processing",
        "paid": "payment_successful",
        "shipped": "order_shipped",
        "delivered": "order_delivered",
        "cancelled": "order_cancelled"
    }
    
    notification_type = status_to_notification.get(status, "order_processing")
    title = f"Your Items {status.title()}" if is_seller else f"Order Items {status.title()}"
    
    # Set priority based on status
    priority = "high" if status in ["shipped", "delivered", "cancelled"] else "medium"
    
    return send_notification_async(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        data=order_data,
        priority=priority,
        channels=["in_app", "email"]
    )


def send_payment_notification(
    user_id: str,
    payment_status: str,
    amount: float,
    order_id: Optional[str] = None,
    additional_data: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Send payment-related notification
    
    Args:
        user_id: User ID to send notification to
        payment_status: Payment status (successful, failed, pending)
        amount: Payment amount
        order_id: Related order ID
        additional_data: Additional payment data
    
    Returns:
        str: Task ID if successful, None if failed
    """
    status_messages = {
        "successful": f"Payment of ₦{amount:,.2f} was successful!",
        "failed": f"Payment of ₦{amount:,.2f} failed. Please try again.",
        "pending": f"Payment of ₦{amount:,.2f} is being processed."
    }
    
    message = status_messages.get(payment_status, f"Payment status: {payment_status}")
    
    if order_id:
        message += f" (Order #{order_id[:8]})"
    
    data = {
        "payment_status": payment_status,
        "amount": amount,
        "order_id": order_id,
        **(additional_data or {})
    }
    
    return send_notification_async(
        user_id=user_id,
        notification_type="payment_successful" if payment_status == "successful" else "payment_failed",
        title=f"Payment {payment_status.title()}",
        message=message,
        data=data,
        priority="high" if payment_status == "successful" else "medium",
        channels=["in_app", "email"]
    )


def send_account_notification(
    user_id: str,
    notification_type: str,
    title: str,
    message: str,
    additional_data: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Send account-related notification (verification, password reset, etc.)
    
    Args:
        user_id: User ID to send notification to
        notification_type: Type of notification (account_verified, password_changed, etc.)
        title: Notification title
        message: Notification message
        additional_data: Additional data
    
    Returns:
        str: Task ID if successful, None if failed
    """
    return send_notification_async(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        data=additional_data,
        priority="medium",
        channels=["in_app", "email"]
    )


def send_system_notification(
    user_id: str,
    title: str,
    message: str,
    notification_type: str = "system_announcement",
    additional_data: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Send system notification
    
    Args:
        user_id: User ID to send notification to
        title: Notification title
        message: Notification message
        notification_type: Type of system notification
        additional_data: Additional data
    
    Returns:
        str: Task ID if successful, None if failed
    """
    return send_notification_async(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        data=additional_data,
        priority="low",
        channels=["in_app"]
    )
