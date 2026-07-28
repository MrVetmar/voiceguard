# VoiceGuard

Discord ses kanalinda otomatik kalma, zamanlama ve AI sohbet botu — GitHub Pages
uzerinden calisan uzaktan kontrol paneliyle.

```
GitHub Pages (panel/)  ──HTTPS + X-API-Key──▶  Railway (bot + kontrol API'si)
```

## Ozellikler

- Ses kanalinda 7/24 otomatik kalma (Muted & Deafened)
- Zamanlama sistemi (belirli saatlerde aktif) — kapatilirsa 7/24 calisir
- **Uzaktan kontrol paneli**: canli durum, baslat/durdur, ayarlar, canli log akisi
- Otomatik selamlasma (`sa` → `as hoş geldin`)
- AI destekli dogal sohbet (`hb` ile baslar)

## Guvenlik notu

Bu proje `discord.py-self` kullanir, yani bir **kullanici hesabini** otomatiklestirir.
Bu Discord'un kullanim sartlarina aykiridir ve hesap kapatilma riski tasir.
Kalici bir kurulum icin gercek bir **bot hesabina** gecmeniz onerilir.

---

## Kurulum (Railway)

### 1. Ortam degiskenleri

Railway > Variables bolumune ekleyin (tam liste icin [.env.example](.env.example)):

| Degisken | Zorunlu | Aciklama |
|---|---|---|
| `DISCORD_TOKEN` | evet | Discord token'i |
| `PANEL_API_KEY` | evet | Panel erisim anahtari. **Tanimli degilse API kilitlenir.** |
| `NVIDIA_API_KEY` | hayir | AI sohbet icin |
| `PANEL_ORIGINS` | hayir | Panelin origin'i, orn. `https://kullaniciadi.github.io` |

Anahtar uretmek icin:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Sirlar **yalnizca** ortam degiskenlerinden okunur; panel bunlari ne gorebilir
ne de degistirebilir, `config.json`'a da yazilmazlar.

### 2. Paneli GitHub Pages'te yayinlayin

Repo ayarlarindan **Settings → Pages → Source = GitHub Actions** secin.
`panel/` klasoru her degistiginde
[pages.yml](.github/workflows/pages.yml) otomatik yayinlar.

Panel adresi: `https://<kullaniciadi>.github.io/<repo>/`

### 3. Panele baglanin

Paneli ilk actiginizda Railway servisinizin public URL'i ile `PANEL_API_KEY`
degerini girin. Bunlar yalnizca tarayicinizin `localStorage`'inda saklanir.

> Panel ayrica botun kendi adresinden de servis edilir (`https://<railway-url>/`),
> boylece GitHub Pages'e erisemediginizde yedek bir yol kalir.

---

## Yerel calistirma

```bash
pip install -r requirements.txt
cp config.example.json config.json   # degerleri doldurun
python main.py
```

Panel: `http://localhost:8080`

## Testler

```bash
python tests/smoke_test.py
```

Discord baglantisi gerektirmez; konfigurasyon dogrulamasini, kontrol API'sini,
yetkilendirmeyi, CORS'u ve zamanlama mantigini kontrol eder.

---

## Kontrol API'si

Tum endpoint'ler `X-API-Key` basligi ister (`/api/health` haric).

| Endpoint | Metod | Aciklama |
|---|---|---|
| `/` | GET | Yedek panel arayuzu |
| `/api/health` | GET | Ayakta mi (auth yok) |
| `/api/config` | GET | Ayarlar (sirlar maskeli) |
| `/api/config` | POST | Ayarlari dogrulayarak gunceller |
| `/api/status` | GET | Canli durum: baglanti, kanal, uptime, son hata |
| `/api/control` | POST | `{"action": "start" \| "stop" \| "reconnect"}` |
| `/api/logs` | GET | Son N log kaydi |
| `/api/logs/stream` | GET | SSE canli log akisi |

Ornek:

```bash
curl -H "X-API-Key: $PANEL_API_KEY" https://<railway-url>/api/status
```

## Aktiflik mantigi

Iki bagimsiz anahtar birlikte calisir:

| `enabled` | `schedule.enabled` | Sonuc |
|---|---|---|
| kapali | — | Bot ses kanalindan cikar |
| acik | kapali | 7/24 kanalda kalir |
| acik | acik | Yalnizca belirtilen saat araliginda kanalda kalir |
