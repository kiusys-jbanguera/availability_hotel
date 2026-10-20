# HU-S03 - Configuracion por proveedor

| Campo | Valor |
| --- | --- |
| Estado | En revision |
| Version | 0.2 |
| Tipo | Setup |
| Dependencias | HU-S01 |

## Historia

**Como** operador de la plataforma
**Quiero** declarar cada proveedor en configuracion y resolver sus credenciales desde AWS Secrets Manager
**Para** agregar o ajustar proveedores sin tocar el orquestador y sin dejar secretos en archivos, variables de entorno ni imagenes

## Contexto

Los riesgos de la constitucion indican autenticaciones distintas, rate limit opcional y variable por proveedor, y crecimiento a 1000+ proveedores. La configuracion no sensible es declarativa y se valida al arranque. Las credenciales viven en AWS Secrets Manager: en local el cliente apunta a LocalStack y en productivo usa la cadena de credenciales de AWS, sin parametros de LocalStack.

## Requisitos funcionales

- **RF-01**: Archivo declarativo versionado (`config/providers.toml`, ver P-01) con una entrada por proveedor.
- **RF-02**: Campos por proveedor:

| Campo | Obligatorio | Descripcion |
| --- | --- | --- |
| `id` | Si | Identificador unico (`provider_a`) |
| `enabled` | Si | Habilita o deshabilita el proveedor |
| `adapter` | Si | Adaptador que lo implementa (HU002) |
| `base_url` | Si | URL base del proveedor |
| `auth.type` | Si | `api_key`, `basic` o `none` |
| `auth.header` | Si para `api_key` | Nombre del header de la API key |
| `auth.secret_id` | Si salvo `none` | Nombre o ARN del secreto en Secrets Manager |
| `timeout_s` | No | Timeout del proveedor; por defecto y maximo 2.0 |
| `rate_limit.enabled` | No | Por defecto `false` |
| `rate_limit.requests` / `rate_limit.per_seconds` | Si con rate limit | Cuota (A: 10 por 1 s) |
| `pricing.taxes_included` | No | Por defecto `true`; B es `false` |
| `pricing.tax_rate` | Si con `taxes_included=false` | Tasa a aplicar (HU006) |
| `billing.cost_per_request` | No | Costo unitario para seguimiento (A) |

- **RF-03**: El archivo nunca contiene el valor del secreto; solo `auth.secret_id`.
- **RF-04**: Validacion al arranque con mensajes claros: campos faltantes, tipos invalidos, `timeout_s > 2.0`, ids duplicados, adaptador inexistente, secreto inexistente o con forma invalida para un proveedor habilitado. El mensaje nombra el `secret_id` y nunca el valor.
- **RF-05**: Los valores por defecto se definen en un unico lugar y se heredan por todos los proveedores (DRY).
- **RF-06**: Un proveedor deshabilitado no se instancia ni se consulta, y no aparece como fallo en la respuesta.
- **RF-07**: El timeout global de consulta (2 s) es configurable a nivel de aplicacion, no por proveedor.

### Secretos (AWS Secrets Manager)

- **RF-08**: Una unica fabrica, `build_secrets_client(settings)`, crea el cliente de Secrets Manager. El resto del codigo solo llama `get_secret(secret_id)` y no distingue entornos.
- **RF-09**: Entorno local (`APP_ENV=local`). El cliente se inicializa con los parametros de LocalStack:

| Parametro del cliente | Origen | Ejemplo local |
| --- | --- | --- |
| `endpoint_url` | `AWS_ENDPOINT_URL` | `http://localhost:4566` o `http://localstack:4566` en compose |
| `region_name` | `AWS_DEFAULT_REGION` | `us-east-1` |
| `aws_access_key_id` | `AWS_ACCESS_KEY_ID` | `test` |
| `aws_secret_access_key` | `AWS_SECRET_ACCESS_KEY` | `test` |

- **RF-10**: Entorno productivo (`APP_ENV=prod`). El cliente se inicializa con `boto3.client("secretsmanager")` y **sin** `endpoint_url`, `aws_access_key_id` ni `aws_secret_access_key`. La region y las credenciales las resuelve el SDK por su cadena por defecto (rol de la tarea o de la instancia, `AWS_REGION`).
- **RF-11**: Cualquier otro valor de `APP_ENV` aborta el arranque. No hay un tercer modo que mezcle endpoint de LocalStack con credenciales productivas.
- **RF-12**: Al arranque se leen, una sola vez, los secretos de los proveedores habilitados. No se consulta Secrets Manager durante una busqueda: esa llamada no entra en el presupuesto de 2 s.
- **RF-13**: Forma del secreto, en JSON:
  - `api_key`: `{"api_key": "..."}`.
  - `basic`: `{"username": "...", "password": "..."}`.
  Un JSON sin las claves esperadas se trata como secreto invalido (RF-04).
- **RF-14**: Se agrega `boto3` con version fijada en `pyproject.toml` y `uv.lock`. El cliente se crea una vez y se reutiliza.
- **RF-15**: En productivo la identidad de ejecucion tiene `secretsmanager:GetSecretValue` solo sobre los secretos referenciados. Un `AccessDenied` aborta el arranque con el `secret_id`, sin el cuerpo de la respuesta de AWS si este pudiera incluir datos sensibles.

## Requisitos no funcionales aplicables

- **RNF-01**: Carga de configuracion en tiempo lineal sobre el numero de proveedores; probada con 1000 entradas sinteticas.
- **RNF-02**: La configuracion cargada, secretos incluidos, es inmutable durante la ejecucion de una consulta.
- **RNF-03**: Los valores resueltos no se escriben en logs, trazas ni mensajes de error (HU-S04).

## Criterios de aceptacion

```gherkin
Escenario: Agregar proveedor sin tocar el orquestador
  Dado un adaptador existente
  Cuando agrego una nueva entrada habilitada en providers.toml
  Entonces el proveedor se consulta en la siguiente ejecucion sin cambios de codigo

Escenario: Timeout invalido
  Dado un proveedor con timeout_s = 5
  Cuando la aplicacion arranca
  Entonces falla la validacion indicando que el maximo es 2.0

Escenario: Secreto faltante
  Dado el proveedor A habilitado y sin el secreto provider/a en Secrets Manager
  Cuando la aplicacion arranca
  Entonces falla indicando el proveedor y el secret_id, sin mostrar valores

Escenario: Cliente local contra LocalStack
  Dado APP_ENV=local y AWS_ENDPOINT_URL=http://localstack:4566
  Cuando se construye el cliente
  Entonces la llamada usa ese endpoint, la region y las credenciales de prueba

Escenario: Cliente productivo sin parametros de LocalStack
  Dado APP_ENV=prod
  Cuando se construye el cliente
  Entonces no recibe endpoint_url ni access key ni secret key
  Y resuelve la credencial por el rol de la tarea o de la instancia
```

## Casos borde y manejo de errores

- Archivo inexistente o mal formado: error de arranque con ruta y linea.
- Todos los proveedores deshabilitados: la aplicacion arranca y la consulta devuelve resultados vacios con advertencia en log. No se contacta Secrets Manager.
- LocalStack caido o inalcanzable en local: el arranque falla con el endpoint configurado y sin reintentos infinitos.
- Rotacion de un secreto en AWS: el proceso sigue con el valor cargado al arranque hasta el reinicio (ligado a P-03).

## Decisiones de complejidad algoritmica (requieren aprobacion manual)

No aplica.

## Preguntas abiertas

- [ ] P-01: Formato: TOML (soportado en la libreria estandar con `tomllib`) o YAML (dependencia extra). Propuesta: TOML.
- [ ] P-02: Para 1000+ proveedores, la configuracion seguira en archivo o migrara a base de datos o servicio de configuracion?
- [ ] P-03: Se requiere recarga en caliente de configuracion o basta con reinicio?
- [ ] P-04: Libreria de validacion: `pydantic`/`pydantic-settings` o `dataclasses` con validacion propia?

## Historial de revision

| Version | Fecha | Cambios | Revisor |
| --- | --- | --- | --- |
| 0.1 | 2026-10-20 | Borrador inicial, entra a loop de revision | - |
| 0.2 | 2026-10-20 | Iteracion 1: credenciales en AWS Secrets Manager. Cliente con endpoint y claves de prueba en local (LocalStack) y sin esos parametros en productivo | Usuario |
