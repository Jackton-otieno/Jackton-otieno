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

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

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


# ---------- photo ----------
def load_photo():
    """'avatar' = use your current GitHub profile picture; otherwise a file in the repo."""
    if CFG["photo"] == "avatar":
        try:
            url = f"https://github.com/{CFG['github_username']}.png?size=460"
            data = urllib.request.urlopen(url, timeout=30).read()
            with open(os.path.join(HERE, "avatar.png"), "wb") as f:
                f.write(data)
            path = os.path.join(HERE, "avatar.png")
        except Exception as e:
            print("Avatar download failed, using photo.png:", e)
            path = os.path.join(HERE, "photo.png")
    else:
        path = os.path.join(HERE, CFG["photo"])
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGBA")
    if CFG.get("crop"):  # [left, top, right, bottom] as fractions of the photo
        l, t, r, b = CFG["crop"]
        img = img.crop((int(l * img.width), int(t * img.height), int(r * img.width), int(b * img.height)))
    if CFG.get("remove_background", False):
        img = remove_background(img, CFG.get("background_tolerance", 40))
    return img


def remove_background(img, tol):
    """Flood-fills from every edge pixel: plain backgrounds touching the border become transparent."""
    rgb = img.convert("RGB").filter(ImageFilter.SMOOTH)
    w, h = rgb.size
    marker = (255, 0, 255)
    work = rgb.copy()
    for x, y in [(x, 0) for x in range(0, w, 8)] + [(x, h - 1) for x in range(0, w, 8)] + \
                [(0, y) for y in range(0, h, 8)] + [(w - 1, y) for y in range(0, h, 8)]:
        if work.getpixel((x, y)) != marker:
            ImageDraw.floodfill(work, (x, y), marker, thresh=tol)
    mask = Image.eval(ImageChops.difference(work, Image.new("RGB", (w, h), marker)).convert("L"),
                      lambda v: 0 if v == 0 else 255)
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    out = img.copy()
    out.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    return out


# ---------- ASCII art ----------
def ascii_art(src, width, invert):
    # transparent pixels (photo with background removed) become blank space
    white = Image.new("RGBA", src.size, (255, 255, 255, 255))
    alpha = src.getchannel("A")
    img = Image.alpha_composite(white, src).convert("L")
    # local contrast boost: brings out eyes, glasses and smile before shrinking
    lc = CFG.get("local_contrast", 0)
    if lc:
        img = img.filter(ImageFilter.UnsharpMask(radius=max(2, img.width // 25), percent=lc, threshold=0))
    h = max(1, int(img.height / img.width * width * (CHAR_W / LINE_H)))
    img = img.resize((width, h), Image.LANCZOS)
    alpha = alpha.resize((width, h))
    # stretch contrast using only the subject's pixels, so faces keep their detail
    mask = alpha.point(lambda v: 255 if v >= 128 else 0)
    if CFG.get("contrast", "equalize") == "equalize":
        img = ImageOps.equalize(img, mask=mask)
    else:
        img = ImageOps.autocontrast(img, cutoff=2, mask=mask)
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
        lines.append(row.rstrip())
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    w = max(len(l) for l in lines)
    return [l.ljust(w) for l in lines]


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
    values["uptime"] = uptime(CFG["birthday"]) if CFG.get("birthday") else "-"
    info = panel_lines(values)
    photo = load_photo()
    inv = CFG.get("invert", False)
    for theme in THEMES:
        # on the dark card, bright pixels get the dense characters (and vice versa)
        a = ascii_art(photo, CFG["ascii_width"], inv if theme == "light" or not CFG.get("invert_on_dark", True) else not inv)
        with open(os.path.join(HERE, f"{theme}_mode.svg"), "w", encoding="utf-8") as f:
            f.write(build_svg(a, info, theme))
        print(f"wrote {theme}_mode.svg")


if __name__ == "__main__":
    main()
