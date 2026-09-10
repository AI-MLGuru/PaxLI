"""Out-of-band credential bootstrap.

Issues a credential directly against the database, bypassing the HTTP
management API. This exists because credential issuance over HTTP requires
an existing administrative credential (SEC-7.12.1); an operator uses this
script once per tenant to mint that first administrative credential.

Usage:
    python -m scripts.issue_credential --tenant-id acme --name "acme-admin" --scope ADMINISTRATIVE
"""

import argparse
import asyncio
from datetime import timedelta

from core.security.credentials import CredentialService
from core.security.models import CredentialScope
from infrastructure.database.repositories.credential import SqlAlchemyCredentialStore
from infrastructure.database.session import session_factory
from infrastructure.security.hashing import ScryptSecretHasher


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--scope", choices=[scope.value for scope in CredentialScope], default="ADMINISTRATIVE"
    )
    parser.add_argument("--expires-in-days", type=int, default=None)
    args = parser.parse_args()

    async with session_factory() as db_session:
        service = CredentialService(SqlAlchemyCredentialStore(db_session), ScryptSecretHasher())
        issued = await service.issue(
            tenant_id=args.tenant_id,
            name=args.name,
            scope=CredentialScope(args.scope),
            expires_in=timedelta(days=args.expires_in_days) if args.expires_in_days else None,
        )
        await db_session.commit()

    print(f"credential_id: {issued.credential_id}")
    print(f"tenant_id:     {issued.tenant_id}")
    print(f"scope:         {issued.scope.value}")
    print(f"secret:        {issued.secret}")
    print("This secret is shown once. Store it now; it cannot be retrieved again.")


if __name__ == "__main__":
    asyncio.run(main())
