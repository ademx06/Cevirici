# Kendin Nasıl Çalıştırırsın?

Bana her seferinde sormana gerek yok. Adres her zaman proje klasöründeki **`PUBLIC_URL.txt`** dosyasında yazar.

---

## Mac’te ilk kurulum (bir kez)

Terminal’i aç:

```bash
# 1) Proje klasörüne git (senin indirdiğin yer)
cd ~/sesli-cevirmen-ios

# 2) cloudflared (internet adresi için)
brew install cloudflared

# 3) Python paketleri (Whisper, edge-tts vb.)
pip3 install faster-whisper edge-tts
```

`ffmpeg` yoksa: `brew install ffmpeg`

---

## Her kullanımda (2 komut)

**Terminal 1 — programı başlat + linki göster:**

```bash
cd ~/sesli-cevirmen-ios
chmod +x scripts/baslat.sh
./scripts/baslat.sh
```

Ekranda şuna benzer bir adres çıkar:

```
https://xxxx.trycloudflare.com
```

Bu adres aynı anda **`PUBLIC_URL.txt`** dosyasına kaydedilir.

**Linki tekrar görmek için:**

```bash
./scripts/baslat.sh url
# veya
cat PUBLIC_URL.txt
```

**Durdurmak için:**

```bash
./scripts/baslat.sh stop
```

**Çalışıyor mu kontrol:**

```bash
./scripts/baslat.sh status
```

---

## iPhone

1. Safari’de `PUBLIC_URL.txt` içindeki adresi aç  
2. **Paylaş → Ana Ekrana Ekle**

| Sayfa | Adres |
|-------|--------|
| Ana menü | `https://....trycloudflare.com/` |
| Eğitim | `https://....trycloudflare.com/education.html` |
| Çeviri | `https://....trycloudflare.com/translate.html` |

---

## Sadece ev Wi‑Fi (tünel olmadan)

Bilgisayar ve iPhone **aynı Wi‑Fi**’deyse:

```bash
cd ~/sesli-cevirmen-ios
python3 server.py
```

Mac IP’ni öğren: **Sistem Ayarları → Ağ → Wi‑Fi → Detaylar → IP**

iPhone Safari: `http://192.168.x.x:8780`

(Bu yöntem ev dışında çalışmaz.)

---

## Adres neden değişiyor?

`trycloudflare.com` geçici tünel — **her `./scripts/baslat.sh` çalıştırışında yeni link** olabilir.

**Kalıcı link istiyorsan:** kendi domain + Cloudflare Named Tunnel → [docs/SABIT-ADRES.md](SABIT-ADRES.md)

---

## Sorun çıkarsa

| Sorun | Çözüm |
|-------|--------|
| Link çalışmıyor | `./scripts/baslat.sh stop` sonra `./scripts/baslat.sh` |
| Linki unuttum | `cat PUBLIC_URL.txt` |
| TypeError / eski arayüz | Safari’de sayfayı yenile |
| Mikrofon yok | Safari kullan, izin ver |

---

**Özet:** `./scripts/baslat.sh` → link ekranda + `PUBLIC_URL.txt` → iPhone Safari → Ana Ekrana Ekle.
