from fastapi import FastAPI
from routers import auth, products, categories, order
from core.config import settings
from db.session import engine
from core.model import Base
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from core.handlers import (
    http_exception_handler,
    validation_exception_handler,
    general_exception_handler,
)


app = FastAPI(title=settings.PROJECT_NAME)

Base.metadata.create_all(bind=engine)

# Routers
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(products.router, prefix="/products", tags=["Products"])
app.include_router(categories.router, prefix="/categories",
                   tags=["Categories"])
app.include_router(order.router, prefix="/orders", tags=["Orders"])

# Register global exception handlers
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)


@app.get("/")
def health_check():
    return {"status": "ok"}
