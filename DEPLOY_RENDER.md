# Render.com Yayınlama

## 1) Kodu GitHub'a gönder
1. Bu proje klasörünü bir GitHub reposuna push et.

## 2) Render'da Blueprint ile kur
1. Render panelinde `New +` -> `Blueprint` seç.
2. GitHub reposunu bağla.
3. Render, kökteki `render.yaml` dosyasını okuyup:
   - `eco-access` web servisini
   - `eco-access-db` Postgres veritabanını
   otomatik oluşturur.

## 3) Zorunlu ortam değişkenleri
Render web servisinde şu değerleri gir:
- `DEEPSEEK_API_KEY` = OpenRouter/DeepSeek anahtarın
- `ECO_OWNER_PASSWORD` = owner hesabı şifresi

İstersen:
- `ECO_OWNER_USERNAME` (varsayılan: `eymen`)
- `OPENROUTER_MODEL` (varsayılan: `deepseek/deepseek-chat`)

## 4) Yayın URL'i
Deploy tamamlandıktan sonra Render sana bir public URL verir.
Bu URL ile herkes siteyi kullanabilir.
