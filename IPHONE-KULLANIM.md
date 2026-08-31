# iPhone’da Sesli Çevirmen — Hızlı Rehber

Bu uygulama iPhone’da **Safari** ile açılır. Sunucu bilgisayarda veya bulutta çalışır; telefon sadece bağlanır.

## Kalıcı adres (bir kez kur, link değişmez)

GitHub + Render ile sabit adres: **[docs/GITHUB-DEPLOY.md](docs/GITHUB-DEPLOY.md)**

Kurulumdan sonra iPhone’a `https://....onrender.com/education.html?v=20` ekleyin — link artık ölmez.

---

## Günlük kullanım (en kolay)

1. Ana ekrandaki **Sesli Çevirmen** simgesine dokun.
2. **Eğitim** veya **Çeviri** modülünü seç.
3. Mikrofon izni istenirse **İzin Ver**.

Bu kadar — her seferinde adres araman gerekmez.

## Adresi telefonda nereden görürsün?

Uygulama açıkken:

1. Ana menüde alttaki **📱 iPhone: Adres & yardım** linkine dokun  
   **veya** tarayıcıda şu sayfayı aç: `/mobil.html`
2. Büyük kutuda **şu anki çalışan adres** yazar.
3. **📋 Adresi kopyala** ile panoya alırsın.

## Uygulama açılmıyorsa

1. **mobil.html** sayfasına git (çalışan bir linkten).
2. Yeşil “Sunucu çalışıyor” görüyorsan adres doğrudur → Ana ekrana tekrar ekle.
3. Kırmızı “ulaşılamıyor” görüyorsan sunucu kapalı veya adres eski.

**Yeni link nereden?** Eski link ölünce telefondan kendin bulamazsın. Çözüm: **[YENI-LINK-NEREDEN.md](YENI-LINK-NEREDEN.md)** (Telegram veya sabit domain).

## Ana ekrana ekleme (Safari)

1. Çalışan adresi Safari’de aç.
2. **Paylaş** (kare + ok) → **Ana Ekrana Ekle** → **Ekle**.

Eski simge artık çalışmıyorsa: simgeyi sil, yeni adresle tekrar ekle.

## Önemli

- iPhone’da `python3 server.py` **çalıştırılamaz** — sunucu Mac/PC/bulutta olmalı.
- Geçici `*.trycloudflare.com` adresleri sunucu yeniden başlayınca **değişebilir**.
- Kalıcı adres için: `docs/SABIT-ADRES.md`

## Şu anki adres (sunucu tarafında)

Sunucu çalışırken `PUBLIC_URL.txt` dosyasına yazılır. Telefonda görmek için yine **mobil.html** kullan — o an bağlı olduğun adresi gösterir.
