# Yapılacaklar / Teknik Borç

- **Teknik borç:** `create_app()` içindeki `db.create_all()` ile Flask-Migrate arasında çakışma riski var - yeni tablo eklerken `db.create_all()` tabloyu migration'dan önce oluşturup Alembic senkronizasyonunu bozabiliyor. İleride `db.create_all()` kullanımını kaldırıp tamamen migration tabanlı bir akışa geçmeyi değerlendir.
