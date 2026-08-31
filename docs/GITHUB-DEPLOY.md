# GitHub + Render ile 7/24 sabit adres (iPhone)

Bu rehber **Mac olmadan**, sadece **iPhone + GitHub + Render** ile uygulamayı sürekli açık tutmanız içindir.

Sonuç: **`https://sesli-cevirmen-xxxx.onrender.com`** gibi **değişmeyen** bir adres. Ana ekrana bir kez eklersiniz.

---

## 1) Kodu GitHub’a yükle

Repo henüz yoksa (iPhone Safari veya bilgisayar):

1. GitHub hesabın: **ademx06**
2. Repo: **Cevirici** — https://github.com/ademx06/Cevirici
3. Cursor’da GitHub bağlıysa agent’a **“push et”** deyin; kod `main` dalına gider.

Manuel push (Mac/PC):

```bash
cd sesli-cevirmen-ios
git remote add origin https://github.com/ademx06/Cevirici.git
git push -u origin main
```

> Repo zaten varsa sadece `git push origin main` yeterli.

---

## 2) Render’da deploy (ücretsiz)

1. [render.com](https://render.com) → **Get Started** → **GitHub** ile giriş
2. **New +** → **Blueprint**
3. GitHub’daki **`sesli-cevirmen-ios`** reposunu seçin
4. `render.yaml` otomatik okunur → **Apply**
5. **Environment** bölümünde şu gizli anahtarları ekleyin:

| Anahtar | Değer |
|---------|--------|
| `GROQ_API_KEY` | Groq konsolundan (ücretsiz AI öğretmen) |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` |
| `TELEGRAM_BOT_TOKEN` | @BotFather token (isteğe bağlı) |
| `TELEGRAM_CHAT_ID` | Telegram chat id (isteğe bağlı) |

6. Deploy bitince adres şöyle olur:

```
https://sesli-cevirmen.onrender.com
```

(Başındaki isim Render’da görünen servis adına göre değişir.)

---

## 3) iPhone kurulum

1. Safari’de Render adresini açın, örn.  
   `https://sesli-cevirmen.onrender.com/education.html?v=20`
2. **Paylaş → Ana Ekrana Ekle**
3. Çeviri: `.../translate.html`

**Link artık sabit** — `trycloudflare.com` gibi her gün değişmez.

---

## 4) Telegram (isteğe bağlı)

Render’da `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` tanımlıysa bot açılır.

Telegram’da bota **`/link`** yazın → sabit Render adresini gönderir.

---

## 5) Ücretsiz planda bilmeniz gerekenler

| Konu | Açıklama |
|------|----------|
| Uyku modu | ~15 dk kullanılmazsa sunucu uyur; ilk açılış **30–60 sn** sürebilir |
| Whisper | Bulutta `tiny` model kullanılır (daha az RAM); ses tanıma biraz daha basit |
| AI öğretmen | Groq anahtarı zorunlu değil ama **önerilir** |

Uyku modunu azaltmak için ücretli Render planı veya [UptimeRobot](https://uptimerobot.com) ile `/api/status` adresine 5 dk’da bir ping atılabilir.

---

## 6) Güncelleme

GitHub’a `git push` yaptığınızda Render **otomatik yeniden deploy** eder. iPhone’daki ana ekran simgesi **aynı kalır**.

---

## Sorun giderme

| Sorun | Çözüm |
|-------|--------|
| Sayfa açılmıyor | Render dashboard → Logs; deploy yeşil mi? |
| AI kapalı | `GROQ_API_KEY` Render env’de var mı? |
| Ses tanıma zayıf | Normal (`WHISPER_MODEL=tiny`); konuşmayı net söyleyin |
| Eski arayüz | Safari’de sert yenile veya `?v=20` ekleyin |

---

## Özet

```
GitHub repo  →  Render Blueprint (render.yaml)  →  Sabit https://....onrender.com
```

Ana ekrana **Render adresini** ekleyin; geçici Cloudflare linklerine gerek kalmaz.
