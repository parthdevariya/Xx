# DATABASE_SCHEMA.md — X

Generated from the SQLAlchemy models (`backend/app/models/`). Migrations: `backend/migrations/` (Alembic). PostgreSQL in production (JSON columns are JSONB); SQLite for local development and tests. 54 tables.

## Integrity rules enforced by the database

| Rule | Mechanism |
|---|---|
| Protected Intellect rules are always active | CHECK `ck_rule_protected_active` |
| Only source rules can be protected (custom rules can never reach tier 1) | CHECK `ck_rule_protected_source` |
| Layer conflict tiers are 2–6 (tier 1 is reserved for guardrails) | CHECK `ck_layer_tier` |
| Rule priorities are P1–P4 | CHECK `ck_rule_priority` |
| Reference-library documents can never be executable | CHECK `ck_refdoc_not_executable` |
| Protected rule content, priority, status and protection cannot be updated | trigger (migration 0002) |
| Protected rules in published/archived versions cannot be deleted | trigger (migration 0002) |
| Protected rules cannot receive extra conditions | trigger (migration 0002) |
| Quantum jobs and results declare a valid execution class | CHECK `ck_qjob_class`, `ck_result_class` |
| Execution events are strictly ordered per execution | UNIQUE (`execution_id`, `seq`) |

## Core platform

### `users`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| email | VARCHAR(254) | no | unique |
| display_name | VARCHAR(120) | no |  |
| password_hash | VARCHAR(255) | no |  |
| role_id | VARCHAR(32) | no | → `roles.id` |
| is_active | BOOLEAN | no |  |
| failed_logins | INTEGER | no |  |
| locked_until | TIMESTAMP WITH TIME ZONE | yes |  |
| last_login_at | TIMESTAMP WITH TIME ZONE | yes |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `roles`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| code | VARCHAR(48) | no | unique |
| name | VARCHAR(120) | no |  |
| description | TEXT | no |  |
| rank | INTEGER | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `permissions`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| code | VARCHAR(80) | no | unique |
| description | TEXT | no |  |
| id | VARCHAR(32) | no | PK |

### `role_permissions`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| role_id | VARCHAR(32) | no | PK → `roles.id` |
| permission_id | VARCHAR(32) | no | PK → `permissions.id` |

### `sessions`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| user_id | VARCHAR(32) | no | → `users.id` |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| expires_at | TIMESTAMP WITH TIME ZONE | no |  |
| revoked_at | TIMESTAMP WITH TIME ZONE | yes |  |
| ip | VARCHAR(64) | no |  |
| user_agent | VARCHAR(400) | no |  |
| id | VARCHAR(32) | no | PK |

### `audit_logs`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| at | TIMESTAMP WITH TIME ZONE | no |  |
| actor_id | VARCHAR(32) | yes | → `users.id` |
| actor_email | VARCHAR(254) | no |  |
| category | VARCHAR(48) | no |  |
| action | VARCHAR(120) | no |  |
| target_type | VARCHAR(64) | no |  |
| target_id | VARCHAR(64) | no |  |
| outcome | VARCHAR(16) | no |  |
| detail | JSONB | no |  |
| ip | VARCHAR(64) | no |  |
| id | VARCHAR(32) | no | PK |

### `system_settings`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| key | VARCHAR(120) | no | PK |
| value | JSONB | no |  |
| description | TEXT | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_by | VARCHAR(32) | yes | → `users.id` |


## AI

### `ai_providers`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| name | VARCHAR(120) | no | unique |
| kind | VARCHAR(48) | no |  |
| base_url | VARCHAR(400) | no |  |
| auth_scheme | VARCHAR(32) | no |  |
| is_active | BOOLEAN | no |  |
| timeout_s | FLOAT | no |  |
| rate_limit_rpm | INTEGER | no |  |
| config | JSONB | no |  |
| health_status | VARCHAR(24) | no |  |
| last_latency_ms | FLOAT | yes |  |
| last_checked_at | TIMESTAMP WITH TIME ZONE | yes |  |
| last_error | TEXT | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `ai_models`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| provider_id | VARCHAR(32) | no | → `ai_providers.id` |
| model_id | VARCHAR(160) | no |  |
| display_name | VARCHAR(160) | no |  |
| capabilities | JSONB | no |  |
| modalities | JSONB | no |  |
| context_window | INTEGER | no |  |
| max_output_tokens | INTEGER | no |  |
| input_cost_per_mtok | FLOAT | no |  |
| output_cost_per_mtok | FLOAT | no |  |
| quality_rank | INTEGER | no |  |
| latency_class | VARCHAR(16) | no |  |
| is_active | BOOLEAN | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `ai_capabilities`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| code | VARCHAR(48) | no | PK |
| description | TEXT | no |  |

### `ai_routing_policies`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| name | VARCHAR(120) | no | unique |
| is_default | BOOLEAN | no |  |
| description | TEXT | no |  |
| rules | JSONB | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `ai_credentials`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| provider_id | VARCHAR(32) | no | unique → `ai_providers.id` |
| secret_encrypted | TEXT | no |  |
| hint | VARCHAR(32) | no |  |
| extra_encrypted | TEXT | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `ai_execution_logs`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| at | TIMESTAMP WITH TIME ZONE | no |  |
| execution_id | VARCHAR(32) | yes | → `executions.id` |
| provider_id | VARCHAR(32) | yes | → `ai_providers.id` |
| model_id | VARCHAR(160) | no |  |
| provider_kind | VARCHAR(48) | no |  |
| purpose | VARCHAR(80) | no |  |
| status | VARCHAR(16) | no |  |
| input_tokens | INTEGER | no |  |
| output_tokens | INTEGER | no |  |
| cost_usd | FLOAT | no |  |
| latency_ms | FLOAT | no |  |
| error | TEXT | no |  |
| id | VARCHAR(32) | no | PK |


## Quantum

### `quantum_providers`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| name | VARCHAR(120) | no | unique |
| vendor | VARCHAR(32) | no |  |
| endpoint | VARCHAR(400) | no |  |
| is_active | BOOLEAN | no |  |
| config | JSONB | no |  |
| sdk_available | BOOLEAN | no |  |
| health_status | VARCHAR(24) | no |  |
| health_detail | TEXT | no |  |
| last_checked_at | TIMESTAMP WITH TIME ZONE | yes |  |
| max_execution_s | FLOAT | no |  |
| max_cost_per_job_usd | FLOAT | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `quantum_backends`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| provider_id | VARCHAR(32) | no | → `quantum_providers.id` |
| backend_key | VARCHAR(120) | no | unique |
| name | VARCHAR(160) | no |  |
| modality | VARCHAR(24) | no |  |
| is_hardware | BOOLEAN | no |  |
| max_qubits | INTEGER | no |  |
| supported_formulations | JSONB | no |  |
| supported_algorithms | JSONB | no |  |
| max_shots | INTEGER | no |  |
| default_shots | INTEGER | no |  |
| pricing | JSONB | no |  |
| two_qubit_error | FLOAT | yes |  |
| queue_depth | INTEGER | yes |  |
| status | VARCHAR(24) | no |  |
| status_detail | TEXT | no |  |
| is_active | BOOLEAN | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

Constraints: `ck_qbackend_modality`

### `quantum_algorithms`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| key | VARCHAR(64) | no | unique |
| name | VARCHAR(160) | no |  |
| description | TEXT | no |  |
| problem_compatibility | JSONB | no |  |
| input_schema | JSONB | no |  |
| output_schema | JSONB | no |  |
| backend_requirements | JSONB | no |  |
| resource_requirements | JSONB | no |  |
| execution_config | JSONB | no |  |
| known_limitations | JSONB | no |  |
| benchmark_methodology | TEXT | no |  |
| benefit_evidence | JSONB | no |  |
| is_active | BOOLEAN | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `quantum_capabilities`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| code | VARCHAR(48) | no | PK |
| description | TEXT | no |  |

### `quantum_credentials`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| provider_id | VARCHAR(32) | no | unique → `quantum_providers.id` |
| secret_encrypted | TEXT | no |  |
| hint | VARCHAR(32) | no |  |
| extra_encrypted | TEXT | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `quantum_jobs`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| execution_id | VARCHAR(32) | yes | → `executions.id` |
| backend_key | VARCHAR(120) | no |  |
| algorithm | VARCHAR(64) | no |  |
| execution_class | VARCHAR(24) | no |  |
| status | VARCHAR(16) | no |  |
| provider_job_id | VARCHAR(200) | no |  |
| qubits | INTEGER | no |  |
| circuit_depth | INTEGER | no |  |
| shots | INTEGER | no |  |
| submitted_at | TIMESTAMP WITH TIME ZONE | no |  |
| completed_at | TIMESTAMP WITH TIME ZONE | yes |  |
| wall_time_s | FLOAT | no |  |
| cost_usd | FLOAT | no |  |
| result | JSONB | no |  |
| error | TEXT | no |  |
| attempts | INTEGER | no |  |
| id | VARCHAR(32) | no | PK |

Constraints: `ck_qjob_class`

### `quantum_execution_logs`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| at | TIMESTAMP WITH TIME ZONE | no |  |
| job_id | VARCHAR(32) | yes | → `quantum_jobs.id` |
| level | VARCHAR(12) | no |  |
| message | TEXT | no |  |
| id | VARCHAR(32) | no | PK |


## Intellect

### `intellect_frameworks`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| slug | VARCHAR(80) | no | unique |
| name | VARCHAR(160) | no |  |
| description | TEXT | no |  |
| source_pack | VARCHAR(80) | no |  |
| active_version_id | VARCHAR(32) | yes | → `intellect_versions.id` |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `intellect_versions`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| framework_id | VARCHAR(32) | no | → `intellect_frameworks.id` |
| label | VARCHAR(64) | no |  |
| status | VARCHAR(16) | no |  |
| parent_version_id | VARCHAR(32) | yes | → `intellect_versions.id` |
| pipeline | JSONB | no |  |
| hierarchy | JSONB | no |  |
| hierarchy_note | TEXT | no |  |
| meta | JSONB | no |  |
| notes | TEXT | no |  |
| validation | JSONB | no |  |
| created_by | VARCHAR(32) | yes | → `users.id` |
| submitted_at | TIMESTAMP WITH TIME ZONE | yes |  |
| published_at | TIMESTAMP WITH TIME ZONE | yes |  |
| published_by | VARCHAR(32) | yes | → `users.id` |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

Constraints: `ck_version_status`

### `intellect_layers`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| version_id | VARCHAR(32) | no | → `intellect_versions.id` |
| code | VARCHAR(8) | no |  |
| name | VARCHAR(160) | no |  |
| question | TEXT | no |  |
| description | TEXT | no |  |
| tier | INTEGER | no |  |
| tier_basis | TEXT | no |  |
| origin | VARCHAR(16) | no |  |
| enabled_by_default | BOOLEAN | no |  |
| position | INTEGER | no |  |
| declared_rule_count | INTEGER | yes |  |
| source_page | INTEGER | yes |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

Constraints: `ck_layer_origin`, `ck_layer_tier`

### `intellect_rules`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| version_id | VARCHAR(32) | no | → `intellect_versions.id` |
| layer_id | VARCHAR(32) | no | → `intellect_layers.id` |
| rule_code | VARCHAR(16) | no |  |
| number | INTEGER | no |  |
| text | TEXT | no |  |
| applies_when | TEXT | no |  |
| not_when | TEXT | no |  |
| priority | INTEGER | no |  |
| provenance | VARCHAR(16) | no |  |
| source_marker | VARCHAR(64) | yes |  |
| is_protected | BOOLEAN | no |  |
| is_active | BOOLEAN | no |  |
| origin | VARCHAR(16) | no |  |
| position | INTEGER | no |  |
| source_page | INTEGER | yes |  |
| source_sha256 | VARCHAR(64) | no |  |
| source_block | TEXT | no |  |
| revision | INTEGER | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

Constraints: `ck_rule_priority`, `ck_rule_origin`, `ck_rule_protected_source`, `ck_rule_protected_active`

### `intellect_rule_conditions`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| rule_id | VARCHAR(32) | no | → `intellect_rules.id` |
| kind | VARCHAR(16) | no |  |
| text | TEXT | no |  |
| data | JSONB | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

Constraints: `ck_cond_kind`

### `intellect_dependencies`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| version_id | VARCHAR(32) | no | → `intellect_versions.id` |
| rule_id | VARCHAR(32) | no | → `intellect_rules.id` |
| depends_on_code | VARCHAR(16) | no |  |
| kind | VARCHAR(24) | no |  |
| origin | VARCHAR(24) | no |  |
| context | TEXT | no |  |
| id | VARCHAR(32) | no | PK |

### `intellect_guardrails`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| version_id | VARCHAR(32) | no | → `intellect_versions.id` |
| rule_id | VARCHAR(32) | no | → `intellect_rules.id` |
| rule_code | VARCHAR(16) | no |  |
| kind | VARCHAR(24) | no |  |
| source_basis | TEXT | no |  |
| id | VARCHAR(32) | no | PK |

### `intellect_evidence`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| version_id | VARCHAR(32) | no | → `intellect_versions.id` |
| code | VARCHAR(16) | no |  |
| meaning | TEXT | no |  |
| id | VARCHAR(32) | no | PK |

### `intellect_execution_policies`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| framework_id | VARCHAR(32) | no | → `intellect_frameworks.id` |
| name | VARCHAR(120) | no |  |
| is_default | BOOLEAN | no |  |
| layer_switches | JSONB | no |  |
| rule_switches | JSONB | no |  |
| settings | JSONB | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `intellect_test_cases`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| framework_id | VARCHAR(32) | no | → `intellect_frameworks.id` |
| name | VARCHAR(200) | no |  |
| prompt | TEXT | no |  |
| layer_switches | JSONB | no |  |
| expected | JSONB | no |  |
| origin | VARCHAR(24) | no |  |
| created_by | VARCHAR(32) | yes | → `users.id` |
| last_run_id | VARCHAR(32) | yes |  |
| last_outcome | VARCHAR(16) | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `intellect_runs`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| started_at | TIMESTAMP WITH TIME ZONE | no |  |
| finished_at | TIMESTAMP WITH TIME ZONE | yes |  |
| version_id | VARCHAR(32) | no | → `intellect_versions.id` |
| execution_id | VARCHAR(32) | yes | → `executions.id` |
| test_case_id | VARCHAR(32) | yes | → `intellect_test_cases.id` |
| origin | VARCHAR(16) | no |  |
| user_id | VARCHAR(32) | yes | → `users.id` |
| prompt | TEXT | no |  |
| layer_switches | JSONB | no |  |
| status | VARCHAR(16) | no |  |
| assessment_mode | VARCHAR(24) | no |  |
| final_output | TEXT | no |  |
| summary | JSONB | no |  |
| error | TEXT | no |  |
| id | VARCHAR(32) | no | PK |

### `intellect_execution_logs`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| run_id | VARCHAR(32) | no | → `intellect_runs.id` |
| position | INTEGER | no |  |
| layer | VARCHAR(8) | no |  |
| mode | VARCHAR(24) | no |  |
| status | VARCHAR(16) | no |  |
| rule_states | JSONB | no |  |
| output | TEXT | no |  |
| data | JSONB | no |  |
| model | VARCHAR(160) | no |  |
| latency_ms | FLOAT | no |  |
| at | TIMESTAMP WITH TIME ZONE | no |  |
| id | VARCHAR(32) | no | PK |

### `intellect_conflicts`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| run_id | VARCHAR(32) | no | → `intellect_runs.id` |
| stage_position | INTEGER | no |  |
| rule_codes | JSONB | no |  |
| layers | JSONB | no |  |
| description | TEXT | no |  |
| hierarchy_step | TEXT | no |  |
| winner | VARCHAR(16) | no |  |
| decision | TEXT | no |  |
| detected_by | VARCHAR(16) | no |  |
| id | VARCHAR(32) | no | PK |

### `intellect_rule_history`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| rule_id | VARCHAR(32) | yes | → `intellect_rules.id` |
| version_id | VARCHAR(32) | no | → `intellect_versions.id` |
| rule_code | VARCHAR(16) | no |  |
| action | VARCHAR(24) | no |  |
| before | JSONB | no |  |
| after | JSONB | no |  |
| changed_by | VARCHAR(32) | yes | → `users.id` |
| at | TIMESTAMP WITH TIME ZONE | no |  |
| id | VARCHAR(32) | no | PK |

### `intellect_reference_documents`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| framework_id | VARCHAR(32) | no | → `intellect_frameworks.id` |
| filename | VARCHAR(200) | no |  |
| description | TEXT | no |  |
| use_for | TEXT | no |  |
| content | TEXT | no |  |
| executable | BOOLEAN | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

Constraints: `ck_refdoc_not_executable`

### `intellect_imports`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| framework_id | VARCHAR(32) | yes | → `intellect_frameworks.id` |
| filename | VARCHAR(255) | no |  |
| file_format | VARCHAR(8) | no |  |
| file_sha256 | VARCHAR(64) | no |  |
| status | VARCHAR(16) | no |  |
| report | JSONB | no |  |
| draft_version_id | VARCHAR(32) | yes | → `intellect_versions.id` |
| created_by | VARCHAR(32) | yes | → `users.id` |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |


## Scenarios

### `scenario_categories`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| slug | VARCHAR(80) | no | unique |
| name | VARCHAR(160) | no |  |
| description | TEXT | no |  |
| position | INTEGER | no |  |
| notice | TEXT | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `scenarios`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| slug | VARCHAR(120) | no | unique |
| category_id | VARCHAR(32) | no | → `scenario_categories.id` |
| status | VARCHAR(16) | no |  |
| current_version_id | VARCHAR(32) | yes | → `scenario_versions.id` |
| is_demo | BOOLEAN | no |  |
| position | INTEGER | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

Constraints: `ck_scenario_status`

### `scenario_versions`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| scenario_id | VARCHAR(32) | no | → `scenarios.id` |
| version_no | INTEGER | no |  |
| name | VARCHAR(200) | no |  |
| tagline | VARCHAR(300) | no |  |
| description | TEXT | no |  |
| problem_statement | TEXT | no |  |
| context | TEXT | no |  |
| demonstrates | TEXT | no |  |
| solver_template | VARCHAR(64) | no |  |
| output_structure | JSONB | no |  |
| recommended_models | JSONB | no |  |
| recommended_framework_slug | VARCHAR(80) | no |  |
| quantum_eligibility | VARCHAR(32) | no |  |
| classical_config | JSONB | no |  |
| benchmark_config | JSONB | no |  |
| visualizations | JSONB | no |  |
| engines | JSONB | no |  |
| expected_output | TEXT | no |  |
| notes | TEXT | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `scenario_input_schemas`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| version_id | VARCHAR(32) | no | unique → `scenario_versions.id` |
| fields | JSONB | no |  |
| defaults | JSONB | no |  |
| validation | JSONB | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `scenario_execution_policies`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| scenario_id | VARCHAR(32) | no | unique → `scenarios.id` |
| allowed_modes | JSONB | no |  |
| default_mode | VARCHAR(24) | no |  |
| max_cost_usd | FLOAT | no |  |
| allow_quantum_hardware | BOOLEAN | no |  |
| demo_enabled | BOOLEAN | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |


## Orchestration

### `computational_problems`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| user_id | VARCHAR(32) | no | → `users.id` |
| scenario_id | VARCHAR(32) | yes | → `scenarios.id` |
| text | TEXT | no |  |
| inputs | JSONB | no |  |
| attachments | JSONB | no |  |
| structured | JSONB | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `execution_plans`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| problem_id | VARCHAR(32) | no | → `computational_problems.id` |
| mode | VARCHAR(24) | no |  |
| steps | JSONB | no |  |
| quantum_decision | JSONB | no |  |
| estimates | JSONB | no |  |
| baselines | JSONB | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

### `executions`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| user_id | VARCHAR(32) | no | → `users.id` |
| problem_id | VARCHAR(32) | no | → `computational_problems.id` |
| plan_id | VARCHAR(32) | yes | → `execution_plans.id` |
| scenario_id | VARCHAR(32) | yes | → `scenarios.id` |
| mode | VARCHAR(24) | no |  |
| status | VARCHAR(20) | no |  |
| framework_version_id | VARCHAR(32) | yes | → `intellect_versions.id` |
| ai_provider | VARCHAR(160) | no |  |
| ai_model | VARCHAR(160) | no |  |
| quantum_backend | VARCHAR(160) | no |  |
| algorithm | VARCHAR(64) | no |  |
| is_demo | BOOLEAN | no |  |
| result_source | VARCHAR(16) | no |  |
| started_at | TIMESTAMP WITH TIME ZONE | yes |  |
| finished_at | TIMESTAMP WITH TIME ZONE | yes |  |
| resource_usage | JSONB | no |  |
| estimated_cost_usd | FLOAT | no |  |
| actual_cost_usd | FLOAT | no |  |
| final_output | JSONB | no |  |
| error | TEXT | no |  |
| cancel_requested | BOOLEAN | no |  |
| event_seq | INTEGER | no |  |
| id | VARCHAR(32) | no | PK |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| updated_at | TIMESTAMP WITH TIME ZONE | no |  |

Constraints: `ck_execution_status`

### `execution_events`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| execution_id | VARCHAR(32) | no | → `executions.id` |
| seq | INTEGER | no |  |
| at | TIMESTAMP WITH TIME ZONE | no |  |
| engine | VARCHAR(16) | no |  |
| type | VARCHAR(48) | no |  |
| message | TEXT | no |  |
| data | JSONB | no |  |
| id | VARCHAR(32) | no | PK |

### `execution_artifacts`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| execution_id | VARCHAR(32) | no | → `executions.id` |
| kind | VARCHAR(32) | no |  |
| name | VARCHAR(255) | no |  |
| content_type | VARCHAR(100) | no |  |
| content | TEXT | no |  |
| storage_path | VARCHAR(500) | no |  |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| id | VARCHAR(32) | no | PK |

### `execution_results`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| execution_id | VARCHAR(32) | no | → `executions.id` |
| step_key | VARCHAR(64) | no |  |
| engine | VARCHAR(16) | no |  |
| content_class | VARCHAR(20) | no |  |
| execution_class | VARCHAR(24) | no |  |
| title | VARCHAR(200) | no |  |
| content | JSONB | no |  |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| id | VARCHAR(32) | no | PK |

Constraints: `ck_result_class`

### `benchmark_runs`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| execution_id | VARCHAR(32) | no | → `executions.id` |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| input_sha256 | VARCHAR(64) | no |  |
| objective | TEXT | no |  |
| environment | JSONB | no |  |
| methodology | JSONB | no |  |
| conclusion | TEXT | no |  |
| id | VARCHAR(32) | no | PK |

### `benchmark_metrics`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| run_id | VARCHAR(32) | no | → `benchmark_runs.id` |
| approach | VARCHAR(48) | no |  |
| metric | VARCHAR(64) | no |  |
| value | FLOAT | yes |  |
| text_value | TEXT | no |  |
| unit | VARCHAR(24) | no |  |
| notes | TEXT | no |  |
| id | VARCHAR(32) | no | PK |


## Infrastructure

### `background_jobs`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| kind | VARCHAR(48) | no |  |
| payload | JSONB | no |  |
| status | VARCHAR(16) | no |  |
| attempts | INTEGER | no |  |
| max_attempts | INTEGER | no |  |
| run_after | TIMESTAMP WITH TIME ZONE | no |  |
| locked_by | VARCHAR(120) | no |  |
| locked_at | TIMESTAMP WITH TIME ZONE | yes |  |
| heartbeat_at | TIMESTAMP WITH TIME ZONE | yes |  |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| finished_at | TIMESTAMP WITH TIME ZONE | yes |  |
| error | TEXT | no |  |
| execution_id | VARCHAR(32) | yes | → `executions.id` |
| id | VARCHAR(32) | no | PK |

### `provider_health`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| provider_type | VARCHAR(16) | no |  |
| provider_id | VARCHAR(32) | no |  |
| status | VARCHAR(24) | no |  |
| latency_ms | FLOAT | yes |  |
| detail | TEXT | no |  |
| checked_at | TIMESTAMP WITH TIME ZONE | no |  |
| id | VARCHAR(32) | no | PK |

### `usage_records`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| at | TIMESTAMP WITH TIME ZONE | no |  |
| user_id | VARCHAR(32) | yes | → `users.id` |
| execution_id | VARCHAR(32) | yes | → `executions.id` |
| kind | VARCHAR(32) | no |  |
| quantity | FLOAT | no |  |
| unit | VARCHAR(16) | no |  |
| provider | VARCHAR(120) | no |  |
| id | VARCHAR(32) | no | PK |

### `cost_records`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| at | TIMESTAMP WITH TIME ZONE | no |  |
| execution_id | VARCHAR(32) | yes | → `executions.id` |
| user_id | VARCHAR(32) | yes | → `users.id` |
| provider | VARCHAR(120) | no |  |
| category | VARCHAR(16) | no |  |
| amount_usd | FLOAT | no |  |
| is_estimate | BOOLEAN | no |  |
| id | VARCHAR(32) | no | PK |

### `notifications`

| Column | Type | Null | Key / reference |
|---|---|---|---|
| user_id | VARCHAR(32) | no | → `users.id` |
| created_at | TIMESTAMP WITH TIME ZONE | no |  |
| title | VARCHAR(200) | no |  |
| body | TEXT | no |  |
| link | VARCHAR(300) | no |  |
| read | BOOLEAN | no |  |
| id | VARCHAR(32) | no | PK |

