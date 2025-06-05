import psycopg2
from psycopg2 import pool
from flask import current_app, g
import logging

logger = logging.getLogger(__name__)

def get_db_pool():
    if 'db_pool' not in g:
        try:
            g.db_pool = psycopg2.pool.SimpleConnectionPool(
                1, 
                20,
                dsn=current_app.config['DATABASE_URL']
            )
            logger.info("Database connection pool created.")
        except Exception as e:
            logger.error(f"Error creating database connection pool: {e}")
            raise
    return g.db_pool

def get_conn():
    db_pool = get_db_pool()
    return db_pool.getconn()

def close_conn(conn, e=None):
    if conn:
        db_pool = get_db_pool()
        db_pool.putconn(conn)
        if e:
            logger.error(f"Database error: {e}")

def init_app(app):
    app.teardown_appcontext(close_app_pool)

def close_app_pool(e=None):
    db_pool = g.pop('db_pool', None)
    if db_pool:
        db_pool.closeall()
        logger.info("Database connection pool closed.")

def execute_query(query, params=None, fetchone=False, fetchall=False, commit=False):
    conn = None
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(query, params)
            if commit:
                conn.commit()
                return None # Or return True for success
            if fetchone:
                return cur.fetchone()
            if fetchall:
                return cur.fetchall()
            # If not commit, fetchone, or fetchall, assume it might be a DDL or a query where we just want execution (e.g. RETURNING)
            # For RETURNING clauses, fetchone/fetchall should be used by the caller if they expect output.
            # If it was an INSERT/UPDATE/DELETE without RETURNING and commit=False, this is unusual but supported.
            # To get rowcount after an UPDATE/DELETE, one might inspect cur.rowcount if needed.
            return None # Default for non-fetching, non-committing queries
    except Exception as e:
        if conn and commit: # Rollback if commit was intended but failed elsewhere in try block or during commit itself
            conn.rollback()
        logger.error(f"Error executing query: {query[:100]}... - {e}")
        raise
    finally:
        if conn:
            close_conn(conn) 