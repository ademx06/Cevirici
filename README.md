# Sesli Çevirmen — iPhone PWA

Safari için sesli çeviri + dil eğitimi.

## 7/24 sabit adres (GitHub + Render) — önerilen

Mac gerekmez. GitHub’a kod, Render’da ücretsiz barındırma:

**[docs/GITHUB-DEPLOY.md](docs/GITHUB-DEPLOY.md)** ← adım adım iPhone rehberi

## Kendin çalıştır (Mac)

```bash
cd sesli-cevirmen-ios
chmod +x scripts/baslat.sh
./scripts/baslat.sh
```

Link ekranda çıkar ve **`PUBLIC_URL.txt`** dosyasına kaydedilir.

Tekrar görmek: `./scripts/baslat.sh url` veya `cat PUBLIC_URL.txt`

Detaylı rehber: **[NASIL-CALISTIRILIR.md](NASIL-CALISTIRILIR.md)**

## iPhone kurulum

1. `PUBLIC_URL.txt` içindeki adresi Safari’de aç
2. **Paylaş → Ana Ekrana Ekle**

## Sabit adres (ana ekran için önerilen)

[docs/SABIT-ADRES.md](docs/SABIT-ADRES.md)

## Modüller

- **Çeviri** — `/translate.html`
- **Eğitim** — `/education.html`
