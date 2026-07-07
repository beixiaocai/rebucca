# 作者：北小菜
"""轻量 SQLite 列升级（无 Django migrations 时使用）"""
import logging

logger = logging.getLogger("app.schema")


def _table_columns(cursor, table):
    cursor.execute("PRAGMA table_info(%s)" % table)
    return {row[1] for row in cursor.fetchall()}


def ensure_biz_algorithm_line_count_columns():
    from django.db import connection

    table = "av_biz_algorithm"
    adds = (
        ("forward_count_threshold", "INTEGER NOT NULL DEFAULT 0"),
        ("reverse_count_threshold", "INTEGER NOT NULL DEFAULT 0"),
        ("detector_model_id", "INTEGER NULL"),
    )
    with connection.cursor() as cur:
        existing = _table_columns(cur, table)
        for col, decl in adds:
            if col in existing:
                continue
            sql = "ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl)
            cur.execute(sql)
            logger.info("schema upgrade: %s", sql)
