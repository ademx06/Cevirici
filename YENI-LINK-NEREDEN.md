# Yeni link nereden alınır? (iPhone)

## Kısa cevap

**Geçici `trycloudflare.com` linkiyle:** Eski link öldüyse telefondan yeni linki **kendin bulamazsın**. Uygulama kapalıyken `mobil.html` de açılmaz — o sayfa zaten eski adreste.

**Her seferinde bana sorman gerekmez.** Aşağıdaki yöntemlerden birini kur; sonra iPhone’dan kendin bakarsın.

---

## Seçenek 1 — Telegram (ücretsiz, iPhone için en pratik)

Sunucu her başlayınca link Telegram’a düşer. Telefonda **Telegram uygulamasını** açarsın — adres hep orada.

### Kurulum (bir kez, ~5 dk)

1. Telegram’da **@BotFather** → `/newbot` → bot adı ver → **token** al.
2. Oluşturduğun bota mesaj at (Start).
3. Tarayıcıda aç (TOKEN yerine kendi token’ını yaz):
   ```
   https://api.telegram.org/botTOKEN/getUpdates
   ```
   `"chat":{"id":123456789}` içindeki sayı = **chat id**.
4. Sunucuyu çalıştıran yerde (Mac veya bulut) ortam değişkenlerini ayarla:
   ```bash
   export TELEGRAM_BOT_TOKEN="123456:ABC..."
   export TELEGRAM_CHAT_ID="123456789"
   ```
5. `./scripts/baslat.sh` çalıştır.

### iPhone’da kullanım

1. **Telegram**’ı aç.
2. Bot sohbetine gir — en son mesajda güncel link yazar.
3. Linke dokun → Safari’de aç → Ana ekrana ekle.

Telegram sohbetini sabitle; link değişince tek bakacağın yer bu.

---

## Seçenek 2 — Sabit domain (en iyi, link hiç değişmez)

Kendi adresin olur, örn. `https://ceviri.senin-adin.com`

- Ana ekrana **bir kez** eklersin, bir daha link aramazsın.
- Kurulum: `docs/SABIT-ADRES.md`

Domain yoksa yıllık ~10$ civarı alınabilir (Namecheap, Cloudflare vb.).

---

## Seçenek 3 — GitHub’da sabit “link dosyası”

Projeyi GitHub’a koyduysan:

1. iPhone Safari’de şu tür **sabit yer imi** kaydet:
   ```
   https://raw.githubusercontent.com/KULLANICI/REPO/main/PUBLIC_URL.txt
   ```
2. Sunucu başlayınca `PUBLIC_URL.txt` GitHub’a push edilir (otomasyon gerekir).
3. Link değişince Safari’de **o yer imine** git — dosyada yeni adres yazar.

GitHub hesabın yoksa Seçenek 1 (Telegram) daha kolay.

---

## Seçenek 4 — GitHub + Render (7/24, sabit adres, Mac gerekmez)

En pratik kalıcı çözüm:

1. Kod GitHub’da → **[docs/GITHUB-DEPLOY.md](docs/GITHUB-DEPLOY.md)** adımlarını izle
2. Render’da ücretsiz deploy → `https://....onrender.com` **sabit kalır**
3. iPhone Safari → Ana ekrana ekle

Telegram `/link` Render adresini gösterir (env tanımlıysa).

---

## Seçenek 5 — Bulut sunucu (VPS) + sabit domain

---

## Şu anki geçici sistemde (Telegram yok, sabit domain yok)

| Durum | Ne yaparsın |
|--------|-------------|
| Ana ekran simgesi var, sunucu çalışıyor | Simgeye dokun |
| Link eski / açılmıyor | Sunucuyu çalıştıran kişiden veya Cursor agent’tan yeni link iste |
| Kendin bağımsız olmak istiyorsun | **Telegram botu** veya **sabit domain** kur |

---

## Özet

| Yöntem | Telefondan kendin bakabilir misin? | Link değişir mi? |
|--------|-----------------------------------|------------------|
| trycloudflare (şimdiki) | Hayır (eski link ölünce) | Evet, sık |
| Telegram bot | **Evet** | Evet, ama Telegram’da görürsün |
| Sabit domain | **Evet** ( hep aynı ) | Hayır |
| GitHub raw dosya | **Evet** (yer imi) | Dosya güncellenirse |

**Tavsiye:** iPhone’dan tek başına kullanacaksan → önce **Telegram**, uzun vadede **sabit domain**.
