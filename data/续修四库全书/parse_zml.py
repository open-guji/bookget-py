# -*- coding: utf-8 -*-
"""解析《續修四庫全書總目錄》（中研院本 PDF 提取文本）为结构化 JSON/CSV。

来源文本混合了三种著录格式（原编者拼接了不同来源，冊次有重叠，需去重）：

  A  经部/史部前段：`類` 标题 + `第 N 冊` 分组，其下每行 `書名 卷數 朝代作者`
     经部 1-260、史部 261-~901

  B  史部后段/子部/集部前段：每行自带冊次
     `書名卷數 (朝代)作者撰 X部第 N 冊 影印底本`

  C  集部后段：冊次前置
     `X部第 N 冊：書名卷數(朝代)作者撰 影印底本`

PDF 提取会在页宽处硬折行，故需先按「续行合并」还原逻辑行。
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

BASE = Path(__file__).parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "续修四库全书总目录-中研院本.txt"   # 源文本不入公开仓，见 README「来源与著作权」

BU_RANGE = {  # 各部冊次范围，用于交叉校验
    "經": (1, 260),
    "史": (261, 930),
    "子": (931, 1300),
    "集": (1301, 1800),
}

# ---------------------------------------------------------------- 预处理

def load_lines(path):
    """读入并还原被 PDF 硬折行截断的逻辑行。"""
    raw = path.read_text(encoding="utf-8")
    # PDF 内混入 CJK 相容表意文字（如「易」U+F9E0、「類」U+F9D0），
    # 与常用码位不同，正则匹配会全部落空；NFKC 归一化统一之。
    raw = unicodedata.normalize("NFKC", raw)
    raw = raw.replace(" ", " ")
    lines = [l.rstrip() for l in raw.split("\n")]

    out = []
    for l in lines:
        s = l.strip()
        if not s:
            continue
        if s in ("上", "下"):  # 分册标记，非条目
            continue
        if "出自往復論壇" in s or s.startswith("續修四庫全書總目錄"):
            continue
        # 续行判定：上一行未以「本/卷/撰/等」等结尾且本行不像新条目开头
        if out and _is_continuation(out[-1], s):
            out[-1] = out[-1].rstrip() + s
        else:
            out.append(s)
    return out


_NEW_ENTRY = re.compile(
    r"^(第\s*\d+\s*冊|[經史子集]部[（(]|[經史子集]部第\s*\d+|[一-鿿]{1,5}類\s*$)"
)


def _is_continuation(prev, cur):
    """cur 是否为 prev 的折行续行。"""
    if _NEW_ENTRY.match(cur):
        return False
    # 括号未闭合 → 卷次范围被截断，如「…（卷 90 至卷」/「…（八瓊」
    if prev.count("（") + prev.count("(") > prev.count("）") + prev.count(")"):
        return True
    # 本行以卷次残段、右括号或单字地名开头 → 属上一行
    if re.match(r"^(卷\s*\d|卷\s*$|\d+\s*[）)]|[）)])", cur):
        return True
    # 前一行以完整结尾词收束，视为已结束
    if prev.endswith(("本", "撰", "輯", "編", "注", "校", "刻", "冊", "等")):
        return False
    # 前一行明显未完（以朝代/机构等修饰语结尾，其后应接底本名）
    if re.search(r"[藏印民國清明宋元遼金元]$", prev):
        return True
    # 含冊次著录但未以「本」收尾 → 底本被截断
    if re.search(r"部第\s*\d+", prev) and not prev.endswith("本"):
        return True
    return False


# ---------------------------------------------------------------- 格式 B / C

RE_B = re.compile(
    r"^(?P<title>.+?)\s*"
    r"(?P<bu>[經史子集])部第\s*(?P<v1>\d+)(?:\s*[-－]\s*(?P<v2>\d+))?\s*冊"
    r"(?:\s*影印\s*(?P<src>.*))?$"
)

RE_C = re.compile(
    r"^(?P<bu>[經史子集])部第\s*(?P<v1>\d+)(?:\s*[-－]\s*(?P<v2>\d+))?\s*冊\s*[：:]\s*"
    r"(?P<title>.+?)"
    r"(?:\s*影印\s*(?P<src>.*))?$"
)

# 作者：`(清)陸增祥撰`、`清陸增祥`、`楊守敬撰`
RE_AUTHOR = re.compile(
    r"[（(]?\s*(?P<dyn>先秦|秦|漢|魏|蜀|吳|晉|南朝宋|南朝齊|南朝梁|南朝陳|後魏|北魏|北齊|北周|隋|唐|五代|後唐|後晉|遼|金|宋|元|明|清|民國)?"
    r"\s*[）)]?\s*(?P<name>[一-鿿]{1,12}?)"
    r"(?P<role>撰|輯|編|注|著|述|校|訂|集解|索隱|正義|疏|釋文|補|纂)\s*$"
)


def split_title_author(text):
    """从『書名卷數 (朝代)作者撰』中切出书名与作者串。"""
    text = text.strip()
    # 以最后一个 `(朝代)` 或空格+朝代 作为切点
    m = re.search(
        r"\s*[（(]\s*(先秦|秦|漢|魏|蜀|吳|晉|南朝宋|南朝齊|南朝梁|南朝陳|後魏|北魏|北齊|北周|隋|唐|五代|後唐|後晉|遼|金|宋|元|明|清|民國)\s*[）)]",
        text,
    )
    if m:
        return text[: m.start()].strip(), text[m.start():].strip()
    # 格式 A 多不加括号，作者紧跟卷次：`周易鄭注 12 卷 宋王應麟輯 清丁傑後定`
    # 从末尾往前找第一个「朝代+人名」起点，其后全部视为作者串。
    m = re.search(
        r"(?:^|\s)((?:題\s*)?(?:先秦|秦|漢|魏|蜀|吳|晉|南朝宋|南朝齊|南朝梁|南朝陳|"
        r"後魏|北魏|北齊|北周|隋|唐|五代|後唐|後晉|遼|金|宋|元|明|清|民國)[一-鿿].*)$",
        text,
    )
    if m:
        return text[: m.start(1)].strip(), m.group(1).strip()
    # 无朝代但有「某某撰/輯/編」结尾
    m = re.search(r"\s([一-鿿]{2,4}(?:撰|輯|編|注|著|述|釋文))\s*$", text)
    if m:
        return text[: m.start(1)].strip(), m.group(1).strip()
    return text, ""


def parse_author(s):
    """解析作者串 → [{dynasty, name, role}]"""
    if not s:
        return []
    s = s.strip()
    out = []
    # 按空格切多作者（`(清)潘祖蔭撰 葉昌熾編 潘承弼增補`）
    for part in re.split(r"\s+", s):
        part = part.strip()
        if not part:
            continue
        m = RE_AUTHOR.match(part)
        if m:
            out.append(
                {
                    "dynasty": m.group("dyn") or "",
                    "name": m.group("name"),
                    "role": m.group("role"),
                }
            )
        else:
            m2 = re.match(
                r"^[（(]?\s*(?P<dyn>先秦|秦|漢|魏|蜀|吳|晉|南朝宋|南朝齊|南朝梁|南朝陳|後魏|北魏|北齊|北周|隋|唐|五代|後唐|後晉|遼|金|宋|元|明|清|民國)?\s*[）)]?\s*(?P<name>[一-鿿]{2,12})$",
                part,
            )
            if m2:
                out.append(
                    {
                        "dynasty": m2.group("dyn") or "",
                        "name": m2.group("name"),
                        "role": "",
                    }
                )
    return out


def extract_juan(title):
    """从书名尾部剥离卷数描述，返回 (clean_title, juan_text)。"""
    m = re.search(
        r"((?:\d+|[一二三四五六七八九十百]+)\s*[卷捲]"
        r"(?:[^\s]*?(?:\d+|[一二三四五六七八九十百]+)\s*[卷捲])*"
        r"(?:首\s*\d+\s*[卷捲]|附錄\s*\d+\s*[卷捲]|不分[卷捲])?)",
        title,
    )
    if m:
        return (title[: m.start()] + title[m.end():]).strip(), m.group(1).strip()
    if title.endswith("不分卷"):
        return title[:-3].strip(), "不分卷"
    return title.strip(), ""


# ---------------------------------------------------------------- 主解析

def parse(lines):
    entries = []
    cur_bu = None
    cur_lei = ""
    cur_vol = None

    for l in lines:
        # 部标题
        m = re.match(r"^([經史子集])部\s*[（(]\s*(\d+)\s*[^\d]{1,3}\s*(\d+)", l)
        if m:
            cur_bu, cur_lei, cur_vol = m.group(1), "", None
            continue

        # 类标题
        if re.match(r"^[一-鿿]{1,5}類$", l):
            cur_lei = l
            continue

        # 格式 C（冊次前置）。B/C 段落原文不带「類」标题，
        # 若沿用格式 A 遗留的 cur_lei 会把整段误标为末一類（如「金石類」），故置空。
        m = RE_C.match(l)
        if m:
            entries.append(_mk(m, "", "C"))
            continue

        # 格式 B（冊次后置）
        m = RE_B.match(l)
        if m and "部第" in l:
            entries.append(_mk(m, "", "B"))
            continue

        # 冊次标记（格式 A）
        m = re.match(r"^第\s*(\d+)\s*冊\s*(.*)$", l)
        if m:
            cur_vol = int(m.group(1))
            rest = m.group(2).strip()
            if not rest:
                continue
            l = rest

        # 格式 A 条目
        if cur_bu and cur_vol and len(l) >= 3:
            title, author_s = split_title_author(l)
            ctitle, juan = extract_juan(title)
            entries.append(
                {
                    "bu": cur_bu,
                    "lei": cur_lei,
                    "vol_start": cur_vol,
                    "vol_end": cur_vol,
                    "title": ctitle,
                    "juan": juan,
                    "authors": parse_author(author_s),
                    "source_edition": "",
                    "fmt": "A",
                }
            )
    return entries


def _mk(m, lei, fmt):
    d = m.groupdict()
    title, author_s = split_title_author(d["title"])
    ctitle, juan = extract_juan(title)
    v1 = int(d["v1"])
    v2 = int(d["v2"]) if d.get("v2") else v1
    return {
        "bu": d["bu"],
        "lei": lei,
        "vol_start": v1,
        "vol_end": v2,
        "title": ctitle,
        "juan": juan,
        "authors": parse_author(author_s),
        "source_edition": (d.get("src") or "").strip(),
        "fmt": fmt,
    }


def dedupe(entries):
    """合并同一部书的多次著录，得到「种」级条目。

    两类重复：
      1. 跨冊分载 —— 格式 A 每冊重列一次书名（如《欽定大清會典事例》见于 17 冊），
         应合并为一条并取冊次区间。
      2. 格式重叠 —— 冊 896-901、1160、1308、1320 等处 A 与 B/C 并存，
         保留带底本信息者。
    """
    best = {}
    order = []
    for e in entries:
        key = (e["bu"], re.sub(r"\s+", "", e["title"]))
        if key not in best:
            best[key] = dict(e)
            order.append(key)
            continue
        old = best[key]
        # 扩展冊次区间
        old["vol_start"] = min(old["vol_start"], e["vol_start"])
        old["vol_end"] = max(old["vol_end"], e["vol_end"])
        # 补全缺失字段，底本/作者/卷数以有值者为准
        if not old["source_edition"] and e["source_edition"]:
            old["source_edition"] = e["source_edition"]
        if not old["authors"] and e["authors"]:
            old["authors"] = e["authors"]
        if not old["juan"] and e["juan"]:
            old["juan"] = e["juan"]
        if not old["lei"] and e["lei"]:
            old["lei"] = e["lei"]
    return [best[k] for k in order]


def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    lines = load_lines(SRC)
    entries = parse(lines)
    before = len(entries)
    entries = dedupe(entries)

    out_json = BASE / "续修四库全书-目录.json"
    out_json.write_text(
        json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    import csv

    with (BASE / "续修四库全书-目录.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["部", "類", "起冊", "迄冊", "書名", "卷數", "作者", "影印底本", "格式"])
        for e in entries:
            au = " ".join(
                f"({a['dynasty']}){a['name']}{a['role']}" if a["dynasty"] else f"{a['name']}{a['role']}"
                for a in e["authors"]
            )
            w.writerow(
                [e["bu"], e["lei"], e["vol_start"], e["vol_end"], e["title"],
                 e["juan"], au, e["source_edition"], e["fmt"]]
            )

    # ---- 统计
    from collections import Counter
    print(f"原始条目 {before} → 去重后 {len(entries)}")
    print("按部：", dict(Counter(e["bu"] for e in entries)))
    print("按格式：", dict(Counter(e["fmt"] for e in entries)))
    print("有底本信息：", sum(1 for e in entries if e["source_edition"]))
    print("有作者：", sum(1 for e in entries if e["authors"]))
    print("有卷数：", sum(1 for e in entries if e["juan"]))
    vols = set()
    for e in entries:
        vols.update(range(e["vol_start"], e["vol_end"] + 1))
    print(f"覆盖冊次 {len(vols)}/1800，缺 {sorted(set(range(1,1801))-vols)[:20]}")
    for bu, (a, b) in BU_RANGE.items():
        n = sum(1 for e in entries if e["bu"] == bu)
        print(f"  {bu}部({a}-{b}): {n} 种")


if __name__ == "__main__":
    main()
