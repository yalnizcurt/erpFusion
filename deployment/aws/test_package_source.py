"""One packaging check: build inputs survive; local secrets and state do not."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from package_source import package_source


class PackageSourceTest(unittest.TestCase):
    def test_reproducible_source_excludes_secrets_state_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                "Dockerfile": "FROM python:3.12-slim\n",
                ".dockerignore": ".env\n",
                "backend/uv.lock": "version = 1\n",
                "frontend/package-lock.json": "{}\n",
                "backend/app/main.py": "print('application')\n",
                "frontend/src/main.jsx": "export default 'application';\n",
                "deployment/aws/buildspec.yml": "version: 0.2\n",
                "backend/tests/test_sample.py": "def test_sample(): assert True\n",
                "backend/scripts/check_quality.py": "print('quality')\n",
                "backend/quality-baseline.json": '{"diagnostics":[]}\n',
                "backend/.env": "SECRET=value\n",
                "backend/app/.env.production": "SECRET=value\n",
                "backend/app/credentials.json": '{"password":"value"}\n',
                "backend/app/secrets.py": "PASSWORD = 'value'\n",
                "backend/app/artifacts/client.json": '{"client":"private"}\n',
                "backend/app/private.pem": "PRIVATE KEY\n",
                "frontend/node_modules/example/index.js": "private dependency\n",
                ".aws/credentials": "private credentials\n",
                "backend/local.sqlite": "private database\n",
            }
            for filename, content in files.items():
                path = root / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            (root / "backend/app/linked.py").symlink_to(root / "backend/app/secrets.py")
            first = package_source(root, root / "first.zip")
            second = package_source(root, root / "second.zip")
            self.assertEqual(first["sha256"], second["sha256"])
            with zipfile.ZipFile(root / "first.zip") as archive:
                self.assertEqual(set(archive.namelist()), set(list(files)[:10]))


if __name__ == "__main__":
    unittest.main()
