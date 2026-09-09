-- Offline review artifact; not executed on any database.
BEGIN;

-- Running upgrade 0002_saas_core -> 0003_org_billing

CREATE TABLE organization_subscriptions (
    organization_id BIGINT NOT NULL, 
    plan VARCHAR(32) NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    stripe_customer_id TEXT, 
    stripe_subscription_id TEXT, 
    current_period_start TIMESTAMP WITH TIME ZONE, 
    current_period_end TIMESTAMP WITH TIME ZONE, 
    cancel_at_period_end INTEGER DEFAULT '0' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    legacy_mode INTEGER DEFAULT '0' NOT NULL, 
    customer_key TEXT NOT NULL, 
    checkout_key TEXT, 
    checkout_plan VARCHAR(32), 
    checkout_price_id TEXT, 
    checkout_id TEXT, 
    checkout_url TEXT, 
    checkout_expires_at BIGINT, 
    PRIMARY KEY (organization_id), 
    CHECK (plan IN ('STARTER','PROFESSIONAL','BUSINESS','ENTERPRISE')), 
    CHECK (status IN ('trialing','active','past_due','canceled','incomplete')), 
    CHECK (cancel_at_period_end IN (0,1) AND legacy_mode IN (0,1)), 
    FOREIGN KEY(organization_id) REFERENCES organizations (id) ON DELETE RESTRICT, 
    UNIQUE (stripe_customer_id), 
    UNIQUE (stripe_subscription_id), 
    UNIQUE (customer_key)
);

CREATE TABLE billing_usage (
    organization_id BIGINT NOT NULL, 
    metric VARCHAR(32) NOT NULL, 
    period VARCHAR(16) NOT NULL, 
    amount BIGINT DEFAULT '0' NOT NULL, 
    PRIMARY KEY (organization_id, metric, period), 
    CHECK (amount>=0), 
    CHECK (metric IN ('members','clients','ai','automations','reports')), 
    FOREIGN KEY(organization_id) REFERENCES organization_subscriptions (organization_id) ON DELETE RESTRICT
);

CREATE TABLE billing_events (
    event_id TEXT NOT NULL, 
    organization_id BIGINT NOT NULL, 
    event_type TEXT NOT NULL, 
    event_created BIGINT NOT NULL, 
    processed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (event_id), 
    FOREIGN KEY(organization_id) REFERENCES organization_subscriptions (organization_id) ON DELETE RESTRICT
);

CREATE INDEX ix_billing_events_organization ON billing_events (organization_id, processed_at);

CREATE TABLE billing_schema_state (
    version VARCHAR(32) NOT NULL, 
    enabled INTEGER NOT NULL, 
    PRIMARY KEY (version), 
    CHECK (enabled IN (0,1))
);

INSERT INTO billing_schema_state(version,enabled) VALUES('0003_org_billing',1) ON CONFLICT(version) DO UPDATE SET enabled=1;

UPDATE alembic_version SET version_num='0003_org_billing' WHERE alembic_version.version_num = '0002_saas_core';

COMMIT;

