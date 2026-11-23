"""Model registry for Alembic autogenerate: importing this registers every table on Base.metadata.

Agent run tables (`orch_*`) are owned by Person 2 on a separate MetaData; see docs/DATABASE.md.
"""

from .. import models as _models  # noqa: F401
from .base import Base  # noqa: F401
