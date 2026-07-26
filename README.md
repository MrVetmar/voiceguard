# VoiceGuard

Discord ses kanalında otomatik kalma, zamanlama ve AI sohbet botu.

## Özellikler
- Ses kanalında 7/24 otomatik kalma (Muted & Deafened)
- Zamanlama sistemi (belirli saatlerde aktif/pasif)
- Web yönetim paneli (http://localhost:8080)
- Otomatik selamlaşma (sa → as hoş geldin)
- AI destekli doğal sohbet

## Kurulum

1. Gereksinimleri yükleyin:
```bash
pip install -r requirements.txt
```

2. `config.example.json` dosyasını `config.json` olarak kopyalayıp kendi bilgilerinizi girin:
```bash
cp config.example.json config.json
```

3. Botu başlatın:
```bash
python main.py
```

## Web Panel
Bot çalışırken tarayıcıdan `http://localhost:8080` adresine giderek ayarları yönetebilirsiniz.
