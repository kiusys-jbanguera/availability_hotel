"""Capa HTTP delgada: parsea, llama al servicio y devuelve la vista (HU008)."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from availability_hotel.controllers.runtime import Runtime
from availability_hotel.controllers.search_service import SearchService
from availability_hotel.models import SearchQuery
from availability_hotel.views import SearchResponse

# Red de seguridad sobre el corte interno de 2 s del orquestador (RNF-02).
REQUEST_TIMEOUT_S = 2.5

router = APIRouter()


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def get_service(runtime: Runtime = Depends(get_runtime)) -> SearchService:
    if runtime.service is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="configuracion de proveedores invalida; servicio no listo",
        )
    return runtime.service


@router.post("/v1/availability", response_model=SearchResponse)
async def availability(
    query: SearchQuery, service: SearchService = Depends(get_service)
) -> SearchResponse:
    try:
        return await asyncio.wait_for(
            service.search(
                destino=query.destino,
                check_in=query.check_in,
                check_out=query.check_out,
                huespedes=query.huespedes,
            ),
            timeout=REQUEST_TIMEOUT_S,
        )
    except TimeoutError:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT, detail="la consulta excedio el tiempo"
        ) from None


@router.get("/health")
async def health(runtime: Runtime = Depends(get_runtime)) -> JSONResponse:
    if runtime.ready:
        return JSONResponse({"status": "ok"})
    return JSONResponse(
        {"status": "not_ready", "error": runtime.error},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
