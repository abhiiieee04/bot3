import psycopg2
import psycopg2.extras
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, database_url: str):
        self.url = database_url

    def _conn(self):
        return psycopg2.connect(self.url, cursor_factory=psycopg2.extras.RealDictCursor)

    # ── Schema ───────────────────────────────────────────────────────────────

    def init(self):
        """Create tables if they don't exist."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS folders (
                        id         SERIAL PRIMARY KEY,
                        name       TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS coupons (
                        id          SERIAL PRIMARY KEY,
                        folder_id   INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
                        code        TEXT NOT NULL,
                        description TEXT DEFAULT '',
                        created_at  TIMESTAMP DEFAULT NOW()
                    );
                """)
            conn.commit()
        logger.info("Database initialised.")

    # ── Folders ──────────────────────────────────────────────────────────────

    def create_folder(self, name: str) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO folders (name) VALUES (%s) RETURNING id;",
                    (name,)
                )
                folder_id = cur.fetchone()["id"]
            conn.commit()
        return folder_id

    def get_folders(self) -> list:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT f.id, f.name, f.created_at,
                           COUNT(c.id) AS coupon_count
                    FROM folders f
                    LEFT JOIN coupons c ON c.folder_id = f.id
                    GROUP BY f.id
                    ORDER BY f.created_at DESC;
                """)
                return cur.fetchall()

    def get_folder(self, folder_id: int) -> dict:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM folders WHERE id = %s;", (folder_id,))
                return cur.fetchone()

    def delete_folder(self, folder_id: int):
        """Cascade deletes all coupons inside."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM folders WHERE id = %s;", (folder_id,))
            conn.commit()

    # ── Coupons ──────────────────────────────────────────────────────────────

    def add_coupon(self, folder_id: int, code: str, description: str = "") -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO coupons (folder_id, code, description) VALUES (%s, %s, %s) RETURNING id;",
                    (folder_id, code, description)
                )
                coupon_id = cur.fetchone()["id"]
            conn.commit()
        return coupon_id

    def get_coupons(self, folder_id: int) -> list:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM coupons WHERE folder_id = %s ORDER BY created_at DESC;",
                    (folder_id,)
                )
                return cur.fetchall()

    def get_all_coupons(self) -> list:
        """Returns all coupons with their folder name (for admin delete list)."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT c.id, c.code, c.description, c.created_at,
                           f.name AS folder_name
                    FROM coupons c
                    JOIN folders f ON f.id = c.folder_id
                    ORDER BY c.created_at DESC;
                """)
                return cur.fetchall()

    def get_coupon(self, coupon_id: int) -> dict:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM coupons WHERE id = %s;", (coupon_id,))
                return cur.fetchone()

    def delete_coupon(self, coupon_id: int):
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM coupons WHERE id = %s;", (coupon_id,))
            conn.commit()
