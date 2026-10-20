#!/bin/sh
# Hook ready.d de LocalStack: crea en Secrets Manager las credenciales de los
# mocks locales (HU-S03 RF-13). Son valores ficticios de desarrollo; los mocks
# solo validan la presencia del header, no su valor. En productivo los
# secretos se gestionan en AWS y nunca en este repositorio.
set -eu

create() {
    awslocal secretsmanager create-secret --name "$1" --secret-string "$2" >/dev/null 2>&1 \
        || awslocal secretsmanager put-secret-value --secret-id "$1" --secret-string "$2" >/dev/null
    echo "secreto listo: $1"
}

create "provider/a" "{\"api_key\": \"local-mock-key-a\"}"
create "provider/b" "{\"username\": \"local-mock-user-b\", \"password\": \"local-mock-pass-b\"}"
create "provider/c" "{\"api_key\": \"local-mock-key-c\"}"
