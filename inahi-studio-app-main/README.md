Fase 6: [CRM comercial, seguimiento y Copilot contextual](docs/CRM_PHASE_6.md).

# Inahistudio — producto por suscripción

Fase 3: [billing por organización, planes, límites y migración explícita](docs/BILLING_PHASE_3.md).
La integración B2B admite únicamente Stripe test mode; conserva el flujo legacy
para cuentas no asociadas y no ejecuta migraciones al arrancar.

Fase 2: [persistencia PostgreSQL, migraciones y rollback](docs/POSTGRESQL_PHASE_2.md).
`DATABASE_URL` selecciona el motor; SQLite y `DATABASE_PATH` siguen disponibles.
Las migraciones son explícitas, con informe previo, y no se ejecutan al importar
ni arrancar la aplicación. PostgreSQL está preparado para ensayo; no se ha
migrado producción.

Aplicación Flask para ofrecer a pequeños negocios un sistema comercial automatizado mediante suscripción mensual.

## Funciones comerciales

- Planes Esencial (29 €), Crecimiento (59 €) y Pro (99 €) al mes.
- Registro con verificación de correo antes de activar la prueba o abrir Stripe Checkout.
- Activación y suspensión automática mediante webhook.
- Portal de Stripe para facturas, cambios y cancelaciones.
- Diagnóstico digital autoservicio con puntuación y prioridades.
- Estrategia comercial personalizada y actualizable con plan de 30, 60 y 90 días.
- Recomendaciones adaptadas por sector, objetivo, canales, presupuesto y tiempo disponible.
- Asistente comercial con IA basada en la estrategia guardada y respuesta automática de respaldo.
- Límites por plan, protección antiabuso y formularios con trampa antispam.
- Calendario mensual automático: 8 ideas en Esencial, 16 en Crecimiento y 30 en Pro.
- Informe automático mensual con conversión, ticket medio, alertas y siguientes acciones.
- Consultas automáticas: 10 en Esencial, 30 en Crecimiento e ilimitadas en Pro.
- Reuniones personales: ninguna en Esencial, 1 de 30 minutos en Crecimiento y 2 de 45 minutos en Pro.
- Separación explícita entre la automatización incluida y los servicios de web/redes contratados aparte.
- Recuperación de contraseña mediante enlace de un solo uso.

## Configuración en Railway

Configura estas variables privadas:

```
SECRET_KEY=una-clave-larga-y-aleatoria
ADMIN_PASSWORD_HASH=hash-seguro
PUBLIC_BASE_URL=https://app.inahistudio.com
DATABASE_PATH=/data/consultas.db
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=inahistudio@gmail.com
SMTP_PASSWORD=clave-de-aplicacion
SMTP_FROM=inahistudio@gmail.com
TEAM_NOTIFICATION_EMAIL=inahistudio@gmail.com
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5-mini
STRIPE_MODE=test
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ESENCIAL=price_...
STRIPE_PRICE_CRECIMIENTO=price_...
STRIPE_PRICE_PRO=price_...
LEGAL_BUSINESS_NAME=
LEGAL_TAX_ID=
LEGAL_ADDRESS=
LEGAL_TERMS_APPROVED=false
ALLOW_LIVE_PAYMENTS=false
```

`DATABASE_PATH` debe apuntar a un volumen persistente. En Railway monta un volumen en `/data` y utiliza `DATABASE_PATH=/data/consultas.db`. El panel de administración incluye una pantalla **Estado del sistema** para comprobar almacenamiento, SMTP y avisos al equipo sin mostrar secretos. Sin claves de Stripe, la aplicación mantiene la demostración de 14 días y no realiza ningún cobro. Sin `OPENAI_API_KEY`, el asistente conserva su respuesta automática de respaldo.

## Stripe

1. Activa **Modo de prueba** en Stripe y crea tres productos con precios mensuales: 29 €, 59 € y 99 €.
2. Copia la clave secreta de prueba `sk_test_...` y cada identificador `price_...` en Railway.
3. Crea un webhook de prueba hacia `https://app.inahistudio.com/stripe/webhook` y copia su secreto `whsec_...`.
4. Suscribe estos eventos: `checkout.session.completed`, `customer.subscription.updated` y `customer.subscription.deleted`.
5. Activa el portal de clientes de Stripe.

Esta versión usa `STRIPE_MODE=test` por defecto y rechaza claves `sk_live_...` para evitar cobros reales accidentales. Para probar Checkout utiliza una tarjeta de prueba oficial de Stripe, nunca una tarjeta bancaria real. Los cobros reales solo se habilitan si se completan las variables de identidad `LEGAL_*`, se marca `LEGAL_TERMS_APPROVED=true` tras una revisión profesional, se cambia `STRIPE_MODE=live` y se establece expresamente `ALLOW_LIVE_PAYMENTS=true`.

## Antes de aceptar pagos reales

Completa la identidad fiscal y los textos legales, confirma obligaciones de alta y facturación y realiza una compra completa en modo de prueba.

## Ejecutar localmente

```
python3 -m pip install -r requirements.txt
python3 -m flask --app app init-db
python3 app.py
```

Ejecuta estos comandos desde `inahi-studio-app-main/`. `init-db` es una operación
administrativa explícita sobre `DATABASE_PATH`: crea las tablas y añade columnas
ausentes, incluida la tabla de deduplicación Stripe. No borra clientes ni recalcula
cuentas de prueba. Antes de usarla con una base existente, ensáyala sobre una copia
y conserva un respaldo; no es una migración completa versionada ni atómica.
Importar `app`, consultar `/salud` o arrancar Gunicorn ya no prepara ni transforma
la base de datos. No añadas `init-db` al arranque automático de workers.

La limpieza histórica de campaña está deshabilitada incluso si se llama a su
función directamente. Los clientes existentes y sus cupos no se reinician.

## Tests de estabilización

Con un intérprete y las dependencias ya disponibles, desde el directorio de la app:

```
python -m unittest discover -s tests -v
```

Las pruebas preparan bases temporales explícitamente, no utilizan las credenciales
de proveedores del entorno y bloquean conexiones de red. La suite nueva verifica
imports en subprocesos, conservación de datos, CSRF, firmas Stripe reales locales,
duplicados, concurrencia y rollback. No necesita claves reales ni acceso a Stripe.

La Fase 0.5 fue validada localmente. Consulta
[el informe de estabilización](../docs/STABILIZATION_0_5.md) y
[el núcleo SaaS de Fase 1](../docs/SAAS_PHASE_1.md) para conocer el estado actualizado.

## Núcleo SaaS B2B — Fase 1

La aplicación conserva el modo legacy hasta activar explícitamente la migración
`0001_saas_core`. Sobre una **copia de ensayo** preparada, seleccionada mediante
`DATABASE_PATH`, desde el directorio de la app:

```
python -m flask --app app saas-upgrade
python -m unittest discover -s tests -v
```

El comando añade Organization, User, Membership y propiedad organizacional sin
borrar clientes ni cambiar sus hashes, cupos o suscripciones. Después se requiere
volver a iniciar sesión con las credenciales existentes. No se ejecuta al importar
la app, en Gunicorn ni desde una petición web.

`python -m flask --app app saas-downgrade` permite volver al modo legacy sin borrar
las tablas añadidas, solo mientras no exista actividad SaaS incompatible. No es un
rollback de producción ni cancela operaciones en Stripe. Revisa el procedimiento,
permisos, endpoints y límites en [SAAS_PHASE_1.md](../docs/SAAS_PHASE_1.md).
