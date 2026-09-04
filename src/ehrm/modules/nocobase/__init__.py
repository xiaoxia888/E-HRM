"""NocoBase application and rights-statement integration."""

from ehrm.modules.nocobase.auth_client import NocoBaseAuthClient
from ehrm.modules.nocobase.auth_session import NocoBaseAuthSession
from ehrm.modules.nocobase.credential_store import NocoBaseCredentialStore
from ehrm.modules.nocobase.models import (
    NocoBaseCredentials,
    NocoBaseLoginResult,
    NocoBasePageMeta,
    NocoBaseProblemType,
    NocoBaseRightsApplication,
    NocoBaseRightsApplicationDetail,
    NocoBaseRightsApplicationPage,
    NocoBaseRelatedPerson,
    NocoBaseTokenClaims,
    NocoBaseUser,
)
from ehrm.modules.nocobase.token_store import (
    create_nocobase_token_manager,
)
from ehrm.modules.nocobase.rights_application_client import (
    NocoBaseRightsApplicationClient,
)

__all__ = [
    "NocoBaseAuthClient",
    "NocoBaseAuthSession",
    "NocoBaseCredentials",
    "NocoBaseCredentialStore",
    "NocoBaseLoginResult",
    "NocoBasePageMeta",
    "NocoBaseProblemType",
    "NocoBaseRightsApplication",
    "NocoBaseRightsApplicationDetail",
    "NocoBaseRightsApplicationClient",
    "NocoBaseRightsApplicationPage",
    "NocoBaseRelatedPerson",
    "NocoBaseTokenClaims",
    "NocoBaseUser",
    "create_nocobase_token_manager",
]
