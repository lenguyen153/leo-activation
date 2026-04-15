"""
Translates a JSONB condition tree into a SQL WHERE clause (+ bind params)
for bulk audience queries against cdp_profiles / product_recommendations.

Condition tree grammar
----------------------
Node   = LogicalNode | LeafNode
LogicalNode = {"operator": "AND"|"OR"|"NOT", "conditions": [Node, ...]}
LeafNode    = {"field": str, "op": str, "value": any}

Field paths
-----------
- Plain column:              "primary_email"
- JSONB drill-down:          "event_statistics.last_login_at"
- Cross-table (product_rec): "product_recommendations.interest_score"
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Maps leaf op → SQL fragment template.
# {col} is replaced by the resolved column expression.
# {param} is replaced by the bind-param placeholder.
_OP_SQL = {
    "eq":              "{col} = {param}",
    "neq":             "{col} != {param}",
    "gt":              "{col} > {param}",
    "gte":             "{col} >= {param}",
    "lt":              "{col} < {param}",
    "lte":             "{col} <= {param}",
    "in":              "{col} = ANY({param})",
    "contains":        "{col} @> {param}::jsonb",
    "not_contains":    "NOT ({col} @> {param}::jsonb)",
    "is_null":         "{col} IS NULL",
    "is_not_null":     "{col} IS NOT NULL",
    "older_than_days": "{col} < NOW() - make_interval(days => {param})",
    "newer_than_days": "{col} > NOW() - make_interval(days => {param})",
    # Array / list predicates on JSONB arrays (e.g. ext_data.abandoned_tickers)
    "has_items":       "jsonb_array_length(COALESCE({col}, '[]'::jsonb)) > 0",
    "is_empty":        "jsonb_array_length(COALESCE({col}, '[]'::jsonb)) = 0",
}

# Fields that live in product_recommendations (triggers a JOIN).
_PRODUCT_REC_FIELDS = {
    "product_recommendations.interest_score",
    "product_recommendations.raw_score",
    "product_recommendations.recommendation_context",
    "product_recommendations.product_id",
    "product_recommendations.last_interaction_at",
}

# Top-level columns on cdp_profiles that are NOT JSONB.
_PLAIN_COLUMNS = {
    "profile_id", "primary_email", "primary_phone", "first_name",
    "last_name", "living_location", "living_country", "living_city",
    "portfolio_risk_score", "portfolio_last_evaluated_at",
}


class ConditionEvaluator:
    """Build a SQL WHERE clause from a condition tree."""

    def __init__(self):
        self._params: dict[str, Any] = {}
        self._counter: int = 0
        self.needs_product_join: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def to_sql(self, tree: dict) -> tuple[str, dict[str, Any]]:
        """
        Returns (where_clause, bind_params).
        Call once per rule — instance is not reusable.
        """
        clause = self._walk(tree)
        return clause, self._params

    # ------------------------------------------------------------------
    # Tree walker
    # ------------------------------------------------------------------

    def _walk(self, node: dict) -> str:
        if "operator" in node:
            return self._walk_logical(node)
        return self._walk_leaf(node)

    def _walk_logical(self, node: dict) -> str:
        op = node["operator"].upper()
        children = node.get("conditions", [])

        if op == "NOT":
            if len(children) != 1:
                raise ValueError("NOT operator requires exactly 1 child condition")
            return f"NOT ({self._walk(children[0])})"

        if op not in ("AND", "OR"):
            raise ValueError(f"Unknown logical operator: {op}")

        parts = [self._walk(c) for c in children]
        joined = f" {op} ".join(f"({p})" for p in parts)
        return joined

    def _walk_leaf(self, node: dict) -> str:
        field: str = node["field"]
        op: str = node["op"]
        value = node.get("value")

        sql_tpl = _OP_SQL.get(op)
        if sql_tpl is None:
            raise ValueError(f"Unsupported operator: {op}")

        _NUMERIC_OPS = {"gt", "gte", "lt", "lte"}
        _TIME_OPS = {"older_than_days", "newer_than_days"}
        _ARRAY_OPS = {"has_items", "is_empty"}

        # Array ops need the raw jsonb value (->) not text (->>).
        as_jsonb = op in _ARRAY_OPS
        col_expr = self._resolve_column(field, as_jsonb=as_jsonb)

        is_jsonb_path = "->>" in col_expr

        if is_jsonb_path and op in _NUMERIC_OPS:
            col_expr = f"({col_expr})::numeric"
        elif is_jsonb_path and op in _TIME_OPS:
            col_expr = f"({col_expr})::timestamptz"

        # Operators that take no value
        if op in ("is_null", "is_not_null", "has_items", "is_empty"):
            return sql_tpl.format(col=col_expr)

        param_name = self._next_param()

        # For contains/not_contains on JSONB arrays, wrap value for @> operator.
        # Segments are stored as [{"name": "..."}] objects, so "contains" on
        # the segments column wraps as [{"name": value}] instead of ["value"].
        if op in ("contains", "not_contains"):
            import json
            if field == "segments" and isinstance(value, str):
                self._params[param_name] = json.dumps([{"name": value}])
            elif isinstance(value, str):
                self._params[param_name] = json.dumps([value])
            else:
                self._params[param_name] = json.dumps(value)
        else:
            self._params[param_name] = value

        return sql_tpl.format(col=col_expr, param=f"%({param_name})s")

    # ------------------------------------------------------------------
    # Column resolution
    # ------------------------------------------------------------------

    def _resolve_column(self, field: str, as_jsonb: bool = False) -> str:
        """
        Map a field path to a SQL column expression.
        If as_jsonb=True, emit -> for the leaf so we get jsonb value (for array ops).
        Otherwise emit ->> for the leaf (text, for comparisons).
        """
        # Cross-table: product_recommendations.*
        if field.startswith("product_recommendations."):
            self.needs_product_join = True
            col = field.split(".", 1)[1]
            return f"pr.{col}"

        # Plain top-level column on cdp_profiles
        if field in _PLAIN_COLUMNS:
            return f"p.{field}"

        parts = field.split(".")
        if len(parts) == 1:
            # Top-level JSONB column (segments, identities, etc.)
            return f"p.{parts[0]}"

        # Nested: first part is column, rest is JSONB path
        column = parts[0]
        json_path = parts[1:]

        expr = f"p.{column}"
        for i, key in enumerate(json_path):
            is_leaf = i == len(json_path) - 1
            if is_leaf and not as_jsonb:
                expr = f"({expr})->>'{key}'"
            else:
                expr = f"({expr})->'{key}'"
        return expr

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_param(self) -> str:
        self._counter += 1
        return f"p{self._counter}"
