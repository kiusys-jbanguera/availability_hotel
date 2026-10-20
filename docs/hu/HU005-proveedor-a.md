# HU005 - Integracion proveedor A

| Campo | Valor |
| --- | --- |
| Estado | En revision |
| Version | 0.2 |
| Tipo | Funcional |
| Dependencias | HU003, HU004 |

## Historia

**Como** consumidor del servicio de disponibilidad
**Quiero** obtener las tarifas del proveedor A en el formato estandarizado
**Para** incluir su oferta respetando su cuota de 10 req/s, su idempotencia obligatoria y controlando su costo por request

## Contexto

Caracteristicas conocidas del proveedor A:

| Aspecto | Valor |
| --- | --- |
| Protocolo | REST/JSON |
| Autenticacion | API key |
| Latencia | Rapido, p95 250 ms |
| Limite | 10 req/s por cliente; responde 429 al superarlo |
| Requisito especial | Header `idempotency-key` obligatorio en cada request |
| Costo | Cobra por request |

## Requisitos funcionales

### Autenticacion y headers

- **RF-01**: Autenticacion con `ApiKeyAuth` (HU002) usando el header de configuracion y el `api_key` resuelto desde Secrets Manager (HU-S03, ver P-01).
- **RF-02**: Cada request lleva el header `idempotency-key` con un UUID4 nuevo por request. Se genera en `extra_headers()` del adaptador.
- **RF-03**: Si en el futuro se permite un reintento (HU003 P-01), el reintento reutiliza **la misma** `idempotency-key` para que el proveedor no lo procese ni lo cobre dos veces (ver P-02).
- **RF-04**: Un request sin `idempotency-key` nunca se envia: se valida antes del envio y se considera error de programacion.

### Rate limit y 429

- **RF-05**: Configuracion por defecto de A: `rate_limit.enabled = true`, `requests = 10`, `per_seconds = 1` (HU004).
- **RF-06**: Respuesta 429: status `rate_limited`, se lee `Retry-After` y se bloquea el limitador de A por ese tiempo (HU004 RF-06). No se reintenta dentro de la consulta salvo aprobacion de HU003 P-01.

### Costo

- **RF-07**: Toda peticion efectivamente enviada a A se marca `billable = true` en el log `provider_call` (HU-S04), incluyendo las que terminen en error o timeout del lado cliente.
- **RF-08**: `search_completed` reporta `billable_requests` y `estimated_cost` usando `billing.cost_per_request` (HU-S03).
- **RF-09**: Las peticiones descartadas por el limitador local no se envian y por tanto no generan costo.
- **RF-10**: No se consulta A si la consulta fue invalida (HU001 RF-02) para evitar cobros innecesarios.

### Mapeo

- **RF-11**: `build_request` traduce la consulta HU001 al contrato de A (endpoint, metodo y parametros, ver P-03).
- **RF-12**: `map_response` traduce el payload de A al modelo HU001; los impuestos se asumen incluidos salvo que P-04 indique lo contrario.
- **RF-13**: Clasificacion de errores en `detect_error`:

| Respuesta de A | Status |
| --- | --- |
| 2xx con tarifas | `ok` |
| 2xx sin tarifas | `ok` con `results_count = 0` |
| 401 / 403 | `http_error` con `error_code = AUTH` y log `ERROR` |
| 409 / 422 por idempotencia | `http_error` con `error_code = IDEMPOTENCY` |
| 429 | `rate_limited` |
| 5xx | `http_error` |
| Sin respuesta en el tiempo efectivo | `timeout` |

## Requisitos no funcionales aplicables

- **RNF-01**: Con p95 de 250 ms, A debe estar en la respuesta en al menos el 95 % de las consultas cuando no se supera su cuota.
- **RNF-02**: La generacion del UUID no debe ser un cuello de botella (`uuid.uuid4()`, O(1)).

## Criterios de aceptacion

```gherkin
Escenario: Idempotency key unica por request
  Dado dos consultas consecutivas
  Cuando se envian a A
  Entonces cada request lleva un header idempotency-key distinto con formato UUID

Escenario: Respeto de la cuota
  Dado 15 consultas simultaneas
  Cuando se procesan
  Entonces A no recibe mas de 10 requests en el mismo segundo
  Y ninguna respuesta 429 es provocada por exceso local

Escenario: Manejo de 429
  Dado A responde 429 con Retry-After 1
  Cuando termina la consulta
  Entonces A aparece como rate_limited
  Y las tarifas de B y C se devuelven normalmente

Escenario: Seguimiento de costo
  Dado una consulta que envia un request a A
  Cuando termina la consulta
  Entonces search_completed reporta billable_requests = 1 y el costo estimado
```

## Casos borde y manejo de errores

- API key invalida o revocada: `http_error` / `AUTH`; debe alertarse en log porque afecta todas las consultas.
- Respuesta 2xx con JSON invalido: `parse_error`; la peticion igual cuenta como facturable.
- Timeout local tras enviar la peticion: se cuenta como facturable aunque no haya resultados.

## Decisiones de complejidad algoritmica (requieren aprobacion manual)

No aplica adicional a las de HU003 y HU004.

## Preguntas abiertas

- [ ] P-01: Nombre exacto del header de la API key (`x-api-key`, `Authorization: ApiKey ...`).
- [ ] P-02: Ventana de validez de la `idempotency-key` en A y si un reintento con la misma clave se cobra.
- [ ] P-03: Contrato de A: endpoint, metodo, parametros y schema de respuesta (se necesita especificacion u OpenAPI).
- [ ] P-04: A devuelve precios con impuestos incluidos? Moneda de la respuesta?
- [ ] P-05: Costo por request y si existe presupuesto maximo diario que obligue a cortar consultas.
- [ ] P-06: Codigo HTTP que usa A ante `idempotency-key` faltante o repetida.

## Historial de revision

| Version | Fecha | Cambios | Revisor |
| --- | --- | --- | --- |
| 0.1 | 2026-10-20 | Borrador inicial, entra a loop de revision | - |
| 0.2 | 2026-10-20 | La API key se resuelve desde Secrets Manager (HU-S03), no desde variables de entorno | Usuario |
