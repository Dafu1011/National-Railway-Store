import unittest
from tempfile import TemporaryDirectory

from app.storage import AppStorage


class StorageRecoveryTests(unittest.TestCase):
    def test_create_marks_interrupted_generation_jobs_failed(self):
        with TemporaryDirectory() as data_dir:
            storage = AppStorage.create(data_dir)
            with storage.connect() as connection:
                connection.execute(
                    "INSERT INTO users (id, email, password_hash) VALUES ('user-1', 'user@example.com', 'hash')"
                )
                connection.execute(
                    """
                    INSERT INTO products (id, user_id, name, brand, model)
                    VALUES ('product-1', 'user-1', 'Cup', 'Zhifeng', 'A1')
                    """
                )
                connection.execute(
                    """
                    INSERT INTO projects (id, user_id, product_id, name, barcode_type, barcode_value, barcode_confirmed, status)
                    VALUES ('project-1', 'user-1', 'product-1', 'Project', 'EAN_13', '4006381333931', 1, 'generating')
                    """
                )
                connection.execute(
                    """
                    INSERT INTO generation_jobs (id, user_id, project_id, status, provider_name)
                    VALUES ('job-1', 'user-1', 'project-1', 'running', 'kele-gpt-image-2')
                    """
                )

            recovered = AppStorage.create(data_dir)

            with recovered.connect() as connection:
                job = connection.execute(
                    "SELECT status, error_code, error_message FROM generation_jobs WHERE id = 'job-1'"
                ).fetchone()
                project = connection.execute("SELECT status FROM projects WHERE id = 'project-1'").fetchone()
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["error_code"], "GENERATION_INTERRUPTED")
            self.assertIn("interrupted", job["error_message"])
            self.assertEqual(project["status"], "failed")


if __name__ == "__main__":
    unittest.main()
