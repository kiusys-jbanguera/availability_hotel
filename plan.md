Consttitucion

Este un API tipo REST, pensada para consultar mutliples proveedores, hotleror, los cuales expondran disponibilidad y tarifas de de habitaciones. La integracion inicial contemplara 3 proveedores que se describiran en HU, de los cuales se espera ampliar hasta 1000 o mas en caso de ser requerido, la respuesta despues de consultar los proveedores se dara con todos aquellos que respondieron en 2s.



Objetivo
Consultar la disponibilidad y tarifas hoteleras de diferentes proveedores y entregar una respuesta estandarizada.


Requisistos:

- No funcionales
    - SetUp:
        - Docker python 3.15.0 bookworm slim
        - Gestor uv
        - niquests 3.21.2
        - fastapi==0.153.0
        - uvicorn[standard]==0.54.0
        - pydantic==2.14.1
    
    - Arquitectura:
        - MVC
    - No negociables
        - Toda sugerencia de codigo debe de cumplir el DRY(Don't repeat yourself)
        - Las sugerencias de codigo deben de cumplir con el estandar PEP8
        - El codigo debe de estar correctamente formateado en el default de black
        - Las decisiones de complejidad algortimica deben de pasar por validaciones e iteracion de consulta y aprobacion manual

- Funcionales
    - Fase 1 expone una API HTTP construida con FastAPI como punto de entrada (ver HU008); niquests se mantiene como cliente saliente hacia los proveedores.
    - Indice de historias de usuario: [docs/hu/README.md](docs/hu/README.md)
        - Setup: HU-S01 a HU-S04
        - Funcionales: HU001 a HU008




Riesgos

- Tiempo de respuesta de los proveedores, al ser diversos y con tiempos de repuesta e implementacion variados, pueden tener tiempos de respuesta diferenetes, es por eso que se debe de estandarizar el tiempo de respuesta a 2s por proveedor.

- El aumento de proveedores es un aumento directamentamen proporcional en el tiempo de ejecucion, por lo cual debe de contemplarse el paralelismo en el llamado de los clientes.

- La gestion de de cada proveedor implica el seguimiento de cada uno por medio de logs ademas de poder responder correctamente sin generar afectacion de del sistemea en generla, agregando robustes a la solucion.

- Los proveedores manejan diferentes tipos de autenticacion y schemas de respuestas, por lo cual la solucion debe de palntearse de forma tal que contemple estas variaciones.

- Las consultas a los proveedores contempla rate limit, por lo cual debe de ser configurarble y opcional el limite de peticiones que se pueden lanzar a proveedores, el criterio del rate limiti puede variar por proveedor.

- Proveedor B (p95 3 s, picos 8 s) quedara excluido de la respuesta en la mayoria de consultas por el corte de 2 s. Se acepta la exclusion y se monitorea (ver HU006).
