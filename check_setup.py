import sys
import os

result_lines = []
result_lines.append("=" * 50)
result_lines.append("CRM Sistemi - Kurulum Kontrol")
result_lines.append("=" * 50)

# Python versiyonu
result_lines.append(f"\n1. Python versiyonu: {sys.version}")

# Mevcut paketleri kontrol et
packages = ['flask', 'flask_sqlalchemy', 'flask_login', 'flask_wtf', 'wtforms', 'email_validator', 'reportlab', 'openpyxl']
result_lines.append("\n2. Paket durumu:")
for pkg in packages:
    try:
        mod_name = pkg.replace('-', '_')
        __import__(mod_name)
        result_lines.append(f"   [OK] {pkg}")
    except ImportError:
        result_lines.append(f"   [MISSING] {pkg}")

# Virtual env kontrol
result_lines.append(f"\n3. Sanal ortam: {'venv' if os.path.isdir('venv') else 'YOK'}")
result_lines.append(f"   Python yolu: {sys.executable}")

# Veritabanı kontrol
db_path = os.path.join('instance', 'crm.db')
result_lines.append(f"\n4. Veritabanı: {'var' if os.path.isfile(db_path) else 'YOK (ilk calistirmada olusacak)'}")

result_lines.append("\n" + "=" * 50)
result_lines.append("Kontrol tamamlandi.")
result_lines.append("=" * 50)

output = "\n".join(result_lines)
print(output)

# Dosyaya yaz
with open('setup_check_result.txt', 'w', encoding='utf-8') as f:
    f.write(output)