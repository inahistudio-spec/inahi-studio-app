"""New SaaS views: real temporary data, original tests untouched, no remote services."""
import os
from unittest.mock import patch
import pytest
import app as inahi
from test_saas_core import SaaSFixture
from persistence.migrations import migrate
from billing.repository import provision


class WorkspaceTests(SaaSFixture):
    def setUp(self):
        super().setUp()
        migrate(self.path.parent / "workspace.json", str(self.path), copilot=True)
        with self.db() as c:
            provision(c, 1, "STARTER", "active")
            provision(c, 2, "BUSINESS", "active")
        self.login()

    def test_valid_saas_login_redirects_to_new_dashboard(self):
        client = inahi.app.test_client()
        client.get("/cliente/acceso")
        response = self.post("/cliente/acceso", {"correo": "a@example.com", "contrasena": self.password}, client)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/saas/dashboard"))

    def test_all_sidebar_views_render_new_shell(self):
        for path in ("dashboard", "clientes", "diagnosticos", "estrategias", "contenido", "informes", "automatizaciones", "copilot", "equipo", "facturacion", "configuracion"):
            response = self.client.get("/saas/" + path)
            self.assertEqual(response.status_code, 200, (path, response.get_data(as_text=True)))
            html = response.get_data(as_text=True)
            self.assertIn("workspace.css", html)
            self.assertIn('id="sidebar"', html)
            self.assertIn("Empresa A", html)
            self.assertNotIn("Empresa B", html)
            self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_dashboard_counts_only_own_resources(self):
        with self.db() as c:
            for _ in range(5):
                c.execute("INSERT INTO informes(cliente_id,organization_id,titulo,contenido) VALUES(2,2,'Foreign title','Foreign content')")
        html = self.client.get("/saas/dashboard").get_data(as_text=True)
        self.assertIn('class="stat-number">1</strong>', html)
        self.assertNotIn("Foreign title", html)
        self.assertNotIn("Consulta B", html)

    def test_resource_views_and_manipulated_id_remain_isolated(self):
        for path, marker in (("informes", "Secret"), ("diagnosticos", "Goal"), ("automatizaciones", "Private")):
            self.assertEqual(self.client.get(f"/saas/{path}/2").status_code, 404)
            response = self.client.get(f"/saas/{path}/1")
            self.assertEqual(response.status_code, 200)
            self.assertIn(marker + " A", response.get_data(as_text=True))
            self.assertNotIn(marker + " B", response.get_data(as_text=True))

    def test_all_collection_details_require_own_organization(self):
        for path in ("diagnosticos", "estrategias", "contenido", "informes", "automatizaciones"):
            self.assertEqual(self.client.get(f"/saas/{path}/2").status_code, 404)
            self.assertEqual(self.client.get(f"/saas/{path}/1").status_code, 200)

    def test_query_scope_overrides_rejected_on_every_view(self):
        for path in ("dashboard", "clientes", "diagnosticos", "estrategias", "contenido", "informes", "automatizaciones", "equipo", "facturacion", "configuracion"):
            self.assertEqual(self.client.get(f"/saas/{path}?organization_id=2").status_code, 400)

    def test_unauthenticated_view_redirects_to_login(self):
        response = inahi.app.test_client().get("/saas/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/cliente/acceso"))

    def test_forged_session_membership_is_rejected(self):
        with self.client.session_transaction() as session:
            session["organization_id"] = 2
        self.assertEqual(self.client.get("/saas/dashboard").status_code, 404)

    def test_viewer_can_read_resources_but_not_billing(self):
        _, _, client = self.member("viewer")
        self.assertEqual(client.get("/saas/dashboard").status_code, 200)
        self.assertEqual(client.get("/saas/informes/1").status_code, 200)
        self.assertEqual(client.get("/saas/facturacion").status_code, 403)
        self.assertNotIn("Abrir herramientas existentes", client.get("/saas/contenido").get_data(as_text=True))

    def test_manager_billing_denied_and_admin_billing_allowed(self):
        # Owner plus these three roles need four seats in this test fixture.
        os.environ["B2B_LIMIT_STARTER_MEMBERS"] = "4"
        for role, status in (("manager", 403), ("member", 403), ("admin", 200)):
            _, _, client = self.member(role)
            self.assertEqual(client.get("/saas/facturacion").status_code, status)

    def test_team_does_not_include_foreign_members(self):
        html = self.client.get("/saas/equipo").get_data(as_text=True)
        self.assertIn("a@example.com", html)
        self.assertNotIn("b@example.com", html)
        for role in ("owner", "admin", "manager", "member", "viewer"):
            self.assertIn(role, html)

    def test_clients_screen_does_not_invent_crm_contacts(self):
        html = self.client.get("/saas/clientes").get_data(as_text=True)
        self.assertIn("Sin contactos registrados", html)
        self.assertNotIn("b@example.com", html)
        self.assertNotIn("Empresa B", html)

    def test_get_views_do_not_mutate_legacy_data_or_call_providers(self):
        with patch("copilot.providers.get_provider", side_effect=AssertionError("No AI calls")), patch("billing.gateway.Gateway", side_effect=AssertionError("No Stripe calls")):
            for path in ("dashboard", "clientes", "diagnosticos", "estrategias", "contenido", "informes", "automatizaciones", "copilot", "equipo", "facturacion", "configuracion"):
                self.assertEqual(self.client.get("/saas/" + path).status_code, 200)
        self.assertEqual(self.before, self.legacy_snapshot())

    def test_unpaid_business_views_enforce_entitlements(self):
        with self.db() as c:
            c.execute("UPDATE organization_subscriptions SET status='past_due' WHERE organization_id=1")
        self.assertEqual(self.client.get("/saas/informes").status_code, 402)
        html = self.client.get("/saas/dashboard").get_data(as_text=True)
        self.assertNotIn("Consulta A", html)
        self.assertIn("necesita atención", html)
        self.assertEqual(self.client.get("/saas/facturacion").status_code, 200)

    def test_stored_html_is_escaped_in_new_views(self):
        with self.db() as c:
            c.execute("UPDATE informes SET contenido='<script>alert(1)</script>' WHERE organization_id=1")
        html = self.client.get("/saas/informes/1").get_data(as_text=True)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)

    def test_new_view_post_cannot_mutate_resources(self):
        response = self.post("/saas/informes/1", {"titulo": "Overwrite"})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.before, self.legacy_snapshot())

    def test_copilot_is_integrated_without_browser_persistent_history(self):
        html = self.client.get("/saas/copilot").get_data(as_text=True)
        for marker in ("assistant-composer", "copilot-history", 'name="csrf_token"', "aria-live"):
            self.assertIn(marker, html)
        from pathlib import Path
        script = (Path(inahi.__file__).parent / "static" / "copilot.js").read_text(encoding="utf-8")
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        self.assertIn("pagehide", script)

    def test_public_landing_and_legacy_portal_still_render(self):
        self.assertEqual(self.client.get("/portal").status_code, 200)
        public = inahi.app.test_client().get("/")
        self.assertEqual(public.status_code, 200)
        self.assertNotIn("workspace.css", public.get_data(as_text=True))

    def test_unassociated_billing_does_not_claim_unlimited_capacity(self):
        with self.db() as c:
            c.execute("DELETE FROM organization_subscriptions WHERE organization_id=1")
        response = self.client.get("/saas/facturacion")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Consumo y límites no disponibles", html)
        self.assertNotIn("/ sin límite", html)
