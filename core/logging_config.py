import logging
import logging.config
import sys
from datetime import datetime
from typing import Dict, Any
import json


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        # Create the log entry dictionary
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception information if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info)
            }
        
        # Add extra fields if any
        if hasattr(record, 'user_id'):
            log_entry["user_id"] = record.user_id
        if hasattr(record, 'request_id'):
            log_entry["request_id"] = record.request_id
        if hasattr(record, 'email'):
            log_entry["email"] = record.email
        if hasattr(record, 'endpoint'):
            log_entry["endpoint"] = record.endpoint
        if hasattr(record, 'method'):
            log_entry["method"] = record.method
        if hasattr(record, 'status_code'):
            log_entry["status_code"] = record.status_code
        if hasattr(record, 'duration'):
            log_entry["duration_ms"] = record.duration
        
        return json.dumps(log_entry)


class ColoredFormatter(logging.Formatter):
    """Colored formatter for console output"""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green  
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m'       # Reset
    }
    
    def format(self, record: logging.LogRecord) -> str:
        # Color the level name
        level_color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        record.levelname = f"{level_color}{record.levelname}{self.COLORS['RESET']}"
        
        # Format the message
        formatted = super().format(record)
        return formatted


def setup_logging(
    log_level: str = "INFO",
    log_to_file: bool = False,
    log_to_console: bool = True,
    json_logs: bool = False
) -> None:
    """
    Setup application logging configuration
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: Whether to log to files (disabled)
        log_to_console: Whether to log to console
        json_logs: Whether to use JSON format (unused when file logging disabled)
    """
    
    # Simplified logging configuration - console only
    config: Dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "colored": {
                "()": ColoredFormatter,
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "colored",
                "level": log_level
            }
        },
        "loggers": {
            # Application loggers
            "": {  # Root logger
                "level": log_level,
                "handlers": ["console"],
                "propagate": False
            },
            "alhaq_backend": {
                "level": log_level,
                "handlers": ["console"],
                "propagate": False
            },
            "core": {
                "level": log_level,
                "handlers": ["console"],
                "propagate": False
            },
            "routers": {
                "level": log_level,
                "handlers": ["console"],
                "propagate": False
            },
            "auth": {
                "level": log_level,
                "handlers": ["console"],
                "propagate": False
            },
            # Third party loggers (reduce noise)
            "uvicorn": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False
            },
            "sqlalchemy.engine": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            "celery": {
                "level": "INFO", 
                "handlers": ["console"],
                "propagate": False
            }
        }
    }
    
    # Apply the configuration
    logging.config.dictConfig(config)
    
    # Log the startup
    logger = logging.getLogger("alhaq_backend")
    logger.info("Logging system initialized (console only)", extra={
        "log_level": log_level,
        "log_to_console": log_to_console
    })


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance"""
    return logging.getLogger(name)


# Utility functions for structured logging
def log_auth_event(logger: logging.Logger, event: str, email: str = None, user_id: str = None, success: bool = True, **kwargs):
    """Log authentication events with structured data"""
    extra = {
        "event": event,
        "success": success,
        **kwargs
    }
    if email:
        extra["email"] = email
    if user_id:
        extra["user_id"] = user_id
    
    level = logging.INFO if success else logging.WARNING
    logger.log(level, f"Auth event: {event}", extra=extra)


def log_api_request(logger: logging.Logger, method: str, endpoint: str, status_code: int, duration_ms: float, user_id: str = None, **kwargs):
    """Log API requests with structured data"""
    extra = {
        "method": method,
        "endpoint": endpoint, 
        "status_code": status_code,
        "duration": duration_ms,
        **kwargs
    }
    if user_id:
        extra["user_id"] = user_id
    
    level = logging.INFO if status_code < 400 else logging.WARNING if status_code < 500 else logging.ERROR
    logger.log(level, f"{method} {endpoint} - {status_code}", extra=extra)


def log_error(logger: logging.Logger, message: str, exception: Exception = None, **kwargs):
    """Log errors with structured data"""
    extra = kwargs
    if exception:
        logger.error(message, exc_info=exception, extra=extra)
    else:
        logger.error(message, extra=extra)