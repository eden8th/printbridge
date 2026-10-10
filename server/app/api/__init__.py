from fastapi import APIRouter

from app.api import routes_jobs, routes_market, routes_printers
from app.api.ws import router as ws_router

api_router = APIRouter()
api_router.include_router(routes_market.router)
api_router.include_router(routes_printers.router)
api_router.include_router(routes_jobs.router)
api_router.include_router(ws_router)