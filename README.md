# Sesli Çevirmen — iPhone PWA

Safari için sesli çeviri + dil eğitimi. Bas-konuş, robot öğretmen, 10 dil.

## iPhone kurulum

1. **Sabit adresinizi** Safari’de açın (aşağıya bakın)
2. **Paylaş** → **Ana Ekrana Ekle** → **Ekle**
3. Ana ekrandan simgeye dokunun

## Önemli: Sunucu adresi

**`*.trycloudflare.com` geçici adresler her tünel restart’ında değişir.** Ana ekrana eklediyseniz kısayol bozulabilir.

Kalıcı kullanım için: **[docs/SABIT-ADRES.md](docs/SABIT-ADRES.md)** — kendi domain + Cloudflare Named Tunnel (önerilen).

## Yerel çalıştırma

```bash
cd sesli-cevirmen-ios
python3 server.py
# http://127.0.0.1:8780
```

Geçici internet adresi (değişken):

```bash
./scripts/start-tunnel-quick.sh
# Adres: PUBLIC_URL.txt
```

## Modüller

- **Çeviri** — Türkçe ↔ diğer diller, bas-konuş
- **Eğitim** — Robot öğretmen, İngilizce konuşma + Türkçe açıklama

## Gereksinimler

- Python 3.10+
- iPhone Safari (mikrofon)
- İnternet (STT/TTS/AI)
