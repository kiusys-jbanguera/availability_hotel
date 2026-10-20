# HU001 - Modelo estandarizado de consulta y respuesta

| Campo | Valor |
| --- | --- |
| Estado | En revision |
| Version | 0.3 |
| Tipo | Funcional |
| Dependencias | HU-S01 |

## Historia

**Como** consumidor del servicio de disponibilidad
**Quiero** enviar una consulta con un formato unico y recibir tarifas en un formato unico sin importar el proveedor
**Para** comparar ofertas por hotel, habitacion y precio final, y saber que proveedores no pudieron responder

## Contexto

El objetivo de la constitucion es "entregar una respuesta estandarizada". La entrada publica es `search(destino, check_in, check_out, huespedes)`, la misma que expone HU008. La salida publica es la vista del body HTTP: cada oferta trae hotel, habitacion, precio final con moneda y proveedor de origen, y `failed_providers` indica que proveedores fallaron. El calculo interno (impuestos de B, latencia, codigos HTTP) no se publica; la latencia y el detalle quedan en los logs (HU-S04).

## Requisitos funcionales

### Consulta (entrada)

- **RF-01**: Campos de la consulta:

| Campo | Tipo | Obligatorio | Regla |
| --- | --- | --- | --- |
| `destino` | texto | Si | No vacio. Codificacion en P-01 |
| `check_in` | fecha ISO 8601 | Si | Mayor o igual a hoy |
| `check_out` | fecha ISO 8601 | Si | Mayor que `check_in`. Maximo de noches en P-02 |
| `huespedes` | entero | Si | Mayor o igual a 1. Maximo en P-02 |

No forman parte de la entrada: filtro por hotel, habitaciones, edades ni moneda solicitada. La moneda viaja solo en cada oferta de la salida.

- **RF-02**: La consulta se valida antes de llamar a cualquier proveedor; si es invalida no se consulta ninguno y se devuelve un error de validacion con la lista de campos fallidos.

### Respuesta (salida)

- **RF-03**: La respuesta publica tiene solo dos bloques: `results` y `failed_providers`.

```json
{
  "results": [
    {
      "hotel": "Hotel Central",
      "room": "Doble estandar",
      "price": "119.00",
      "currency": "USD",
      "provider": "provider_a"
    }
  ],
  "failed_providers": [
    {
      "provider": "provider_b",
      "reason": "timeout"
    }
  ]
}
```

- **RF-04**: Cada oferta publica exactamente estos campos:

| Campo | Contenido |
| --- | --- |
| `hotel` | Nombre del hotel. Si el proveedor solo entrega un codigo, se publica ese codigo. |
| `room` | Nombre de la habitacion. Misma regla que `hotel` si solo hay codigo. |
| `price` | Precio final, impuestos incluidos, texto con 2 decimales. |
| `currency` | Moneda ISO 4217 de ese precio. |
| `provider` | Identificador del proveedor de origen (`provider_a`, `provider_b`, `provider_c`). |

- **RF-05**: `price` es el precio final. Si el proveedor no incluye impuestos, el adaptador los suma antes de publicar (HU006) y la respuesta no lleva desglose de neto ni de impuestos.
- **RF-06**: Los montos se representan como `Decimal` internamente y como texto con 2 decimales en la salida; nunca como `float`.
- **RF-07**: `failed_providers` lista solo a los proveedores habilitados que fallaron. Cada entrada tiene `provider` y `reason`, con uno de estos valores: `timeout`, `rate_limited`, `business_error`, `http_error`, `parse_error`.
- **RF-08**: Un proveedor que responde a tiempo y sin error no aparece en `failed_providers`, aunque no tenga ofertas. No tener disponibilidad no es un fallo.
- **RF-09**: Un proveedor con todas sus ofertas invalidas (sin hotel, sin habitacion o sin precio) aparece en `failed_providers` con `reason = parse_error`. Si al menos una oferta es valida, se publican las validas y el proveedor no se marca como fallido; las descartadas quedan solo en el log.
- **RF-10**: `results` se ordena por `price` ascendente (ver DC-01).
- **RF-11**: Si ningun proveedor aporta ofertas, la respuesta es valida con `results` vacio. Los que fallaron siguen en `failed_providers`. No es un error de la consulta.

## Requisitos no funcionales aplicables

- **RNF-01**: Modelos inmutables (por ejemplo `dataclass(frozen=True)` o modelos `pydantic` congelados).
- **RNF-02**: La serializacion vive solo en `views/` y es el body de la respuesta HTTP (HU008).

## Criterios de aceptacion

```gherkin
Escenario: Consulta invalida
  Dado una consulta con check_out anterior a check_in
  Cuando se ejecuta la busqueda
  Entonces no se llama a ningun proveedor
  Y se devuelve un error de validacion sobre check_out

Escenario: Oferta estandar
  Dado que A devuelve una habitacion doble del Hotel Central a 119 USD con impuestos incluidos
  Cuando se arma la respuesta
  Entonces results contiene hotel "Hotel Central", room "Doble estandar", price "119.00", currency "USD" y provider "provider_a"
  Y no incluye neto, impuestos, regimen ni politica de cancelacion

Escenario: Proveedores fallidos
  Dado que A responde con ofertas, B supera los 2 s y C responde un error de negocio
  Cuando termina la consulta
  Entonces results solo tiene ofertas de A
  Y failed_providers contiene a B con reason timeout y a C con reason business_error
  Y A no aparece en failed_providers

Escenario: Sin disponibilidad no es fallo
  Dado que C responde a tiempo sin ofertas y sin error
  Cuando termina la consulta
  Entonces C no aparece en failed_providers

Escenario: Sin respuestas a tiempo
  Dado que ningun proveedor responde en 2 s
  Cuando termina la consulta
  Entonces results esta vacio
  Y failed_providers lista a cada proveedor consultado con reason timeout
```

## Casos borde y manejo de errores

- Proveedor devuelve moneda distinta a la solicitada: ver P-03 (convertir, descartar o devolver tal cual).
- Oferta sin hotel, sin habitacion o sin precio: se descarta. Si era la unica del proveedor, el proveedor entra en `failed_providers` con `parse_error`.
- Precio negativo o cero: se descarta con la misma regla.
- Mismo hotel en varios proveedores: se publican todas las ofertas, cada una con su `provider`. La deduplicacion queda fuera de fase 1 (ver P-04).
- Monedas distintas en la misma respuesta: no se convierten (P-03). El orden por precio solo agrupa ofertas de la misma moneda.

## Decisiones de complejidad algoritmica (requieren aprobacion manual)

| ID | Decision propuesta | Complejidad | Alternativas | Estado |
| --- | --- | --- | --- | --- |
| DC-01 | Ordenar resultados con `sorted` por `price` | O(n log n), n = ofertas | Sin orden (O(1)); top-k con `heapq` (O(n log k)) | Pendiente |

## Preguntas abiertas

- [ ] P-01: Codificacion del destino: IATA, codigo interno o texto libre? Cada proveedor puede usar codigos distintos.
- [ ] P-02: Maximo de noches y maximo de `huespedes`?
- [ ] P-03: La entrada no pide moneda. Se convierten los precios de los proveedores a una moneda comun en fase 1? Si es asi, cual y con que fuente de tasas.
- [ ] P-04: Se requiere deduplicar o agrupar el mismo hotel entre proveedores (mapeo de hoteles)?
- [x] P-05: Regimen y politica de cancelacion. **Resuelta**: no forman parte de la respuesta. La salida publica es hotel, habitacion, precio final, moneda y proveedor.

## Historial de revision

| Version | Fecha | Cambios | Revisor |
| --- | --- | --- | --- |
| 0.1 | 2026-10-20 | Borrador inicial, entra a loop de revision | - |
| 0.2 | 2026-10-20 | Iteracion 1: la salida publica es hotel, habitacion, precio final con moneda y proveedor. `failed_providers` indica solo quienes fallaron. Sin desglose de impuestos ni estado de los que respondieron bien | Usuario |
| 0.3 | 2026-10-20 | Entrada reducida a destino, check_in, check_out y huespedes, alineada con search de HU008 | Usuario |
