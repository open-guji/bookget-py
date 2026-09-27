"""LuaLaTeX engine: the archival PDF with a typeset, boxed metadata form.

This reproduces the documents built for the NPM → Wikimedia Commons batches:
every image page at its native pixel size (JPEG embedded unmodified by
\\includegraphics), then a form (文物資料表) with selectable CJK text, plus
PDF Info + XMP (hyperxmp), bookmarks, page labels and embedded attachments.

Requirements (not installed by bookget): a TeX Live with LuaLaTeX and the
packages fontspec, luatexja, geometry, xcolor, longtable, tabularx, xurl,
embedfile, hyperref, hyperxmp, bookmark; a CJK font such as Source Han Serif
(``BOOKGET_CJK_FONT`` overrides the font file name).
"""

from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

PUA_MAP = {"木\uf6a4挈": "㮮"}
TOOL_URL = "https://github.com/open-guji/bookget-py"


class LatexNotAvailable(RuntimeError):
    pass


# ---------------------------------------------------------------- toolchain
def find_lualatex() -> Optional[str]:
    """lualatex from $BOOKGET_LUALATEX, PATH, or the usual TeX Live locations."""
    env = os.environ.get("BOOKGET_LUALATEX")
    if env and Path(env).exists():
        return env
    exe = shutil.which("lualatex")
    if exe:
        return exe
    pats = [str(Path.home() / "texlive" / "*" / "bin" / "*" / "lualatex"),
            "/usr/local/texlive/*/bin/*/lualatex", "/opt/texlive/*/bin/*/lualatex",
            "C:/texlive/*/bin/*/lualatex.exe", "/Library/TeX/texbin/lualatex"]
    for pat in pats:
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None


def _kpsewhich(lualatex: str, name: str) -> bool:
    exe = str(Path(lualatex).with_name("kpsewhich" + Path(lualatex).suffix))
    if not Path(exe).exists():
        exe = "kpsewhich"
    try:
        r = subprocess.run([exe, name], capture_output=True, text=True)
        return bool(r.stdout.strip())
    except OSError:
        return False


def find_font(lualatex: str, *names: str) -> str:
    for n in names:
        if _kpsewhich(lualatex, n):
            return n
    raise LatexNotAvailable(f"none of these fonts is installed in TeX Live: {names}")


# ---------------------------------------------------------------- text helpers
def esc(s) -> str:
    """LaTeX-escape body text (drops any private-use characters the site leaks)."""
    s = str(s if s is not None else "")
    for k, v in PUA_MAP.items():
        s = s.replace(k, v)
    s = "".join(ch for ch in s if not 0xE000 <= ord(ch) <= 0xF8FF)
    for a, b in [("\\", r"\textbackslash{}"), ("{", r"\{"), ("}", r"\}"), ("$", r"\$"), ("&", r"\&"),
                 ("#", r"\#"), ("^", r"\^{}"), ("_", r"\_"), ("%", r"\%"), ("~", r"\textasciitilde{}")]:
        s = s.replace(a, b)
    return s.replace("--", "-{}-")


def hs(s) -> str:
    """hyperref/hyperxmp key values (pdfstringdef): no braces, escape specials."""
    return (str(s if s is not None else "").replace("\\", "").replace("{", "").replace("}", "")
            .replace("%", r"\%").replace("&", r"\&").replace("#", r"\#")
            .replace("_", r"\textunderscore{}").replace("--", "-{}-"))


def url_arg(u: str) -> str:
    return (u or "").replace("&", r"\&").replace("%", r"\%").replace("#", r"\#")


def chunks(text: str, limit: int) -> List[str]:
    """Split text into pieces of at most ~limit chars, preferring sentence ends (。；)."""
    text = text or ""
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for part in re.split(r"(?<=[。；;])", text):
        while len(part) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.append(part[:limit])
            part = part[limit:]
        if cur and len(cur) + len(part) > limit:
            out.append(cur)
            cur = ""
        cur += part
    if cur:
        out.append(cur)
    return out


def fit_rows(rows, n):
    """Source tables occasionally have rows with more or fewer cells than the header."""
    out = []
    for r in rows:
        r = [str(c) for c in r]
        if len(r) > n:
            r = r[:n - 1] + [" / ".join(c for c in r[n - 1:] if c)]
        out.append(r + [""] * (n - len(r)))
    return out


def colspec(widths):
    n = len(widths)
    fixed = sum(float(x[:-2]) for x in widths if x)
    rest = r"\dimexpr(\textwidth-%smm-%d\tabcolsep-%d\arrayrulewidth)/%d\relax" % (fixed, 2 * n, n + 1, max(1, widths.count(None)))
    return "|".join(r">{\raggedright\arraybackslash}p{%s}" % (x or rest) for x in widths)


PREAMBLE = r"""\documentclass[11pt]{article}
\usepackage{fontspec}
\usepackage[match]{luatexja-fontspec}
\setmainfont{%(latin)s}
\setmainjfont{%(cjk)s}[BoldFont=%(cjk)s,BoldFeatures={FakeBold=1.6}]
\setmonofont{%(mono)s}[Scale=MatchLowercase]
\usepackage[a4paper,margin=18mm]{geometry}
\usepackage[table]{xcolor}
\usepackage{graphicx,longtable,booktabs,tabularx,array,xurl}
\renewcommand{\UrlFont}{\ttfamily\small}
\usepackage{embedfile}
\usepackage[unicode,hidelinks,bookmarksopen,bookmarksnumbered=false]{hyperref}
\usepackage{hyperxmp}
\hypersetup{keeppdfinfo}
\usepackage{bookmark}
\definecolor{dim}{gray}{0.45}
\definecolor{labelbg}{gray}{0.92}
\definecolor{sectbg}{RGB}{58,58,58}
\definecolor{rulec}{gray}{0.55}
\arrayrulecolor{rulec}
\renewcommand{\arraystretch}{1.5}
\setlength{\tabcolsep}{5pt}
\setlength{\LTleft}{0pt}\setlength{\LTright}{0pt}\setlength{\LTpre}{0pt}\setlength{\LTpost}{6pt}
\setlength{\fboxsep}{4pt}
\setlength{\parindent}{0pt}\setlength{\parskip}{3pt}
\newcommand{\en}[1]{{\footnotesize\color{dim}#1}}
\newcommand{\val}[1]{\textbf{#1}}
\newlength{\labw}\setlength{\labw}{50mm}
\newlength{\valw}\setlength{\valw}{\dimexpr\textwidth-\labw-4\tabcolsep-3\arrayrulewidth\relax}
%% section bar as a table row spanning #1 columns, so it can never be separated from its table
\newcommand{\sbar}[3]{\multicolumn{#1}{|>{\columncolor{sectbg}}l|}{\color{white}\textbf{#2}\quad{\small #3}}\\\hline}
\newenvironment{form}[2]{\par\vspace{6pt}\begin{longtable}{|>{\columncolor{labelbg}\raggedright\arraybackslash}p{\labw}|>{\raggedright\arraybackslash}p{\valw}|}\hline\sbar{2}{#1}{#2}\endfirsthead\hline\endhead}{\end{longtable}}
\makeatletter
\newcommand{\imagepage}[5]{%%
  %% the whole vertical layout must be set BEFORE \clearpage: LaTeX takes the next page's goal from these
  %% values when \clearpage runs, so a taller page after a shorter one would otherwise be pushed to a blank page
  %% (this produces a harmless "overfull vbox" warning when the previous page was the taller one)
  \textheight=\dimexpr#3bp+20pt\relax \vsize=\textheight \global\@colht=\textheight \global\@colroom=\textheight
  \clearpage
  \pagewidth=#2bp \pageheight=#3bp \textwidth=#2bp \hsize=#2bp \linewidth=#2bp \columnwidth=#2bp
  \hoffset=-1in \voffset=-1in \oddsidemargin=0pt \evensidemargin=0pt \topmargin=0pt
  \headheight=0pt \headsep=0pt \footskip=0pt \topskip=0pt \parindent=0pt \parskip=0pt \lineskip=0pt \lineskiplimit=0pt \maxdepth=0pt
  \thispagestyle{empty}\thispdfpagelabel{#4}#5%%
  \noindent\includegraphics[width=#2bp,height=#3bp]{#1}\par}
\newlength\F@tw\newlength\F@th\newlength\F@osm\newlength\F@esm\newlength\F@tm\newlength\F@hh\newlength\F@hs\newlength\F@fs
\AtBeginDocument{\setlength\F@tw\textwidth\setlength\F@th\textheight\setlength\F@osm\oddsidemargin\setlength\F@esm\evensidemargin
  \setlength\F@tm\topmargin\setlength\F@hh\headheight\setlength\F@hs\headsep\setlength\F@fs\footskip}
\newcommand{\formpage}{%%
  \textheight=\F@th \vsize=\textheight \global\@colht=\textheight \global\@colroom=\textheight
  \clearpage
  \pagewidth=\paperwidth \pageheight=\paperheight \hoffset=0pt \voffset=0pt
  \textwidth=\F@tw \textheight=\F@th \global\@colht=\textheight \global\@colroom=\textheight \oddsidemargin=\F@osm \evensidemargin=\F@esm \topmargin=\F@tm
  \headheight=\F@hh \headsep=\F@hs \footskip=\F@fs
  \hsize=\textwidth \vsize=\textheight \columnwidth=\textwidth \linewidth=\textwidth
  \global\@colht=\textheight \global\@colroom=\textheight
  \topskip=11pt \lineskip=1pt \lineskiplimit=0pt \maxdepth=.5pt \parindent=0pt \parskip=3pt
  \pagestyle{plain}}
\makeatother
"""


# ---------------------------------------------------------------- document
def render_tex(m: Dict, book_dir: Path, fonts: Dict[str, str], dpi: float) -> str:
    """The complete .tex source for schema ``m`` (paths absolute, forward slashes)."""
    L: List[str] = []
    w = L.append
    w(PREAMBLE % fonts)

    lic = m["license"]
    holder = m["holder"]
    pdfinfo = {k: v for k, v in dict(m.get("pdfinfo", {})).items() if v}
    pdfinfo.setdefault("Retrieved", m.get("retrieved", ""))
    source_url = next((u for u in m.get("urls", {}).values() if u), "")
    copyright_ = f'{holder["zh"]} ({holder["en"]}). {lic["image_license"]}。{lic["attribution_zh"]}' if holder.get("en") \
        else f'{holder["zh"]}. {lic["image_license"]}。{lic["attribution_zh"]}'
    w(r"""\hypersetup{
  pdftitle={%s}, pdfauthor={%s}, pdfsubject={%s}, pdfkeywords={%s},
  pdfpublisher={%s}, pdflang={zh-TW}, pdfmetalang={zh-TW}, pdftype={Image},
  pdfcopyright={%s}, pdflicenseurl={%s},
  pdfsource={%s}, pdfcontacturl={%s},
  pdfcreator={bookget-py (%s)},
  pdfinfo={%s}}
""" % (hs(m["title"]), hs(m.get("author")), hs(m.get("subject")), hs(", ".join(m.get("keywords", []))),
       hs(holder["zh"]), hs(copyright_), url_arg(lic.get("image_license_url", "")), url_arg(source_url),
       url_arg(holder.get("url", "")), TOOL_URL, ", ".join(f"{k}={{{hs(v)}}}" for k, v in pdfinfo.items() if v)))

    for name, desc, mime in m.get("attachments", []):
        p = book_dir / name
        if p.exists():
            w(r"\embedfile[filespec=%s,mimetype=%s,desc={%s}]{%s}" % (Path(name).name, mime, esc(desc), p.as_posix()))

    w(r"\begin{document}")
    for p in m["pages"]:
        f = (book_dir / p["file"]).as_posix()
        bms = "".join(r"\pdfbookmark[%d]{%s}{bm%d-%d}" % (level, esc(text), p["index"], level)
                      for level, text in p.get("bookmarks", []))
        w(r"\imagepage{%s}{%.4f}{%.4f}{%s}{%s}" % (f, p["width"] * 72 / dpi, p["height"] * 72 / dpi, esc(p["label"]), bms))

    w(r"\formpage\pagenumbering{roman}\pdfbookmark[0]{%s Metadata}{meta}" % esc(m["form_title"]))
    w(r"\begin{center}{\Large\bfseries %s\quad %s}\\[3pt]{\color{dim}%s · %s}\end{center}\vspace{-6pt}"
      % (esc(holder["zh"]), esc(m["form_title"]), esc(holder.get("en", "")), esc(m["record_label"])))

    def header_row(header_zh, header_en):
        hen = header_en or []
        return " & ".join(r"%s%s" % (esc(h), (r" \en{%s}" % esc(hen[i])) if i < len(hen) and hen[i] and hen[i] != h else "")
                          for i, h in enumerate(header_zh))

    def grid(header_zh, header_en, rows, bar, widths=None, bold=True):
        n = len(header_zh)
        spec = colspec(widths) if widths else "|".join(["X"] * n)
        w(r"\par\vspace{6pt}\begin{tabularx}{\textwidth}{|%s|}\hline" % spec)
        w(r"\sbar{%d}{%s}{%s}" % (n, esc(bar[0]), esc(bar[1] or "")))
        w(r"\rowcolor{labelbg}" + header_row(header_zh, header_en) + r"\\\hline")
        for r in fit_rows(rows, n):
            w(" & ".join((r"\val{%s}" % esc(c)) if (bold and c) else esc(c) for c in r) + r"\\\hline")
        w(r"\end{tabularx}\par\vspace{6pt}")

    def breakable_grid(header_zh, header_en, rows, bar, widths=None):
        """longtable version for lists that may run over a page."""
        n = len(header_zh)
        widths = widths or [None] * n
        spec = colspec(widths)
        # a longtable row cannot break across pages, so cap each cell by what fits in ~24 lines of its column
        fixed = sum(float(x[:-2]) for x in widths if x)
        rest_mm = max(20.0, (174 - fixed - 3.5 * n) / max(1, widths.count(None)))
        limits = [max(40, int((float(x[:-2]) if x else rest_mm) / 4.0 * 24)) for x in widths]
        w(r"\par\vspace{6pt}\begin{longtable}{|%s|}\hline\sbar{%d}{%s}{%s}" % (spec, n, esc(bar[0]), esc(bar[1] or "")))
        head = r"\rowcolor{labelbg}" + header_row(header_zh, header_en) + r"\\\hline"
        w(head + r"\endfirsthead\hline" + head + r"\endhead")
        for r in fit_rows(rows, n):
            parts = [chunks(c, min(300, limits[j])) for j, c in enumerate(r)]
            for k in range(max(len(x) for x in parts)):
                w(" & ".join((r"\val{%s}" % esc(x[k])) if k < len(x) and x[k] else "" for x in parts) + r"\\\hline")
        w(r"\end{longtable}")

    for s in m["sections"]:
        bar = (s["title_zh"], s.get("title_en") or "")
        if s.get("note"):
            w(r"\par\vspace{6pt}\begin{tabularx}{\textwidth}{|X|}\hline\sbar{1}{%s}{%s} %s\\\hline\end{tabularx}\par\vspace{6pt}"
              % (esc(bar[0]), esc(bar[1]), esc(s["note"])))
        if s.get("fields"):
            w(r"\begin{form}{%s}{%s}" % (esc(bar[0]), esc(bar[1])))
            for f in s["fields"]:
                label = r"%s \en{%s}" % (esc(f["label_zh"]), esc(f.get("label_en") or ""))
                for k, chunk in enumerate(chunks(str(f["value"]), 320)):
                    v = esc(chunk)
                    if f["label_zh"] == m["title_field"]:
                        v = r"{\large %s}" % v
                    w(r"%s & \val{%s} \\ \hline" % (label if k == 0 else r"\en{（續）}", v))
            w(r"\end{form}")
        elif s.get("rows"):
            if len(s["rows"]) > 12 or any(len(str(c)) > 150 for r in s["rows"] for c in r):   # tabularx cannot break
                breakable_grid(s["header_zh"], s.get("header_en"), s["rows"], bar, widths=s.get("widths"))
            else:
                grid(s["header_zh"], s.get("header_en"), s["rows"], bar, widths=s.get("widths"))

    if lic.get("image_license"):
        w(r"\begin{form}{授權與引用}{License and attribution}")
        w(r"授權條款 \en{License} & \val{%s}\quad\url{%s}\\ \hline" % (esc(lic["image_license"]), lic.get("image_license_url", "")))
        if lic.get("image_tier"):
            w(r"圖檔層級 \en{Image tier} & \val{%s}\\ \hline" % esc(lic["image_tier"]))
        if lic.get("attribution_zh"):
            w(r"姓名標示（中） \en{Attribution} & \val{%s}\\ \hline" % esc(lic["attribution_zh"]))
        if lic.get("attribution_en"):
            w(r"姓名標示（英） \en{Attribution} & \val{%s}\\ \hline" % esc(lic["attribution_en"]))
        if lic.get("policy_zh"):
            w(r"開放政策 \en{Policy} & %s\\ \hline" % esc(lic["policy_zh"]))
        if lic.get("site_statement"):
            st = lic["site_statement"]
            w(r"網站授權聲明 \en{Site terms} & %s\\ \hline" % ((r"\url{%s}" % st) if st.startswith("http") else esc(st)))
        w(r"\end{form}")

    w(r"\begin{form}{數位影像}{Digital images}")
    w(r"影像數量 \en{Images} & \val{%d 幅}\\ \hline" % len(m["pages"]))
    w(r"取得方式 \en{Source} & %s\\ \hline" % esc(m["images_note"]))
    if m.get("images_service"):
        w(r"服務位址 \en{Service} & \url{%s}\texttt{\{影像編號\}}\\ \hline" % m["images_service"])
    w(r"\end{form}")
    extra_label = m.get("page_extra_label") or ""
    header = ["頁", "影像編號"] + ([extra_label] if extra_label else []) + ["像素"]
    widths = ["9mm", None] + (["42mm"] if extra_label else []) + ["24mm"]
    breakable_grid(header, None,
                   [[str(p["index"]), p["image_name"]] + ([p.get("extra") or ""] if extra_label else []) + ["%d×%d" % (p["width"], p["height"])]
                    for p in m["pages"]], ("影像清單", "Image list"), widths=widths)

    w(r"\begin{form}{來源與製作}{Provenance}")
    for label_zh, label_en, value, is_url in m.get("provenance", []):
        label = r"%s \en{%s}" % (esc(label_zh), esc(label_en)) if label_en else esc(label_zh)
        w(r"%s & %s\\ \hline" % (label, (r"\url{%s}" % value) if is_url else r"\val{%s}" % esc(value)))
    w(r"擷取時間 \en{Retrieved} & \val{%s}\\ \hline" % esc(m.get("retrieved", "")))
    present = [Path(x[0]).name for x in m.get("attachments", []) if (book_dir / x[0]).exists()]
    if present:
        w(r"附加檔案 \en{Attachments} & %s\\ \hline" % esc("、".join(present)))
    w(r"製作工具 \en{Tools} & bookget-py\quad\url{%s}\\ \hline" % TOOL_URL)
    w(r"\end{form}")
    w(r"\end{document}")
    return "\n".join(L)


def build_latex_pdf(m: Dict, book_dir, out_path, dpi: float = 300.0, keep_build: bool = False) -> Path:
    """Typeset schema ``m`` with LuaLaTeX; returns ``out_path``. Raises LatexNotAvailable
    when no lualatex/fonts are found and RuntimeError when the run fails (the build
    directory with doc.log is kept in that case)."""
    book_dir, out_path = Path(book_dir).resolve(), Path(out_path)
    lualatex = find_lualatex()
    if not lualatex:
        raise LatexNotAvailable("lualatex not found (install TeX Live or set BOOKGET_LUALATEX)")
    cjk_env = os.environ.get("BOOKGET_CJK_FONT")
    cjk = find_font(lualatex, *([cjk_env] if cjk_env else []),
                    "SourceHanSerifTC-Regular.otf", "SourceHanSerifSC-Regular.otf", "SourceHanSerif-Regular.ttc",
                    "SourceHanSansTC-Regular.otf", "NotoSerifCJKtc-Regular.otf", "NotoSansCJKtc-Regular.otf",
                    "FandolSong-Regular.otf", "TW-Kai-98_1.ttf")
    fonts = {"cjk": cjk,
             "latin": find_font(lualatex, "texgyrepagella-regular.otf", "lmroman10-regular.otf"),
             "mono": find_font(lualatex, "lmmono10-regular.otf", "DejaVuSansMono.ttf")}
    build = book_dir / "build"
    build.mkdir(exist_ok=True)
    # luatexja defaults to HaranoAji fonts, which need not be installed; point its fallbacks at our CJK font
    (build / "luatexja.cfg").write_text("\\def\\ltj@stdmcfont{%s}\n\\def\\ltj@stdgtfont{%s}\n" % (cjk, cjk), encoding="utf-8")
    (build / "doc.tex").write_text(render_tex(m, book_dir, fonts, dpi), encoding="utf-8")
    env = dict(os.environ, PATH=str(Path(lualatex).parent) + os.pathsep + os.environ.get("PATH", ""))
    for _ in range(2):          # twice: bookmarks / longtable widths need a second pass
        r = subprocess.run([lualatex, "-interaction=nonstopmode", "-halt-on-error", "doc.tex"],
                           cwd=build, capture_output=True, text=True, errors="replace", env=env)
        if r.returncode:
            raise RuntimeError(f"lualatex failed (see {build / 'doc.log'}):\n{r.stdout[-2500:]}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(build / "doc.pdf"), str(out_path))
    log = (build / "doc.log").read_text(encoding="utf-8", errors="replace")
    missing = len(re.findall(r"Missing character", log))
    if missing:
        logger.warning(f"{missing} characters missing from the fonts (see {build / 'doc.log'})")
    if not keep_build:
        shutil.rmtree(build, ignore_errors=True)
    return out_path
