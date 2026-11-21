"""Write the burned-in captions of the demo video as an .srt file, from the word timings in work/data.js.

Same grouping as the on-screen captions (sariKata in pentas.js): a new line at sentence punctuation or after `had` words.
  python3 demo/video/srt.py <out.srt> [had]
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def lines(data: dict, had: int) -> list[tuple[float, float, str]]:
    chunks = []
    for bid in data["garis"].get("sari_kata", []):
        cur = []
        words = data["kata"][bid]
        for i, w in enumerate(words):
            cur.append(w)
            end = re.search(r"[.,:?!]$", w["w"]) and len(cur) >= 2
            if len(cur) >= had or end or i == len(words) - 1:
                chunks.append(cur)
                cur = []
    out = []
    for i, c in enumerate(chunks):
        start = c[0]["a"] - 0.08
        stop = c[-1]["b"] + 0.6
        if i + 1 < len(chunks):
            stop = min(chunks[i + 1][0]["a"] - 0.08, stop)
        out.append((start, stop, " ".join(w["w"] for w in c)))
    return out


def stamp(s: float) -> str:
    ms = int(round(max(s, 0) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main(argv: list[str]) -> None:
    raw = (HERE / "work" / "data.js").read_text()
    data = json.loads(raw[raw.index("=") + 1:].rstrip().rstrip(";"))
    had = int(argv[2]) if len(argv) > 2 else 9
    body = "\n".join(f"{n}\n{stamp(a)} --> {stamp(b)}\n{t}\n" for n, (a, b, t) in enumerate(lines(data, had), 1))
    Path(argv[1]).write_text(body)
    print(argv[1], body.count("-->"), "captions")


if __name__ == "__main__":
    main(sys.argv)
