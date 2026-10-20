# HU002 - Contrato comun de proveedor y registro

| Campo | Valor |
| --- | --- |
| Estado | En revision |
| Version | 0.1 |
| Tipo | Funcional |
| Dependencias | HU001, HU-S03 |

## Historia

**Como** desarrollador que integra proveedores
**Quiero** un contrato comun y una clase base reutilizable para todos los proveedores
**Para** integrar un proveedor nuevo implementando solo lo que lo hace distinto (autenticacion, request, mapeo y deteccion de errores)

## Contexto

Los riesgos de la constitucion senalan autenticaciones y schemas distintos, y la meta de 1000+ proveedores. Sin un contrato comun cada integracion repetiria timeout, logging, manejo de errores y medicion de latencia, violando DRY.

## Requisitos funcionales

- **RF-01**: Clase base abstracta `BaseProvider` en `providers/base.py` que implementa el flujo comun (metodo plantilla):
  1. Esperar turno de rate limit si esta habilitado (HU004).
  2. Construir el request (`build_request`).
  3. Aplicar autenticacion (`AuthStrategy`).
  4. Enviar con la sesion compartida y el timeout configurado.
  5. Detectar errores (`detect_error`).
  6. Mapear al modelo comun (`map_response`).
  7. Devolver un `ProviderResult` con tarifas y estado; medir latencia y emitir el log `provider_call` (HU-S04).
- **RF-02**: Cada adaptador solo implementa los puntos de variacion:

| Metodo | Responsabilidad |
| --- | --- |
| `build_request(query)` | Traducir la consulta HU001 al request del proveedor |
| `detect_error(response)` | Clasificar errores HTTP y de negocio (clave para C) |
| `map_response(payload, query)` | Traducir el payload al modelo HU001 (clave para B) |
| `extra_headers()` | Headers propios (por ejemplo `idempotency-key` de A) |

- **RF-03**: Estrategias de autenticacion reutilizables en `providers/auth.py`: `ApiKeyAuth(header, secret)`, `BasicAuth(user, password)`, `NoAuth`. Se seleccionan por configuracion (`auth.type`), no por codigo en el adaptador.
- **RF-04**: Registro de adaptadores: mapa `nombre de adaptador -> clase`, poblado por declaracion explicita o decorador `@register_provider("provider_a")`. El orquestador obtiene los proveedores habilitados del registro + configuracion (HU-S03).
- **RF-05**: `ProviderResult` contiene: `provider_id`, `status`, `rates`, `latency_ms`, `http_status`, `error_code`, `billable`.
- **RF-06**: Jerarquia de excepciones propia (`ProviderTimeout`, `ProviderRateLimited`, `ProviderBusinessError`, `ProviderHttpError`, `ProviderParseError`) traducida a `status` en un unico punto de la clase base.
- **RF-07**: Ninguna excepcion de un adaptador escapa de `BaseProvider`; siempre se devuelve un `ProviderResult`.

## Requisitos no funcionales aplicables

- **RNF-01**: Un adaptador nuevo con schema simple no deberia requerir mas de los cuatro metodos de RF-02.
- **RNF-02**: Los adaptadores son probables de forma aislada con respuestas grabadas (fixtures JSON).
- **RNF-03**: Los adaptadores no comparten estado mutable entre consultas salvo la sesion HTTP y el rate limiter.

## Criterios de aceptacion

```gherkin
Escenario: Integrar proveedor nuevo
  Dado un proveedor ficticio con API key y schema plano
  Cuando implemento build_request, detect_error y map_response y lo registro
  Entonces se consulta con timeout, logging y rate limit sin escribir esa logica

Escenario: Excepcion inesperada en adaptador
  Dado un adaptador cuyo map_response lanza una excepcion no controlada
  Cuando se ejecuta la consulta
  Entonces ese proveedor queda con status parse_error
  Y los demas proveedores devuelven sus resultados normalmente
```

## Casos borde y manejo de errores

- Adaptador registrado con nombre duplicado: error en el arranque.
- Configuracion que referencia un adaptador no registrado: error de validacion (HU-S03).
- Payload parcialmente valido: se devuelven las tarifas validas y se registran las descartadas (ver P-02).

## Decisiones de complejidad algoritmica (requieren aprobacion manual)

No aplica (la busqueda en el registro es por diccionario, O(1)).

## Preguntas abiertas

- [ ] P-01: Registro por decorador (implicito al importar) o por lista explicita en configuracion? Propuesta: lista explicita para trazabilidad.
- [ ] P-02: Ante payload parcialmente invalido: descartar solo las tarifas invalidas o todo el proveedor?
- [ ] P-03: Se preve que algun proveedor futuro no sea REST/JSON (SOAP, XML)? Afecta si `map_response` recibe JSON o bytes.

## Historial de revision

| Version | Fecha | Cambios | Revisor |
| --- | --- | --- | --- |
| 0.1 | 2026-10-20 | Borrador inicial, entra a loop de revision | - |
