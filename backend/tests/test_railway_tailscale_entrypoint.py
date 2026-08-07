import subprocess
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


class RailwayTailscaleEntrypointTest(unittest.TestCase):
    def test_entrypoint_is_valid_shell_and_keeps_proxy_loopback_only(self):
        script = _ROOT / "docker-entrypoint.sh"
        subprocess.run(["sh", "-n", str(script)], check=True)
        source = script.read_text()
        self.assertIn("--tun=userspace-networking", source)
        self.assertIn("--state=mem:", source)
        self.assertIn("--socks5-server=127.0.0.1:1055", source)
        self.assertIn("--outbound-http-proxy-listen=127.0.0.1:1055", source)
        self.assertIn("json.load(sys.stdin).get", source)
        self.assertNotIn("HTTP_PROXY=", source)
        self.assertNotIn("HTTPS_PROXY=", source)
        self.assertNotIn("ALL_PROXY=", source)

    def test_railway_predeploy_does_not_enter_tailscale_lifecycle(self):
        railway_toml = (_ROOT / "railway.toml").read_text()
        self.assertIn('builder = "DOCKERFILE"', railway_toml)
        self.assertIn("python -m alembic upgrade head", railway_toml)
        self.assertIn('startCommand = "./docker-entrypoint.sh"', railway_toml)
