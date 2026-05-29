from __future__ import annotations

import threading
import webbrowser

import uvicorn


HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def open_browser() -> None:
    print(f"[VideoTimeLapse] Opening browser: {URL}")
    webbrowser.open(URL)


def main() -> None:
    print("[VideoTimeLapse] Starting server...")
    print(f"[VideoTimeLapse] Local URL: {URL}")
    print("[VideoTimeLapse] Press CTRL+C to stop.")

    timer = threading.Timer(1.5, open_browser)
    timer.daemon = True
    timer.start()

    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
