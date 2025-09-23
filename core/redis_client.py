import redis
import json
from typing import Optional, Any, Dict
from datetime import timedelta
from core.config import settings


class RedisClient:
    """Redis client wrapper for caching and session management"""
    
    def __init__(self):
        """Initialize Redis connection"""
        self.redis_client = redis.from_url(
            settings.REDIS_URL,
            password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
            decode_responses=True,
            retry_on_timeout=True,
            socket_connect_timeout=5,
            socket_timeout=5
        )
    
    async def ping(self) -> bool:
        """Test Redis connection"""
        try:
            return self.redis_client.ping()
        except Exception:
            return False
    
    def set(self, key: str, value: Any, expire: Optional[int] = None) -> bool:
        """
        Set a key-value pair with optional expiration
        
        Args:
            key: Redis key
            value: Value to store (will be JSON serialized if not string)
            expire: Expiration in seconds
            
        Returns:
            bool: Success status
        """
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            elif not isinstance(value, str):
                value = str(value)
                
            return self.redis_client.set(key, value, ex=expire)
        except Exception:
            return False
    
    def get(self, key: str, as_json: bool = False) -> Optional[Any]:
        """
        Get value by key
        
        Args:
            key: Redis key
            as_json: Whether to parse value as JSON
            
        Returns:
            Value or None if not found
        """
        try:
            value = self.redis_client.get(key)
            if value is None:
                return None
                
            if as_json:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return value
        except Exception:
            return None
    
    def delete(self, key: str) -> bool:
        """Delete a key"""
        try:
            return bool(self.redis_client.delete(key))
        except Exception:
            return False
    
    def exists(self, key: str) -> bool:
        """Check if key exists"""
        try:
            return bool(self.redis_client.exists(key))
        except Exception:
            return False
    
    def expire(self, key: str, seconds: int) -> bool:
        """Set expiration for existing key"""
        try:
            return bool(self.redis_client.expire(key, seconds))
        except Exception:
            return False
    
    def ttl(self, key: str) -> int:
        """Get time to live for key"""
        try:
            return self.redis_client.ttl(key)
        except Exception:
            return -1
    
    def keys(self, pattern: str = "*") -> list:
        """Get keys matching pattern"""
        try:
            return self.redis_client.keys(pattern)
        except Exception:
            return []
    
    def incr(self, key: str, amount: int = 1) -> Optional[int]:
        """Increment value by amount"""
        try:
            return self.redis_client.incr(key, amount)
        except Exception:
            return None
    
    def decr(self, key: str, amount: int = 1) -> Optional[int]:
        """Decrement value by amount"""
        try:
            return self.redis_client.decr(key, amount)
        except Exception:
            return None


class VerificationCodeManager:
    """Manager for email verification codes using Redis"""
    
    def __init__(self, redis_client: RedisClient):
        self.redis = redis_client
        self.EMAIL_VERIFY_PREFIX = "email_verify:"
        self.PASSWORD_RESET_PREFIX = "password_reset:"
        self.EMAIL_RATE_LIMIT_PREFIX = "email_rate:"
    
    def generate_verification_code(self, email: str, code_type: str = "verification") -> str:
        """
        Generate a 6-digit verification code
        
        Args:
            email: User's email address
            code_type: Type of verification ("verification" or "password_reset")
            
        Returns:
            Generated verification code
        """
        import secrets
        import string
        
        # Generate 6-digit numeric code
        code = ''.join(secrets.choice(string.digits) for _ in range(6))
        
        # Store in Redis with appropriate expiration
        prefix = self.EMAIL_VERIFY_PREFIX if code_type == "verification" else self.PASSWORD_RESET_PREFIX
        expire_minutes = (
            settings.EMAIL_VERIFICATION_EXPIRE_MINUTES 
            if code_type == "verification" 
            else settings.PASSWORD_RESET_EXPIRE_MINUTES
        )
        
        key = f"{prefix}{email}"
        self.redis.set(key, code, expire=expire_minutes * 60)
        
        return code
    
    def verify_code(self, email: str, code: str, code_type: str = "verification") -> bool:
        """
        Verify a verification code
        
        Args:
            email: User's email address
            code: Verification code to check
            code_type: Type of verification ("verification" or "password_reset")
            
        Returns:
            bool: True if code is valid
        """
        prefix = self.EMAIL_VERIFY_PREFIX if code_type == "verification" else self.PASSWORD_RESET_PREFIX
        key = f"{prefix}{email}"
        
        stored_code = self.redis.get(key)
        if stored_code and stored_code == code:
            # Delete code after successful verification to prevent reuse
            self.redis.delete(key)
            return True
        
        return False
    
    def is_rate_limited(self, email: str, max_attempts: int = 5, window_minutes: int = 60) -> bool:
        """
        Check if email is rate limited for verification requests
        
        Args:
            email: User's email address
            max_attempts: Maximum attempts allowed
            window_minutes: Rate limit window in minutes
            
        Returns:
            bool: True if rate limited
        """
        key = f"{self.EMAIL_RATE_LIMIT_PREFIX}{email}"
        current_attempts = self.redis.get(key)
        
        if current_attempts is None:
            return False
        
        return int(current_attempts) >= max_attempts
    
    def increment_rate_limit(self, email: str, window_minutes: int = 60) -> int:
        """
        Increment rate limit counter for email
        
        Args:
            email: User's email address
            window_minutes: Rate limit window in minutes
            
        Returns:
            int: Current attempt count
        """
        key = f"{self.EMAIL_RATE_LIMIT_PREFIX}{email}"
        
        if not self.redis.exists(key):
            self.redis.set(key, 1, expire=window_minutes * 60)
            return 1
        else:
            return self.redis.incr(key) or 1
    
    def get_remaining_time(self, email: str, code_type: str = "verification") -> int:
        """
        Get remaining time for verification code in seconds
        
        Args:
            email: User's email address
            code_type: Type of verification
            
        Returns:
            int: Remaining time in seconds, -1 if not found
        """
        prefix = self.EMAIL_VERIFY_PREFIX if code_type == "verification" else self.PASSWORD_RESET_PREFIX
        key = f"{prefix}{email}"
        
        return self.redis.ttl(key)
    
    def delete_verification_code(self, email: str, code_type: str = "verification") -> bool:
        """
        Delete verification code manually
        
        Args:
            email: User's email address
            code_type: Type of verification
            
        Returns:
            bool: Success status
        """
        prefix = self.EMAIL_VERIFY_PREFIX if code_type == "verification" else self.PASSWORD_RESET_PREFIX
        key = f"{prefix}{email}"
        
        return self.redis.delete(key)


# Global Redis client instance
redis_client = RedisClient()
verification_manager = VerificationCodeManager(redis_client)