# HU-S01 - Proyecto base con uv y calidad de codigo

| Campo | Valor |
| --- | --- |
| Estado | En revision |
| Version | 0.3 |
| Tipo | Setup |
| Dependencias | - |

## Historia

**Como** desarrollador del equipo
**Quiero** un proyecto Python inicializado con uv, dependencias fijadas y herramientas de calidad automatizadas
**Para** que todo el codigo cumpla PEP8, el formato black por defecto y la arquitectura MVC desde el primer commit

## Contexto

La constitucion fija Python 3.15.0, el gestor uv, niquests 3.21.2 como cliente saliente hacia proveedores y FastAPI como punto de entrada HTTP de la Fase 1 (HU008), ademas de los no negociables DRY, PEP8 y black. Esta HU deja la base sobre la que se construyen el resto de historias.

## Requisitos funcionales

- **RF-01**: El proyecto se inicializa con `uv init` y se gestiona exclusivamente con uv (`uv add`, `uv sync`, `uv run`). No se usan `pip` ni `requirements.txt` como fuente de verdad.
- **RF-02**: `pyproject.toml` declara `requires-python = "==3.15.*"` y las dependencias fijadas en version exacta:

| Paquete | Version | Rol |
| --- | --- | --- |
| `niquests` | `3.21.2` | Cliente HTTP saliente hacia los proveedores |
| `fastapi` | `0.153.0` | Framework de la API HTTP de entrada (HU008) |
| `uvicorn[standard]` | `0.54.0` | Servidor ASGI que ejecuta la aplicacion FastAPI |
| `pydantic` | `2.14.1` | Modelos de request/response y validacion (HU001, HU008); piso minimo real para Python 3.15 |

No se agrega `python-multipart` salvo que una HU futura requiera formularios o carga de archivos (la API es JSON-only en fase 1), para no sumar una dependencia con historial de CVEs sin necesidad real.
- **RF-03**: Se versiona `uv.lock` y existe un archivo `.python-version` con `3.15.0`.
- **RF-04**: Dependencias de desarrollo en un grupo separado (`[dependency-groups] dev`): `black`, `ruff` (linter PEP8 con reglas `E`, `W`, `F`), `pytest`, `pytest-asyncio`, `pytest-cov` y `pre-commit`.
- **RF-05**: Estructura de paquetes MVC:

```text
src/availability_hotel/
    models/        # Modelos de dominio: consulta, tarifa, estado de proveedor (HU001)
    views/         # Serializacion de la respuesta estandarizada (HU001, HU008)
    controllers/   # Servicio de consulta y orquestador (HU003, HU008)
    providers/     # Adaptadores por proveedor y contrato comun (HU002, HU005-HU007)
    config/        # Carga y validacion de configuracion (HU-S03)
    core/          # Utilidades transversales: logging, rate limit (HU-S04, HU004)
tests/
    unit/
    integration/
```

- **RF-06**: Comandos estandar documentados en `README.md`:
  - `uv run black --check .`
  - `uv run ruff check .`
  - `uv run pytest --cov --cov-fail-under=90`
- **RF-07**: Hook de `pre-commit` que ejecuta black y ruff; un commit que no cumpla es rechazado. En fase 1 no hay pipeline de CI: pre-commit es el unico control automatico.
- **RF-08**: Cobertura minima de pruebas del 90 %; `pytest` falla por debajo de ese umbral.
- **RF-09**: Criterio de bloqueo: antes de cerrar la HU se valida que niquests 3.21.2 instala y funciona (incluido `AsyncSession`) sobre Python 3.15.0. Si falla, se detiene el avance y se escala la decision de version.
- **RF-10**: Criterio de bloqueo: antes de cerrar la HU se valida que `fastapi==0.153.0`, `uvicorn[standard]==0.54.0` y `pydantic==2.14.1` instalan con `uv sync` sobre Python 3.15.0 y que un servidor `uvicorn` minimo con un endpoint FastAPI arranca y responde correctamente. Al momento de esta revision ninguno de los tres paquetes trae certificacion oficial completa de Python 3.15 en su ultimo release publicado (pydantic 2.14.0 si la declara desde el 2026-10-08; fastapi y uvicorn instalan por no tener techo de version pero aun no publican el release con el clasificador 3.15). Si la validacion falla, se detiene el avance y se escala la decision de version (por ejemplo esperar el proximo release de `uvicorn` que incluya el soporte ya fusionado en su rama principal).
- **RF-11**: Se valida ademas que `starlette` (dependencia transitiva de FastAPI) resuelva en `uv.lock` a una version `>=1.7.0`, que es la primera con soporte declarado de Python 3.15 y que ya incluye la correccion de las vulnerabilidades conocidas de validacion del header `Host` y de despacho de metodo en `HTTPEndpoint`.

## Requisitos no funcionales aplicables

- **RNF-01**: Configuracion de black sin overrides (longitud de linea 88 por defecto).
- **RNF-02**: ruff se configura compatible con black (`line-length = 88`, ignorar `E203`) para evitar conflictos entre herramientas.
- **RNF-03**: Las capas MVC no se saltan: `views` no llama proveedores y `providers` no serializan la respuesta final.

## Criterios de aceptacion

```gherkin
Escenario: Instalacion reproducible
  Dado un clon limpio del repositorio
  Cuando ejecuto "uv sync"
  Entonces se instala Python 3.15.0 y niquests 3.21.2 exactamente como en uv.lock

Escenario: Formato obligatorio
  Dado un archivo Python sin formatear con black
  Cuando intento hacer commit
  Entonces el hook de pre-commit falla e indica el archivo

Escenario: Cumplimiento PEP8
  Dado el codigo del repositorio
  Cuando ejecuto "uv run ruff check ."
  Entonces no reporta errores

Escenario: Cobertura minima
  Dado una cobertura de pruebas inferior al 90 %
  Cuando ejecuto "uv run pytest --cov --cov-fail-under=90"
  Entonces la ejecucion falla

Escenario: Compatibilidad de niquests con Python 3.15
  Dado el entorno creado con "uv sync"
  Cuando ejecuto una prueba que abre una niquests.AsyncSession
  Entonces la prueba pasa sobre Python 3.15.0

Escenario: Compatibilidad de FastAPI y uvicorn con Python 3.15
  Dado el entorno creado con "uv sync" con fastapi==0.153.0, uvicorn[standard]==0.54.0 y pydantic==2.14.1
  Cuando levanto un servidor uvicorn con un endpoint FastAPI minimo sobre Python 3.15.0
  Y hago una peticion HTTP a ese endpoint
  Entonces recibo una respuesta valida sin errores de arranque ni de importacion
```

## Casos borde y manejo de errores

- Si niquests 3.21.2 no publica wheel compatible con Python 3.15, `uv sync` falla; se aplica el criterio de bloqueo de RF-09.
- Si `uvicorn` 0.54.0 no arranca sobre Python 3.15.0 (por ejemplo por una dependencia C de `uvicorn[standard]` como `httptools` o `uvloop` sin wheel 3.15), se aplica el criterio de bloqueo de RF-10: se evalua esperar el siguiente release de `uvicorn`, usar `uvicorn` sin el extra `standard` (implementacion pura Python) como mitigacion temporal, o escalar la decision de version.
- Si un desarrollador usa otra version de Python localmente, uv debe forzar la version declarada.

## Decisiones de complejidad algoritmica (requieren aprobacion manual)

No aplica.

## Preguntas abiertas

- [x] P-01: Linter PEP8. **Resuelta**: ruff con reglas `E`, `W`, `F`.
- [x] P-02: Compatibilidad de niquests 3.21.2 con Python 3.15.0. **Resuelta**: se convierte en criterio de bloqueo (RF-09).
- [x] P-03: Pipeline de CI. **Resuelta**: solo pre-commit en fase 1.
- [x] P-04: Cobertura minima. **Resuelta**: 90 % (RF-08).
- [ ] P-05: Compatibilidad de FastAPI 0.153.0, uvicorn 0.54.0 y pydantic 2.14.1 con Python 3.15.0. Se convierte en criterio de bloqueo (RF-10, RF-11); pendiente de ejecutar la validacion real antes de volver a aprobar la HU.

## Historial de revision

| Version | Fecha | Cambios | Revisor |
| --- | --- | --- | --- |
| 0.1 | 2026-10-20 | Borrador inicial, entra a loop de revision | - |
| 0.2 | 2026-10-20 | Iteracion 1: ruff como linter, sin CI (solo pre-commit), cobertura 90 %, compatibilidad niquests/Python 3.15 como criterio de bloqueo. HU aprobada | Usuario |
| 0.3 | 2026-10-20 | Se agregan fastapi==0.153.0, uvicorn[standard]==0.54.0 y pydantic==2.14.1 como dependencias fijadas (punto de entrada HTTP de HU008); se agrega criterio de bloqueo de compatibilidad con Python 3.15 para este stack y validacion del piso de starlette >=1.7.0. La HU vuelve a "En revision" hasta validar RF-10/RF-11 | Usuario |
