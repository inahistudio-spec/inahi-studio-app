"""Phase 3: local databases, real signature checks, mocked Stripe; no provider network."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import io
import json
import os
import sqlite3
import time
from unittest.mock import Mock, patch

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

import app as inahi
from test_saas_core import SaaSFixture
from persistence.migrations import migrate, configuration
from persistence.database import make_engine
from billing import service, gateway
from billing.plans import PLANS, METRICS, catalog, price
from billing.repository import provision, subscription, enabled
from billing.entitlements import describe, reserve, require_paid, LimitExceeded
from billing.migration import associate
from billing.webhooks import process, EVENTS
from billing.schema import TABLES


def remote(sid="sub_A", customer="cus_A", status="active", plan="STARTER"):
    return {"id": sid, "customer": customer, "livemode": False, "status": status,
            "current_period_start": 1900000000, "current_period_end": 1902592000,
            "cancel_at_period_end": False, "metadata": {},
            "items": {"data": [{"id": "si_A", "price": {"id": f"price_test_{plan}"}, "quantity": 1}]}}


def event(kind="customer.subscription.updated", eid="evt_test_1", created=200, sid="sub_A", customer="cus_A"):
    obj = {"id": sid if kind.startswith("customer.subscription.") else "cs_test" if kind.startswith("checkout") else "in_test",
           "customer": customer, "subscription": sid, "status": "active"}
    return {"id": eid, "type": kind, "created": created, "livemode": False, "data": {"object": obj}}


class BillingTests(SaaSFixture):
    def setUp(self):
        super().setUp()
        migrate(self.path.parent / "phase3.json", str(self.path), billing=True)
        env = {f"STRIPE_B2B_PRICE_{p}": f"price_test_{p}" for p in PLANS}
        env.update(STRIPE_B2B_WEBHOOK_SECRET="whsec_test_local", B2B_RETURN_URL="http://localhost/return")
        mock = patch.dict(os.environ, env)
        mock.start()
        self.addCleanup(mock.stop)
        with self.db() as c:
            provision(c, 1, "STARTER", "active", "cus_A", "sub_A")
            provision(c, 2, "BUSINESS", "active", "cus_B", "sub_B")
        self.snapshots = {"sub_A": remote(), "sub_B": remote("sub_B", "cus_B", plan="BUSINESS")}
        self.provider = Mock()
        self.provider.retrieve_subscription.side_effect = lambda sid: deepcopy(self.snapshots[sid])
        self.provider.portal.return_value = {"url": "https://billing.stripe.com/p/session_test"}
        self.provider.create_customer.return_value = {"id": "cus_new", "livemode": False}
        self.provider.checkout.return_value = {"id": "cs_new", "customer": "cus_new", "livemode": False, "url": "https://checkout.stripe.com/c/pay/test"}
        mocked = patch("billing.gateway.Gateway", return_value=self.provider)
        mocked.start()
        self.addCleanup(mocked.stop)

    def signed(self, value, signature=None):
        payload = json.dumps(value).encode()
        stamp = int(time.time())
        digest = hmac.new(b"whsec_test_local", str(stamp).encode() + b"." + payload, hashlib.sha256).hexdigest()
        return self.client.post("/stripe/b2b/webhook", data=payload, content_type="application/json", headers={"Stripe-Signature": signature or f"t={stamp},v1={digest}"})

    def state(self, oid=1):
        with self.db() as c:
            return subscription(c, oid)

    def test_admin_a_cannot_read_or_modify_b_subscription_using_manipulated_ids(self):
        _uid, _mid, client = self.member("admin")
        assert client.get("/saas/billing/1").status_code == 200
        before = self.state(2)
        assert client.get("/saas/billing/2").status_code == 404
        for path in ("checkout", "portal", "change-plan", "cancel"):
            response = self.post(f"/saas/billing/2/{path}", {"plan": "ENTERPRISE"}, client)
            assert response.status_code == 404
        assert self.state(2) == before
        self.provider.retrieve_subscription.assert_not_called()
        self.provider.portal.assert_not_called()
        self.provider.checkout.assert_not_called()

    def test_owner_cannot_inject_customer_or_organization_in_form(self):
        self.login()
        assert self.post("/saas/billing/1/portal", {"stripe_customer_id": "cus_B"}).status_code == 400
        assert self.client.get("/saas/billing/1?organization_id=2").status_code == 400
        self.provider.portal.assert_not_called()

    def test_member_has_no_billing_permission(self):
        _uid, _mid, client = self.member("member")
        assert client.get("/saas/billing/1").status_code == 403
        assert self.post("/saas/billing/1/portal", client=client).status_code == 403

    def test_owner_can_view_limits_and_portal_without_exposing_internal_keys(self):
        self.login()
        response = self.client.get("/saas/billing/1")
        data = response.get_json()
        assert data["subscription"]["organization_id"] == 1
        assert data["entitlements"]["limits"]["members"] == 3
        assert "customer_key" not in response.text
        assert "whsec_" not in response.text
        assert self.post("/saas/billing/1/portal").status_code == 200
        self.provider.portal.assert_called_once_with("cus_A", None)

    def test_change_plan_requires_customer_confirmation_and_does_not_grant_plan(self):
        self.login()
        response = self.post("/saas/billing/1/change-plan", {"plan": "BUSINESS"})
        assert response.status_code == 200
        assert self.state()["plan"] == "STARTER"
        customer, flow = self.provider.portal.call_args.args
        assert customer == "cus_A"
        assert flow["subscription_update_confirm"]["items"][0]["price"] == "price_test_BUSINESS"

    def test_cancellation_is_portal_confirmation_not_immediate_local_cancellation(self):
        self.login()
        assert self.post("/saas/billing/1/cancel").status_code == 200
        assert self.state()["status"] == "active"
        assert self.provider.portal.call_args.args[1]["type"] == "subscription_cancel"

    def test_csrf_is_required_for_billing_actions(self):
        self.login()
        assert self.client.post("/saas/billing/1/portal").status_code == 400
        self.provider.portal.assert_not_called()

    def test_old_checkout_cannot_create_second_subscription_after_b2b_adoption(self):
        self.login()
        with patch.object(inahi, "stripe_cliente") as old_provider:
            response = self.client.get("/pago/crecimiento")
            assert response.status_code == 303
            assert response.location.endswith("/saas/billing/1")
            old_provider.assert_not_called()
        self.provider.checkout.assert_not_called()

    def test_old_billing_button_uses_organization_owned_portal(self):
        self.login()
        with patch.object(inahi, "stripe_cliente") as old_provider:
            response = self.post("/cliente/facturacion")
            assert response.status_code == 303
            old_provider.assert_not_called()
        self.provider.portal.assert_called_once_with("cus_A", None)

    def test_platform_view_is_separate_from_tenant_admin(self):
        self.login()
        assert self.client.get("/platform/billing").status_code == 403
        platform = inahi.app.test_client()
        with platform.session_transaction() as session:
            session["administrador"] = True
        response = platform.get("/platform/billing")
        assert response.status_code == 200
        assert len(response.get_json()["organizations"]) == 2
        assert "customer_key" not in response.text and "SECRET" not in response.text
        assert platform.get("/platform/billing/2").get_json()["subscription"]["stripe_customer_id"] == "cus_B"

    def test_subscription_and_customer_are_unique_and_have_foreign_keys(self):
        with self.db() as c:
            for sql in (
                "UPDATE organization_subscriptions SET stripe_customer_id='cus_B' WHERE organization_id=1",
                "UPDATE organization_subscriptions SET stripe_subscription_id='sub_B' WHERE organization_id=1",
                "UPDATE organization_subscriptions SET organization_id=999 WHERE organization_id=1",
                "UPDATE organization_subscriptions SET status='browser_paid' WHERE organization_id=1",
                "UPDATE organization_subscriptions SET plan='CHEAP' WHERE organization_id=1",
            ):
                with pytest.raises(sqlite3.IntegrityError):
                    c.execute(sql)

    def test_metrics_limits_are_atomic_and_organization_scoped(self):
        for metric in ("ai", "clients", "automations", "reports"):
            with patch.dict(os.environ, {f"B2B_LIMIT_STARTER_{metric.upper()}": "1"}):
                with self.db() as c:
                    reserve(c, 1, metric)
                with self.db() as c, pytest.raises(LimitExceeded):
                    reserve(c, 1, metric)
                with self.db() as c:
                    assert describe(c, 1)["usage"][metric] == 1
                    assert describe(c, 2)["usage"][metric] == 0

    def test_concurrent_usage_cannot_exceed_limit(self):
        def use():
            try:
                with self.db() as c:
                    c.execute("BEGIN IMMEDIATE")
                    reserve(c, 1, "ai")
                return True
            except LimitExceeded:
                return False
        with patch.dict(os.environ, B2B_LIMIT_STARTER_AI="1"):
            with ThreadPoolExecutor(max_workers=2) as pool:
                assert sorted(pool.map(lambda _: use(), range(2))) == [False, True]

    def test_member_limit_enforced_on_creation(self):
        from saas_core import create_user, add_membership
        with patch.dict(os.environ, B2B_LIMIT_STARTER_MEMBERS="1"):
            with self.db() as c:
                uid = create_user(c, "extra@example.com", "extra-password-123", "Extra")
                with pytest.raises(LimitExceeded):
                    add_membership(c, 1, uid, "viewer")

    def test_member_limit_enforced_on_reactivation(self):
        from saas_core import change_membership, TenantContext
        uid, mid, _client = self.member("viewer")
        with self.db() as c:
            c.execute("UPDATE organization_memberships SET status='revoked' WHERE id=?", (mid,))
        with patch.dict(os.environ, B2B_LIMIT_STARTER_MEMBERS="1"):
            with self.db() as c, pytest.raises(LimitExceeded):
                change_membership(c, TenantContext(1, 1, 1, "owner", 1), mid, "viewer", "active")

    def test_report_endpoint_enforces_limit_without_inserting(self):
        self.login()
        with patch.dict(os.environ, B2B_LIMIT_STARTER_REPORTS="0"):
            assert self.post("/saas/reports", {"titulo": "new", "contenido": "secret"}).status_code == 402
        assert self.legacy_snapshot() == self.before

    def test_legacy_assistant_endpoint_checks_b2b_limit_before_ai_call(self):
        self.login()
        with patch.dict(os.environ, B2B_LIMIT_STARTER_AI="0"), patch.object(inahi, "asesor_comercial_ia") as ai:
            self.post("/cliente/solicitud", {"asunto": "test", "descripcion": "test"})
            ai.assert_not_called()
        assert self.legacy_snapshot() == self.before

    def test_two_workers_deduplicate_the_same_webhook(self):
        value = event()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: process(value, inahi.conectar), range(2)))
        assert sorted(results) == [False, True]
        self.provider.retrieve_subscription.assert_called_once()

    def test_failed_transaction_rolls_back_reconciliation_and_is_retryable(self):
        before = self.state()
        with patch("billing.webhooks.audit", side_effect=RuntimeError("injected before commit")), pytest.raises(RuntimeError):
            process(event(), inahi.conectar)
        assert self.state() == before
        with self.db() as c:
            assert c.execute("SELECT count(*) FROM billing_events").fetchone()[0] == 0
        assert process(event(), inahi.conectar)

    def test_paid_status_is_server_side_and_billing_recovery_stays_accessible(self):
        self.login()
        with self.db() as c:
            c.execute("UPDATE organization_subscriptions SET status='past_due' WHERE organization_id=1")
        assert self.client.get("/saas/resources/informes/1").status_code == 402
        assert self.client.get("/saas/billing/1").status_code == 200
        assert self.post("/saas/billing/1/portal").status_code == 200

    def test_expired_trial_does_not_grant_paid_features(self):
        with self.db() as c:
            end = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            c.execute("UPDATE organization_subscriptions SET status='trialing',current_period_end=? WHERE organization_id=1", (end,))
            with pytest.raises(LimitExceeded):
                require_paid(c, 1)

    def test_premium_policy_is_centralized(self):
        with self.db() as c:
            with pytest.raises(LimitExceeded):
                require_paid(c, 1, premium=True)
            assert require_paid(c, 2, premium=True)["premium"]

    def test_valid_signature_and_duplicate_events(self):
        value = event()
        assert self.signed(value).status_code == 200
        assert self.signed(value).get_json()["processed"] is False
        self.provider.retrieve_subscription.assert_called_once_with("sub_A")
        with self.db() as c:
            assert c.execute("SELECT count(*) FROM billing_events").fetchone()[0] == 1

    def test_all_six_event_types_reconcile_and_deduplicate(self):
        for index, kind in enumerate(sorted(EVENTS)):
            with self.subTest(event=kind):
                value = event(kind, f"evt_supported_{index}")
                assert process(value, inahi.conectar)
                assert not process(value, inahi.conectar)
        with self.db() as c:
            assert c.execute("SELECT count(*) FROM billing_events").fetchone()[0] == 6

    def test_invalid_signature_does_not_reconcile(self):
        assert self.signed(event(), "t=1,v1=invalid").status_code == 400
        self.provider.retrieve_subscription.assert_not_called()

    def test_live_event_is_rejected_without_provider_call(self):
        value = event()
        value["livemode"] = True
        assert self.signed(value).status_code == 400
        self.provider.retrieve_subscription.assert_not_called()

    def test_payment_failed_uses_canonical_past_due_and_blocks_paid_features(self):
        self.snapshots["sub_A"]["status"] = "past_due"
        assert self.signed(event("invoice.payment_failed")).status_code == 200
        assert self.state()["status"] == "past_due"
        with self.db() as c:
            assert c.execute("SELECT activo FROM clientes WHERE id=1").fetchone()[0] == 0

    def test_old_payment_failure_does_not_overwrite_current_active_subscription(self):
        assert process(event("invoice.paid", created=300), inahi.conectar)
        assert process(event("invoice.payment_failed", "evt_old", created=100), inahi.conectar)
        assert self.state()["status"] == "active"

    def test_old_paid_event_does_not_reactivate_canceled_subscription(self):
        self.snapshots["sub_A"]["status"] = "canceled"
        process(event("customer.subscription.deleted", created=300), inahi.conectar)
        process(event("invoice.paid", "evt_old", created=100), inahi.conectar)
        assert self.state()["status"] == "canceled"

    def test_old_replaced_subscription_is_acknowledged_without_overwriting_current_one(self):
        self.snapshots["sub_old"] = remote("sub_old", "cus_A", status="canceled")
        assert process(event("customer.subscription.deleted", sid="sub_old"), inahi.conectar)
        assert self.state()["stripe_subscription_id"] == "sub_A"
        assert self.state()["status"] == "active"
        assert not process(event("customer.subscription.deleted", sid="sub_old"), inahi.conectar)

    def test_same_second_events_reconcile_current_state_not_arbitrary_event_id_order(self):
        process(event(eid="evt_z", created=300), inahi.conectar)
        self.snapshots["sub_A"]["status"] = "past_due"
        process(event(eid="evt_a", created=300), inahi.conectar)
        assert self.state()["status"] == "past_due"

    def test_safe_retry_after_provider_failure_has_no_ledger_or_effect(self):
        self.provider.retrieve_subscription.side_effect = OSError("temporary outage")
        before = self.state()
        with pytest.raises(OSError):
            process(event(), inahi.conectar)
        with self.db() as c:
            assert c.execute("SELECT count(*) FROM billing_events").fetchone()[0] == 0
        assert self.state() == before
        self.provider.retrieve_subscription.side_effect = lambda sid: deepcopy(self.snapshots[sid])
        assert process(event(), inahi.conectar)

    def test_snapshot_of_b_cannot_change_a_even_with_valid_signature(self):
        self.provider.retrieve_subscription.side_effect = None
        self.provider.retrieve_subscription.return_value = remote(customer="cus_B")
        before = self.state()
        assert self.signed(event()).status_code == 400
        assert self.state() == before

    def test_unknown_price_cannot_grant_an_arbitrary_plan(self):
        self.snapshots["sub_A"]["items"]["data"][0]["price"]["id"] = "price_unconfigured"
        assert self.signed(event()).status_code == 400
        assert self.state()["plan"] == "STARTER"

    def test_invoice_parent_subscription_shape_is_supported(self):
        value = event("invoice.paid")
        obj = value["data"]["object"]
        del obj["subscription"]
        obj["parent"] = {"subscription_details": {"subscription": "sub_A"}}
        assert self.signed(value).status_code == 200

    def test_cancel_at_period_end_remains_active_until_stripe_cancels(self):
        self.snapshots["sub_A"]["cancel_at_period_end"] = True
        process(event(), inahi.conectar)
        assert self.state()["status"] == "active"
        assert self.state()["cancel_at_period_end"] == 1

    def test_legacy_prices_remain_supported_after_explicit_association(self):
        with self.db() as c:
            c.execute("UPDATE organization_subscriptions SET legacy_mode=1 WHERE organization_id=1")
        with patch.dict(os.environ, STRIPE_PRICE_CRECIMIENTO="price_old"):
            self.snapshots["sub_A"]["items"]["data"][0]["price"]["id"] = "price_old"
            process(event(), inahi.conectar)
        assert self.state()["plan"] == "PROFESSIONAL"
        assert self.state()["legacy_mode"] == 1
        with self.db() as c:
            assert describe(c, 1)["limits"]["ai"] is None

    def test_checkout_retries_share_customer_and_checkout_keys(self):
        with self.db() as c:
            c.execute("UPDATE organization_subscriptions SET stripe_customer_id=NULL,stripe_subscription_id=NULL,status='incomplete' WHERE organization_id=1")
        first = service.start_checkout(inahi.conectar, 1, "STARTER")
        second = service.start_checkout(inahi.conectar, 1, "STARTER")
        assert first == second
        self.provider.create_customer.assert_called_once()
        self.provider.checkout.assert_called_once()
        assert self.provider.checkout.call_args.args[0]["checkout_key"] == self.state()["checkout_key"]
        assert self.state()["status"] == "incomplete"

    def test_checkout_failure_keeps_same_persisted_retry_key(self):
        with self.db() as c:
            c.execute("UPDATE organization_subscriptions SET stripe_customer_id=NULL,stripe_subscription_id=NULL,status='incomplete' WHERE organization_id=1")
        self.provider.checkout.side_effect = OSError("lost response")
        with pytest.raises(OSError):
            service.start_checkout(inahi.conectar, 1, "STARTER")
        key = self.state()["checkout_key"]
        self.provider.checkout.side_effect = None
        service.start_checkout(inahi.conectar, 1, "STARTER")
        assert self.state()["checkout_key"] == key

    def test_checkout_retry_preserves_price_even_if_environment_price_changes(self):
        with self.db() as c:
            c.execute("UPDATE organization_subscriptions SET stripe_customer_id=NULL,stripe_subscription_id=NULL,status='incomplete' WHERE organization_id=1")
        self.provider.checkout.side_effect = OSError("lost response")
        with pytest.raises(OSError):
            service.start_checkout(inahi.conectar, 1, "STARTER")
        self.provider.checkout.side_effect = None
        with patch.dict(os.environ, STRIPE_B2B_PRICE_STARTER="price_new_config"):
            service.start_checkout(inahi.conectar, 1, "STARTER")
        assert self.provider.checkout.call_args.args[1] == "price_test_STARTER"

    def test_expired_local_checkout_does_not_duplicate_a_completed_stripe_subscription(self):
        with self.db() as c:
            c.execute("""UPDATE organization_subscriptions SET stripe_subscription_id=NULL,status='incomplete',
                checkout_key='old-key',checkout_plan='STARTER',checkout_id='cs_old',checkout_expires_at=1 WHERE organization_id=1""")
        self.provider.retrieve_checkout.return_value = {"livemode": False, "customer": "cus_A", "status": "complete", "subscription": "sub_A"}
        with pytest.raises(ValueError, match="reconciliar"):
            service.start_checkout(inahi.conectar, 1, "STARTER")
        self.provider.checkout.assert_not_called()
        assert self.state()["checkout_key"] == "old-key"

    def test_lost_checkout_response_never_rotates_key_based_only_on_local_expiry(self):
        with self.db() as c:
            c.execute("""UPDATE organization_subscriptions SET stripe_subscription_id=NULL,status='incomplete',stripe_customer_id='cus_new',
                checkout_key='lost-key',checkout_plan='STARTER',checkout_expires_at=1 WHERE organization_id=1""")
        service.start_checkout(inahi.conectar, 1, "STARTER")
        assert self.provider.checkout.call_args.args[0]["checkout_key"] == "lost-key"

    def test_confirmed_expired_checkout_can_create_new_session(self):
        with self.db() as c:
            c.execute("""UPDATE organization_subscriptions SET stripe_subscription_id=NULL,status='incomplete',stripe_customer_id='cus_new',
                checkout_key='expired-key',checkout_plan='STARTER',checkout_id='cs_expired',checkout_expires_at=1 WHERE organization_id=1""")
        self.provider.retrieve_checkout.return_value = {"livemode": False, "customer": "cus_new", "status": "expired"}
        service.start_checkout(inahi.conectar, 1, "STARTER")
        assert self.state()["checkout_key"] != "expired-key"

    def test_checkout_rejects_second_subscription_for_existing_active_account(self):
        with pytest.raises(ValueError):
            service.start_checkout(inahi.conectar, 1, "BUSINESS")
        self.provider.checkout.assert_not_called()

    def test_fresh_subscription_requires_server_checkout_binding(self):
        with self.db() as c:
            c.execute("UPDATE organization_subscriptions SET stripe_subscription_id=NULL,status='incomplete',checkout_key='server-key' WHERE organization_id=1")
        with pytest.raises(ValueError):
            process(event(), inahi.conectar)
        self.snapshots["sub_A"]["metadata"] = {"organization_id": "1", "billing_scope": "b2b", "billing_key": "server-key"}
        assert process(event(), inahi.conectar)
        assert self.state()["status"] == "active"

    def test_billing_rollback_refuses_new_activity(self):
        with pytest.raises(ValueError):
            migrate(self.path.parent / "rollback.json", str(self.path), downgrade=True)
        with self.db() as c:
            assert enabled(c)


class LegacyBillingMigrationTests(SaaSFixture):
    def setUp(self):
        super().setUp()
        migrate(self.path.parent / "phase3.json", str(self.path), billing=True)

    def test_dry_run_counts_without_modifying_any_bytes(self):
        before = self.path.read_bytes()
        report = associate(str(self.path))
        assert report["subscriptions_to_associate"] == 2 and not report["conflicts"]
        assert self.path.read_bytes() == before
        assert "cus_A" not in json.dumps(report)

    def test_dry_run_works_with_logically_disabled_billing(self):
        # Roll back logical activation to represent a Phase 2 installation.
        migrate(self.path.parent / "disable.json", str(self.path), downgrade=True, billing=True)
        before = self.path.read_bytes()
        report = associate(str(self.path))
        assert not report["billing_schema_ready"]
        assert report["subscriptions_to_associate"] == 2
        assert self.path.read_bytes() == before

    def test_association_preserves_the_complete_last_legacy_trial_day(self):
        today = datetime.now(timezone.utc).date().isoformat()
        with self.db() as c:
            c.execute("UPDATE clientes SET subscription_status='prueba',trial_end=? WHERE id=1", (today,))
        associate(str(self.path), self.path.parent / "trial.json")
        with self.db() as c:
            assert describe(c, 1)["paid"] is True
            assert c.execute("SELECT trial_end FROM clientes WHERE id=1").fetchone()[0] == today

    def test_explicit_association_preserves_all_legacy_fields(self):
        associate(str(self.path), self.path.parent / "association.json")
        assert self.legacy_snapshot() == self.before
        with self.db() as c:
            row = subscription(c, 1)
            assert row["stripe_customer_id"] == "cus_A" and row["stripe_subscription_id"] == "sub_A"
            assert row["legacy_mode"] == 1 and row["plan"] == "PROFESSIONAL"
        assert associate(str(self.path))["subscriptions_to_associate"] == 0

    def test_duplicate_legacy_customer_blocks_association(self):
        with self.db() as c:
            c.execute("UPDATE clientes SET stripe_customer_id='cus_A' WHERE id=2")
        before = self.path.read_bytes()
        with pytest.raises(ValueError):
            associate(str(self.path), self.path.parent / "conflict.json")
        assert self.path.read_bytes() == before

    def test_legacy_only_association_can_be_rolled_back_logically(self):
        associate(str(self.path), self.path.parent / "association.json")
        migrate(self.path.parent / "rollback.json", str(self.path), downgrade=True)
        assert self.legacy_snapshot() == self.before
        with self.db() as c:
            assert not enabled(c)
            assert c.execute("SELECT count(*) FROM organization_subscriptions").fetchone()[0] == 2

    def test_billing_only_rollback_preserves_phase_two_saas(self):
        from saas_schema import enabled as saas_enabled
        associate(str(self.path), self.path.parent / "association.json")
        migrate(self.path.parent / "billing-rollback.json", str(self.path), downgrade=True, billing=True)
        with self.db() as c:
            assert not enabled(c)
            assert saas_enabled(c)
            assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002_saas_core"

    def test_legacy_stripe_reference_requires_association_before_checkout(self):
        with pytest.raises(ValueError, match="Asociar"):
            service.ensure(inahi.conectar, 1, "STARTER")


class BeforeBillingTests(SaaSFixture):
    def test_legacy_dry_run_works_before_billing_tables_exist(self):
        from persistence.database import has_table
        migrate(self.path.parent / "phase2.json", str(self.path))
        with self.db() as c:
            assert not has_table(c, "organization_subscriptions")
        before = self.path.read_bytes()
        report = associate(str(self.path))
        assert not report["billing_schema_ready"]
        assert report["subscriptions_to_associate"] == 2
        assert self.path.read_bytes() == before


@pytest.mark.parametrize("plan", PLANS)
def test_catalog_has_all_limit_dimensions_and_no_hardcoded_prices(plan, monkeypatch):
    monkeypatch.delenv(f"STRIPE_B2B_PRICE_{plan}", raising=False)
    assert set(catalog(plan)["limits"]) == set(METRICS)
    with pytest.raises(ValueError):
        price(plan)


@pytest.mark.parametrize("value", ["sk_live_forbidden", "", "rk_live_forbidden"])
def test_b2b_gateway_rejects_live_or_missing_credentials(value, monkeypatch):
    monkeypatch.setenv("STRIPE_B2B_SECRET_KEY", value)
    with patch("stripe.StripeClient") as client, pytest.raises(ValueError):
        gateway.Gateway()
    client.assert_not_called()


def test_limits_can_be_configured_without_code_changes(monkeypatch):
    monkeypatch.setenv("B2B_LIMIT_STARTER_AI", "7")
    monkeypatch.setenv("B2B_PREMIUM_STARTER", "true")
    assert catalog("STARTER")["limits"]["ai"] == 7
    assert catalog("STARTER")["premium"] is True
    monkeypatch.setenv("B2B_LIMIT_STARTER_AI", "-1")
    with pytest.raises(ValueError):
        catalog("STARTER")


def test_gateway_uses_configured_test_client_and_persistent_idempotency_keys(monkeypatch):
    monkeypatch.setenv("STRIPE_B2B_SECRET_KEY", "sk_test_local_mock")
    monkeypatch.setenv("STRIPE_B2B_MODE", "test")
    monkeypatch.setenv("B2B_RETURN_URL", "http://localhost/return")
    with patch("stripe.StripeClient") as client:
        transport = gateway.Gateway()
        transport.create_customer(7, "Company", "customer-key")
        transport.checkout({"organization_id": 7, "stripe_customer_id": "cus_test", "checkout_key": "checkout-key", "checkout_expires_at": 2000000000}, "price_test")
        customer = client.return_value.v1.customers.create
        assert customer.call_args.kwargs["options"]["idempotency_key"] == "customer-key"
        checkout = client.return_value.v1.checkout.sessions.create
        assert checkout.call_args.kwargs["options"]["idempotency_key"] == "checkout-key"
        assert checkout.call_args.args[0]["subscription_data"]["metadata"]["organization_id"] == "7"
        client.assert_called_once_with("sk_test_local_mock", max_network_retries=2)


def test_postgres_driver_is_loaded_only_on_explicit_connection_and_error_propagates():
    with patch("persistence.database.create_engine", side_effect=ImportError("OS driver policy")) as factory:
        engine = make_engine(sa.URL.create("postgresql+psycopg", host="localhost", database="offline"))
        factory.assert_not_called()
        with pytest.raises(ImportError, match="OS driver policy"):
            engine.connect()
        engine.dispose()


def test_billing_postgresql_schema_compiles_with_unique_references_and_timestamps():
    ddl = "\n".join(str(CreateTable(table).compile(dialect=postgresql.dialect())) for table in TABLES)
    for value in ("UNIQUE (stripe_customer_id)", "UNIQUE (stripe_subscription_id)", "TIMESTAMP WITH TIME ZONE", "REFERENCES organizations (id)", "amount>=0"):
        assert value in ddl


def test_billing_revision_compiles_offline_without_provider_or_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://offline@localhost/preview")
    cfg = configuration()
    cfg.output_buffer = io.StringIO()
    with patch("sqlalchemy.create_engine", side_effect=AssertionError("No database")), patch("stripe.StripeClient", side_effect=AssertionError("No Stripe")):
        command.upgrade(cfg, "head", sql=True)
    assert "0003_org_billing" in cfg.output_buffer.getvalue()
    assert "CREATE TABLE organization_subscriptions" in cfg.output_buffer.getvalue()
