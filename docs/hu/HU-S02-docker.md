# HU-S02 - Contenedor Docker

| Campo | Valor |
| --- | --- |
| Estado | En revision |
| Version | 0.3 |
| Tipo | Setup |
| Dependencias | HU-S01 |

## Historia

**Como** desarrollador y operador
**Quiero** ejecutar la solucion dentro de un contenedor basado en Python 3.15.0 bookworm slim
**Para** tener un entorno identico en desarrollo, pruebas y despliegue

## Contexto

La constitucion exige la imagen Python 3.15.0 bookworm slim y uv como gestor. La fase 1 expone una API HTTP (FastAPI servida por `uvicorn`, ver HU008); el contenedor levanta ese servidor.

## Requisitos funcionales

- **RF-01**: `Dockerfile` basado en `python:3.15.0-slim-bookworm` con la etiqueta fijada (y digest, ver P-01).
- **RF-02**: uv se instala copiando el binario oficial (`COPY --from=ghcr.io/astral-sh/uv:<version> /uv /bin/uv`) con version fijada.
- **RF-03**: Instalacion de dependencias con `uv sync --frozen --no-dev` en la imagen final; las de desarrollo solo en una etapa o target `dev`.
- **RF-04**: Build multi-etapa: etapa `builder` resuelve dependencias, etapa `runtime` contiene solo el entorno virtual y el codigo.
- **RF-05**: El contenedor corre con un usuario no root.
- **RF-06**: El `ENTRYPOINT` levanta el servidor ASGI de la API HTTP (HU008), por ejemplo `uvicorn availability_hotel.main:app --host 0.0.0.0 --port ${PORT:-8000}`; el puerto es configurable por variable de entorno (`PORT`, por defecto `8000`).
- **RF-07**: `.dockerignore` excluye `.git`, `.venv`, caches y archivos de secretos.
- **RF-08**: `docker-compose.yml` con:
  - Servicio `app` (la solucion), que publica el puerto `8000` hacia el host.
  - Servicios `mock-provider-a`, `mock-provider-b`, `mock-provider-c` que simulan el comportamiento descrito en HU005, HU006 y HU007 (latencias, 429, errores en HTTP 200, timeouts).
  - Servicio `localstack` con Secrets Manager, para el cliente local de HU-S03.
- **RF-09**: La imagen y el compose no contienen API keys ni credenciales de proveedores. En local, `APP_ENV=local` y `AWS_ENDPOINT_URL` apuntan al servicio `localstack`; las credenciales de proveedores se crean en ese Secrets Manager. En productivo no se definen endpoint ni claves estaticas (HU-S03 RF-10).
- **RF-10**: La imagen declara `EXPOSE 8000` (o el puerto configurado via `PORT`) y un `HEALTHCHECK` que hace `GET /health` (HU008 RF-06) para reportar el estado del contenedor a Docker/orquestadores.

## Requisitos no funcionales aplicables

- **RNF-01**: La imagen de runtime no incluye compiladores ni herramientas de desarrollo.
- **RNF-02**: Capas ordenadas para aprovechar cache: primero `pyproject.toml` y `uv.lock`, despues el codigo.
- **RNF-03**: Variables `PYTHONDONTWRITEBYTECODE=1` y `PYTHONUNBUFFERED=1` para logs inmediatos (HU-S04).

## Criterios de aceptacion

```gherkin
Escenario: Build reproducible
  Dado el repositorio con uv.lock
  Cuando ejecuto "docker build ."
  Entonces la imagen se construye sin resolver dependencias nuevas

Escenario: Ejecucion sin root
  Dado la imagen construida
  Cuando ejecuto "docker run <imagen> id -u"
  Entonces el resultado es distinto de 0

Escenario: Entorno local con mocks
  Dado docker-compose levantado
  Cuando ejecuto una consulta desde el servicio app
  Entonces se consultan los tres mocks y se obtiene una respuesta estandarizada

Escenario: Secretos fuera de la imagen
  Dado la imagen construida
  Cuando inspecciono sus capas
  Entonces no encuentro API keys ni credenciales

Escenario: API HTTP accesible desde el contenedor
  Dado el contenedor corriendo con el puerto 8000 publicado
  Cuando hago GET a "http://localhost:8000/health"
  Entonces obtengo un 200 y Docker reporta el contenedor como "healthy"
```

## Casos borde y manejo de errores

- Si falta `APP_ENV` o, en local, `AWS_ENDPOINT_URL`, el contenedor termina con codigo distinto de 0 y mensaje claro (validacion de HU-S03).
- Los mocks deben poder configurarse para forzar escenarios (lento, 429, error de negocio) sin reconstruir la imagen.
- Si `uvicorn` no puede enlazar el puerto configurado (por ejemplo por un conflicto de puertos en el host), el contenedor termina con codigo distinto de 0 y mensaje claro.

## Decisiones de complejidad algoritmica (requieren aprobacion manual)

No aplica.

## Preguntas abiertas

- [ ] P-01: Se fija la imagen base por digest SHA256 ademas de la etiqueta?
- [ ] P-02: Tecnologia de los mocks: servidor ligero en Python dentro del repo o herramienta externa (WireMock, Prism)?
- [ ] P-03: Hay registro de contenedores y plataforma de despliegue definidos para esta fase?

## Historial de revision

| Version | Fecha | Cambios | Revisor |
| --- | --- | --- | --- |
| 0.1 | 2026-10-20 | Borrador inicial, entra a loop de revision | - |
| 0.2 | 2026-10-20 | Alineada con HU-S03: LocalStack en compose local; sin secretos de proveedor en imagen ni en variables de entorno | Usuario |
| 0.3 | 2026-10-20 | El ENTRYPOINT pasa de CLI (HU008) a servidor uvicorn/FastAPI; se agrega EXPOSE/HEALTHCHECK y publicacion de puerto en compose | Usuario |
