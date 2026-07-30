"""Compatibility imports for shared revision primitives."""
from services.revisions import (TouchedEntities, bump_existing, check_entity_revision,
                                claim_project_revision, revision_conflict)

__all__ = ["TouchedEntities", "bump_existing", "check_entity_revision",
           "claim_project_revision", "revision_conflict"]
