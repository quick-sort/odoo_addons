"""PostgreSQL control-plane adapter with detect-only extension handling."""

import json
import secrets

from odoo import _, fields
from odoo.exceptions import UserError

from odoo.addons.component.core import Component
from odoo.addons.component.exception import NoComponentError

SCHEMA_NAME = "llm_data"
TABLE_NAME = "records"
CONNECT_TIMEOUT = 15


class PostgreSQLStoreAdapter(Component):
    _name = "postgresql.store.adapter"
    _inherit = "llm.store.adapter"
    _usage = "postgresql"

    def _psycopg2(self):
        try:
            import psycopg2
            from psycopg2 import sql
            from psycopg2.extras import Json
        except ImportError as error:
            raise UserError(
                _("The psycopg2 Python package is required by llm_pg.")
            ) from error
        return psycopg2, sql, Json

    def _connection_parameters(
        self, store, database=None, maintenance=False, application=False
    ):
        psycopg2, _sql, _json = self._psycopg2()
        if application and database and database.connection_uri:
            dsn = database.connection_uri
        else:
            dsn = store.connection_uri
        if not dsn:
            raise UserError(_("PostgreSQL store '%s' has no connection URI.", store.name))
        try:
            parameters = psycopg2.extensions.parse_dsn(dsn)
        except Exception as error:
            raise UserError(_("The PostgreSQL connection URI is invalid.")) from error

        if maintenance:
            parameters["dbname"] = store.pg_maintenance_database or "postgres"
        elif database and database.database_name:
            parameters["dbname"] = database.database_name

        if application and database:
            if database.database_user:
                parameters["user"] = database.database_user
            if database.database_secret:
                parameters["password"] = database.database_secret
        else:
            if store.admin_user:
                parameters["user"] = store.admin_user
            if store.api_key:
                parameters["password"] = store.api_key
        parameters["connect_timeout"] = CONNECT_TIMEOUT
        return parameters

    def _connect(
        self,
        store,
        database=None,
        maintenance=False,
        application=False,
        autocommit=False,
    ):
        psycopg2, _sql, _json = self._psycopg2()
        connection = psycopg2.connect(
            **self._connection_parameters(
                store,
                database=database,
                maintenance=maintenance,
                application=application,
            )
        )
        connection.autocommit = autocommit
        return connection

    def _data_plane_dsn(self, store, database):
        psycopg2, _sql, _json = self._psycopg2()
        parameters = self._connection_parameters(store, database=database)
        parameters.pop("password", None)
        parameters["dbname"] = database.database_name
        parameters["user"] = database.database_user
        parameters.pop("connect_timeout", None)
        return psycopg2.extensions.make_dsn(**parameters)

    def _capability_lines(self, database):
        lines = database._pg_enabled_capabilities()
        by_code = {line.capability_id.code: line for line in lines}
        selected = set(by_code)
        for line in lines:
            missing = set(line.capability_id.dependency_codes or []) - selected
            if missing:
                raise UserError(
                    _(
                        "Capability '%(capability)s' requires: %(dependencies)s.",
                        capability=line.capability_id.name,
                        dependencies=", ".join(sorted(missing)),
                    )
                )

        ordered = []
        resolved = set()
        remaining = dict(by_code)
        while remaining:
            ready = [
                (code, line)
                for code, line in remaining.items()
                if set(line.capability_id.dependency_codes or []).issubset(resolved)
            ]
            if not ready:
                raise UserError(_("PostgreSQL capability dependencies contain a cycle."))
            ready.sort(key=lambda item: (item[1].capability_id.sequence, item[1].id))
            for code, line in ready:
                ordered.append(line.id)
                resolved.add(code)
                remaining.pop(code)
        return database.env["llm.pg.database.capability"].browse(ordered)

    def _capability_component(self, line):
        try:
            return self.component(usage=line.capability_id.component_usage)
        except NoComponentError as error:
            raise UserError(
                _(
                    "Capability adapter '%(usage)s' is not installed.",
                    usage=line.capability_id.component_usage,
                )
            ) from error

    def _required_extensions(self, store, database):
        requirements = {}
        for line in self._capability_lines(database):
            component = self._capability_component(line)
            for extension in component.required_extensions(store, database, line):
                requirements.setdefault(extension, []).append(line)
        return requirements

    def _sync_extension_status(
        self,
        store,
        database,
        extension_name,
        scope,
        available_version,
        installed_version,
        state,
        details=None,
    ):
        Status = store.env["llm.pg.extension.status"]
        domain = [
            ("store_id", "=", store.id),
            ("database_id", "=", database.id if database else False),
            ("scope", "=", scope),
            ("extension_name", "=", extension_name),
        ]
        status = Status.search(domain, limit=1)
        values = {
            "store_id": store.id,
            "database_id": database.id if database else False,
            "scope": scope,
            "extension_name": extension_name,
            "available_version": available_version,
            "installed_version": installed_version,
            "state": state,
            "details": details or {},
            "checked_at": fields.Datetime.now(),
        }
        if status:
            status.write(values)
        else:
            Status.create(values)

    def _probe_extension_rows(self, cursor, names):
        if not names:
            return {}
        cursor.execute(
            """
            SELECT available.name,
                   available.default_version,
                   installed.extversion
              FROM pg_available_extensions available
              LEFT JOIN pg_extension installed
                ON installed.extname = available.name
             WHERE available.name = ANY(%s)
            """,
            [list(names)],
        )
        return {
            name: {
                "available_version": available_version,
                "installed_version": installed_version,
            }
            for name, available_version, installed_version in cursor.fetchall()
        }

    def probe_server(self, store):
        capabilities = store.env["llm.pg.capability"].search([("active", "=", True)])
        extensions = sorted(
            {
                extension
                for capability in capabilities
                for extension in (capability.extension_names or [])
            }
        )
        try:
            connection = self._connect(store, maintenance=True)
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW server_version_num")
                    server_version = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        SELECT rolsuper, rolcreatedb, rolcreaterole
                          FROM pg_roles
                         WHERE rolname = current_user
                        """
                    )
                    privileges = cursor.fetchone() or (False, False, False)
                    rows = self._probe_extension_rows(cursor, extensions)
            finally:
                connection.close()

            store.write(
                {
                    "pg_server_version": server_version,
                    "pg_probe_state": "ready",
                    "pg_can_create_database": bool(privileges[0] or privileges[1]),
                    "pg_can_create_role": bool(privileges[0] or privileges[2]),
                    "pg_last_probe_at": fields.Datetime.now(),
                    "pg_last_probe_error": False,
                }
            )
            for extension in extensions:
                row = rows.get(extension)
                state = "unavailable"
                available_version = installed_version = False
                if row:
                    available_version = row["available_version"]
                    installed_version = row["installed_version"]
                    state = "installed" if installed_version else "available_not_installed"
                self._sync_extension_status(
                    store,
                    None,
                    extension,
                    "server",
                    available_version,
                    installed_version,
                    state,
                )
            return {
                "server_version": server_version,
                "can_create_database": store.pg_can_create_database,
                "can_create_role": store.pg_can_create_role,
            }
        except Exception as error:
            store.write(
                {
                    "pg_probe_state": "error",
                    "pg_last_probe_at": fields.Datetime.now(),
                    "pg_last_probe_error": str(error),
                }
            )
            return {"error": str(error)}

    def probe_database(self, store, database):
        lines = self._capability_lines(database)
        requirements = self._required_extensions(store, database)
        connection = self._connect(store, database=database)
        try:
            with connection.cursor() as cursor:
                rows = self._probe_extension_rows(cursor, requirements)
                line_versions = {line.id: {} for line in lines}
                line_extension_states = {line.id: [] for line in lines}
                for extension, dependent_lines in requirements.items():
                    row = rows.get(extension)
                    available_version = row and row["available_version"]
                    installed_version = row and row["installed_version"]
                    if not row:
                        state = "unavailable"
                    elif not installed_version:
                        state = "available_not_installed"
                    else:
                        state = "installed"
                    self._sync_extension_status(
                        store,
                        database,
                        extension,
                        "database",
                        available_version,
                        installed_version,
                        state,
                    )
                    for line in dependent_lines:
                        line_versions[line.id][extension] = installed_version
                        line_extension_states[line.id].append((extension, state))

                states_by_code = {}
                for line in lines:
                    errors = []
                    runtime = {}
                    extension_states = line_extension_states[line.id]
                    unavailable = [
                        extension
                        for extension, state in extension_states
                        if state == "unavailable"
                    ]
                    not_installed = [
                        extension
                        for extension, state in extension_states
                        if state == "available_not_installed"
                    ]
                    failed_dependencies = [
                        dependency
                        for dependency in (line.capability_id.dependency_codes or [])
                        if states_by_code.get(dependency) != "ready"
                    ]
                    if unavailable:
                        errors.append("unavailable: " + ", ".join(unavailable))
                        line_state = "unavailable"
                    elif not_installed:
                        errors.append("not installed: " + ", ".join(not_installed))
                        line_state = "awaiting_extension"
                    elif failed_dependencies:
                        errors.append(
                            "dependencies not ready: " + ", ".join(failed_dependencies)
                        )
                        line_state = "error"
                    else:
                        try:
                            runtime = self._capability_component(line).probe_runtime(
                                store, database, line, cursor
                            ) or {}
                            if runtime.get("ready") is False:
                                errors.append(runtime.get("error") or "runtime probe failed")
                                line_state = "error"
                            else:
                                line_state = "ready"
                        except Exception as error:
                            errors.append(str(error))
                            line_state = "error"

                    if line_state == "error" and extension_states:
                        statuses = store.env["llm.pg.extension.status"].search(
                            [
                                ("database_id", "=", database.id),
                                (
                                    "extension_name",
                                    "in",
                                    [name for name, _state in extension_states],
                                ),
                                ("state", "=", "installed"),
                            ]
                        )
                        statuses.write(
                            {
                                "state": "installed_unusable",
                                "details": {"runtime_error": "\n".join(errors)},
                                "checked_at": fields.Datetime.now(),
                            }
                        )
                    line.write(
                        {
                            "state": line_state,
                            "installed_versions": line_versions[line.id],
                            "runtime_capabilities": runtime,
                            "last_error": "\n".join(errors) or False,
                            "last_checked_at": fields.Datetime.now(),
                        }
                    )
                    states_by_code[line.capability_id.code] = line_state
        finally:
            connection.close()
        return all(line.state == "ready" for line in lines)

    @staticmethod
    def _ownership_marker(database):
        return f"llm_pg:{database.uuid}"

    def _role_marker(self, cursor, role_name):
        cursor.execute(
            "SELECT shobj_description(oid, 'pg_authid') FROM pg_roles WHERE rolname = %s",
            [role_name],
        )
        row = cursor.fetchone()
        return None if row is None else row[0]

    def _database_marker(self, cursor, database_name):
        cursor.execute(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s",
            [database_name],
        )
        row = cursor.fetchone()
        return None if row is None else row[0]

    def _role_exists(self, cursor, role_name):
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role_name])
        return bool(cursor.fetchone())

    def _database_exists_on_server(self, cursor, database_name):
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [database_name])
        return bool(cursor.fetchone())

    def _ensure_managed_database(self, store, database):
        _psycopg2, sql, _json = self._psycopg2()
        marker = self._ownership_marker(database)
        if not database.database_secret:
            database.write({"database_secret": secrets.token_urlsafe(32)})

        role_created = database.pg_role_created
        database_created = database.pg_database_created
        connection = self._connect(store, maintenance=True, autocommit=True)
        try:
            with connection.cursor() as cursor:
                role_exists = self._role_exists(cursor, database.database_user)
                database_exists = self._database_exists_on_server(
                    cursor, database.database_name
                )
                if role_exists and self._role_marker(
                    cursor, database.database_user
                ) != marker:
                    raise UserError(
                        _(
                            "PostgreSQL role '%s' already exists and is not owned "
                            "by this control-plane record.",
                            database.database_user,
                        )
                    )
                if database_exists and self._database_marker(
                    cursor, database.database_name
                ) != marker:
                    raise UserError(
                        _(
                            "PostgreSQL database '%s' already exists and is not "
                            "owned by this control-plane record.",
                            database.database_name,
                        )
                    )

                if not role_exists:
                    cursor.execute(
                        sql.SQL(
                            "CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER "
                            "NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION "
                            "NOBYPASSRLS"
                        ).format(sql.Identifier(database.database_user)),
                        [database.database_secret],
                    )
                    cursor.execute(
                        sql.SQL("COMMENT ON ROLE {} IS %s").format(
                            sql.Identifier(database.database_user)
                        ),
                        [marker],
                    )
                role_created = True

                if not database_exists:
                    template = database.pg_template_database or "template1"
                    cursor.execute(
                        sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE {}").format(
                            sql.Identifier(database.database_name),
                            sql.Identifier(database.database_user),
                            sql.Identifier(template),
                        )
                    )
                    cursor.execute(
                        sql.SQL("COMMENT ON DATABASE {} IS %s").format(
                            sql.Identifier(database.database_name)
                        ),
                        [marker],
                    )
                database_created = True
        finally:
            connection.close()

        database.write(
            {
                "pg_role_created": role_created,
                "pg_database_created": database_created,
                "connection_uri": self._data_plane_dsn(store, database),
            }
        )

    def _provision_base_schema(self, store, database, cursor):
        _psycopg2, sql, _json = self._psycopg2()
        schema = sql.Identifier(SCHEMA_NAME)
        table = sql.Identifier(TABLE_NAME)
        cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(schema))
        if database.pg_partition_strategy == "hash":
            cursor.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {}.{} ("
                    "id text NOT NULL, generation text NOT NULL, "
                    "content text NOT NULL, payload jsonb NOT NULL DEFAULT '{}'::jsonb, "
                    "PRIMARY KEY (id)) PARTITION BY HASH (id)"
                ).format(schema, table)
            )
            for remainder in range(database.pg_partition_count):
                child = sql.Identifier(f"{TABLE_NAME}_p{remainder:03d}")
                cursor.execute(
                    sql.SQL(
                        "CREATE TABLE IF NOT EXISTS {}.{} PARTITION OF {}.{} "
                        "FOR VALUES WITH (MODULUS %s, REMAINDER %s)"
                    ).format(schema, child, schema, table),
                    [database.pg_partition_count, remainder],
                )
        else:
            cursor.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {}.{} ("
                    "id text PRIMARY KEY, generation text NOT NULL, "
                    "content text NOT NULL, payload jsonb NOT NULL DEFAULT '{}'::jsonb)"
                ).format(schema, table)
            )
        cursor.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} (generation)").format(
                sql.Identifier("records_generation_idx"), schema, table
            )
        )
        cursor.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} USING gin (payload)").format(
                sql.Identifier("records_payload_idx"), schema, table
            )
        )

    def _grant_data_plane(self, store, database, cursor):
        _psycopg2, sql, _json = self._psycopg2()
        role = sql.Identifier(database.database_user)
        if database.pg_resource_mode == "managed":
            cursor.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(database.database_name)
                )
            )
            cursor.execute(
                sql.SQL("GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}").format(
                    sql.Identifier(database.database_name), role
                )
            )
        cursor.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(SCHEMA_NAME), role
            )
        )
        cursor.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {}.{} TO {}").format(
                sql.Identifier(SCHEMA_NAME), sql.Identifier(TABLE_NAME), role
            )
        )

    def provision_database(self, store, database, **kwargs):
        if database.isolation_mode != "database":
            raise UserError(
                _("llm_pg currently provisions one physical PostgreSQL database per library.")
            )
        if database.pg_resource_mode == "managed":
            self._ensure_managed_database(store, database)
        elif not self.database_exists(store, database):
            raise UserError(_("The existing PostgreSQL database is not reachable."))

        if not self.probe_database(store, database):
            missing = self._capability_lines(database).filtered(
                lambda line: line.state != "ready"
            )
            return {
                "status": "awaiting_extensions",
                "message": _(
                    "Database created or adopted, but required extensions are not "
                    "ready: %s. Ask the DBA to install them in database '%s', then "
                    "probe and resume provisioning.",
                    ", ".join(missing.mapped("capability_id.name")),
                    database.database_name,
                ),
            }

        connection = self._connect(store, database=database)
        try:
            with connection.cursor() as cursor:
                self._provision_base_schema(store, database, cursor)
                resources = {}
                for line in self._capability_lines(database):
                    component = self._capability_component(line)
                    component.provision_schema(
                        store, database, line, cursor, SCHEMA_NAME, TABLE_NAME
                    )
                    indexes = component.create_indexes(
                        store,
                        database,
                        line,
                        cursor,
                        SCHEMA_NAME,
                        TABLE_NAME,
                    )
                    resources[line.capability_id.code] = {"indexes": indexes or []}
                    line.write(
                        {
                            "state": "ready",
                            "resource_metadata": resources[line.capability_id.code],
                            "last_error": False,
                        }
                    )
                self._grant_data_plane(store, database, cursor)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"status": "ready", "capabilities": resources}

    def database_exists(self, store, database, **kwargs):
        if database.pg_resource_mode == "existing":
            try:
                connection = self._connect(store, database=database)
                connection.close()
                return True
            except Exception:
                return False
        connection = self._connect(store, maintenance=True)
        try:
            with connection.cursor() as cursor:
                return self._database_exists_on_server(cursor, database.database_name)
        finally:
            connection.close()

    def drop_database(self, store, database, **kwargs):
        if database.pg_resource_mode == "existing" or database.pg_drop_policy == "detach":
            return True
        _psycopg2, sql, _json = self._psycopg2()
        marker = self._ownership_marker(database)
        connection = self._connect(store, maintenance=True, autocommit=True)
        try:
            with connection.cursor() as cursor:
                if self._database_exists_on_server(cursor, database.database_name):
                    if self._database_marker(cursor, database.database_name) != marker:
                        raise UserError(
                            _("Refusing to drop a PostgreSQL database not owned by this record.")
                        )
                    cursor.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid()",
                        [database.database_name],
                    )
                    cursor.execute(
                        sql.SQL("DROP DATABASE {}").format(
                            sql.Identifier(database.database_name)
                        )
                    )
                if self._role_exists(cursor, database.database_user):
                    if self._role_marker(cursor, database.database_user) != marker:
                        raise UserError(
                            _("Refusing to drop a PostgreSQL role not owned by this record.")
                        )
                    cursor.execute(
                        sql.SQL("DROP ROLE {}").format(
                            sql.Identifier(database.database_user)
                        )
                    )
        finally:
            connection.close()
        database.write(
            {
                "pg_database_created": False,
                "pg_role_created": False,
                "connection_uri": False,
                "database_secret": False,
            }
        )
        return True

    def insert_database_vectors(
        self,
        store,
        database,
        vectors=None,
        sparse_vectors=None,
        metadata=None,
        ids=None,
        **kwargs,
    ):
        ids = [str(value) for value in (ids or [])]
        vectors = list(vectors) if vectors is not None else None
        sparse_vectors = list(sparse_vectors) if sparse_vectors is not None else None
        payloads = list(metadata or [{} for _value in ids])
        if not ids:
            return []
        if len(payloads) != len(ids):
            raise UserError(_("Record IDs and payload counts must match."))

        columns = ["id", "generation", "content", "payload"]
        rows = []
        _psycopg2, sql, Json = self._psycopg2()
        for record_id, payload in zip(ids, payloads, strict=True):
            payload = dict(payload or {})
            content = payload.get("text")
            generation = payload.get("generation") or database.active_generation
            if not isinstance(content, str):
                raise UserError(_("Every PostgreSQL record payload needs string field 'text'."))
            rows.append([record_id, generation, content, Json(payload)])

        contributed = False
        for line in self._capability_lines(database):
            contribution = self._capability_component(line).prepare_upsert(
                store,
                database,
                line,
                vectors=vectors,
                sparse_vectors=sparse_vectors,
                metadata=payloads,
                ids=ids,
            )
            if not contribution:
                continue
            extra_columns = list(contribution.get("columns") or [])
            extra_values = list(contribution.get("values") or [])
            if len(extra_values) != len(rows):
                raise UserError(_("Capability upsert contribution has the wrong row count."))
            if set(columns).intersection(extra_columns):
                raise UserError(_("Capability upsert columns collide with base columns."))
            columns.extend(extra_columns)
            for row, values in zip(rows, extra_values, strict=True):
                row.extend(values)
            contributed = True
        if (vectors is not None or sparse_vectors is not None) and not contributed:
            raise UserError(_("No enabled PostgreSQL capability accepts vector data."))

        column_sql = sql.SQL(", ").join(map(sql.Identifier, columns))
        placeholders = sql.SQL(", ").join(sql.Placeholder() for _column in columns)
        updates = sql.SQL(", ").join(
            sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(column), sql.Identifier(column))
            for column in columns
            if column != "id"
        )
        statement = sql.SQL(
            "INSERT INTO {}.{} ({}) VALUES ({}) "
            "ON CONFLICT (id) DO UPDATE SET {}"
        ).format(
            sql.Identifier(SCHEMA_NAME),
            sql.Identifier(TABLE_NAME),
            column_sql,
            placeholders,
            updates,
        )
        connection = self._connect(store, database=database, application=True)
        try:
            with connection.cursor() as cursor:
                cursor.executemany(statement, rows)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return ids

    def delete_database_vectors(self, store, database, ids, **kwargs):
        ids = [str(value) for value in (ids or [])]
        if not ids:
            return True
        _psycopg2, sql, _json = self._psycopg2()
        connection = self._connect(store, database=database, application=True)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DELETE FROM {}.{} WHERE id = ANY(%s)").format(
                        sql.Identifier(SCHEMA_NAME), sql.Identifier(TABLE_NAME)
                    ),
                    [ids],
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return True

    def _query_capability(self, database, mode, kwargs):
        provider_map = kwargs.get("channel_providers") or {}
        requested = provider_map.get(mode) or kwargs.get(f"{mode}_provider")
        for line in self._capability_lines(database):
            if requested and line.capability_id.code != requested:
                continue
            component = self._capability_component(line)
            if component.supports_query(mode):
                return line, component
        raise UserError(_("No enabled PostgreSQL capability supports '%s' queries.", mode))

    def search_database_vectors(
        self, store, database, query_vector=None, limit=10, filter=None, **kwargs
    ):
        mode = kwargs.get("query_mode") or ("dense" if query_vector is not None else "bm25")
        line, component = self._query_capability(database, mode, kwargs)
        connection = self._connect(store, database=database, application=True)
        try:
            with connection.cursor() as cursor:
                return component.search(
                    store,
                    database,
                    line,
                    cursor,
                    SCHEMA_NAME,
                    TABLE_NAME,
                    query_vector=query_vector,
                    limit=limit,
                    filter=filter,
                    **kwargs,
                )
        finally:
            connection.close()

    def create_database_index(self, store, database, index_type=None, **kwargs):
        connection = self._connect(store, database=database)
        created = {}
        try:
            with connection.cursor() as cursor:
                for line in self._capability_lines(database):
                    created[line.capability_id.code] = self._capability_component(
                        line
                    ).create_indexes(
                        store,
                        database,
                        line,
                        cursor,
                        SCHEMA_NAME,
                        TABLE_NAME,
                        index_type=index_type,
                        **kwargs,
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return created
