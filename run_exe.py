import os
import sys
import webbrowser
import threading
import time

def open_browser():
    time.sleep(2)
    webbrowser.open('http://localhost:5000')

def main():
    os.chdir(os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__)))
    
    from app import create_app
    app = create_app()
    
    threading.Thread(target=open_browser, daemon=True).start()
    
    print("=" * 50)
    print("    CRM Sistemi v3.0 Baslatildi")
    print("    Tarayicinizda: http://localhost:5000")
    print("    Kullanici: admin / Sifre: 1234")
    print("    Kapatmak icin bu pencereyi kapatin.")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    main()
