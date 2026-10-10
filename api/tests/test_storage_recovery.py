import unittest
from tempfile import TemporaryDirectory

from app.storage import AppStorage, output_folder_name


class StorageRecoveryTests(unittest.TestCase):
    def test_output_folder_name_uses_safe_username_beijing_time_and_job_suffix(self):
        folder_name = output_folder_name(
            username='张/三: "A*B"?',
            job_id="12345678-90ab-cdef-1234-567890abcdef",
            created_at="2026-10-09T07:30:45+00:00",
        )

        self.assertEqual(folder_name, "张_三_A_B_20261009_153045_12345678")

    def test_output_folder_name_falls_back_to_user_when_username_has_no_safe_characters(self):
        folder_name = output_folder_name(
            username=' /\\:*?"<>| ',
            job_id="abcdef12-90ab-cdef-1234-567890abcdef",
            created_at="2026-10-09 23:59:59",
        )

        self.assertEqual(folder_name, "user_20261010_075959_abcdef12")

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
