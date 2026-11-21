<p align="center"><img src="brand/logo-512.png" width="96" height="96" alt="Terkini"></p>

<h1 align="center">Terkini</h1>

<p align="center"><a href="https://github.com/aimanmalib/terkini/actions/workflows/ci.yml"><img src="https://github.com/aimanmalib/terkini/actions/workflows/ci.yml/badge.svg" alt="CI"></a> <a href="LICENSE"><img src="https://img.shields.io/github/license/aimanmalib/terkini" alt="Lesen: Apache-2.0"></a> <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python 3.12"></p>

<p align="center"><b>Adakah jawapan AI ini masih betul di tempat anda?</b><br>
<a href="README.md">English</a> · <a href="https://aimanmalib.github.io/terkini/">halaman ulang tayang</a> · <a href="#demo-satu-arahan-docker">demo</a> · <a href="https://aimanmalib.github.io/terkini/deck.pdf">slaid (Inggeris)</a> · <a href="docs/EVAL.md">penilaian (Inggeris)</a> · Dibina di Malaysia oleh <a href="https://aimanmalib.com">Aiman Malib</a></p>

Terkini mengambil jawapan AI tentang peraturan Malaysia, seperti gaji minimum, kadar caruman KWSP, tarif elektrik atau had
jualan untuk e-Invois. Ia memecahkan jawapan itu kepada dakwaan, menyemak setiap dakwaan dengan laman rasmi kerajaan melalui
Tavily Search dan Extract, dan memberi skor kesegaran bersama petikan tepat dari sumber rasmi. Semua panggilan model AI melalui
gerbang Bifrost.

> **Bukan nasihat undang-undang.** Terkini membandingkan jawapan dengan apa yang laman rasmi katakan pada hari ia dijalankan.
> Ia boleh terlepas sesuatu laman, tersalah baca, atau membaca laman yang sudah lapuk. Sahkan perkara penting dengan agensi.

Video demo (72 s, Inggeris, sari kata dibakar): <https://aimanmalib.github.io/terkini/media/terkini-demo.mp4>. Suara
naratif ialah klon AI suara saya sendiri (ElevenLabs), dinyatakan pada kad akhir. Video dirakam sebelum langkah hibrid dan menunjukkan angka v0.1.0 (10 daripada 17 tanda betul, precision 59%, recall 36%).

## Apa yang berfungsi / had diketahui

**Apa yang berfungsi**

- Semakan penuh dari baris arahan. Tiga larian sebenar pada 20 Nov 2026 dirakam dan boleh dimainkan
  semula tanpa rangkaian.
- Penilaian, 21 Nov 2026: 28 daripada 68 jawapan daripada 3 model menyatakan peraturan Malaysia
  yang berbeza daripada nilai rasmi semasa. Dengan langkah hibrid (model mencadang nilai semasa, petikan rasmi mesti
  menyatakannya), Terkini menanda 13 daripadanya (precision 65%, recall 46%); v0.1.0 tanpanya menanda 10 (59%, 36%).
  Butiran dan kegagalan: [`docs/EVAL.md`](docs/EVAL.md) (Inggeris).
- Garis asas: model hakim sahaja, tanpa laman rasmi, menanda 24 daripada 28 jawapan basi (precision 73%,
  recall 86%), tetapi tanpa sumber. Terkini menanda lebih sedikit, setiap satu dengan petikan rasmi tepat.
- Halaman ulang tayang (enam larian dirakam, BM dan Inggeris), `POST /api/check`, yang
  memulangkan laporan yang sama sebagai JSON, dan demo satu arahan dengan Docker.

**Had diketahui**

- Halaman ulang tayang tidak menjalankan semakan langsung. Ia menunjukkan larian yang dirakam dan memberi arahan untuk
  menyemak jawapan anda sendiri di komputer anda.
- Pek India belum dibina (digugurkan supaya kekal dalam bajet kredit Tavily, D-017).

## Cuba

Perlu [uv](https://docs.astral.sh/uv/). Mod ulang tayang tidak memerlukan kunci API.

```bash
git clone https://github.com/aimanmalib/terkini && cd terkini
uv run terkini check --list                            # 3 larian dirakam dan 68 larian eval tersimpan
uv run terkini check --pack my --case my-03--grok-4-7  # papar satu daripadanya, luar talian
uv run terkini serve                                   # halaman ulang tayang di http://127.0.0.1:8710
```

Arahan kedua memapar jawapan Grok 4.7 yang menyebut kadar cukai perkhidmatan 6%. Terkini menandanya `outdated`:
kadar rasmi 8% sejak 1 Mac 2024, dengan petikan tepat dari panduan kastam. Kunci jawapan melabel jawapan ini basi.
Positif palsu juga ada: `uv run terkini check --case my-12-kimi-k3-1-pro` memapar satu daripadanya (lihat
[`docs/EVAL.md`](docs/EVAL.md)).

Halaman ulang tayang yang sama (enam larian dirakam, BM dan Inggeris): <https://aimanmalib.github.io/terkini/>. Buka "Cara semakan ini dijalankan" di bawah setiap larian untuk melihat setiap pertanyaan Tavily, `include_domains` dan kreditnya, serta setiap panggilan Bifrost dengan model yang diminta, model yang menjawab dan token.

## Demo satu arahan (Docker)

Jika anda ada Docker tetapi tiada uv, arahan ini menghidupkan halaman ulang tayang dan API dari klon. Tiada kunci diperlukan.

```bash
demo/run.sh          # cetak satu laporan dirakam, URL halaman dan baris curl untuk API
demo/run.sh stop     # buang kontena
```

## Had utama

- **Laman rasmi yang lebih lama boleh mengesahkan nilai lama.** Laman kerajaan masih menghidang halaman dengan nilai
  terdahulu, dan Terkini membaca hasil carian teratas, bukan halaman paling baharu. Jadi nilai lama boleh dinilai
  `current` dengan petikan rasmi yang sah. Dua contoh dari larian kami sendiri: untuk soalan gaji minimum, halaman yang
  dipilih ialah dokumen PERKESO dari 2025 yang menyebut "RM1,500 as of 2024", sedangkan kadar semasa RM1,700 (dakwaan itu
  berakhir `unverifiable`). Larian e-Invois yang dirakam (`my-09-grok-4-7`) diputuskan dengan kenyataan Kementerian
  Kewangan yang lebih lama, bukan pengecualian RM3,000,000 yang lebih baharu. Pembaikan dirancang: susun bukti ikut
  tarikh dokumen.

Cara ia berfungsi, tempat Tavily dan Bifrost digunakan, dan senarai had penuh diterangkan dalam [README Inggeris](README.md#limitations).

## Menyumbang

Isu dan pull request dialu-alukan: [`CONTRIBUTING.md`](CONTRIBUTING.md) (Inggeris). Laporkan isu keselamatan secara
peribadi ([`SECURITY.md`](SECURITY.md)).

## Lesen

Apache-2.0. Lihat [`LICENSE`](LICENSE).
