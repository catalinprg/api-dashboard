from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from database import Base


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    kind = Column(String, nullable=False, default="http")  # http | graphql
    base_url = Column(String, nullable=False)
    auth_type = Column(String, nullable=False, default="bearer")  # bearer | basic | oauth2_cc | header | query | hmac | jwt_hs | none
    auth_header_name = Column(String, default="Authorization")
    auth_prefix = Column(String, default="Bearer ")
    auth_query_param = Column(String, default="")
    api_key_encrypted = Column(Text, default="")
    extra_headers = Column(Text, default="{}")  # JSON string
    variables = Column(Text, default="{}")  # JSON dict of {var_name: value} for {{var}} substitution
    # OAuth 2.0 (client credentials) — client_secret reuses api_key_encrypted
    oauth_client_id = Column(String, default="")
    oauth_token_url = Column(String, default="")
    oauth_scope = Column(String, default="")
    oauth_auth_style = Column(String, default="body")  # "body" (creds in form) or "basic" (Basic header)
    enabled = Column(Boolean, default=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    endpoints = relationship("Endpoint", back_populates="provider", cascade="all, delete-orphan")


class Endpoint(Base):
    __tablename__ = "endpoints"

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    name = Column(String, nullable=False)
    method = Column(String, default="POST")
    path = Column(String, nullable=False)  # appended to provider.base_url
    description = Column(Text, default="")
    api_key_encrypted = Column(Text, default="")  # used when auth_mode = 'override'
    auth_mode = Column(String, default="inherit")  # inherit | override | none

    provider = relationship("Provider", back_populates="endpoints")


class RequestPreset(Base):
    __tablename__ = "request_presets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    provider_id = Column(Integer, nullable=True)
    endpoint_id = Column(Integer, nullable=True)
    method = Column(String, default="GET")
    url = Column(String, default="")   # used when no provider/endpoint
    path = Column(String, default="")
    headers_json = Column(Text, default="{}")
    query_json = Column(Text, default="{}")
    body_json = Column(Text, default="")   # JSON-encoded body (string, object, etc.)
    body_type = Column(String, default="json")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Run(Base):
    """A data-driven request template (Postman-runner-style).

    The request fields mirror HTTPInvokeRequest; data_content holds the raw
    CSV/TSV/JSON blob. One row per execution iteration; row columns become
    variables referenced in the template as {{column_name}}.
    """
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, default="")
    notes = Column(Text, default="")

    # Request template
    provider_id = Column(Integer, nullable=True)
    endpoint_id = Column(Integer, nullable=True)
    method = Column(String, default="GET")
    url = Column(String, default="")
    path = Column(String, default="")
    headers_json = Column(Text, default="{}")
    query_json = Column(Text, default="{}")
    body_json = Column(Text, default="")
    body_type = Column(String, default="json")

    # Data source: raw text in data_content, parsed per data_format
    data_format = Column(String, default="csv")  # csv | tsv | json
    data_content = Column(Text, default="")

    # Execution settings
    delay_ms = Column(Integer, default=0)           # delay between iterations
    stop_on_error = Column(Boolean, default=False)
    max_rows = Column(Integer, nullable=True)       # optional cap; None = no cap (enforced at limit)

    # Assertions (applied to each iteration's response)
    # JSON: {"expected_status": [200,201], "body_contains": "...", "body_not_contains": "..."}
    assertions_json = Column(Text, default="{}")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    executions = relationship(
        "RunExecution",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunExecution.id.desc()",
    )


class RunExecution(Base):
    """A single execution of a Run — tracks progress + overall status."""
    __tablename__ = "run_executions"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False, index=True)

    # Lifecycle
    status = Column(String, default="pending")  # pending | running | completed | canceled | failed
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    error = Column(Text, default="")

    # Progress counters
    total_rows = Column(Integer, default=0)
    completed_rows = Column(Integer, default=0)
    succeeded = Column(Integer, default=0)
    failed = Column(Integer, default=0)

    # Cancel signal — flipped by the cancel endpoint, polled each iteration.
    cancel_requested = Column(Boolean, default=False)

    # Snapshot of assertions used at execution time (so later schema changes don't
    # rewrite history).
    assertions_json = Column(Text, default="{}")

    run = relationship("Run", back_populates="executions")
    iterations = relationship(
        "RunIteration",
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="RunIteration.row_index.asc()",
    )


class RunIteration(Base):
    """One row of the data file, run through the template."""
    __tablename__ = "run_iterations"

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("run_executions.id"), nullable=False, index=True)
    row_index = Column(Integer, nullable=False)

    # Input row (the CSV row as a dict — small, OK to store JSON)
    variables_json = Column(Text, default="{}")

    # Resolved request (after substitution)
    method = Column(String, default="")
    url = Column(String, default="")

    # Response
    status_code = Column(Integer, default=0)
    latency_ms = Column(Integer, default=0)
    ok = Column(Boolean, default=False)           # HTTP-level success
    passed = Column(Boolean, default=False)       # assertions pass AND http ok
    error = Column(Text, default="")
    # Response body preview, capped in code.
    response_preview = Column(Text, default="")
    # Per-assertion pass/fail detail.
    assertion_results_json = Column(Text, default="[]")

    created_at = Column(DateTime, default=datetime.utcnow)

    execution = relationship("RunExecution", back_populates="iterations")


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, default="")
    enabled = Column(Boolean, default=True)
    # "interval" (every N seconds) or "cron" (5-field expression)
    trigger_type = Column(String, default="interval")
    interval_seconds = Column(Integer, nullable=True)
    cron_expr = Column(String, default="")

    # What to execute — mirrors HTTPInvokeRequest so we can reuse invoke logic.
    provider_id = Column(Integer, nullable=True)
    endpoint_id = Column(Integer, nullable=True)
    method = Column(String, default="")
    url = Column(String, default="")
    path = Column(String, default="")
    headers_json = Column(Text, default="{}")
    query_json = Column(Text, default="{}")
    body_json = Column(Text, default="")  # JSON-encoded: string | object | null
    body_type = Column(String, default="json")

    last_run_at = Column(DateTime, nullable=True)
    last_ok = Column(Boolean, nullable=True)
    last_status_code = Column(Integer, nullable=True)
    last_latency_ms = Column(Integer, nullable=True)
    last_error = Column(Text, default="")
    next_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Webhook(Base):
    __tablename__ = "webhooks"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False, default="")
    notes = Column(Text, default="")
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    events = relationship(
        "WebhookEvent",
        back_populates="webhook",
        cascade="all, delete-orphan",
        order_by="WebhookEvent.id.desc()",
    )


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(Integer, primary_key=True, index=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id"), nullable=False, index=True)
    method = Column(String, default="POST")
    path = Column(String, default="")  # any extra path after /hook/<slug>/...
    query_string = Column(Text, default="")
    headers_json = Column(Text, default="{}")
    body_text = Column(Text, default="")
    content_type = Column(String, default="")
    source_ip = Column(String, default="")
    received_at = Column(DateTime, default=datetime.utcnow, index=True)

    webhook = relationship("Webhook", back_populates="events")


class HistoryEntry(Base):
    __tablename__ = "history"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, nullable=False)  # "http" | "graphql"
    provider_id = Column(Integer, nullable=True)
    provider_name = Column(String, default="")
    label = Column(String, default="")  # preview label: model id / endpoint name / method+url
    status_code = Column(Integer, default=0)
    ok = Column(Boolean, default=False)
    latency_ms = Column(Integer, default=0)
    request_json = Column(Text, default="{}")
    response_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
