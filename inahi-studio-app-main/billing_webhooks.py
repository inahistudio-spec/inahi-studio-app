"""Efectos locales de eventos Stripe ya autenticados por la ruta HTTP."""

from contextlib import closing
from datetime import datetime, timezone


def procesar_evento_stripe(evento, conectar, planes, nombre_plan, plan_por_precio):
    """Confirma evento y cambios juntos; devuelve False para una entrega duplicada.

    No realiza llamadas de red ni crea esquema. BEGIN IMMEDIATE serializa la
    comprobación/actualización entre conexiones SQLite, incluidos otros workers.
    Una excepción revierte tanto el registro del evento como sus efectos.
    """
    event_id = evento.get("id")
    tipo = evento.get("type")
    objeto = (evento.get("data") or {}).get("object")
    if not isinstance(event_id, str) or not event_id or not isinstance(tipo, str) or not tipo:
        raise ValueError("Evento sin identidad o tipo")
    if not isinstance(objeto, dict):
        raise ValueError("Objeto de evento inválido")

    with closing(conectar()) as c, c:
        c.execute("BEGIN IMMEDIATE")
        insertado = c.execute(
            """INSERT INTO stripe_webhook_events(event_id,event_type,processed_at)
               VALUES(?,?,?) ON CONFLICT(event_id) DO NOTHING""",
            (event_id, tipo, datetime.now(timezone.utc).isoformat()),
        )
        if insertado.rowcount == 0:
            return False

        if tipo == "checkout.session.completed":
            metadata = objeto.get("metadata") or {}
            referencia = objeto.get("client_reference_id") or metadata.get("cliente_id")
            plan_key = metadata.get("plan_key", "crecimiento")
            if not referencia or not str(referencia).isascii() or not str(referencia).isdigit() or plan_key not in planes:
                raise ValueError("Referencia o plan inválidos")
            cliente_id = int(referencia)
            if not 0 < cliente_id <= 9223372036854775807:
                raise ValueError("Referencia fuera de rango")
            c.execute(
                """UPDATE clientes SET activo=1,plan_key=?,plan=?,subscription_status='activa',
                   stripe_customer_id=?,stripe_subscription_id=? WHERE id=?""",
                (plan_key, nombre_plan(plan_key), objeto.get("customer", ""),
                 objeto.get("subscription", ""), cliente_id),
            )
        elif tipo in ("customer.subscription.updated", "customer.subscription.deleted"):
            subscription_id = objeto.get("id")
            if not isinstance(subscription_id, str) or not subscription_id:
                raise ValueError("Falta la suscripción; no actualizar identificadores vacíos")
            estado = objeto.get("status", "cancelada")
            activo = 1 if estado in ("active", "trialing") else 0
            items = (objeto.get("items") or {}).get("data", [])
            price_id = items[0].get("price", {}).get("id") if items else None
            plan_key = plan_por_precio(price_id)
            if plan_key:
                c.execute(
                    "UPDATE clientes SET activo=?,subscription_status=?,plan_key=?,plan=? WHERE stripe_subscription_id=?",
                    (activo, estado, plan_key, nombre_plan(plan_key), subscription_id),
                )
            else:
                c.execute(
                    "UPDATE clientes SET activo=?,subscription_status=? WHERE stripe_subscription_id=?",
                    (activo, estado, subscription_id),
                )
    return True
