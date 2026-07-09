import mysql.connector.pooling
import os
from flask import g

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = mysql.connector.pooling.MySQLConnectionPool(
        pool_name="weathertrip",
        pool_size=5,
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DB"],
        ssl_disabled=True,
        )
    return _pool

def get_db():
    if "db" not in g:
        g.db = get_pool().get_connection()
    return g.db

def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
