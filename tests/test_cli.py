import subprocess
import sys
import os

def test_cli_help():
    env = os.environ.copy()
    env["PATH"] = "D:\\Anaconda3;D:\\Anaconda3\\Scripts;D:\\Anaconda3\\Library\\bin;" + env.get("PATH", "")
    env["PYTHONPATH"] = "."
    res = subprocess.run([sys.executable, "main.py", "--help"], capture_output=True, text=True, env=env)
    assert res.returncode == 0
    assert "厦大体育馆自动预约" in res.stdout
    assert "book" in res.stdout
    assert "heartbeat" in res.stdout
    assert "check" in res.stdout
