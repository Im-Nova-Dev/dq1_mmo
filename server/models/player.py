from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)
    username: str = Field(min_length=2, max_length=24)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Username must be at least 2 characters")
        if len(v) > 24:
            raise ValueError("Username too long")
        if not all(ch.isalnum() or ch in "_-" for ch in v):
            raise ValueError("Username may only use letters, numbers, _ and -")
        return v

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password too long")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v


class PasswordChange(BaseModel):
    """Change password for an authenticated local account."""

    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=6, max_length=72)

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password too long")
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str


class CharacterCreate(BaseModel):
    name: str = Field(min_length=2, max_length=16)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        v = " ".join(v.split())  # collapse whitespace
        if len(v) < 2:
            raise ValueError("Name must be at least 2 characters")
        if len(v) > 16:
            raise ValueError("Name too long")
        if not all(ch.isalnum() or ch in "_- " for ch in v):
            raise ValueError("Name may only use letters, numbers, spaces, _ and -")
        if v.strip() != v or "  " in v:
            raise ValueError("Invalid name spacing")
        # Block spoofing system / staff chat identity
        reserved = {
            "system",
            "admin",
            "server",
            "gm",
            "moderator",
            "console",
            "god",
            "null",
            "undefined",
            "npc",
            "staff",
            "owner",
            "root",
            "dragonlord",
        }
        if v.casefold() in reserved:
            raise ValueError("That name is reserved")
        return v


class CharacterOut(BaseModel):
    id: int
    name: str
    level: int
    experience: int
    strength: int
    agility: int
    max_hp: int
    max_mp: int
    current_hp: int
    current_mp: int
    gold: str
    world_x: float
    world_y: float
    map_id: int
    equipment_weapon: str | None = None
    equipment_armor: str | None = None
    equipment_shield: str | None = None
    equipment_helmet: str | None = None


class UserOut(BaseModel):
    id: int
    email: str
    username: str
