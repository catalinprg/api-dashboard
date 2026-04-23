from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field


class EndpointBase(BaseModel):
    name: str
    method: str = "POST"
    path: str
    description: str = ""
    auth_mode: str = "inherit"  # inherit | override | none


class EndpointCreate(EndpointBase):
    api_key: Optional[str] = None  # None = no change / leave as-is; "" = clear; non-empty = set


class EndpointOut(EndpointBase):
    id: int
    provider_id: int
    has_api_key: bool = False
    api_key_preview: str = ""

    class Config:
        from_attributes = True


class ProviderBase(BaseModel):
    name: str
    kind: str = "http"  # http | graphql
    base_url: str
    auth_type: str = "bearer"
    auth_header_name: str = "Authorization"
    auth_prefix: str = "Bearer "
    auth_query_param: str = ""
    extra_headers: str = "{}"
    variables: str = "{}"  # JSON string of {var_name: value}
    # OAuth 2.0 client-credentials (client_secret lives in api_key)
    oauth_client_id: str = ""
    oauth_token_url: str = ""
    oauth_scope: str = ""
    oauth_auth_style: str = "body"  # "body" | "basic"
    enabled: bool = True
    notes: str = ""


class ProviderCreate(ProviderBase):
    api_key: str = ""
    endpoints: List[EndpointCreate] = []


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    base_url: Optional[str] = None
    auth_type: Optional[str] = None
    auth_header_name: Optional[str] = None
    auth_prefix: Optional[str] = None
    auth_query_param: Optional[str] = None
    extra_headers: Optional[str] = None
    variables: Optional[str] = None
    oauth_client_id: Optional[str] = None
    oauth_token_url: Optional[str] = None
    oauth_scope: Optional[str] = None
    oauth_auth_style: Optional[str] = None
    enabled: Optional[bool] = None
    notes: Optional[str] = None
    api_key: Optional[str] = None  # if provided, re-encrypt; empty string = clear


class ProviderOut(ProviderBase):
    id: int
    has_api_key: bool
    api_key_preview: str = ""
    endpoints: List[EndpointOut] = []

    class Config:
        from_attributes = True


class HTTPInvokeRequest(BaseModel):
    provider_id: Optional[int] = None
    endpoint_id: Optional[int] = None  # if set, method+path come from this endpoint
    method: Optional[str] = None
    url: Optional[str] = None  # full override
    path: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    query: Dict[str, str] = Field(default_factory=dict)
    body: Optional[Any] = None
    body_type: str = "json"  # json | text | form


class GraphQLInvokeRequest(BaseModel):
    provider_id: int
    query: str
    variables: Optional[Dict[str, Any]] = None
    operation_name: Optional[str] = None


class RequestEcho(BaseModel):
    method: str
    url: str
    headers: Dict[str, str]  # Authorization is masked
    query: Dict[str, str] = Field(default_factory=dict)
    body: Optional[Any] = None


class InvokeResponse(BaseModel):
    ok: bool
    status_code: int
    latency_ms: int
    headers: Dict[str, str]
    body: Any
    error: Optional[str] = None
    request: Optional[RequestEcho] = None


class PresetBase(BaseModel):
    name: str
    provider_id: Optional[int] = None
    endpoint_id: Optional[int] = None
    method: str = "GET"
    url: str = ""
    path: str = ""
    headers: Dict[str, str] = Field(default_factory=dict)
    query: Dict[str, str] = Field(default_factory=dict)
    body: Any = None
    body_type: str = "json"
    notes: str = ""


class PresetCreate(PresetBase):
    pass


class PresetUpdate(BaseModel):
    name: Optional[str] = None
    provider_id: Optional[int] = None
    endpoint_id: Optional[int] = None
    method: Optional[str] = None
    url: Optional[str] = None
    path: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    query: Optional[Dict[str, str]] = None
    body: Optional[Any] = None
    body_type: Optional[str] = None
    notes: Optional[str] = None


class PresetOut(PresetBase):
    id: int
    created_at: str
    updated_at: str


class RunAssertions(BaseModel):
    """Assertion rules applied to each iteration."""
    expected_status: Optional[List[int]] = None  # e.g. [200, 201] — any match passes
    body_contains: Optional[str] = None          # substring must be present
    body_not_contains: Optional[str] = None      # substring must be absent


class RunBase(BaseModel):
    name: str = ""
    notes: str = ""
    provider_id: Optional[int] = None
    endpoint_id: Optional[int] = None
    method: str = "GET"
    url: str = ""
    path: str = ""
    headers: Dict[str, str] = Field(default_factory=dict)
    query: Dict[str, str] = Field(default_factory=dict)
    body: Optional[Any] = None
    body_type: str = "json"
    data_format: str = "csv"  # csv | tsv | json
    data_content: str = ""
    delay_ms: int = 0
    stop_on_error: bool = False
    max_rows: Optional[int] = None
    assertions: RunAssertions = Field(default_factory=RunAssertions)


class RunCreate(RunBase):
    pass


class RunUpdate(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None
    provider_id: Optional[int] = None
    endpoint_id: Optional[int] = None
    method: Optional[str] = None
    url: Optional[str] = None
    path: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    query: Optional[Dict[str, str]] = None
    body: Optional[Any] = None
    body_type: Optional[str] = None
    data_format: Optional[str] = None
    data_content: Optional[str] = None
    delay_ms: Optional[int] = None
    stop_on_error: Optional[bool] = None
    max_rows: Optional[int] = None
    assertions: Optional[RunAssertions] = None


class RunOut(RunBase):
    id: int
    created_at: str
    updated_at: str
    last_execution_id: Optional[int] = None
    last_execution_status: Optional[str] = None


class RunIterationOut(BaseModel):
    id: int
    execution_id: int
    row_index: int
    variables: Dict[str, Any]
    method: str
    url: str
    status_code: int
    latency_ms: int
    ok: bool
    passed: bool
    error: str
    response_preview: str
    assertion_results: List[Dict[str, Any]]
    created_at: str


class RunExecutionOut(BaseModel):
    id: int
    run_id: int
    status: str
    started_at: str
    finished_at: Optional[str] = None
    error: str
    total_rows: int
    completed_rows: int
    succeeded: int
    failed: int
    assertions: RunAssertions


class RunExecutionDetail(RunExecutionOut):
    iterations: List[RunIterationOut] = []


class ScheduledJobBase(BaseModel):
    name: str = ""
    enabled: bool = True
    trigger_type: str = "interval"  # "interval" | "cron"
    interval_seconds: Optional[int] = None
    cron_expr: str = ""
    provider_id: Optional[int] = None
    endpoint_id: Optional[int] = None
    method: str = ""
    url: str = ""
    path: str = ""
    headers: Dict[str, str] = Field(default_factory=dict)
    query: Dict[str, str] = Field(default_factory=dict)
    body: Optional[Any] = None
    body_type: str = "json"


class ScheduledJobCreate(ScheduledJobBase):
    pass


class ScheduledJobUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    trigger_type: Optional[str] = None
    interval_seconds: Optional[int] = None
    cron_expr: Optional[str] = None
    provider_id: Optional[int] = None
    endpoint_id: Optional[int] = None
    method: Optional[str] = None
    url: Optional[str] = None
    path: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    query: Optional[Dict[str, str]] = None
    body: Optional[Any] = None
    body_type: Optional[str] = None


class ScheduledJobOut(ScheduledJobBase):
    id: int
    last_run_at: Optional[str] = None
    last_ok: Optional[bool] = None
    last_status_code: Optional[int] = None
    last_latency_ms: Optional[int] = None
    last_error: str = ""
    next_run_at: Optional[str] = None
    created_at: str
    updated_at: str


class WebhookCreate(BaseModel):
    name: str = ""
    notes: str = ""


class WebhookUpdate(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None
    enabled: Optional[bool] = None


class WebhookOut(BaseModel):
    id: int
    slug: str
    name: str
    notes: str
    enabled: bool
    created_at: str
    event_count: int = 0
    last_event_at: Optional[str] = None


class WebhookEventOut(BaseModel):
    id: int
    webhook_id: int
    method: str
    path: str
    query_string: str
    headers: Dict[str, str]
    body: str
    content_type: str
    source_ip: str
    received_at: str


class HistoryOut(BaseModel):
    id: int
    kind: str
    provider_id: Optional[int] = None
    provider_name: str = ""
    label: str = ""
    status_code: int
    ok: bool
    latency_ms: int
    created_at: str
    request: Dict[str, Any] = Field(default_factory=dict)
    response: Dict[str, Any] = Field(default_factory=dict)
