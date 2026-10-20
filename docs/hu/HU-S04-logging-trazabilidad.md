# HU-S04 - Logging y trazabilidad

| Campo | Valor |
| --- | --- |
| Estado | En revision |
| Version | 0.2 |
| Tipo | Setup |
| Dependencias | HU-S01 |

## Historia

**Como** operador de la plataforma
**Quiero** logs estructurados por consulta y por proveedor
**Para** seguir el comportamiento de cada proveedor, diagnosticar fallos y controlar costos sin afectar el sistema en general

## Contexto

La constitucion pide seguimiento de cada proveedor por medio de logs. Con 1000+ proveedores el volumen de logs crece y debe ser filtrable por consulta y por proveedor.

## Requisitos funcionales

- **RF-01**: Logs en formato JSON, una linea por evento, hacia stderr; la respuesta de la consulta va unicamente en el body de la respuesta HTTP (HU008), nunca mezclada con los logs.
- **RF-02**: Cada consulta genera un `correlation_id` (UUID4) que se propaga a todos los logs de esa consulta y a cada llamada a proveedor.
- **RF-03**: Por cada llamada a proveedor se emite un evento `provider_call` con:

| Campo | Descripcion |
| --- | --- |
| `correlation_id` | Id de la consulta |
| `provider_id` | Proveedor consultado |
| `status` | `ok`, `timeout`, `rate_limited`, `business_error`, `http_error`, `parse_error`, `skipped` |
| `http_status` | Codigo HTTP si hubo respuesta |
| `latency_ms` | Latencia medida |
| `results_count` | Tarifas normalizadas devueltas |
| `error_code` | Codigo de error del proveedor si aplica |
| `billable` | `true` si la llamada genera costo (A) |
| `idempotency_key` | Para A, la clave usada |

- **RF-04**: Al final de cada consulta se emite un evento `search_completed` con totales: proveedores consultados, respondidos a tiempo, excluidos por timeout, con error, latencia total y costo estimado.
- **RF-05**: El nivel de log es configurable por variable de entorno (`LOG_LEVEL`, por defecto `INFO`).
- **RF-06**: Una unica utilidad de logging en `core/` usada por todas las capas (DRY); ningun modulo configura handlers propios.

## Requisitos no funcionales aplicables

- **RNF-01**: Nunca se registran API keys, headers `Authorization`, contrasenas ni datos personales de huespedes. Se aplica un filtro de redaccion centralizado.
- **RNF-02**: Escribir logs no puede bloquear el ciclo de eventos ni agregar latencia relevante al presupuesto de 2 s (ver P-02).
- **RNF-03**: Un fallo al escribir logs no interrumpe la consulta.

## Criterios de aceptacion

```gherkin
Escenario: Trazabilidad por consulta
  Dado una consulta a A, B y C
  Cuando filtro los logs por su correlation_id
  Entonces encuentro un evento provider_call por proveedor y un search_completed

Escenario: Redaccion de secretos
  Dado una llamada al proveedor A con API key
  Cuando reviso los logs
  Entonces la API key no aparece en ningun evento

Escenario: Timeout registrado
  Dado que B no responde en 2 s
  Cuando termina la consulta
  Entonces existe un provider_call de B con status timeout
```

## Casos borde y manejo de errores

- Respuestas de proveedor muy grandes: no se registran cuerpos completos; solo en nivel `DEBUG` y truncados.
- Excepciones inesperadas en un adaptador se registran con traza en nivel `ERROR` y status `http_error` o `parse_error`.

## Decisiones de complejidad algoritmica (requieren aprobacion manual)

No aplica.

## Preguntas abiertas

- [ ] P-01: Libreria: `logging` estandar con formateador JSON propio o `structlog`?
- [ ] P-02: Se requiere logging asincrono (por ejemplo `QueueHandler`) desde la fase 1?
- [ ] P-03: Hay plataforma destino de logs y metricas (ELK, Datadog, CloudWatch) que imponga formato?
- [ ] P-04: Se necesitan metricas (Prometheus/OpenTelemetry) ademas de logs en esta fase?

## Historial de revision

| Version | Fecha | Cambios | Revisor |
| --- | --- | --- | --- |
| 0.1 | 2026-10-20 | Borrador inicial, entra a loop de revision | - |
| 0.2 | 2026-10-20 | Se ajusta RF-01: la respuesta ya no sale por stdout (ya no hay CLI); va en el body de la respuesta HTTP de HU008 | Usuario |
