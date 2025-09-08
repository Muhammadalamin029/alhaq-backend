from fastapi.responses import JSONResponse
from fastapi.requests import Request
from fastapi import status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


def create_response(success: bool, message: str, data=None, code=status.HTTP_200_OK):
    return JSONResponse(
        status_code=code,
        content={
            "success": success,
            "message": message,
            "data": data if data is not None else []
        }
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return create_response(
        success=False,
        message=exc.detail if isinstance(
            exc.detail, str) else "Error occurred",
        data=None,
        code=exc.status_code,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return create_response(
        success=False,
        message="Validation error",
        data=exc.errors(),
        code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


async def general_exception_handler(request: Request, exc: Exception):
    return create_response(
        success=False,
        message="Internal server error",
        data=None,
        code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
