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
    kind: str = "llm"  # llm | http
    base_url: str
    auth_type: str = "bearer"
    auth_header_name: str = "Authorization"
    auth_prefix: str = "Bearer "
    auth_query_param: str = ""
    default_model: str = ""
    models: List[str] = Field(default_factory=list)
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
    default_model: Optional[str] = None
    models: Optional[List[str]] = None
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


class LLMInvokeRequest(BaseModel):
    provider_id: int
    session_id: Optional[int] = None  # if set, message is saved and assistant reply appended
    model: Optional[str] = None
    messages: List[Dict[str, Any]]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: bool = False
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Any] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: Any
    created_at: str


class ChatSessionBase(BaseModel):
    name: str = "New chat"
    provider_id: Optional[int] = None
    model: str = ""
    system_prompt: str = ""
    temperature: str = "0.7"
    max_tokens: Optional[int] = None
    tools: List[Dict[str, Any]] = Field(default_factory=list)


class ChatSessionCreate(ChatSessionBase):
    pass


class ChatSessionUpdate(BaseModel):
    name: Optional[str] = None
    provider_id: Optional[int] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    temperature: Optional[str] = None
    max_tokens: Optional[int] = None
    tools: Optional[List[Dict[str, Any]]] = None


class ChatSessionOut(ChatSessionBase):
    id: int
    created_at: str
    updated_at: str
    message_count: int = 0
    messages: List[ChatMessageOut] = []


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
