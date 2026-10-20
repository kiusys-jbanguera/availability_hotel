# HU003 - Orquestacion paralela con corte de 2 s

| Campo | Valor |
| --- | --- |
| Estado | En revision |
| Version | 0.2 |
| Tipo | Funcional |
| Dependencias | HU002, HU-S04 |

## Historia

**Como** consumidor del servicio de disponibilidad
**Quiero** que todos los proveedores se consulten en paralelo y recibir respuesta en maximo 2 s con los que alcanzaron a responder
**Para** obtener resultados rapidos aunque haya proveedores lentos o caidos, sin que el tiempo crezca con el numero de proveedores

## Contexto

La constitucion establece que la respuesta se da con todos los proveedores que respondieron en 2 s y que el aumento de proveedores no debe aumentar proporcionalmente el tiempo de ejecucion. El orquestador vive en `controllers/`.

## Requisitos funcionales

- **RF-01**: El orquestador lanza la consulta a todos los proveedores habilitados de forma concurrente usando `niquests.AsyncSession` (DC-01).
- **RF-02**: Presupuesto global de 2 s medido desde el inicio de la orquestacion. Al cumplirse, se cancelan las llamadas pendientes y se arma la respuesta con las completadas.
- **RF-03**: Cada proveedor tiene ademas su propio timeout (`timeout_s`, maximo 2 s, HU-S03); el efectivo es el menor entre su timeout y el tiempo restante del presupuesto global.
- **RF-04**: Los proveedores cancelados por el corte entran en `failed_providers` con `reason = timeout` (HU001).
- **RF-05**: Aislamiento de fallos: el error, timeout o excepcion de un proveedor no afecta a los demas ni a la respuesta (respaldado por RF-07 de HU002).
- **RF-06**: Sin reintentos dentro de la misma consulta por defecto; un reintento solo es valido si cabe en el tiempo restante y esta habilitado por proveedor (ver P-01).
- **RF-07**: Una sola sesion HTTP compartida (pool de conexiones) reutilizada entre consultas, con limites de conexiones configurables.
- **RF-08**: El orquestador recibe la consulta validada (HU001) y devuelve las ofertas y `failed_providers`. No serializa (eso es de `views/`). La latencia se registra en el log (HU-S04) y no forma parte de la respuesta.
- **RF-09**: Al cancelar llamadas pendientes se liberan sus conexiones sin dejar tareas huerfanas ni advertencias de corutinas no esperadas.

## Requisitos no funcionales aplicables

- **RNF-01**: Tiempo total de la consulta <= 2 s + margen de armado de respuesta (propuesta: 2.1 s p99, ver P-02).
- **RNF-02**: Con 3 proveedores y con 1000 proveedores simulados, la latencia total no crece linealmente con el numero de proveedores.
- **RNF-03**: Uso de memoria acotado al consultar 1000+ proveedores (DC-02).

## Criterios de aceptacion

```gherkin
Escenario: Respuesta parcial por proveedor lento
  Dado A responde en 250 ms, B tarda 3 s y C responde en 400 ms
  Cuando ejecuto la consulta
  Entonces la respuesta llega en 2 s o menos
  Y contiene tarifas de A y C
  Y B aparece en failed_providers con reason timeout

Escenario: Paralelismo real
  Dado 3 proveedores que tardan 1.5 s cada uno
  Cuando ejecuto la consulta
  Entonces el tiempo total es cercano a 1.5 s y no a 4.5 s

Escenario: Fallo aislado
  Dado C lanza un error de conexion
  Cuando ejecuto la consulta
  Entonces A y B se procesan normalmente y C aparece con status http_error

Escenario: Escala
  Dado 1000 proveedores simulados con latencias entre 100 ms y 3 s
  Cuando ejecuto la consulta
  Entonces la respuesta llega en 2 s o menos con los que respondieron a tiempo
```

## Casos borde y manejo de errores

- Proveedor que responde justo en el limite: si la respuesta llega pero el mapeo excede el presupuesto, se descarta como `timeout` (ver P-03).
- Cero proveedores habilitados: respuesta inmediata con `results` vacio.
- Respuesta lenta de cuerpo grande (streaming): el timeout aplica a la respuesta completa, no solo al primer byte.

## Decisiones de complejidad algoritmica (requieren aprobacion manual)

| ID | Decision propuesta | Complejidad | Alternativas | Estado |
| --- | --- | --- | --- | --- |
| DC-01 | `asyncio` + `niquests.AsyncSession` con `asyncio.wait(timeout=restante)` o `asyncio.timeout` | Tiempo O(max latencia), memoria O(n) tareas | Hilos con `ThreadPoolExecutor` (costo por hilo alto a 1000+); multiplexado HTTP/2 de niquests sobre sesion sync | Pendiente |
| DC-02 | Limite global de concurrencia con `asyncio.Semaphore` y limites del pool de conexiones | O(n) tareas, O(k) conexiones activas | Sin limite (riesgo de agotar sockets); lotes fijos (aumenta latencia) | Pendiente |

## Preguntas abiertas

- [ ] P-01: Se permiten reintentos dentro de los 2 s (por ejemplo ante 429 de A o timeout esporadico de B)?
- [ ] P-02: Margen aceptable por encima de 2 s para armar y serializar la respuesta.
- [ ] P-03: El corte de 2 s incluye el mapeo y normalizacion, o solo la llamada HTTP?
- [ ] P-04: Valor de concurrencia maxima (k) para 1000 proveedores.

## Historial de revision

| Version | Fecha | Cambios | Revisor |
| --- | --- | --- | --- |
| 0.1 | 2026-10-20 | Borrador inicial, entra a loop de revision | - |
| 0.2 | 2026-10-20 | Alineada con HU001: el corte de 2 s se publica en failed_providers, no en un estado por proveedor | Usuario |
