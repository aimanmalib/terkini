<p align="center"><img src="brand/logo-512.png" width="96" height="96" alt="Terkini"></p>

<h1 align="center">Terkini</h1>

<p align="center"><b>Adakah jawapan AI ini masih betul di tempat anda?</b><br>
<a href="README.md">English</a> · <a href="https://aimanmalib.github.io/terkini/deck.pdf">slaid (Inggeris)</a> · Dibina di Malaysia oleh <a href="https://aimanmalib.com">Aiman Malib</a></p>

Terkini mengambil jawapan AI tentang peraturan Malaysia, seperti gaji minimum, kadar caruman KWSP, tarif elektrik atau had
jualan untuk e-Invois. Ia memecahkan jawapan itu kepada dakwaan, menyemak setiap dakwaan dengan laman rasmi kerajaan melalui
Tavily Search dan Extract, dan memberi skor kesegaran bersama petikan tepat dari sumber rasmi. Semua panggilan model AI melalui
gerbang Bifrost.

> **Bukan nasihat undang-undang.** Terkini membandingkan jawapan dengan apa yang laman rasmi katakan pada hari ia dijalankan.
> Ia boleh terlepas sesuatu laman, tersalah baca, atau membaca laman yang sudah lapuk. Sahkan perkara penting dengan agensi.

## Status

- **Sudah berfungsi:** semakan penuh dari baris arahan. Tiga larian sebenar pada 20 Nov 2026 dirakam dan boleh dimainkan
  semula tanpa rangkaian.
- **Penilaian, 21 Nov 2026:** 28 daripada 68 jawapan daripada 3 model menyatakan peraturan Malaysia
  yang berbeza daripada nilai rasmi semasa; Terkini menanda 10 daripadanya dengan laman rasmi
  (precision 59%, recall 36%). Butiran dan kegagalan: [`docs/EVAL.md`](docs/EVAL.md) (Inggeris).
- **Belum siap:** halaman web untuk menampal jawapan, dan video.

## Cuba

Perlu [uv](https://docs.astral.sh/uv/). Mod ulang tayang tidak memerlukan kunci API.

```bash
git clone https://github.com/aimanmalib/terkini && cd terkini
uv run terkini check --list
uv run terkini check --pack my --case my-12-kimi-k3-1-pro
```

Cara ia berfungsi, tempat Tavily dan Bifrost digunakan, dan had alat ini diterangkan dalam [README Inggeris](README.md).

## Lesen

Apache-2.0. Lihat [`LICENSE`](LICENSE).
