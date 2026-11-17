-- STAGING ONLY: reviewed draft, not applied to the campus database.
CREATE TYPE screening_action_enum AS ENUM ('ALLOW', 'REVIEW', 'ALERT');

CREATE TYPE screening_reason_code_enum AS ENUM (
  'ALLOW_PERMITTED_FOOD',
  'ALLOW_PERMITTED_GOODS',
  'CATEGORY_RULE_ALLOW',
  'REVIEW_UNCERTAIN_CLASSIFICATION',
  'REVIEW_CONTROLLED_ITEM',
  'REVIEW_HAZARDOUS_QUANTITY',
  'CATEGORY_RULE_REVIEW',
  'MANUAL_REVIEW_REQUIRED',
  'UNKNOWN_CATEGORY',
  'LOW_CLASSIFIER_CONFIDENCE',
  'MISSING_CLASSIFIER_CONFIDENCE',
  'INVALID_CLASSIFICATION',
  'MISSING_QUANTITY',
  'INVALID_QUANTITY',
  'UNSUPPORTED_QUANTITY_UNIT',
  'POLICY_RULE_CONFLICT',
  'POLICY_VERSION_INVALID',
  'HAZARDOUS_THRESHOLD_MET',
  'ALERT_PROHIBITED_CHEMICAL',
  'ALERT_PROHIBITED_TOBACCO',
  'ALERT_PROHIBITED_ALCOHOL',
  'ALERT_PROHIBITED_DRUG',
  'ALERT_PROHIBITED_WEAPON',
  'CATEGORY_RULE_ALERT',
  'NO_MATCHING_POLICY_RULE',
  'POLICY_RULE_INACTIVE',
  'POLICY_RULE_EXPIRED',
  'MISSING_REQUIRED_PLATFORM',
  'MULTIPLE_RULES_MATCHED',
  'HAZARDOUS_THRESHOLD_NOT_MET'
);

CREATE TABLE item_categories (
  code varchar(50) PRIMARY KEY,
  display_name varchar(100) NOT NULL,
  description text NOT NULL,
  default_action screening_action_enum NOT NULL,
  severity varchar(20) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE screening_policy_rules (
  id uuid PRIMARY KEY,
  category_code varchar(50) NOT NULL REFERENCES item_categories(code),
  action screening_action_enum NOT NULL,
  min_quantity integer,
  max_quantity integer,
  platform varchar(30),
  priority integer NOT NULL DEFAULT 100,
  policy_version varchar(40) NOT NULL DEFAULT '1.0',
  effective_from timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  effective_to timestamptz,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE invoice_line_classifications (
  id uuid PRIMARY KEY,
  invoice_item_id uuid NOT NULL REFERENCES invoice_items(id),
  category_code varchar(50) NOT NULL REFERENCES item_categories(code),
  confidence double precision, -- Nullable for manual entries or low-res images without score
  classifier_name varchar(120) NOT NULL,
  classifier_version varchar(120) NOT NULL,
  normalized_item_text varchar(300) NOT NULL,
  raw_item_text text, -- raw item text is retained only if the resulting screening outcome is not ALLOW
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE invoice_screening_results (
  id uuid PRIMARY KEY,
  invoice_id uuid NOT NULL REFERENCES invoices(id),
  outcome screening_action_enum NOT NULL,
  matched_rule_ids uuid[] NOT NULL,
  reason_codes varchar(80)[] NOT NULL, -- Standardized ReasonCode enum values
  policy_version varchar(40) NOT NULL DEFAULT '1.0',
  raw_payload jsonb NOT NULL, -- Full immutable raw screening JSON payload for audit verification
  security_alert_id uuid REFERENCES security_alerts(id),
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ml_eval_runs (
  id uuid PRIMARY KEY,
  track varchar(20) NOT NULL,
  model_name varchar(160) NOT NULL,
  model_version varchar(160) NOT NULL,
  dataset_name varchar(160) NOT NULL,
  metrics jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_screening_policy_rules_category_code ON screening_policy_rules(category_code);
CREATE INDEX ix_invoice_line_classifications_invoice_item_id ON invoice_line_classifications(invoice_item_id);
CREATE INDEX ix_invoice_screening_results_invoice_id ON invoice_screening_results(invoice_id);
CREATE INDEX ix_ml_eval_runs_track ON ml_eval_runs(track);
-- Never hard-delete these records. Soft-deactivate rules/categories with active/effective_to.
