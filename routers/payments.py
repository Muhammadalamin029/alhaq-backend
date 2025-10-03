from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import Optional
import hashlib
import hmac
import json

from core.auth import role_required, get_current_user
from db.session import get_db
from core.paystack_service import paystack_service
from core.model import Payment, Order, OrderItem, Product, User
from schemas.payment import (
    PaymentInitializeRequest,
    PaymentInitializeResponse,
    PaymentVerifyRequest,
    PaymentVerifyResponse,
    PaymentWebhookData,
    TransferRecipientRequest,
    TransferRecipientResponse,
    TransferRequest,
    TransferResponse,
    BankResponse,
    PaymentResponse,
    PaymentListResponse
)
from core.logging_config import get_logger, log_error
from core.notifications_service import create_notification

# Get logger for payment routes
payment_logger = get_logger("routers.payments")

router = APIRouter()

@router.post("/initialize", response_model=PaymentInitializeResponse)
async def initialize_payment(
    request: PaymentInitializeRequest,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    """Initialize a Paystack payment"""
    try:
        # Get the order
        order = db.query(Order).filter(
            Order.id == request.order_id,
            Order.buyer_id == user["id"]
        ).first()
        
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
        
        if order.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order is not in pending status"
            )
        
        # Generate unique reference
        import uuid
        reference = f"ALHAQ_{uuid.uuid4().hex[:10].upper()}"
        
        # Initialize Paystack transaction
        try:
            paystack_response = paystack_service.initialize_transaction(
                email=request.email,
                amount=request.amount,
                reference=reference,
                metadata={
                    "order_id": str(order.id),
                    "user_id": user["id"],
                    "user_email": request.email
                }
            )
            
            if not paystack_response.get("status"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to initialize payment"
                )
        except Exception as e:
            payment_logger.error(f"Paystack initialization error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Payment service error: {str(e)}"
            )
        
        # Store payment record
        # Try to get seller_id from the first order item
        # In a multi-vendor system, you might need to create separate payments for each seller
        seller_id = None
        if order.order_items:
            first_item = order.order_items[0]
            if hasattr(first_item, 'product') and first_item.product:
                seller_id = first_item.product.seller_id
        
        # If no seller_id found and the column is NOT NULL, we need to handle this
        # For now, we'll try to create the payment and handle the error if it fails
        try:
            payment = Payment(
                order_id=order.id,
                buyer_id=user["id"],
                seller_id=seller_id,  # Will be None if no seller found
                amount=request.amount / 100,  # Convert from kobo to NGN
                status="pending",
                payment_method="paystack",
                transaction_id=reference
            )
        except Exception as db_error:
            if "seller_id" in str(db_error) and "null value" in str(db_error):
                # Database still has NOT NULL constraint on seller_id
                payment_logger.error(f"Database constraint error: {db_error}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Payment system configuration error. Please contact support."
                )
            else:
                raise db_error
        db.add(payment)
        db.commit()
        
        payment_logger.info(f"Payment initialized for order {order.id}: {reference}")
        
        return PaymentInitializeResponse(
            success=True,
            message="Payment initialized successfully",
            data=paystack_response["data"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(payment_logger, f"Failed to initialize payment for order {request.order_id}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialize payment"
        )

@router.post("/verify", response_model=PaymentVerifyResponse)
async def verify_payment(
    request: PaymentVerifyRequest,
    user=Depends(role_required(["customer"])),
    db: Session = Depends(get_db)
):
    """Verify a Paystack payment"""
    try:
        # Verify with Paystack
        paystack_response = paystack_service.verify_transaction(request.reference)
        
        if not paystack_response.get("status"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment verification failed"
            )
        
        transaction_data = paystack_response["data"]
        
        # Get payment record
        payment = db.query(Payment).filter(
            Payment.transaction_id == request.reference
        ).first()
        
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment record not found"
            )
        
        # Update payment status
        if transaction_data["status"] == "success":
            payment.status = "completed"
            
            # Update order status
            order = db.query(Order).filter(Order.id == payment.order_id).first()
            if order:
                old_status = order.status
                order.status = "processing"
                
                # Update seller balances for this order
                from core.seller_payout_service import seller_payout_service
                from core.order import order_service
                order_service.update_seller_balances_for_order(db, order.id, "processing", old_status)
                
                # Create notification for successful payment (Customer)
                try:
                    create_notification(db, {
                        "user_id": str(payment.buyer_id),
                        "type": "payment_successful",
                        "title": "Payment Successful",
                        "message": f"Your payment of ₦{payment.amount:,.2f} has been processed successfully. Order #{str(order.id)[:8]} is now being processed.",
                        "priority": "high",
                        "channels": ["in_app", "email"],
                        "to_email": request.email if hasattr(request, 'email') else None,
                        "data": {
                            "order_id": str(order.id),
                            "payment_id": str(payment.id),
                            "amount": float(payment.amount)
                        }
                    })
                except Exception as e:
                    payment_logger.error(f"Failed to create payment success notification: {e}")
                
                # Create notifications for sellers involved in this order
                try:
                    # Get all sellers involved in this order
                    order_items = db.query(OrderItem).join(Product).filter(OrderItem.order_id == order.id).all()
                    sellers_involved = set()
                    for item in order_items:
                        if item.product and item.product.seller_id:
                            sellers_involved.add(str(item.product.seller_id))
                    
                    # Send notification to each seller
                    for seller_id in sellers_involved:
                        # Get seller's items in this order
                        seller_items = [item for item in order_items if item.product and str(item.product.seller_id) == seller_id]
                        seller_total = sum(item.quantity * item.price for item in seller_items)
                        
                        # Create seller-specific message showing their amount only
                        seller_message = f"Payment of ₦{seller_total:,.2f} received for your items in order #{str(order.id)[:8]}. Order is now being processed."
                        if len(sellers_involved) > 1:
                            seller_message += f" (This order involves {len(sellers_involved)} sellers - you received ₦{seller_total:,.2f})"
                        
                        create_notification(db, {
                            "user_id": seller_id,
                            "type": "payment_successful",
                            "title": "New Order Payment Received",
                            "message": seller_message,
                            "priority": "high",
                            "channels": ["in_app", "email"],
                            "data": {
                                "order_id": str(order.id),
                                "payment_id": str(payment.id),
                                "amount": float(seller_total),
                                "total_order_amount": float(payment.amount),
                                "is_seller_notification": True,
                                "sellers_count": len(sellers_involved),
                                "is_multi_seller": len(sellers_involved) > 1
                            }
                        })
                        
                    payment_logger.info(f"Sent payment notifications to {len(sellers_involved)} sellers for order {order.id}")
                    
                except Exception as e:
                    payment_logger.error(f"Failed to create seller payment notifications: {e}")
            
            payment_logger.info(f"Payment verified successfully: {request.reference}")
        else:
            payment.status = "failed"
            
            # Create notification for failed payment
            try:
                create_notification(db, {
                    "user_id": str(payment.buyer_id),
                    "type": "payment_failed",
                    "title": "Payment Failed",
                    "message": f"Your payment of ₦{payment.amount:,.2f} could not be processed. Please try again or contact support.",
                    "priority": "high",
                    "channels": ["in_app", "email"],
                    "to_email": request.email if hasattr(request, 'email') else None,
                    "data": {
                        "order_id": str(payment.order_id),
                        "payment_id": str(payment.id),
                        "amount": float(payment.amount)
                    }
                })
            except Exception as e:
                payment_logger.error(f"Failed to create payment failure notification: {e}")
            
            payment_logger.warning(f"Payment verification failed: {request.reference}")
        
        db.commit()
        
        return PaymentVerifyResponse(
            success=True,
            message="Payment verified successfully",
            data=transaction_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(payment_logger, f"Failed to verify payment {request.reference}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify payment"
        )

@router.post("/webhook")
async def paystack_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Paystack webhook events"""
    try:
        # Get the raw body
        body = await request.body()
        
        # Verify webhook signature
        signature = request.headers.get("x-paystack-signature")
        if not signature:
            payment_logger.warning("Webhook request missing signature")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing signature"
            )
        
        # Verify signature
        if not paystack_service.verify_webhook_signature(body, signature):
            payment_logger.warning("Webhook signature verification failed")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid signature"
            )
        
        webhook_data = json.loads(body)
        event = webhook_data.get("event")
        data = webhook_data.get("data", {})
        
        payment_logger.info(f"Processing webhook event: {event}")
        
        # Handle different webhook events
        reference = data.get("reference")
        if not reference:
            payment_logger.warning(f"No reference found in webhook event: {event}")
            return {"status": "ignored", "reason": "no_reference"}
        
        # Find payment record
        payment = db.query(Payment).filter(
            Payment.transaction_id == reference
        ).first()
        
        if not payment:
            payment_logger.warning(f"Payment not found for reference: {reference}")
            return {"status": "ignored", "reason": "payment_not_found"}
        
        # Check if already processed (idempotency)
        if payment.status in ["completed", "failed"]:
            payment_logger.info(f"Payment {reference} already processed with status: {payment.status}")
            return {"status": "ignored", "reason": "already_processed"}
        
        if event == "charge.success":
            # Handle successful payment
            payment.status = "completed"
            
            # Update order status
            order = db.query(Order).filter(Order.id == payment.order_id).first()
            if order:
                old_status = order.status
                order.status = "processing"
                
                # Update seller balances for this order
                from core.seller_payout_service import seller_payout_service
                from core.order import order_service
                order_service.update_seller_balances_for_order(db, order.id, "processing", old_status)
                
                # Create notification for successful payment (Customer)
                try:
                    create_notification(db, {
                        "user_id": str(payment.buyer_id),
                        "type": "payment_successful",
                        "title": "Payment Successful",
                        "message": f"Your payment of ₦{payment.amount:,.2f} has been processed successfully. Order #{str(order.id)[:8]} is now being processed.",
                        "priority": "high",
                        "channels": ["in_app", "email"],
                        "data": {
                            "order_id": str(order.id),
                            "payment_id": str(payment.id),
                            "amount": float(payment.amount)
                        }
                    })
                except Exception as e:
                    payment_logger.error(f"Failed to create webhook payment success notification: {e}")
                
                # Create notifications for sellers involved in this order
                try:
                    # Get all sellers involved in this order
                    order_items = db.query(OrderItem).join(Product).filter(OrderItem.order_id == order.id).all()
                    sellers_involved = set()
                    for item in order_items:
                        if item.product and item.product.seller_id:
                            sellers_involved.add(str(item.product.seller_id))
                    
                    # Send notification to each seller
                    for seller_id in sellers_involved:
                        # Get seller's items in this order
                        seller_items = [item for item in order_items if item.product and str(item.product.seller_id) == seller_id]
                        seller_total = sum(item.quantity * item.price for item in seller_items)
                        
                        # Create seller-specific message showing their amount only
                        seller_message = f"Payment of ₦{seller_total:,.2f} received for your items in order #{str(order.id)[:8]}. Order is now being processed."
                        if len(sellers_involved) > 1:
                            seller_message += f" (This order involves {len(sellers_involved)} sellers - you received ₦{seller_total:,.2f})"
                        
                        create_notification(db, {
                            "user_id": seller_id,
                            "type": "payment_successful",
                            "title": "New Order Payment Received",
                            "message": seller_message,
                            "priority": "high",
                            "channels": ["in_app", "email"],
                            "data": {
                                "order_id": str(order.id),
                                "payment_id": str(payment.id),
                                "amount": float(seller_total),
                                "total_order_amount": float(payment.amount),
                                "is_seller_notification": True,
                                "sellers_count": len(sellers_involved),
                                "is_multi_seller": len(sellers_involved) > 1
                            }
                        })
                        
                    payment_logger.info(f"Webhook: Sent payment notifications to {len(sellers_involved)} sellers for order {order.id}")
                    
                except Exception as e:
                    payment_logger.error(f"Webhook: Failed to create seller payment notifications: {e}")
            
            db.commit()
            payment_logger.info(f"Webhook: Payment completed for {reference}")
            
        elif event == "charge.failed":
            # Handle failed payment
            payment.status = "failed"
            db.commit()
            payment_logger.warning(f"Webhook: Payment failed for {reference}")
            
        elif event == "charge.dispute.create":
            # Handle dispute creation
            payment.status = "disputed"
            db.commit()
            payment_logger.warning(f"Webhook: Payment disputed for {reference}")
            
        elif event == "transfer.success":
            # Handle successful transfer (seller payout)
            from core.seller_payout_service import seller_payout_service
            seller_payout_service.handle_payout_webhook(db, data)
            payment_logger.info(f"Webhook: Transfer successful for {reference}")
            
        elif event == "transfer.failed":
            # Handle failed transfer (seller payout)
            from core.seller_payout_service import seller_payout_service
            seller_payout_service.handle_payout_webhook(db, data)
            payment_logger.warning(f"Webhook: Transfer failed for {reference}")
            
        else:
            # Log unhandled events
            payment_logger.info(f"Unhandled webhook event: {event} for reference: {reference}")
        
        return {"status": "success"}
        
    except Exception as e:
        log_error(payment_logger, "Webhook processing failed", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed"
        )

@router.post("/webhook/test")
async def test_webhook(request: Request, db: Session = Depends(get_db)):
    """Test webhook endpoint for development"""
    try:
        body = await request.body()
        webhook_data = json.loads(body)
        
        payment_logger.info(f"Test webhook received: {webhook_data}")
        
        return {
            "status": "success",
            "message": "Test webhook processed",
            "received_data": webhook_data
        }
        
    except Exception as e:
        log_error(payment_logger, "Test webhook failed", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Test webhook failed"
        )

@router.get("/banks", response_model=BankResponse)
async def get_banks():
    """Get list of supported banks"""
    try:
        banks_data = paystack_service.get_banks()
        
        return BankResponse(
            success=True,
            message="Banks retrieved successfully",
            data=banks_data.get("data", [])
        )
        
    except Exception as e:
        log_error(payment_logger, "Failed to get banks", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get banks"
        )

@router.post("/transfer-recipient", response_model=TransferRecipientResponse)
async def create_transfer_recipient(
    request: TransferRecipientRequest,
    user=Depends(role_required(["seller", "admin"])),
    db: Session = Depends(get_db)
):
    """Create a transfer recipient for seller payouts"""
    try:
        recipient_data = paystack_service.create_transfer_recipient(
            name=request.name,
            account_number=request.account_number,
            bank_code=request.bank_code,
            email=request.email
        )
        
        return TransferRecipientResponse(
            success=True,
            message="Transfer recipient created successfully",
            data=recipient_data["data"]
        )
        
    except Exception as e:
        log_error(payment_logger, f"Failed to create transfer recipient for {request.email}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create transfer recipient"
        )

@router.post("/transfer", response_model=TransferResponse)
async def initiate_transfer(
    request: TransferRequest,
    user=Depends(role_required(["admin"])),
    db: Session = Depends(get_db)
):
    """Initiate a transfer to a seller"""
    try:
        transfer_data = paystack_service.initiate_transfer(
            amount=request.amount,
            recipient_code=request.recipient_code,
            reference=request.reference,
            reason=request.reason
        )
        
        return TransferResponse(
            success=True,
            message="Transfer initiated successfully",
            data=transfer_data["data"]
        )
        
    except Exception as e:
        log_error(payment_logger, f"Failed to initiate transfer {request.reference}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate transfer"
        )

@router.get("/", response_model=PaymentListResponse)
async def list_payments(
    user=Depends(role_required(["customer", "seller", "admin"])),
    db: Session = Depends(get_db),
    page: int = 1,
    limit: int = 20
):
    """List payments for the current user"""
    try:
        query = db.query(Payment)
        
        if user["role"] == "customer":
            query = query.filter(Payment.buyer_id == user["id"])
        elif user["role"] == "seller":
            query = query.filter(Payment.seller_id == user["id"])
        # Admin can see all payments
        
        total = query.count()
        payments = query.offset((page - 1) * limit).limit(limit).all()
        
        return PaymentListResponse(
            success=True,
            message="Payments retrieved successfully",
            data=[PaymentResponse.model_validate(p) for p in payments],
            pagination={
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit
            }
        )
        
    except Exception as e:
        log_error(payment_logger, f"Failed to list payments for user {user['id']}", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve payments"
        )
