"""Contact identity is independent of login credentials and recovery channels."""
import unicodedata

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator


def clean_name(value: str, *, allow_empty: bool = False) -> str:
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        raise ValueError('Invalid name') from None
    if any(unicodedata.category(char) in {'Cc', 'Cs'} and not char.isspace() for char in value):
        raise ValueError('Invalid name')
    value = ' '.join(value.split())
    if (not value and not allow_empty) or (value and not any(char.isalnum() for char in value)):
        raise ValueError('Invalid name')
    return value


def contact_email(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    if len(value.strip()) > 320:
        raise HTTPException(422, {'code': 'invalid_email'})
    try:
        return validate_email(value.strip(), check_deliverability=False).normalized
    except (EmailNotValidError, UnicodeError):
        raise HTTPException(422, {'code': 'invalid_email'}) from None


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    first_name: str = Field(default='', max_length=120)
    last_name: str = Field(default='', max_length=120)
    email: str | None = Field(default=None, max_length=320)

    @field_validator('first_name', 'last_name')
    @classmethod
    def valid_name(cls, value):
        return clean_name(value, allow_empty=True)

    @field_validator('email', mode='before')
    @classmethod
    def valid_email(cls, value):
        return contact_email(value) if value is None or isinstance(value, str) else value


def identity_values(previous: dict, changes: dict) -> dict:
    values = {field: changes.get(field, previous[field]) for field in ('first_name', 'last_name', 'email')}
    if {'first_name', 'last_name'} & changes.keys():
        values['display_name'] = ' '.join(filter(None, (values['first_name'], values['last_name']))) or previous['username']
    else:
        values['display_name'] = changes.get('display_name', previous['display_name'])
    return values


def identity_conflict(error) -> HTTPException:
    code = 'email_in_use' if error.diag.constraint_name == 'auth_users_email_lower_unique' else 'username_in_use'
    return HTTPException(409, {'code': code})
