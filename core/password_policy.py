import re
from typing import List, Optional
from fastapi import HTTPException, status


class PasswordPolicy:
    """Password policy validation utility"""
    
    MIN_LENGTH = 8
    MAX_LENGTH = 128
    
    @classmethod
    def validate_password(cls, password: str) -> bool:
        """
        Validate password against security policy
        
        Returns True if password meets all requirements
        Raises HTTPException with details if password is invalid
        """
        errors = cls.get_password_errors(password)
        
        if errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Password does not meet security requirements",
                    "requirements": errors
                }
            )
        
        return True
    
    @classmethod
    def get_password_errors(cls, password: str) -> List[str]:
        """
        Get list of password policy violations
        
        Returns empty list if password is valid
        """
        errors = []
        
        # Length check
        if len(password) < cls.MIN_LENGTH:
            errors.append(f"Password must be at least {cls.MIN_LENGTH} characters long")
        
        if len(password) > cls.MAX_LENGTH:
            errors.append(f"Password must be no more than {cls.MAX_LENGTH} characters long")
        
        # Character type checks
        if not re.search(r"[A-Z]", password):
            errors.append("Password must contain at least one uppercase letter")
        
        if not re.search(r"[a-z]", password):
            errors.append("Password must contain at least one lowercase letter")
        
        if not re.search(r"\d", password):
            errors.append("Password must contain at least one number")
        
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            errors.append("Password must contain at least one special character (!@#$%^&*(),.?\":{}|<>)")
        
        # Check for common weak passwords
        weak_passwords = [
            "password", "123456", "qwerty", "abc123", "admin", "letmein",
            "welcome", "monkey", "1234567890", "password123", "admin123"
        ]
        
        if password.lower() in weak_passwords:
            errors.append("Password is too common and easily guessed")
        
        return errors
    
    @classmethod
    def get_password_strength(cls, password: str) -> dict:
        """
        Get password strength assessment
        
        Returns dictionary with strength score and feedback
        """
        score = 0
        feedback = []
        
        # Length scoring
        if len(password) >= 8:
            score += 1
        if len(password) >= 12:
            score += 1
        if len(password) >= 16:
            score += 1
        
        # Character variety scoring
        if re.search(r"[a-z]", password):
            score += 1
        if re.search(r"[A-Z]", password):
            score += 1
        if re.search(r"\d", password):
            score += 1
        if re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            score += 1
        
        # Bonus for high character variety
        unique_chars = len(set(password))
        if unique_chars >= len(password) * 0.7:
            score += 1
        
        # Determine strength level
        if score <= 2:
            strength = "Weak"
            feedback.append("Consider using a longer password with mixed characters")
        elif score <= 4:
            strength = "Fair"
            feedback.append("Good start! Consider adding more character types")
        elif score <= 6:
            strength = "Good"
            feedback.append("Strong password! Well done")
        else:
            strength = "Excellent"
            feedback.append("Excellent password strength!")
        
        return {
            "score": score,
            "max_score": 8,
            "strength": strength,
            "feedback": feedback
        }


def validate_password_change(current_password: str, new_password: str, user_email: str) -> bool:
    """
    Additional validation for password changes
    
    Args:
        current_password: Current password (for verification)
        new_password: New password to validate
        user_email: User's email (to prevent email in password)
    
    Returns True if valid, raises HTTPException if invalid
    """
    # Basic policy validation
    PasswordPolicy.validate_password(new_password)
    
    # Additional change-specific validations
    errors = []
    
    # Don't allow same password
    if current_password == new_password:
        errors.append("New password must be different from current password")
    
    # Don't allow email in password
    email_local = user_email.split('@')[0].lower()
    if email_local in new_password.lower():
        errors.append("Password should not contain your email address")
    
    # Don't allow simple variations of current password
    if len(current_password) > 3 and current_password.lower() in new_password.lower():
        errors.append("New password should not be a simple variation of your current password")
    
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Password change validation failed",
                "requirements": errors
            }
        )
    
    return True


# Password policy constants for frontend
PASSWORD_REQUIREMENTS = {
    "min_length": PasswordPolicy.MIN_LENGTH,
    "max_length": PasswordPolicy.MAX_LENGTH,
    "requires_uppercase": True,
    "requires_lowercase": True,
    "requires_number": True,
    "requires_special_char": True,
    "special_chars": "!@#$%^&*(),.?\":{}|<>",
    "description": f"Password must be {PasswordPolicy.MIN_LENGTH}-{PasswordPolicy.MAX_LENGTH} characters with uppercase, lowercase, number, and special character"
}
