import inspect
import unittest

from app.core.object_storage import material_object_key
from app.core.runtime_services import LocalRuntimeServices
from app.storage import AppStorage, is_postgres_database_url, normalize_postgres_database_url


class ProductionInfrastructureTests(unittest.TestCase):
    def test_material_object_key_is_scoped_to_user_library(self):
        key = material_object_key(user_id="user-1", upload_token="upload-1", filename="../cup.png")

        self.assertEqual(key, "users/user-1/materials/pending/upload-1/cup.png")

    def test_local_runtime_lock_blocks_concurrent_same_key(self):
        services = LocalRuntimeServices()

        with services.lock("lock:register:email"):
            with self.assertRaisesRegex(RuntimeError, "LOCK_BUSY"):
                with services.lock("lock:register:email"):
                    pass

    def test_local_runtime_rate_limit_counts_within_window(self):
        services = LocalRuntimeServices()

        self.assertFalse(services.hit_rate_limit("rate:login:ip", limit=2, window_seconds=60))
        self.assertFalse(services.hit_rate_limit("rate:login:ip", limit=2, window_seconds=60))
        self.assertTrue(services.hit_rate_limit("rate:login:ip", limit=2, window_seconds=60))

    def test_postgres_database_url_is_recognized_and_normalized(self):
        url = "postgresql+asyncpg://root:root123@postgres:5432/zhifeng"

        self.assertTrue(is_postgres_database_url(url))
        self.assertEqual(normalize_postgres_database_url(url), "postgresql://root:root123@postgres:5432/zhifeng")

    def test_schema_uses_text_timestamp_when_backfilling_email_verification(self):
        schema_source = inspect.getsource(AppStorage.init_schema)

        self.assertIn("COALESCE(email_verified_at, CAST(CURRENT_TIMESTAMP AS TEXT))", schema_source)

    def test_local_runtime_cache_round_trips_json_and_can_delete(self):
        services = LocalRuntimeServices()

        self.assertIsNone(services.get_cache_json("cache:products:user-1"))
        services.set_cache_json("cache:products:user-1", {"items": [{"id": "product-1"}]}, ttl_seconds=60)

        self.assertEqual(services.get_cache_json("cache:products:user-1"), {"items": [{"id": "product-1"}]})

        services.delete_cache("cache:products:user-1")
        self.assertIsNone(services.get_cache_json("cache:products:user-1"))

    def test_local_runtime_slot_rejects_when_limit_is_reached(self):
        services = LocalRuntimeServices()

        with services.slot("slot:provider:generation", limit=1, ttl_seconds=60):
            with self.assertRaisesRegex(RuntimeError, "SLOT_BUSY"):
                with services.slot("slot:provider:generation", limit=1, ttl_seconds=60):
                    pass

        with services.slot("slot:provider:generation", limit=1, ttl_seconds=60):
            pass


if __name__ == "__main__":
    unittest.main()
