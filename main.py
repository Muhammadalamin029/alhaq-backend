from fastapi import FastAPI
from routers import auth, products
from core.config import settings
from db.session import engine
from core.model import Base

app = FastAPI(title=settings.PROJECT_NAME)

Base.metadata.create_all(bind=engine)

# Routers
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(products.router, prefix="/products", tags=["Products"])


@app.get("/")
def health_check():
    return {"status": "ok"}
