"""Request and response shapes. FastAPI uses these to validate input and build the API docs."""
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# ---- auth
class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=72)


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    telegram_chat_id: str | None = None

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SettingsIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    telegram_chat_id: str | None = Field(default=None, max_length=64)


# ---- holdings
class HoldingIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    quantity: float = Field(gt=0)
    avg_price: float = Field(ge=0)
    sector: str | None = Field(default=None, max_length=80)

    @field_validator("symbol")
    @classmethod
    def upper(cls, v: str) -> str:
        return v.strip().upper()


class HoldingOut(BaseModel):
    id: int
    symbol: str
    name: str
    sector: str
    quantity: float
    avg_price: float

    model_config = {"from_attributes": True}


class UploadOut(BaseModel):
    detected_format: str
    imported: int
    warnings: list[str]
    holdings: list[HoldingOut]


# ---- scenarios
class SectorShockIn(BaseModel):
    sector: str
    drop_pct: float = Field(gt=0, le=100)
    knock_on: bool = True


class MarketShockIn(BaseModel):
    drop_pct: float = Field(gt=0, le=100)


class CustomShockIn(BaseModel):
    shocks: dict[str, float]  # symbol -> % move, negative = fall


class HistoricalIn(BaseModel):
    event: str


# ---- chat
class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str = Field(max_length=4000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


class ToolCallOut(BaseModel):
    tool: str
    args: dict


class ChatOut(BaseModel):
    answer: str
    tool_calls: list[ToolCallOut]
    mode: str  # "gemini" or "offline"


# ---- alerts
class AlertOut(BaseModel):
    id: int
    kind: str
    severity: str
    symbol: str | None
    title: str
    body: str
    url: str | None
    read: bool
    sent_telegram: bool
    created_at: datetime

    model_config = {"from_attributes": True}
