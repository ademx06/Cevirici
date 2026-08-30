# Sabit sunucu adresi (Ana ekran / PWA için)

## Neden adres değişiyor?

Şu an kullanılan **Cloudflare Quick Tunnel** (`*.trycloudflare.com`) her başlatmada **rastgele yeni bir adres** üretir.

iPhone’da **Ana Ekrana Ekle** yaptığınızda kısayol **o adrese kilitlenir**. Tünel yeniden başlayınca adres değişir → kısayol eski adrese gider → uygulama açılmaz veya hata verir.

Uygulama kodunda sunucu adresi **sabit yazılı değil** ( `/api/...` göreli yollar kullanılıyor ). Sorun tamamen **hangi URL’den açtığınız** ile ilgili.

---

## Ne yapmalıyım?

### Seçenek A — Sabit domain (önerilen, ana ekran için en iyi)

Kendi domain’iniz varsa (ör. `benimadim.com`):

1. Domain’i [Cloudflare](https://dash.cloudflare.com) ücretsiz plana ekleyin
2. `cloudflared` kurun: `brew install cloudflared` (Mac)
3. Tünel oluşturun:
   ```bash
   cloudflared tunnel login
   cloudflared tunnel create sesli-cevirmen
   ```
4. `cloudflare-tunnel.example.yml` → `cloudflare-tunnel.yml` kopyalayın, UUID ve hostname’i doldurun
5. DNS kaydı:
   ```bash
   cloudflared tunnel route dns sesli-cevirmen ceviri.sizin-domain.com
   ```
6. Sunucu + sabit tünel:
   ```bash
   ./scripts/start-server.sh          # bir terminal
   ./scripts/start-tunnel-named.sh    # başka terminal
   ```
7. Safari’de **https://ceviri.sizin-domain.com** açın → Ana Ekrana Ekle

Bu adres **değişmez** (tünel çalıştığı sürece).

---

### Seçenek B — Evde Mac/PC’de sürekli çalıştırma

Sunucuyu kendi bilgisayarınızda 24/7 açık tutun:

```bash
cd sesli-cevirmen-ios
python3 server.py
```

- **Aynı Wi‑Fi’de iPhone:** `http://BILGISAYAR-IP:8780` (ör. `192.168.1.50:8780`) — IP genelde sabittir, ama **ev dışından çalışmaz**
- **Her yerden + sabit adres:** Seçenek A’daki Named Tunnel’ı ev bilgisayarınızda kurun

---

### Seçenek C — Geçici test (adres YİNE değişir)

```bash
./scripts/start-server.sh
./scripts/start-tunnel-quick.sh
```

Çıkan adres `PUBLIC_URL.txt` dosyasına yazılır. **Her tünel restart = yeni adres = ana ekranı yeniden eklemeniz gerekir.**

---

## Ana ekran kısayolu bozulduysa

1. Güncel adresi öğrenin (`PUBLIC_URL.txt` veya tünel logu)
2. Safari’de **yeni adresi** açın
3. Eski simgeyi silin
4. **Paylaş → Ana Ekrana Ekle** tekrar yapın

---

## Özet

| Yöntem | Adres sabit mi? | Ana ekran uygun mu? |
|--------|-----------------|---------------------|
| trycloudflare.com (quick) | Hayır | Kötü |
| Kendi domain + Named Tunnel | Evet | İyi |
| Ev ağı IP (8780) | Evet (LAN) | Sadece aynı Wi‑Fi |
| Railway / VPS + domain | Evet | İyi |

**Ana ekrana bir kez ekleyip unutmak istiyorsanız:** mutlaka **sabit domain** (Seçenek A veya barındırma) kullanın.
