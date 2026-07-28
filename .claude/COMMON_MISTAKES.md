# Common Mistakes

**⚠️ CRITICAL - Read at session start**

---

## Top 5 Critical Mistakes

### 1. Discord ID'lerini JSON sayisi olarak gondermek

**Symptom**: Panelde kaydedilen sunucu/kanal ID'si yanlis oluyor
(`...377805` → `...378000`), bot "sunucu bulunamadi" diyor.
**Check**: Snowflake'ler 2^53'u asar; JavaScript `Number` hassasiyeti yetmez.
**Fix**: API'ye cikan tum ID'ler **string** olmali — `config_store.ID_KEYS` ve
`runtime_state._serialize()`. Dahili kullanimda int kalirlar.

### 2. Sirlari config.json'a yazmak

**Symptom**: Token panelde gorunuyor veya diske sizmis oluyor; Railway'de
env degiskenleri sessizce yok sayiliyor.
**Check**: `config_store.SECRET_KEYS` — bunlar yalnizca env'den okunur.
**Fix**: `store.update()` sadece `EDITABLE_KEYS`'i yazar. Yeni bir sir eklerken
mutlaka `SECRET_KEYS`'e ekle, `public()` otomatik maskeler.

### 3. config.json'a atomik olmayan yazma

**Symptom**: Nadiren `JSONDecodeError`; monitor loop yarim dosya okuyor.
**Check**: `monitor_loop` her `check_interval` saniyede dosyayi okur.
**Fix**: Daima `store.update()` kullan — `.tmp` + `os.replace` ile atomik yazar.
Dogrudan `json.dump(open("config.json","w"))` yazma.

### 4. `enabled` ile `schedule.enabled` karistirmak

**Symptom**: Zamanlama kapatilinca bot ses kanalindan cikiyor (7/24 beklenirken).
**Check**: Bunlar iki ayri anahtar — bkz. `voice_keeper.should_be_connected()`.
**Fix**: `enabled` = master switch (panel Baslat/Durdur).
`schedule.enabled` = saat kisiti; **kapaliysa 7/24 aktif** demektir.

### 5. Panelin canli akisi icin EventSource kullanmak

**Symptom**: SSE 401 donuyor veya API anahtari URL'e konuluyor.
**Check**: `EventSource` ozel HTTP basligi gonderemez.
**Fix**: `fetch` + `ReadableStream` ile SSE'yi elle ayristir
(`panel/index.html` → `streamLogs()`). Anahtar asla query string'e girmemeli.

---

## Ayrica

- **Yeni endpoint eklerken**: auth `web_server._PUBLIC_PATHS` disindaki her yolu
  korur; yeni public yol eklemek bilincli bir karar olmali.
- **`PANEL_API_KEY` tanimli degilse** API 503 doner — bu kasitli, paneli
  yanlislikla herkese acmayi engeller.
- **Degisiklikten sonra**: `python tests/smoke_test.py` (Discord gerektirmez).

---

**Last Updated**: 2026-07-28
