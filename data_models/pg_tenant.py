import logging
import psycopg

logger = logging.getLogger(__name__)

DEFAULT_TENANT_NAME = "master app"


def resolve_and_set_default_tenant(
    conn: psycopg.Connection,
    tenant_name: str = DEFAULT_TENANT_NAME,
) -> str:
    """
    Resolves tenant_id by tenant_name and sets
    app.current_tenant_id for the session (RLS-aware).

    Returns tenant_id as string.
    """

    sql_resolve = """
        SELECT tenant_id
        FROM tenant
        WHERE tenant_name = %s
        LIMIT 1
    """

    sql_set_context = """
        SELECT set_config('app.current_tenant_id', %s, false)
    """

    with conn.cursor() as cur:
        cur.execute(sql_resolve, (tenant_name,))
        row = cur.fetchone()

        if not row:
            raise RuntimeError(
                f"Default tenant '{tenant_name}' not found in DB"
            )

        tenant_id = str(row[0])

        cur.execute(sql_set_context, (tenant_id,))

    conn.commit()

    logger.info(
        "Postgres session configured for tenant '%s' (%s)",
        tenant_name,
        tenant_id,
    )

    return tenant_id
