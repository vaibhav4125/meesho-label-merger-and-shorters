import os
import sys
import socket
import webbrowser
import uvicorn
try:
    from backend.tunnel import start_tunnel, get_tunnel_status
except (ImportError, ValueError):
    from tunnel import start_tunnel, get_tunnel_status

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    host = "0.0.0.0"
    port_env = os.environ.get("PORT")
    port = int(port_env) if port_env else 8000
    is_cloud = bool(os.environ.get("RENDER") or os.environ.get("RAILWAY_STATIC_URL") or port_env)

    local_ip = get_local_ip()
    local_url = f"http://localhost:{port}"
    mobile_wifi_url = f"http://{local_ip}:{port}"

    print("=" * 70)
    print(" [*] Meesho Multi-Account PDF Order Sorting & Merging System")
    print("=" * 70)

    _cur = os.path.dirname(os.path.abspath(__file__))
    app_module = "backend.main:app" if os.path.exists(os.path.join(_cur, "backend", "main.py")) else "main:app"

    if is_cloud:
        print(f" [OK] Cloud Server Active on 0.0.0.0:{port} (using {app_module})")
        uvicorn.run(app_module, host=host, port=port, reload=False)
    else:
        print(f" PC Local Browser:        {local_url}")
        print(f" Mobile (Same Wi-Fi):     {mobile_wifi_url}")
        print(" Mobile (Anywhere Live):   Starting Cloudflare Tunnel...")
        
        # Start Cloudflare Tunnel in background for local mode
        tunnel_url = start_tunnel(port=port, wait_for_url=3.0)
        if tunnel_url:
            print(f" Mobile (Anywhere Live):   {tunnel_url}")
        else:
            print(" Mobile (Anywhere Live):   Connecting... (URL will print once ready)")
        print("=" * 70)
        print(" Tip: Open the Mobile Live link or scan the QR code inside the app!")
        print("=" * 70)
        
        # Auto-open browser on PC
        try:
            webbrowser.open(local_url)
        except Exception:
            pass
            
        uvicorn.run("backend.main:app", host=host, port=port, reload=True)
