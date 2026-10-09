from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

Service = Literal["Education & Student Performance", "CCTV & Surveillance", "Cybersecurity", "Cloud & Infrastructure", "Managed IT Support", "Software Development", "Data & AI", "Quotation & Invoice Verification", "Not sure yet"]
Status = Literal["new", "in_progress", "waiting", "closed"]

class Enquiry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr = Field(max_length=150)
    service: Service
    requirements: str = Field(min_length=10, max_length=4000)
    organization: str = Field(default="", max_length=120)
    phone: str = Field(default="", max_length=40)
    timeline: str = Field(default="", max_length=80)
    site_type: str = Field(default="", max_length=100)
    existing_system: str = Field(default="", max_length=100)
    coverage_areas: str = Field(default="", max_length=1000)
    service_context: str = Field(default="",max_length=1000)
    consent: Literal[True]
    website: str = Field(default="", max_length=200)

    @field_validator("consent", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("Consent must be explicitly accepted")
        return value

    @field_validator("name", "organization", "phone", "timeline", "site_type", "existing_system")
    @classmethod
    def clean_single_line(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError("Please use a single line")
        return value

    @model_validator(mode="after")
    def cctv_only(self):
        if self.service != "CCTV & Surveillance":
            self.site_type = self.existing_system = self.coverage_areas = ""
        return self

class Login(BaseModel):
    otp: str = Field(default="",max_length=6)
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=1, max_length=512)

class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status

class Note(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=2000)
