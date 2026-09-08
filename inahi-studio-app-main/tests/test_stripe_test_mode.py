import os
import gc
import tempfile
import unittest
from unittest.mock import patch


# A regression in startup must fail discovery, never touch DATABASE_PATH.
with patch("sqlite3.connect", side_effect=AssertionError("DB access during test discovery")), \
     patch("os.makedirs", side_effect=AssertionError("Directory creation during test discovery")):
    import app as inahi


class FakeCheckoutSession:
    @staticmethod
    def retrieve(_session_id):
        return {
            "status": "complete",
            "client_reference_id": "1",
            "metadata": {"plan_key": "crecimiento"},
            "customer": "cus_test_1",
            "subscription": "sub_test_1",
        }


class FakeStripe:
    class checkout:
        Session = FakeCheckoutSession


class StripeTestModeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.addCleanup(gc.collect)
        environment = patch.dict(os.environ, {
            "STRIPE_MODE": "test", "STRIPE_PRICE_CRECIMIENTO": "price_test_crecimiento",
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        database = patch.object(inahi, "DB", os.path.join(temporary.name, "test.db"))
        database.start()
        self.addCleanup(database.stop)
        directory = patch.object(inahi, "DB_DIR", temporary.name)
        directory.start()
        self.addCleanup(directory.stop)
        network = patch("socket.socket.connect", side_effect=OSError("Network disabled in tests"))
        network.start()
        self.addCleanup(network.stop)
        configuration = patch.dict(inahi.app.config, TESTING=True, SECRET_KEY="test-secret")
        configuration.start()
        self.addCleanup(configuration.stop)
        inahi.inicializar_base_datos()
        self.client = inahi.app.test_client()

    def test_live_secret_is_rejected_in_test_mode(self):
        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "sk_live_forbidden"}):
            self.assertIsNone(inahi.stripe_cliente())

    def test_live_payments_require_legal_approval_and_explicit_switch(self):
        variables = {
            "STRIPE_MODE": "live", "STRIPE_SECRET_KEY": "sk_live_example",
            "LEGAL_BUSINESS_NAME": "Empresa", "LEGAL_TAX_ID": "B12345678",
            "LEGAL_ADDRESS": "Calle de prueba", "ALLOW_LIVE_PAYMENTS": "true",
            "LEGAL_TERMS_APPROVED": "false",
        }
        with patch.dict(os.environ, variables, clear=False):
            self.assertIsNone(inahi.stripe_cliente())

    def test_registration_verifies_email_before_checkout(self):
        with self.client as client, patch.object(inahi, "stripe_cliente", return_value=FakeStripe()), patch.object(inahi, "email_verificar_cuenta", return_value=True):
            client.get("/cliente/registro?plan=crecimiento")
            with client.session_transaction() as session:
                csrf = session["csrf_token"]
            response = client.post(
                "/cliente/registro",
                data={
                    "csrf_token": csrf,
                    "nombre": "Negocio de prueba",
                    "correo": "prueba@example.com",
                    "plan": "crecimiento",
                    "contrasena": "segura123",
                    "repetida": "segura123",
                    "acepta_legal": "si",
                },
            )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/cliente/acceso"))
        with inahi.conectar() as connection:
            customer = connection.execute("SELECT id,activo,subscription_status,email_verificado FROM clientes").fetchone()
            verification = connection.execute("SELECT token FROM email_verifications WHERE cliente_id=?", (customer["id"],)).fetchone()
        self.assertEqual(customer["activo"], 0)
        self.assertEqual(customer["email_verificado"], 0)
        self.assertEqual(customer["subscription_status"], "verificacion_pendiente")
        with self.client as client, patch.object(inahi, "stripe_cliente", return_value=FakeStripe()):
            response = client.get(f"/cliente/verificar-email/{verification['token']}")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/pago/crecimiento"))
        with inahi.conectar() as connection:
            customer = connection.execute("SELECT activo,subscription_status,email_verificado FROM clientes").fetchone()
        self.assertEqual(customer["email_verificado"], 1)
        self.assertEqual(customer["subscription_status"], "pendiente")

    def test_successful_test_checkout_activates_the_customer(self):
        with inahi.conectar() as connection:
            connection.execute(
                """INSERT INTO clientes
                   (id,nombre,correo,contrasena,plan,activo,plan_key,subscription_status)
                   VALUES(1,'Negocio','pago@example.com','hash','Plan Crecimiento',0,'crecimiento','pendiente')"""
            )
        with self.client as client, patch.object(inahi, "stripe_cliente", return_value=FakeStripe()):
            with client.session_transaction() as session:
                session["cliente_id"] = 1
            response = client.get("/pago/correcto?session_id=cs_test_1")
        self.assertEqual(response.status_code, 200)
        with inahi.conectar() as connection:
            customer = connection.execute(
                "SELECT activo,subscription_status,stripe_customer_id,stripe_subscription_id FROM clientes WHERE id=1"
            ).fetchone()
        self.assertEqual(customer["activo"], 1)
        self.assertEqual(customer["subscription_status"], "activa")
        self.assertEqual(customer["stripe_customer_id"], "cus_test_1")
        self.assertEqual(customer["stripe_subscription_id"], "sub_test_1")

    def test_strategy_generator_adapts_to_a_hairdresser(self):
        strategy = inahi.generar_estrategia_comercial({
            "nombre_negocio": "Peluquería Tania",
            "sector": "peluqueria_estetica",
            "actividad": "peluquería",
            "conversion": "cita",
            "ubicacion": "Burlada",
            "oferta": "corte y color",
            "cliente_ideal": "mujeres de 25 a 55 años",
            "objetivo": "aumentar_reservas",
            "meta": "15 reservas nuevas al mes",
            "canales": ["Google Business", "Instagram"],
            "presupuesto": "hasta_100",
            "tiempo": "2_4",
            "fortaleza": "trato cercano",
            "problema": "pocas reservas entre semana",
        })
        self.assertIn("Peluquería Tania", strategy["titulo"])
        self.assertIn("aumentar las reservas", strategy["resumen"])
        self.assertTrue(any("reseñas" in action.lower() for action in strategy["prioridades"]))
        self.assertEqual(len(strategy["plan_30"]), 4)
        self.assertEqual(len(strategy["plan_60"]), 4)
        self.assertEqual(len(strategy["plan_90"]), 4)
        self.assertNotIn("un peluquería", strategy["resumen"])
        self.assertIn("Plan para peluquería", strategy["resumen"])

    def test_promotion_response_contains_ready_to_use_copy(self):
        response = inahi.generar_respuesta_automatica(
            "Promoción para el martes",
            "Necesito llenar las horas libres sin bajar demasiado el precio.",
            {"datos": {
                "oferta": "corte y color",
                "cliente_ideal": "mujeres de 25 a 55 años",
                "ubicacion": "Burlada",
            }},
        )
        for section in ("NOMBRE DE LA PROMOCIÓN", "TEXTO PARA INSTAGRAM", "TEXTO PARA WHATSAPP", "DURACIÓN RECOMENDADA", "CONDICIONES", "LLAMADA A LA ACCIÓN"):
            self.assertIn(section, response["respuesta"])

    def test_customer_can_generate_and_save_strategy(self):
        with inahi.conectar() as connection:
            connection.execute(
                """INSERT INTO clientes
                   (id,nombre,correo,contrasena,plan,activo,plan_key,subscription_status)
                   VALUES(1,'Comercio Demo','estrategia@example.com','hash','Plan Crecimiento',1,'crecimiento','activa')"""
            )
        with self.client as client:
            with client.session_transaction() as session:
                session["cliente_id"] = 1
                session["csrf_token"] = "csrf-strategy"
            response = client.post(
                "/cliente/estrategia",
                data={
                    "csrf_token": "csrf-strategy",
                    "sector": "comercio",
                    "actividad": "boutique de moda",
                    "conversion": "compra",
                    "ubicacion": "Pamplona",
                    "oferta": "ropa y complementos",
                    "cliente_ideal": "mujeres de 30 a 55 años",
                    "objetivo": "aumentar_ventas",
                    "meta": "10 ventas nuevas al mes",
                    "canales": ["Google Business", "Instagram"],
                    "presupuesto": "sin_presupuesto",
                    "tiempo": "2_4",
                    "fortaleza": "atención personalizada",
                    "problema": "pocas visitas entre semana",
                },
            )
            strategy_page = client.get("/cliente/estrategia")
            portal_page = client.get("/portal")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/cliente/estrategia"))
        self.assertEqual(strategy_page.status_code, 200)
        self.assertIn("Estrategia comercial para Comercio Demo", strategy_page.get_data(as_text=True))
        self.assertEqual(portal_page.status_code, 200)
        self.assertIn("Estrategia comercial", portal_page.get_data(as_text=True))
        with inahi.conectar() as connection:
            saved = connection.execute(
                "SELECT respuestas,estrategia FROM estrategias_comerciales WHERE cliente_id=1"
            ).fetchone()
        self.assertIsNotNone(saved)
        self.assertIn("Pamplona", saved["respuestas"])
        self.assertIn("plan_90", saved["estrategia"])

    def _create_active_customer_with_strategy(self, plan_key="crecimiento"):
        plan = inahi.PLANES_INFO[plan_key]
        with inahi.conectar() as connection:
            connection.execute(
                """INSERT INTO clientes
                   (id,nombre,correo,contrasena,plan,activo,plan_key,subscription_status)
                   VALUES(1,'Peluquería Demo','demo@example.com','hash',?,1,?,'activa')""",
                (f"Plan {plan['nombre']}", plan_key),
            )
            connection.execute(
                """INSERT INTO estrategias_comerciales(cliente_id,respuestas,estrategia,actualizado)
                   VALUES(1,?,?,?)""",
                ('{"sector":"peluqueria_estetica","actividad":"peluquería","conversion":"cita","oferta":"corte y color","objetivo":"aumentar_reservas","ubicacion":"Burlada","cliente_ideal":"mujeres de Burlada","fortaleza":"trato cercano"}',
                 '{"resumen":"Aumentar reservas"}', "2026-09-02T10:00:00"),
            )

    def test_commercial_assistant_answers_immediately(self):
        self._create_active_customer_with_strategy()
        with self.client as client:
            with client.session_transaction() as session:
                session["cliente_id"] = 1
                session["csrf_token"] = "csrf-assistant"
            response = client.post("/cliente/solicitud", data={
                "csrf_token": "csrf-assistant", "asunto": "Promoción de color",
                "descripcion": "Quiero llenar las horas libres del martes con una oferta.",
            })
        self.assertEqual(response.status_code, 302)
        with inahi.conectar() as connection:
            saved = connection.execute("SELECT estado,respuesta FROM solicitudes WHERE cliente_id=1").fetchone()
        self.assertEqual(saved["estado"], "Respondida automáticamente")
        self.assertIn("Qué medir", saved["respuesta"])

    def test_commercial_assistant_prefers_ai_when_available(self):
        self._create_active_customer_with_strategy()
        with self.client as client, patch.object(inahi, "asesor_comercial_ia", return_value="Respuesta real de IA"):
            with client.session_transaction() as session:
                session["cliente_id"] = 1
                session["csrf_token"] = "csrf-ai"
            response = client.post("/cliente/solicitud", data={
                "csrf_token": "csrf-ai", "asunto": "Captar clientes",
                "descripcion": "Necesito un plan concreto para esta semana.",
            })
        self.assertEqual(response.status_code, 302)
        with inahi.conectar() as connection:
            saved = connection.execute("SELECT estado,respuesta,origen_respuesta FROM solicitudes WHERE cliente_id=1").fetchone()
        self.assertEqual(saved["estado"], "Respondida con IA")
        self.assertEqual(saved["origen_respuesta"], "ia")
        self.assertEqual(saved["respuesta"], "Respuesta real de IA")

    def test_only_first_five_verified_companies_receive_free_trial(self):
        expires = "2099-01-01T00:00:00+00:00"
        with inahi.conectar() as connection:
            for customer_id in range(1, 7):
                connection.execute(
                    """INSERT INTO clientes
                       (id,nombre,correo,contrasena,plan,activo,plan_key,subscription_status,email_verificado)
                       VALUES(?,?,?,?,?,0,'crecimiento','verificacion_pendiente',0)""",
                    (customer_id, f"Negocio {customer_id}", f"negocio{customer_id}@example.com", "hash", "Plan Crecimiento"),
                )
                connection.execute(
                    "INSERT INTO email_verifications(token,cliente_id,expira) VALUES(?,?,?)",
                    (f"token-{customer_id}", customer_id, expires),
                )

        with patch.object(inahi, "stripe_cliente", return_value=None):
            responses = [self.client.get(f"/cliente/verificar-email/token-{customer_id}") for customer_id in range(1, 7)]

        self.assertTrue(all(response.status_code == 302 for response in responses))
        with inahi.conectar() as connection:
            trials = connection.execute(
                "SELECT COUNT(*) FROM clientes WHERE trial_slot=1 AND subscription_status='prueba' AND activo=1"
            ).fetchone()[0]
            waiting = connection.execute(
                "SELECT activo,subscription_status,trial_slot FROM clientes WHERE id=6"
            ).fetchone()
        self.assertEqual(trials, 5)
        self.assertEqual(dict(waiting), {"activo": 0, "subscription_status": "lista_espera", "trial_slot": 0})

    def test_campaign_cleanup_is_disabled_and_preserves_accounts(self):
        with inahi.conectar() as connection:
            connection.execute(
                """INSERT INTO clientes
                   (id,nombre,correo,contrasena,plan,activo,plan_key,subscription_status)
                   VALUES(1,'Cuenta antigua','antigua@example.com','hash','Plan Crecimiento',1,'crecimiento','prueba')"""
            )
            connection.execute(
                "INSERT INTO solicitudes(cliente_id,asunto,descripcion) VALUES(1,'Antigua','Borrar')"
            )

        with self.assertRaises(RuntimeError):
            inahi.limpiar_cuentas_anteriores_a_campana()
        with inahi.conectar() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM solicitudes").fetchone()[0], 1)

    def test_trial_customer_is_blocked_after_ten_total_queries(self):
        with inahi.conectar() as connection:
            connection.execute(
                """INSERT INTO clientes
                   (id,nombre,correo,contrasena,plan,activo,plan_key,subscription_status,
                    trial_end,trial_slot,trial_queries_used)
                   VALUES(1,'Prueba','prueba@example.com','hash','Plan Crecimiento',1,
                          'crecimiento','prueba','2099-01-01',1,9)"""
            )
        with self.client as client, patch.object(inahi, "asesor_comercial_ia", return_value="Respuesta de prueba"):
            with client.session_transaction() as session:
                session["cliente_id"] = 1
                session["csrf_token"] = "csrf-trial"
            first = client.post("/cliente/solicitud", data={
                "csrf_token": "csrf-trial", "asunto": "Consulta diez", "descripcion": "Última consulta disponible",
            })
            second = client.post("/cliente/solicitud", data={
                "csrf_token": "csrf-trial", "asunto": "Consulta once", "descripcion": "Debe quedar bloqueada",
            })

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        with inahi.conectar() as connection:
            customer = connection.execute("SELECT trial_queries_used FROM clientes WHERE id=1").fetchone()
            queries = connection.execute("SELECT COUNT(*) FROM solicitudes WHERE cliente_id=1").fetchone()[0]
        self.assertEqual(customer["trial_queries_used"], 10)
        self.assertEqual(queries, 1)

    def test_content_calendar_uses_exact_plan_quota(self):
        self._create_active_customer_with_strategy("crecimiento")
        with self.client as client:
            with client.session_transaction() as session:
                session["cliente_id"] = 1
            response = client.get("/cliente/contenidos")
        self.assertEqual(response.status_code, 200)
        with inahi.conectar() as connection:
            saved = connection.execute("SELECT contenido FROM calendarios_contenido WHERE cliente_id=1").fetchone()
        import json
        contents = json.loads(saved["contenido"])["contenidos"]
        self.assertEqual(len(contents), 16)
        self.assertEqual(len({item["idea"] for item in contents}), 16)
        self.assertFalse(any("que comete Mujeres" in item["idea"] for item in contents))
        self.assertTrue(all(item["texto_instagram"] and item["texto_facebook"] and item["texto_whatsapp"] for item in contents))

    def test_bakery_uses_orders_instead_of_appointments(self):
        bakery = {
            "sector": "comercio", "actividad": "pastelería artesanal", "conversion": "encargo",
            "oferta": "tartas personalizadas", "cliente_ideal": "familias de Pamplona",
            "ubicacion": "Pamplona", "fortaleza": "elaboración artesanal",
        }
        response = inahi.generar_respuesta_automatica("Promoción", "Quiero vender más", {"datos": bakery})
        self.assertIn("QUIERO ENCARGAR", response["respuesta"])
        self.assertNotIn("QUIERO MI CITA", response["respuesta"])
        calendar = inahi.generar_calendario_contenidos(bakery, 16, "2026-09")
        rendered = " ".join(item["idea"] + " " + item["cta"] for item in calendar["contenidos"])
        self.assertIn("Haz tu encargo", rendered)
        self.assertNotIn("Reserva tu cita", rendered)
        self.assertEqual(calendar["version"], 2)

    def test_essential_plan_cannot_request_a_meeting(self):
        self._create_active_customer_with_strategy("esencial")
        with self.client as client:
            with client.session_transaction() as session:
                session["cliente_id"] = 1
            response = client.get("/cliente/solicitar-cita")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/portal"))

    def test_password_recovery_creates_token_and_sends_email(self):
        with inahi.conectar() as connection:
            connection.execute(
                """INSERT INTO clientes
                   (id,nombre,correo,contrasena,plan,activo,plan_key,subscription_status)
                   VALUES(1,'Pastelería','pasteleria@example.com','hash','Plan Crecimiento',1,'crecimiento','prueba')"""
            )
        with self.client as client, patch.object(inahi, "enviar_email", return_value=True) as send:
            client.get("/cliente/recuperar-contrasena")
            with client.session_transaction() as session:
                csrf = session["csrf_token"]
            response = client.post("/cliente/recuperar-contrasena", data={"csrf_token": csrf, "correo": "pasteleria@example.com"})
        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        with inahi.conectar() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM password_resets WHERE cliente_id=1").fetchone()[0], 1)

    def test_smtp_email_is_built_logged_in_and_sent(self):
        variables = {
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "inahistudio@gmail.com",
            "SMTP_PASSWORD": "app-password",
            "SMTP_FROM": "inahistudio@gmail.com",
        }
        with patch.dict(os.environ, variables), patch.object(inahi.smtplib, "SMTP") as smtp:
            servidor = smtp.return_value.__enter__.return_value
            enviado = inahi.enviar_email(
                "cliente@example.com", "Prueba", "Mensaje", "<p>Mensaje</p>"
            )

        self.assertTrue(enviado)
        smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=15)
        servidor.starttls.assert_called_once()
        servidor.login.assert_called_once_with("inahistudio@gmail.com", "app-password")
        servidor.send_message.assert_called_once()

    def test_resend_https_api_is_preferred(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_args): return False

        variables = {
            "RESEND_API_KEY": "re_test",
            "RESEND_FROM": "Inahi Studio <notificaciones@send.inahistudio.com>",
        }
        with patch.dict(os.environ, variables), patch.object(inahi, "urlopen", return_value=Response()) as send:
            enviado = inahi.enviar_email("cliente@example.com", "Prueba", "Mensaje", "<p>Mensaje</p>")

        self.assertTrue(enviado)
        peticion = send.call_args.args[0]
        self.assertEqual(peticion.full_url, "https://api.resend.com/emails")
        self.assertIn(b"notificaciones@send.inahistudio.com", peticion.data)
        self.assertEqual(
            peticion.get_header("User-agent"),
            "InahiStudio/1.0 (+https://app.inahistudio.com)",
        )
        self.assertEqual(peticion.get_header("Accept"), "application/json")

    def test_public_consultation_builds_and_sends_html_email(self):
        with self.client as client, patch.object(inahi, "enviar_email", return_value=True) as send:
            client.get("/")
            with client.session_transaction() as session:
                csrf = session["csrf_token"]
            response = client.post("/", data={
                "csrf_token": csrf, "empresa": "Prueba correo Inahi Studio",
                "correo": "inahistudio@gmail.com", "problema": "Comprobación del envío automático",
            })
        self.assertEqual(response.status_code, 302)
        send.assert_called_once()
        args = send.call_args.args
        self.assertEqual(args[0], "inahistudio@gmail.com")
        self.assertIn("<a href=", args[3])

    def test_meeting_request_notifies_the_team(self):
        self._create_active_customer_with_strategy("crecimiento")
        future = (inahi.date.today() + inahi.timedelta(days=2)).isoformat()
        with self.client as client, patch.object(inahi, "notificar_equipo", return_value=True) as notify:
            with client.session_transaction() as session:
                session["cliente_id"] = 1
                session["csrf_token"] = "csrf-meeting"
            response = client.post("/cliente/solicitar-cita", data={
                "csrf_token": "csrf-meeting", "fecha": future, "hora": "10:00",
                "modalidad": "Online", "motivo": "Revisar estrategia",
            })
        self.assertEqual(response.status_code, 302)
        notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
