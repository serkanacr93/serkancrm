import os
import sys
import threading
import time
import webbrowser

def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

os.chdir(get_base_path())

from app import create_app

app = create_app()

def start_flask():
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

def main():
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    time.sleep(3)

    webbrowser.open('http://localhost:5000')

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
