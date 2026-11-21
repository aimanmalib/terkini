# Demo video source

The demo video (`docs/media/terkini-demo.mp4`, 72 s, 1920x1080) is rendered frame by frame from a web page, so it can be
rebuilt the same way every time. Frame 0 shows the question and the stale answer. The real replay page starts at 7 s.

| File | What |
|---|---|
| `skrip.json` | Narration, one line per scene. `sari` is the caption, `baca` the text read aloud when it differs |
| `garis.json` | Scene times, events tied to spoken words, sound effects, and all on-screen text |
| `tangkap.py` | Captures the real replay page from `docs/` on localhost, and reads the domain list and eval numbers from `packs/my.toml` and `eval/my/results.json` |
| `work/stage.html` | The stage: a pure function of time, `seek(t)` |
| `srt.py` | Writes the burned-in captions as `docs/media/terkini-demo.srt` |
| `kongsi.txt` | Caption text for posting the video |

The narration is an AI clone of the builder's own voice (ElevenLabs), labelled on the end card. Music: Sascha Ende,
ende.app (CC BY 4.0). Sound effects: Kenney (CC0).

The build uses the author's video kit (`vp`), which is not in this repository: `vp suara` (voice), `vp data` (timings),
`vp render`, `vp bunyi` (mix), `vp gabung` (mux). The final file is then loudness-normalised to -16.5 LUFS with a true peak
under -1.5 dBTP.
