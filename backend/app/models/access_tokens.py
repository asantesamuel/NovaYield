"""Database-backed authentication session documents (NY-11)."""

from fastapi_users_db_beanie.access_token import BeanieBaseAccessTokenDocument

from app.database.registry import register_document_model

ACCESS_TOKEN_COLLECTION_NAME = "access_tokens"


@register_document_model
class AccessToken(BeanieBaseAccessTokenDocument):
    """A revocable session token referencing its owner by MongoDB ObjectId."""

    class Settings(BeanieBaseAccessTokenDocument.Settings):
        name = ACCESS_TOKEN_COLLECTION_NAME
