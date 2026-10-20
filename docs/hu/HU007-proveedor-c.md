# HU007 - Integracion proveedor C

| Campo | Valor |
| --- | --- |
| Estado | En revision |
| Version | 0.3 |
| Tipo | Funcional |
| Dependencias | HU003 |

## Historia

**Como** consumidor del servicio de disponibilidad
**Quiero** que los errores de negocio del proveedor C se detecten aunque lleguen con HTTP 200
**Para** no confundir un error con "sin disponibilidad" ni publicar tarifas a partir de una respuesta fallida

## Contexto

Caracteristicas conocidas del proveedor C:

| Aspecto | Valor |
| --- | --- |
| Protocolo | REST/JSON |
| Autenticacion | API key |
| Particularidad | Devuelve errores de negocio dentro de un HTTP 200 |
| Latencia | No especificada (ver P-04) |
| Rate limit | No especificado (desactivado por defecto) |

## Requisitos funcionales

### Autenticacion

- **RF-01**: Autenticacion con `ApiKeyAuth` (HU002) usando el header de configuracion y el `api_key` resuelto desde Secrets Manager (HU-S03, ver P-01).

### Deteccion de errores en HTTP 200

- **RF-02**: `detect_error` inspecciona el cuerpo de **toda** respuesta 2xx antes de mapear. Una respuesta se considera error de negocio si cumple la regla definida en configuracion (ver P-02), por ejemplo:
  - Existe el campo `error` o `errors` no vacio, o
  - `success == false`, o
  - `status` distinto de `OK`.
- **RF-03**: La regla de deteccion es declarativa (ruta del campo + condicion) para reutilizarla con futuros proveedores con el mismo patron (DRY).
- **RF-04**: Error de negocio detectado: el proveedor entra en `failed_providers` con `reason = business_error` (HU001). El codigo queda en el log (HU-S04). No se publican ofertas.
- **RF-05**: Catalogo de codigos de C clasificado en (ver P-03):

| Categoria | Ejemplos esperados | Tratamiento |
| --- | --- | --- |
| Sin disponibilidad | `NO_AVAILABILITY` | No entra en `failed_providers` y no publica ofertas |
| Error de consulta | `INVALID_DATES`, `INVALID_DESTINATION` | `business_error`, log `WARNING` |
| Error de credenciales | `INVALID_KEY` | `business_error` / `AUTH`, log `ERROR` |
| Error interno de C | `INTERNAL_ERROR` | `business_error`, log `ERROR` |
| Codigo desconocido | cualquiera no catalogado | `business_error`, log `WARNING` con el codigo |

- **RF-06**: Errores HTTP reales (4xx, 5xx) se tratan como `http_error` igual que en el resto de proveedores.

### Mapeo

- **RF-07**: `build_request` y `map_response` traducen entre HU001 y el contrato de C (ver P-05).
- **RF-08**: Respuesta 200 sin error y sin ofertas: no entra en `failed_providers` y no publica ofertas.

## Requisitos no funcionales aplicables

- **RNF-01**: La deteccion de error de negocio es O(1) sobre campos de primer nivel o O(d) sobre la profundidad de la ruta configurada.
- **RNF-02**: Pruebas con fixtures por cada categoria del catalogo.

## Criterios de aceptacion

```gherkin
Escenario: Error de negocio en HTTP 200
  Dado C responde 200 con {"success": false, "error": {"code": "INVALID_DATES"}}
  Cuando se procesa la respuesta
  Entonces C aparece en failed_providers con reason business_error
  Y no se publican ofertas de C

Escenario: Sin disponibilidad no es error
  Dado C responde 200 con codigo NO_AVAILABILITY
  Cuando se procesa la respuesta
  Entonces C no aparece en failed_providers y no publica ofertas

Escenario: Respuesta exitosa
  Dado C responde 200 con tarifas validas y sin error
  Cuando se procesa la respuesta
  Entonces las tarifas aparecen en el formato estandarizado

Escenario: Codigo desconocido
  Dado C responde 200 con un codigo de error no catalogado
  Cuando se procesa la respuesta
  Entonces C aparece como business_error y el codigo queda registrado en log
```

## Casos borde y manejo de errores

- Respuesta 200 con error **y** tarifas a la vez: prevalece el error; no se publican tarifas (ver P-06).
- Respuesta 200 con cuerpo vacio o no JSON: `parse_error`.
- Campo de error presente pero vacio (`"errors": []`): no es error.

## Decisiones de complejidad algoritmica (requieren aprobacion manual)

No aplica adicional a las de HU003.

## Preguntas abiertas

- [ ] P-01: Nombre exacto del header de API key.
- [ ] P-02: Campo y condicion exactos que indican error en el cuerpo de la respuesta 200.
- [ ] P-03: Catalogo completo de codigos de error de negocio de C.
- [ ] P-04: Latencia esperada y rate limit de C, si existen.
- [ ] P-05: Contrato de C: endpoint, metodo, parametros y schema de respuesta.
- [ ] P-06: Puede C devolver errores parciales (por hotel) junto con tarifas validas? Si es asi, se publican las validas?
- [ ] P-07: C devuelve precios con o sin impuestos? Moneda?

## Historial de revision

| Version | Fecha | Cambios | Revisor |
| --- | --- | --- | --- |
| 0.1 | 2026-10-20 | Borrador inicial, entra a loop de revision | - |
| 0.2 | 2026-10-20 | La API key se resuelve desde Secrets Manager (HU-S03), no desde variables de entorno | Usuario |
| 0.3 | 2026-10-20 | Alineada con HU001: el error de negocio se publica en failed_providers. Sin disponibilidad no es un fallo | Usuario |
