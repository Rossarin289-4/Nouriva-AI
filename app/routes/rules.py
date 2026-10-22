
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/rules", tags=["Rules"])


@router.get("")
def get_rules(
    category: Optional[str] = None,
    lifecycle_status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = """
        SELECT
            rule_definition_id,
            rule_code,
            version,
            category,
            rule_name,
            purpose,
            required_inputs,
            preconditions,
            decision_logic,
            success_behavior,
            failure_behavior,
            exceptions,
            source_locator,
            test_case_ids,
            implementation_key,
            lifecycle_status,
            effective_from,
            effective_to,
            reviewed_at,
            created_at,
            updated_at
        FROM rule_definitions
    """

    conditions = []
    params = {"limit": limit}

    if category is not None:
        conditions.append("category = :category")
        params["category"] = category

    if lifecycle_status is not None:
        conditions.append("lifecycle_status = :lifecycle_status")
        params["lifecycle_status"] = lifecycle_status

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += """
        ORDER BY category, rule_code, version DESC
        LIMIT :limit
    """

    result = db.execute(text(query), params)
    rules = [dict(row) for row in result.mappings().all()]

    return {
        "count": len(rules),
        "items": rules,
    }


@router.get("/{rule_code}")
def get_rule_by_code(
    rule_code: str,
    db: Session = Depends(get_db),
):
    query = text("""
        SELECT *
        FROM rule_definitions
        WHERE rule_code = :rule_code
        ORDER BY version DESC
        LIMIT 1
    """)

    result = db.execute(
        query,
        {"rule_code": rule_code}
    ).mappings().first()

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Rule not found"
        )

    return dict(result)

