# HU006 - Integracion proveedor B

| Campo | Valor |
| --- | --- |
| Estado | En revision |
| Version | 0.3 |
| Tipo | Funcional |
| Dependencias | HU003 |

## Historia

**Como** consumidor del servicio de disponibilidad
**Quiero** obtener las tarifas del proveedor B normalizadas y con impuestos calculados
**Para** comparar sus precios en igualdad de condiciones con el resto, aceptando que se excluya cuando no responda en 2 s

## Contexto

Caracteristicas conocidas del proveedor B:

| Aspecto | Valor |
| --- | --- |
| Protocolo | REST/JSON |
| Autenticacion | Basica (usuario y contrasena) |
| Schema | Propio: estructura anidada, fechas y montos en formatos no estandar |
| Latencia | Lento: p95 3 s, picos de 8 s, timeouts esporadicos |
| Precios | Sin impuestos |

**Decision aceptada**: B se excluye de la respuesta cuando supera el corte de 2 s. Dado su p95 de 3 s, se espera que quede fuera en la mayoria de consultas. Se documenta como riesgo y se monitorea.

## Requisitos funcionales

### Autenticacion

- **RF-01**: Autenticacion con `BasicAuth` (HU002) con usuario y contrasena del secreto resuelto en Secrets Manager (HU-S03). Nunca se registran en logs.

### Tiempo de respuesta

- **RF-02**: Timeout efectivo = menor entre `timeout_s` (maximo 2 s) y el tiempo restante del presupuesto (HU003 RF-03).
- **RF-03**: Al exceder el tiempo, la llamada se cancela, B queda con status `timeout` y no bloquea ni retrasa la respuesta.
- **RF-04**: Timeouts esporadicos y errores de conexion se clasifican como `timeout` o `http_error` respectivamente, sin reintento dentro de la consulta.
- **RF-05**: Metrica de exclusion: el log `search_completed` permite calcular la tasa de consultas en que B fue excluido por timeout.

### Mapeo del schema anidado

- **RF-06**: `map_response` recorre la estructura anidada de B (por ejemplo `hoteles -> habitaciones -> tarifas`) y produce una tarifa del modelo HU001 por cada combinacion valida (ver P-01).
- **RF-07**: El acceso a campos anidados usa una utilidad comun de extraccion por ruta (por ejemplo `get_path(payload, "a.b.c")`) reutilizable por futuros proveedores (DRY).
- **RF-08**: Campos obligatorios faltantes en un nodo descartan solo esa tarifa y se registran en `DEBUG`.

### Fechas y montos no estandar

- **RF-09**: Parser de fechas configurable por proveedor con los formatos declarados (ver P-02), produciendo `datetime.date`. Formato invalido: tarifa descartada con `parse_error`.
- **RF-10**: Parser de montos configurable (separador de miles, separador decimal, simbolo o codigo de moneda, posicion) que produce `Decimal`; nunca `float` (ver P-03).
- **RF-11**: Los parsers de fechas y montos viven en una utilidad compartida y se parametrizan por configuracion, no con logica ad hoc en el adaptador (DRY).

### Impuestos

- **RF-12**: B se configura con `pricing.taxes_included = false` y `pricing.tax_rate` (HU-S03).
- **RF-13**: Para cada oferta el calculo interno es `neto` = monto de B y `impuesto = round(neto * tax_rate, 2)`. El `price` publicado (HU001) es `neto + impuesto`. La respuesta no incluye neto, impuesto ni una marca de si el proveedor los traia.
- **RF-14**: Redondeo con `ROUND_HALF_UP` a 2 decimales (ver P-05).
- **RF-15**: Si no existe tasa aplicable, la tarifa se descarta y se registra (no se publica un precio incompleto).

## Requisitos no funcionales aplicables

- **RNF-01**: El mapeo de un payload tipico de B debe tomar pocos milisegundos para no consumir el presupuesto de 2 s.
- **RNF-02**: Pruebas unitarias con fixtures reales o representativos del schema de B, cubriendo cada formato de fecha y monto.

## Criterios de aceptacion

```gherkin
Escenario: Exclusion por lentitud
  Dado B tarda 3 s en responder
  Cuando ejecuto la consulta
  Entonces la respuesta llega en 2 s o menos sin tarifas de B
  Y B aparece en failed_providers con reason timeout

Escenario: Respuesta a tiempo con impuestos
  Dado B responde en 1.2 s una tarifa de "1.234,50" y tax_rate 0.19
  Cuando se normaliza
  Entonces la oferta publicada tiene price "1469.06" y currency de B
  Y la respuesta no incluye el neto 1234.50 ni el impuesto 234.56

Escenario: Fecha no estandar
  Dado B devuelve la fecha en su formato propio
  Cuando se normaliza
  Entonces el adaptador la interpreta como fecha ISO 8601 para validar la estadia
  Y esa fecha no se publica: la oferta solo lleva hotel, habitacion, precio, moneda y proveedor

Escenario: Nodo invalido
  Dado una respuesta de B con una tarifa sin monto
  Cuando se normaliza
  Entonces se descarta solo esa tarifa y el resto se devuelve
```

## Casos borde y manejo de errores

- Pico de 8 s: la conexion se cancela a los 2 s y se libera; no debe acumular conexiones abiertas.
- Respuesta valida que llega cuando el presupuesto ya se agoto: se descarta.
- Credenciales invalidas (401): `http_error` / `AUTH` con log `ERROR`.
- Montos ambiguos (por ejemplo `1.234` sin decimales): se resuelven segun la configuracion declarada, nunca por heuristica.

## Decisiones de complejidad algoritmica (requieren aprobacion manual)

| ID | Decision propuesta | Complejidad | Alternativas | Estado |
| --- | --- | --- | --- | --- |
| DC-01 | Parseo de montos y fechas por formato declarado en configuracion (lista de formatos probados en orden) | O(f) por valor, f = formatos declarados | Deteccion heuristica (fragil); un unico formato fijo (rigido) | Pendiente |
| DC-02 | Recorrido del arbol anidado de B en una pasada | O(t), t = nodos del payload | Aplanado previo a estructura intermedia (O(t) con memoria extra) | Pendiente |

## Riesgos

- Con p95 de 3 s, B estara ausente en la mayoria de respuestas; el negocio pierde su oferta en esos casos. Mitigaciones fuera de alcance de fase 1 (cache, precarga) requieren nueva HU y aprobacion.

## Preguntas abiertas

- [ ] P-01: Especificacion del schema anidado de B (ejemplo real de respuesta).
- [ ] P-02: Formatos exactos de fecha (por ejemplo `DD/MM/YYYY`, `YYYYMMDD`, epoch) y zona horaria.
- [ ] P-03: Formato exacto de montos (separadores, simbolo, moneda) y si la moneda viene en otro campo.
- [ ] P-04: Tasa de impuesto: unica, por pais, por ciudad o por hotel? Fuente oficial de la tasa.
- [ ] P-05: Regla de redondeo exigida por negocio (`ROUND_HALF_UP` o `ROUND_HALF_EVEN`).
- [x] P-06: Desglose de impuestos en la respuesta. **Resuelta**: solo se publica el precio final (HU001). El neto y el impuesto se calculan y no salen en el JSON.

## Historial de revision

| Version | Fecha | Cambios | Revisor |
| --- | --- | --- | --- |
| 0.1 | 2026-10-20 | Borrador inicial, entra a loop de revision. Se registra la decision de aceptar exclusion de B por timeout | - |
| 0.2 | 2026-10-20 | Usuario y contrasena se resuelven desde Secrets Manager (HU-S03), no desde variables de entorno | Usuario |
| 0.3 | 2026-10-20 | Alineada con HU001: el impuesto se suma al precio final y no se publica el desglose. El timeout de B va en failed_providers | Usuario |
