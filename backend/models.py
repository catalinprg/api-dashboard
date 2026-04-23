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
