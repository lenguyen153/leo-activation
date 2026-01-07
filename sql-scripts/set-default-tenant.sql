-- Set default tenant to 'master app' if it does not exist
INSERT INTO tenant(tenant_name)
SELECT
	'master app'
WHERE
	NOT EXISTS(
		SELECT
			1
		FROM
			tenant
		WHERE
			tenant_name = 'master app'
	);

-- Set the current tenant to 'master app'
BEGIN;
SELECT
	set_config(
		'app.current_tenant_id'
	,	(
			SELECT
				tenant_id::text
			FROM
				tenant
			WHERE
				tenant_name = 'master app'
		)
	,	FALSE
	);
COMMIT;