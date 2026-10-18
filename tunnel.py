import os
import re
import sys
import time
import atexit
import logging
import threading
import subprocess

logger = logging.getLogger("cloudflare_tunnel")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOUDFLARED_EXE = os.path.join(BASE_DIR, "cloudflared.exe")
TUNNEL_URL_FILE = os.path.join(BASE_DIR, "data", "tunnel_url.txt")

_tunnel_state = {
    "url": None,
    "status": "offline",  # "offline", "connecting", "online", "error"
    "process": None,
    "error": None
}
_state_lock = threading.Lock()

def _reader_thread(proc):
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    try:
        for line in iter(proc.stdout.readline, ''):
            if not line:
                break
            match = url_pattern.search(line)
            if match:
                url = match.group(0)
                with _state_lock:
                    _tunnel_state["url"] = url
                    _tunnel_state["status"] = "online"
                print(f"\n[Cloudflare Live] Mobile URL ready: {url}\n", flush=True)
                try:
                    os.makedirs(os.path.dirname(TUNNEL_URL_FILE), exist_ok=True)
                    with open(TUNNEL_URL_FILE, "w", encoding="utf-8") as f:
                        f.write(url)
                except Exception as e:
                    logger.warning(f"Could not save tunnel URL to file: {e}")
    except Exception as e:
        logger.error(f"Error reading cloudflared output: {e}")
    finally:
        with _state_lock:
            if _tunnel_state["process"] == proc:
                _tunnel_state["status"] = "offline"
                _tunnel_state["process"] = None

def start_tunnel(port: int = 8000, wait_for_url: float = 0.0):
    """
    Starts cloudflared quick tunnel in background.
    If wait_for_url > 0, blocks up to that many seconds waiting for URL detection.
    """
    global _tunnel_state
    with _state_lock:
        if _tunnel_state["process"] is not None and _tunnel_state["process"].poll() is None:
            # Already running
            return _tunnel_state["url"]

        cloudflared_bin = CLOUDFLARED_EXE if os.path.exists(CLOUDFLARED_EXE) else "cloudflared"
        cmd = [
            cloudflared_bin,
            "tunnel",
            "--url", f"http://127.0.0.1:{port}",
            "--no-autoupdate"
        ]

        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=creationflags
            )
            _tunnel_state["process"] = proc
            _tunnel_state["status"] = "connecting"
            _tunnel_state["error"] = None
        except Exception as e:
            _tunnel_state["status"] = "error"
            _tunnel_state["error"] = str(e)
            logger.error(f"Failed to launch cloudflared: {e}")
            return None

    # Start stdout/stderr consumer thread
    t = threading.Thread(target=_reader_thread, args=(proc,), daemon=True)
    t.start()

    if wait_for_url > 0:
        start_time = time.time()
        while time.time() - start_time < wait_for_url:
            with _state_lock:
                if _tunnel_state["url"] or _tunnel_state["status"] == "error":
                    return _tunnel_state["url"]
            time.sleep(0.5)

    return _tunnel_state.get("url")

def stop_tunnel():
    global _tunnel_state
    with _state_lock:
        proc = _tunnel_state.get("process")
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        _tunnel_state["process"] = None
        _tunnel_state["status"] = "offline"

atexit.register(stop_tunnel)

def get_tunnel_status():
    with _state_lock:
        return {
            "url": _tunnel_state["url"],
            "status": _tunnel_state["status"],
            "error": _tunnel_state["error"]
        }
