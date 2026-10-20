# HU004 - Rate limit configurable por proveedor

| Campo | Valor |
| --- | --- |
| Estado | En revision |
| Version | 0.1 |
| Tipo | Funcional |
| Dependencias | HU-S03 |

## Historia

**Como** operador de la plataforma
**Quiero** limitar opcionalmente las peticiones por segundo hacia cada proveedor segun su propio criterio
**Para** no exceder sus cuotas, evitar respuestas 429 y costos innecesarios

## Contexto

La constitucion pide un rate limit configurable, opcional y con criterio variable por proveedor. El proveedor A limita a 10 req/s por cliente y responde 429 al superarlo (HU005).

## Requisitos funcionales

- **RF-01**: El rate limit se activa por proveedor con `rate_limit.enabled`; por defecto esta desactivado.
- **RF-02**: Parametros configurables por proveedor: `requests` y `per_seconds` (A: 10 por 1 s), y opcionalmente `burst`.
- **RF-03**: Un limitador independiente por proveedor; el limite de uno no afecta a otro.
- **RF-04**: El limitador se aplica en `BaseProvider` antes de enviar (HU002); los adaptadores no implementan su propia logica de limite (DRY).
- **RF-05**: Si no hay cupo, la espera maxima es el tiempo restante del presupuesto de 2 s. Si no se obtiene cupo a tiempo, el proveedor queda con status `rate_limited` y **no se envia la peticion** (no se genera costo en A) (DC-02).
- **RF-06**: Si el proveedor responde 429 pese al limitador, se marca `rate_limited`, se registra y se respeta `Retry-After` bloqueando el limitador de ese proveedor durante ese tiempo.
- **RF-07**: El estado del limitador es compartido entre consultas concurrentes del mismo proceso.

## Requisitos no funcionales aplicables

- **RNF-01**: Adquirir un cupo es O(1) y no bloquea el ciclo de eventos.
- **RNF-02**: Precision suficiente para no superar `requests` en cualquier ventana de `per_seconds`.

## Criterios de aceptacion

```gherkin
Escenario: Rate limit desactivado
  Dado el proveedor C sin rate limit configurado
  Cuando lanzo 50 consultas simultaneas
  Entonces C recibe 50 peticiones sin espera

Escenario: Respetar el limite de A
  Dado A con limite 10 por segundo
  Cuando lanzo 25 consultas simultaneas
  Entonces A no recibe mas de 10 peticiones en ningun segundo
  Y las consultas sin cupo dentro de 2 s marcan A como rate_limited sin enviar peticion

Escenario: 429 con Retry-After
  Dado A responde 429 con Retry-After de 1 s
  Cuando llega otra consulta en ese segundo
  Entonces no se envia peticion a A y queda como rate_limited
```

## Casos borde y manejo de errores

- `Retry-After` en formato fecha HTTP o en segundos: ambos se soportan.
- `Retry-After` mayor a 2 s: el proveedor se omite en las consultas siguientes hasta que expire.
- Varias replicas del servicio: el limite por proceso no garantiza el limite global por cliente (ver P-01).

## Decisiones de complejidad algoritmica (requieren aprobacion manual)

| ID | Decision propuesta | Complejidad | Alternativas | Estado |
| --- | --- | --- | --- | --- |
| DC-01 | Token bucket en memoria por proveedor (asyncio) | O(1) por adquisicion, O(p) memoria, p = proveedores | Ventana deslizante con log (O(r) memoria, mas exacta); ventana fija (O(1), permite rafagas 2x en el borde) | Pendiente |
| DC-02 | Esperar cupo hasta el tiempo restante de 2 s y luego descartar | Espera acotada por presupuesto | Descartar inmediatamente sin esperar; encolar (no cabe en 2 s) | Pendiente |

## Preguntas abiertas

- [ ] P-01: Habra multiples replicas del servicio? Si es asi, se necesita limitador distribuido (por ejemplo Redis) para respetar 10 req/s por cliente de A.
- [ ] P-02: El limite de A de 10 req/s es por API key o por IP?
- [ ] P-03: Se requiere rafaga (`burst`) o el limite debe ser estricto?

## Historial de revision

| Version | Fecha | Cambios | Revisor |
| --- | --- | --- | --- |
| 0.1 | 2026-10-20 | Borrador inicial, entra a loop de revision | - |
