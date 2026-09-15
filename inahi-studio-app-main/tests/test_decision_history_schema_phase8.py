from crm.decision_history_schema import DecisionOutcomeRecord, DecisionSnapshot, TABLES


def test_decision_history_tables_are_additive_and_explicit():
    names = {table.name for table in TABLES}
    assert names == {"decision_snapshots", "decision_outcome_records", "decision_history_schema_state"}


def test_snapshot_keeps_tenant_and_explainability_fields():
    columns = set(DecisionSnapshot.c.keys())
    assert {"organization_id", "opportunity_id", "owner_user_id", "risk_score", "decision_priority", "money_at_risk", "recommended_action", "why_now", "attention_age_days", "captured_at"} <= columns


def test_outcome_record_keeps_observed_before_after_evidence():
    columns = set(DecisionOutcomeRecord.c.keys())
    assert {"organization_id", "snapshot_id", "action_taken", "outcome", "effectiveness_score", "previous_risk_score", "current_risk_score", "previous_probability", "current_probability", "observed_at", "explanation"} <= columns


def test_decision_history_has_tenant_scoped_foreign_keys():
    snapshot_targets = {tuple(fk.column_keys) for fk in DecisionSnapshot.foreign_key_constraints}
    outcome_targets = {tuple(fk.column_keys) for fk in DecisionOutcomeRecord.foreign_key_constraints}
    assert ("organization_id", "opportunity_id") in snapshot_targets
    assert ("organization_id", "owner_user_id") in snapshot_targets
    assert ("organization_id", "snapshot_id") in outcome_targets
