"""One access policy for semantic searches and identifier/parent lookups."""

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue


def build_org_access_filter(
    organisation_id: str | None,
    org_idcc_list: list[str] | None = None,
) -> Filter | None:
    # Only explicit administrative callers may omit the organisation.
    if not organisation_id:
        return None
    ccn_types = ["convention_collective_nationale", "accord_branche"]
    should = [
        FieldCondition(key="organisation_id", match=MatchValue(value=organisation_id)),
        Filter(
            must=[FieldCondition(key="organisation_id", match=MatchValue(value="common"))],
            must_not=[FieldCondition(key="source_type", match=MatchAny(any=ccn_types))],
        ),
    ]
    if org_idcc_list:
        for source_type in ccn_types:
            should.append(
                Filter(
                    must=[
                        FieldCondition(key="organisation_id", match=MatchValue(value="common")),
                        FieldCondition(key="source_type", match=MatchValue(value=source_type)),
                        FieldCondition(key="idcc", match=MatchAny(any=org_idcc_list)),
                    ]
                )
            )
    return Filter(should=should)
