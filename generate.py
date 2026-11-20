"""Builds dark_mode.svg and light_mode.svg: ASCII portrait + neofetch-style info panel.

Usage:  python generate.py
Needs:  pip install pillow
Optional env var GITHUB_TOKEN (set automatically inside GitHub Actions) for live stats.
"""
import json
import os
import urllib.request
from datetime import date
from html import escape

from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))

# dark -> light characters
RAMP = "@%#*+=-:. "
FONT = 16          # px
CHAR_W = FONT * 0.6
LINE_H = 20
PANEL_COLS = 60    # width of each info line, in characters

THEMES = {
    "dark":  {"bg": "#161b22", "text": "#c9d1d9", "key": "#ffa657", "value": "#a5d6ff",
              "title": "#c9d1d9", "dots": "#616e7f", "art": "#c9d1d9"},
    "light": {"bg": "#f6f8fa", "text": "#24292f", "key": "#953800", "value": "#0a3069",
              "title": "#24292f", "dots": "#c2cfde", "art": "#24292f"},
}


# ---------- ASCII art ----------
def ascii_art(path, width, invert):
    src = ImageOps.exif_transpose(Image.open(path)).convert("RGBA")
    # transparent pixels (photo with background removed) become blank space
    white = Image.new("RGBA", src.size, (255, 255, 255, 255))
    alpha = src.getchannel("A")
    img = Image.alpha_composite(white, src).convert("L")
    img = ImageOps.autocontrast(img, cutoff=2)
    h = max(1, int(img.height / img.width * width * (CHAR_W / LINE_H)))
    img = img.resize((width, h))
    alpha = alpha.resize((width, h))
    px, al = img.load(), alpha.load()
    lines = []
    for y in range(h):
        row = ""
        for x in range(width):
            if al[x, y] < 128:
                row += " "
                continue
            v = px[x, y] / 255
            if invert:
                v = 1 - v
            row += RAMP[min(len(RAMP) - 1, int(v * len(RAMP)))]
        lines.append(row)
    return lines


# ---------- GitHub stats ----------
def gql(query, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req, timeout=30))


def github_stats(user):
    stats = {"repos": "-", "contributed": "-", "stars": "-", "followers": "-", "commits": "-"}
    token = os.environ.get("GITHUB_TOKEN")
    if not token or user == "your-username":
        return stats
    try:
        q = f"""{{ user(login: "{user}") {{
            followers {{ totalCount }}
            repositoriesContributedTo(contributionTypes:[COMMIT,PULL_REQUEST,REPOSITORY]) {{ totalCount }}
            contributionsCollection {{ totalCommitContributions }}
            repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {{
              totalCount nodes {{ stargazerCount }} }} }} }}"""
        u = gql(q, token)["data"]["user"]
        stats.update(
            repos=u["repositories"]["totalCount"],
            contributed=u["repositoriesContributedTo"]["totalCount"],
            stars=sum(n["stargazerCount"] for n in u["repositories"]["nodes"]),
            followers=u["followers"]["totalCount"],
            commits=u["contributionsCollection"]["totalCommitContributions"],
        )
    except Exception as e:  # keep building even if the API fails
        print("Stats fetch failed:", e)
    return {k: f"{v:,}" if isinstance(v, int) else v for k, v in stats.items()}


def uptime(bday):
    b = date.fromisoformat(bday)
    t = date.today()
    years = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
    months = (t.month - b.month - (t.day < b.day)) % 12
    anniv_month = (b.month + months - 1) % 12 + 1
    try:
        last = date(t.year if anniv_month <= t.month else t.year - 1, anniv_month, b.day)
    except ValueError:
        last = t
    days = (t - last).days
    return f"{years} years, {months} months, {days} days"


# ---------- SVG ----------
def panel_lines(values):
    out = []
    for i, sec in enumerate(CFG["sections"]):
        if i:
            out.append(("blank",))
        title = sec["title"]
        out.append(("title", title, "-" * (PANEL_COLS - len(title) - 1)))
        for key, val in sec["rows"]:
            if not key:
                out.append(("blank",))
                continue
            val = val.format_map(values)
            dots = PANEL_COLS - len(key) - len(val) - 6
            out.append(("row", key, " " + "." * max(1, dots) + " ", val))
    return out


def build_svg(art, info, theme):
    c = THEMES[theme]
    art_w = int(len(art[0]) * CHAR_W) + 40
    width = art_w + int(PANEL_COLS * CHAR_W) + 40
    height = max(len(art), len(info)) * LINE_H + 50

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" font-family="ConsolasFallback,Consolas,'
         f"'Courier New',monospace\" width=\"{width}px\" height=\"{height}px\" font-size=\"{FONT}px\">",
         "<style>",
         "@font-face{src:local('Consolas'),local('Consolas Bold');font-family:'ConsolasFallback';"
         "font-display:swap;-webkit-size-adjust:109%;size-adjust:109%;}",
         f".k{{fill:{c['key']}}}.v{{fill:{c['value']}}}.d{{fill:{c['dots']}}}"
         f".t{{fill:{c['title']};font-weight:bold}}",
         "text,tspan{white-space:pre}",
         "</style>",
         f'<rect width="{width}px" height="{height}px" fill="{c["bg"]}" rx="15"/>']

    s.append(f'<text x="15" y="30" fill="{c["art"]}" class="ascii">')
    for i, line in enumerate(art):
        s.append(f'<tspan x="15" y="{30 + i * LINE_H}">{escape(line)}</tspan>')
    s.append("</text>")

    x = art_w
    s.append(f'<text x="{x}" y="30" fill="{c["text"]}">')
    for i, item in enumerate(info):
        y = 30 + i * LINE_H
        if item[0] == "blank":
            s.append(f'<tspan x="{x}" y="{y}"> </tspan>')
        elif item[0] == "title":
            s.append(f'<tspan x="{x}" y="{y}" class="t">{escape(item[1])}</tspan>'
                     f'<tspan class="d"> {item[2]}</tspan>')
        else:
            _, k, dots, v = item
            s.append(f'<tspan x="{x}" y="{y}" class="d">. </tspan><tspan class="k">{escape(k)}</tspan>'
                     f'<tspan class="d">:{dots}</tspan><tspan class="v">{escape(v)}</tspan>')
    s.append("</text></svg>")
    return "\n".join(s)


def main():
    values = github_stats(CFG["github_username"])
    values["uptime"] = uptime(CFG["birthday"])
    info = panel_lines(values)
    art = ascii_art(os.path.join(HERE, CFG["photo"]), CFG["ascii_width"], CFG.get("invert", False))
    inv = CFG.get("invert", False)
    for theme in THEMES:
        # on the dark card, bright pixels get the dense characters (and vice versa)
        a = ascii_art(os.path.join(HERE, CFG["photo"]), CFG["ascii_width"],
                      inv if theme == "light" else not inv)
        with open(os.path.join(HERE, f"{theme}_mode.svg"), "w", encoding="utf-8") as f:
            f.write(build_svg(a, info, theme))
        print(f"wrote {theme}_mode.svg")


if __name__ == "__main__":
    main()
