from datetime import datetime, timezone
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)
    data_dir: Path = Field(default=Path(".arena"), validation_alias="ARENA_DATA_DIR")
    submission_deadline: datetime = datetime(2026, 12, 31, 15, 59, 59, tzinfo=timezone.utc)
    max_inline_bytes: int = 5 * 1024 * 1024
    staff_userids: str = ""
    admin_userids: str = ""
    policy_release: str = Field(default="demo-unpublished", validation_alias="ARENA_POLICY_RELEASE")
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    llm_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("LLM_API_KEY", "DEEPSEEK_API_KEY")
    )
    wecom_bot_id: str = ""
    wecom_bot_secret: SecretStr = SecretStr("")

    @field_validator("submission_deadline")
    @classmethod
    def aware_deadline(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("SUBMISSION_DEADLINE 必须带时区")
        return value

    def role(self, userid: str) -> str:
        if userid in self.admin_userids.split(",") and userid:
            return "admin"
        if userid in self.staff_userids.split(",") and userid:
            return "staff"
        return "participant"
