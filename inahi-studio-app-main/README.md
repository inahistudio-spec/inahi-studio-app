# Inahistudio — producto por suscripción

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
python3 app.py
```
