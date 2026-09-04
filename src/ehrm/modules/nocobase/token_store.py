from __future__ import annotations

from pathlib import Path

from ehrm.browser.access_token import AccessTokenManager
from ehrm.core.auth_repository import (
    AuthenticationRepository,
    LOCAL_OWNER_ID,
    RepositorySessionStore,
    SystemType,
)
from ehrm.modules.nocobase.jwt_token import decode_jwt_claims


def create_nocobase_token_manager(
    database_path: Path,
    account: str,
    *,
    password: str = "",
    owner_id: str = LOCAL_OWNER_ID,
) -> AccessTokenManager:
    repository = AuthenticationRepository(database_path)
    saved = repository.get_account(
        SystemType.NOCOBASE,
        account,
        owner_id=owner_id,
    )
    if saved is None:
        saved = repository.save_account(
            SystemType.NOCOBASE,
            account,
            password,
            owner_id=owner_id,
        )
    elif password and password != saved.password:
        saved = repository.save_account(
            SystemType.NOCOBASE,
            account,
            password,
            owner_id=owner_id,
        )
    return AccessTokenManager(
        str(saved.id),
        RepositorySessionStore(
            repository,
            saved.id,
            expires_at_resolver=(
                lambda token: decode_jwt_claims(token).expires_at
            ),
        ),
    )
