#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分歧指数 · 自动抓取版
====================
前端选比赛 -> 后端自动抓取 500.com 百家欧赔 -> 自动计算分歧指数

数据源：
  赛事列表：https://live.500.com/?e=YYYY-MM-DD
  百家欧赔：https://odds.500.com/fenxi/ouzhi-{fid}.shtml  （服务端渲染，可直接解析）

启动：
  pip3 install flask requests
  python3 server.py
  浏览器打开 http://127.0.0.1:8777

免责：仅供数据学习研究，不构成投注建议；境内参与境外博彩属违法。
"""
import re
import os
import json
import math
import time
import datetime
import hashlib
import threading

FILE_LOCK = threading.Lock()      # 保护所有 JSON 落盘，避免多线程并发写坏文件


def atomic_json_write(path, payload, ensure_ascii=False):
    """原子写 JSON：先写临时文件再 rename，避免并发/中断时读到半截文件"""
    tmp = path + ".tmp%d" % os.getpid()
    with FILE_LOCK:
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=ensure_ascii)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
from collections import OrderedDict

import requests
from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, ".cache")
# 随仓库一起提交的战绩基线：Render 免费版重启会清空 .cache，
# 而 history/ 不是隐藏目录，能随代码一起上传 GitHub，战绩库因此不会归零。
SEED_DIR = os.path.join(BASE_DIR, "history")
os.makedirs(CACHE_DIR, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
CACHE_TTL = 300  # 5 分钟

app = Flask(__name__, static_folder=None)


# ---------------------------------------------------------------- HTTP 层

_GC = {"n": 0}


def gc_cache(max_files=260, max_mb=90):
    """清理最旧的页面缓存。
    云主机配额很紧（PythonAnywhere 免费账户磁盘仅 512MB），而每场比赛的赔率页
    缓存会长期累积，跑几个月就能撑爆。这里按「文件数 + 总体积」双上限回收最旧的。
    """
    try:
        files = [(f, os.path.getmtime(os.path.join(CACHE_DIR, f)))
                 for f in os.listdir(CACHE_DIR) if f.endswith(".html")]
        if not files:
            return
        files.sort(key=lambda x: x[1])                      # 最旧的排前面
        over = len(files) - max_files
        total = sum(os.path.getsize(os.path.join(CACHE_DIR, f)) for f, _ in files)
        i = 0
        while (over > 0 or total > max_mb * 1024 * 1024) and i < len(files):
            f = files[i][0]
            p = os.path.join(CACHE_DIR, f)
            total -= os.path.getsize(p)
            os.remove(p)
            over -= 1
            i += 1
    except Exception:
        pass


def get(url, ttl=CACHE_TTL):
    """带磁盘缓存的 GET，返回已解码文本（自动识别 GBK / UTF-8）"""
    key = hashlib.md5(url.encode()).hexdigest() + ".html"
    path = os.path.join(CACHE_DIR, key)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        raw = open(path, "rb").read()
    else:
        last = None
        for attempt in range(3):                      # 网络抖动重试 3 次（指数退避）
            try:
                r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://live.500.com/"},
                                 timeout=15)
                r.raise_for_status()
                if len(r.content) < 500:              # 明显异常的空/拦截页
                    raise RuntimeError("响应过短，疑似被拦截")
                raw = r.content
                with open(path, "wb") as f:
                    f.write(raw)
                _GC["n"] += 1
                if _GC["n"] % 20 == 0:
                    gc_cache()
                break
            except Exception as e:
                last = e
                if attempt < 2:
                    time.sleep(1.2 * (attempt + 1))
        else:
            # 全部失败：若磁盘上有过期缓存，降级使用（比直接报错友好）
            if os.path.exists(path) and os.path.getsize(path) > 500:
                raw = open(path, "rb").read()
            else:
                raise last
    for enc in ("gbk", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


# ---------------------------------------------------------------- 赛事列表

def parse_matches(html):
    """解析 live.500.com 的比赛列表"""
    out = []
    rows = re.split(r'(?=<tr[^>]*infoid="\d+")', html)[1:]
    for r in rows:
        fid = re.search(r'/fenxi/ouzhi-(\d+)\.shtml', r)
        if not fid:
            continue
        fid = fid.group(1)
        st = re.search(r'status="(\d+)"', r)
        tds = [strip_tags(t) for t in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        if len(tds) < 8:
            continue
        lg = re.search(r'zuqiu-\d+/"[^>]*>([^<]+)</a>', r)
        home = re.search(r'team/\d+/"[^>]*>([^<]+)</a>\s*<span class="sp_sr"', r) \
            or re.search(r'<td align="right"[^>]*>.*?team/\d+/"[^>]*>([^<]+)</a>', r, re.S)
        away = re.search(r'</div></td>\s*<td align="left"[^>]*>.*?team/\d+/"[^>]*>([^<]+)</a>', r, re.S)
        handicap = re.search(r'data-ao="([^"]*)"', r)
        out.append({
            "fid": fid,
            "no": tds[0],
            "league": lg.group(1) if lg else (tds[1] if len(tds) > 1 else ""),
            "round": tds[2] if len(tds) > 2 else "",
            "time": tds[3] if len(tds) > 3 else "",
            "home": home.group(1) if home else tds[5] if len(tds) > 5 else "",
            "away": away.group(1) if away else tds[7] if len(tds) > 7 else "",
            "handicap": handicap.group(1) if handicap else "",
        })
        # 列序：tds[6]=比分列（pk div：主进球+盘口+客进球），tds[8]=半场比分
        # 注意：500 偶尔会把 clt1/clt3 的书写顺序倒过来，必须按 class 名取值，不能按位置
        pk = re.search(r'<div class="pk">(.*?)</div>', r, re.S)
        g1 = re.search(r'class="clt1"[^>]*>\s*(\d+)', pk.group(1)) if pk else None
        g3 = re.search(r'class="clt3"[^>]*>\s*(\d+)', pk.group(1)) if pk else None
        if g1 and g3:      # clt1=主队进球, clt3=客队进球
            out[-1]["hg"], out[-1]["ag"] = int(g1.group(1)), int(g3.group(1))
            out[-1]["score"] = f"{g1.group(1)} - {g3.group(1)}"
        else:
            # pk 缺失时退回比分列文本（tds[6]=「主进球盘口客进球」）；
            # 注意 tds[8] 是半场比分列，绝不能当全场比分用
            msc = re.search(r"(\d+)\D+(\d+)", tds[6] if len(tds) > 6 else "")
            out[-1]["hg"], out[-1]["ag"] = (int(msc.group(1)), int(msc.group(2))) if msc else (None, None)
            out[-1]["score"] = f"{out[-1]['hg']} - {out[-1]['ag']}" if msc else ""
        # 半场比分
        ht = re.search(r"(\d+)\s*-\s*(\d+)", tds[8] if len(tds) > 8 else "")
        out[-1]["hs"], out[-1]["as_"] = (int(ht.group(1)), int(ht.group(2))) if ht else (None, None)
        out[-1]["status"] = st.group(1) if st else ""
    return out


# status 码：0=未开赛 1/2/3=进行中（上/中场/下），4=完场
STATUS_TXT = {"0": "未开赛", "1": "进行中", "2": "进行中", "3": "进行中", "4": "完场"}


@app.route("/api/score")
def api_score():
    """单场实时比分与状态（轻量，走列表页短缓存）"""
    fid = request.args.get("fid")
    if not fid:
        return jsonify({"error": "缺少 fid"}), 400
    date = request.args.get("date") or today_str()
    try:
        ms = get_matches(date, full=True)
    except Exception as e:
        return jsonify({"error": f"比分抓取失败：{e}"}), 502
    m = next((x for x in ms if x["fid"] == fid), None)
    if not m:
        return jsonify({"error": "未找到该场比赛", "date": date}), 404
    state = STATUS_TXT.get(m.get("status"), "未知")
    return jsonify({"fid": fid, "date": date, "state": state, "status": m.get("status"),
                    "score": m["score"] if m["hg"] is not None else "",
                    "hg": m["hg"], "ag": m["ag"], "time": m["time"],
                    "home": m["home"], "away": m["away"]})


# ---------------------------------------------------------------- 完整赛事列表

def parse_wanchang(html):
    """解析 live.500.com/wanchang.php 的完整赛事（含低级别联赛、女足等）"""
    out = []
    for r in re.split(r'(?=<tr id="a\d+")', html)[1:]:
        m0 = re.search(r'id="a(\d+)"', r)
        if not m0:
            continue
        fid = m0.group(1)
        tds = [strip_tags(t) for t in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        if len(tds) < 6:
            continue
        lg = re.search(r'zuqiu-\d+/"[^>]*>([^<]+)</a>', r)
        teams = re.findall(r'team/\d+/"[^>]*>([^<]+)</a>', r)
        home = teams[0] if teams else tds[3]
        away = teams[1] if len(teams) > 1 else (tds[5] if len(tds) > 5 else "")
        score = tds[4] if len(tds) > 4 else ""
        msc = re.search(r"(\d+)\s*-\s*(\d+)", score or "")
        row = {"fid": fid, "no": "-", "league": lg.group(1) if lg else "",
               "round": tds[1] if len(tds) > 1 else "", "time": tds[2] if len(tds) > 2 else "",
               "home": home, "away": away, "handicap": "", "score": score,
               "hg": int(msc.group(1)) if msc else None, "ag": int(msc.group(2)) if msc else None,
               "status": "", "has_odds": False}
        out.append(row)
    # 推断状态：有比分按完场；当天且开球 2 小时内视为进行中
    now = datetime.datetime.now()
    for r in out:
        if r["hg"] is None:
            r["status"] = "0"
            continue
        try:
            t = datetime.datetime.strptime(f"{now.year}-" + r["time"], "%Y-%m-%d %H:%M")
            r["status"] = "3" if (now - t).total_seconds() < 7200 else "4"
        except Exception:
            r["status"] = "4"
    return out


# 应用时区：Render 等云主机默认是 UTC，直接 date.today() 会让北京时间
# 08:00 之前的凌晨场被算到前一天。默认按 UTC+8（北京时间）计算。
APP_TZ = datetime.timezone(datetime.timedelta(hours=int(os.environ.get("TZ_OFFSET", "8"))))


def today_str():
    """取应用时区下的「今天」（YYYY-MM-DD）"""
    return datetime.datetime.now(APP_TZ).strftime("%Y-%m-%d")


def get_matches(date, full=False):
    """按开球日期取当天全部场次：合并「前一竞彩销售日 + 当天」两个列表，
    因为凌晨（00:00-08:30）开球的比赛挂在上一销售日名下"""
    try:
        d0 = datetime.date.fromisoformat(date)
    except Exception:
        d0 = datetime.date.fromisoformat(today_str())   # 非法日期回退到「应用时区」的今天
    today = today_str()
    ttl = 25 if date == today else 300
    out, seen, err = [], set(), None
    for d in (d0 - datetime.timedelta(days=1), d0):
        try:
            for m in parse_matches(get(f"https://live.500.com/?e={d.isoformat()}", ttl=ttl)):
                if m["fid"] not in seen:
                    seen.add(m["fid"])
                    m["has_odds"] = True
                    out.append(m)
        except Exception as e:
            err = e          # 一天失败不算失败（可能是无赛事的日期）；两天都失败才报错
    if not out and err:
        raise RuntimeError(f"500 列表页抓取失败：{err}")
    out.sort(key=lambda m: (m["time"], m["league"]))
    return out


# ---------------------------------------------------------------- 百家欧赔

# 站方对公司名做了掩码处理（如 B*****）。下列按「首字符 + 字数 + 注册地」可唯一确定，作为别名标注
KNOWN = {
    "1": "竞彩官方", "2": "立博", "3": "Bet365", "4": "Interwetten", "5": "澳门",
    "6": "伟德", "8": "SNAI", "9": "易胜博", "14": "Coral", "16": "10Bet",
    "280": "皇冠", "293": "威廉希尔",
}

def parse_ouzhi(html):
    """解析 odds.500.com/fenxi/ouzhi-{fid}.shtml -> 各公司初盘/即时赔率"""
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    companies = []
    rows = re.split(r'(?=<tr class="tr[12]" id="\d+")', html)
    for r in rows[1:]:
        cid = re.search(r'ouzhi\.php\?cid=(\d+)', r)
        name = re.search(r'class="tb_plgs" title="([^"]*)"', r)
        if not cid:
            continue
        tables = re.findall(r'<table[^>]*class="pl_table_data"[^>]*>(.*?)</table>', r, re.S)
        odds_t = tables[0] if tables else ""
        prob_t = tables[1] if len(tables) > 1 else ""
        trs = re.findall(r"<tr[^>]*>(.*?)</tr>", odds_t, re.S)
        nums = [re.findall(r">\s*([0-9]+\.[0-9]+)\s*<", t) for t in trs]
        if len(nums) < 2 or any(len(n) < 3 for n in nums[:2]):
            continue
        open_odds = [float(x) for x in nums[0][:3]]   # 初盘 胜/平/负
        live_odds = [float(x) for x in nums[1][:3]]   # 即时 胜/平/负
        kelly = None
        try:
            kelly = [float(x) for x in re.findall(r'klfc="([0-9.]+)"', trs[1])[:3]]
        except Exception:
            pass
        dt = re.search(r'data-time="([^"]+)"', r)
        companies.append({
            "cid": cid.group(1),
            "name": name.group(1) if name else f"公司{cid.group(1)}",
            "alias": KNOWN.get(cid.group(1)),
            "open": open_odds,
            "live": live_odds,
            "kelly": kelly,
            "updated": dt.group(1) if dt else "",
        })
    return strip_tags(title.group(1)) if title else "", companies


# ---------------------------------------------------------------- 分歧算法

def fair(x):
    """赔率三元组 -> 去水后公平概率"""
    p = [1.0 / i for i in x]
    s = sum(p)
    return [i / s for i in p]


def stats(v):
    n = len(v)
    m = sum(v) / n
    sd = math.sqrt(sum((i - m) ** 2 for i in v) / n)
    return m, sd, (sd / m if m else 0.0)


def divergence(companies, key="live"):
    """返回胜/平/负的 {均值, 标准差, 变异系数, 各公司概率}"""
    probs = [fair(c[key]) for c in companies]
    res = []
    for i in range(3):
        col = [p[i] for p in probs]
        m, sd, cv = stats(col)
        res.append({"mean": m, "std": sd, "cv": cv})
    return res, probs


def compute_divergence(companies, trim_outlier=False):
    """计算分歧指数（可选：剔除统计意义上的异常公司）"""
    res, probs = divergence(companies, "live")
    used = list(range(len(companies)))
    if trim_outlier and len(companies) >= 5:
        # 以三项平均偏离度最大的公司为基点，进行 1 次 IQR 剔除
        dev = []
        for i, p in enumerate(probs):
            d = sum(abs(p[j] - res[j]["mean"]) / (res[j]["std"] or 1e-9) for j in range(3)) / 3
            dev.append((d, i))
        dev.sort(reverse=True)
        worst = dev[0][1]
        if dev[0][0] > 2.0:
            used = [i for i in used if i != worst]
            res, probs = divergence([companies[i] for i in used], "live")

    labels = ["胜", "平", "负"]
    items = []
    for i in range(3):
        mean = res[i]["mean"]
        sd = res[i]["std"]
        cv = res[i]["cv"]
        items.append({
            "label": labels[i],
            "cv": round(cv, 6),
            "std": round(sd, 6),
            "mean_prob": round(mean, 6),
            "std_prob": round(sd, 6),
        })

    detail = []
    for k, idx in enumerate(used):
        c = companies[idx]
        p = probs[k]
        z = [abs(p[j] - res[j]["mean"]) / (res[j]["std"] or 1e-9) for j in range(3)]
        detail.append({
            "name": c["name"],
            "alias": c.get("alias"),
            "cid": c["cid"],
            "open": c["open"],
            "live": c["live"],
            "fair": [round(x, 6) for x in p],
            "z": [round(x, 2) for x in z],
            "is_outlier": max(z) > 2.0,
            "updated": c["updated"],
        })

    open_res, _ = divergence([companies[i] for i in used], "open")
    open_cv = [round(r["cv"], 6) for r in open_res]
    consensus = min(items, key=lambda x: x["cv"])["label"]
    return {
        "companies_used": len(used),
        "companies_total": len(companies),
        "items": items,
        "open_cv": open_cv,
        "detail": detail,
        "consensus": consensus,
    }


# ---------------------------------------------------------------- 亚盘（让球）

def parse_yazhi(html):
    """解析 odds.500.com/fenxi/yazhi-{fid}.shtml -> 各公司初盘/即时亚盘
    每行结构：[即时: 主水, 盘口(ref), 客水] [初盘: 主水, 盘口(ref), 客水]"""
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    companies = []
    rows = re.split(r'(?=<tr class="tr[12]"[^>]*xls="row")', html)
    for r in rows[1:]:
        cid = re.search(r'yazhi\.php\?cid=(\d+)', r) or re.search(r'id="(\d+)"', r)
        name = re.search(r'class="tb_plgs"[^>]*>.*?title="([^"]*)"', r, re.S)
        if not cid:
            continue
        tables = re.findall(r'<table[^>]*class="pl_table_data"[^>]*>(.*?)</table>', r, re.S)
        if len(tables) < 2:
            continue
        def block(t):
            cells = re.findall(r"(<td[^>]*>.*?</td>)", t, re.S)
            vals = []
            for c in cells:
                txt = strip_tags(c).replace("↑", "").replace("↓", "").strip()
                ref = re.search(r'ref="(-?[0-9.]+)"', c)
                vals.append({"txt": txt, "ref": float(ref.group(1)) if ref else None})
            return vals
        live_b, open_b = block(tables[0]), block(tables[1])
        # 每块取前三个有效格子：主水 / 盘口 / 客水
        def triple(b):
            t = [x for x in b if x["txt"]][:3]
            if len(t) < 3:
                return None
            try:
                return [float(t[0]["txt"]), t[1]["ref"], float(t[2]["txt"])]
            except ValueError:
                return None
        live, opn = triple(live_b), triple(open_b)
        if not live or not opn:
            continue
        dt = re.search(r'dt="([^"]+)"', r)
        companies.append({
            "cid": cid.group(1),
            "name": name.group(1) if name else f"公司{cid.group(1)}",
            "alias": KNOWN.get(cid.group(1)),
            "open": opn,          # [主水, 盘口(主队视角,负=让), 客水]
            "live": live,
            "updated": dt.group(1) if dt else "",
        })
    return strip_tags(title.group(1)) if title else "", companies


def fmt_ah(ref):
    """数值盘口 -> 「让球方 -x」格式（博彩公司标准写法）：
    0.25 -> 0/0.5，0.75 -> 0.5/1，1.25 -> 1/1.5；整盘/半盘保持 0.5、1、1.5
    主队让 = 主队 -x，主队受让 = 客队 -x，0 = 平手"""
    if ref is None:
        return "—"
    if ref == 0:
        return "平手 0"
    team = "主队" if ref < 0 else "客队"
    v = abs(ref)
    low = int(v * 2) / 2          # 0.25 -> 0.0, 0.75 -> 0.5, 1.25 -> 1.0
    high = low + 0.5
    def f(x):
        return f"{int(x)}" if x == int(x) else f"{x:.1f}"
    frac = round(v - int(v), 2)      # 抗浮点误差：0.7500000001 也要判成 0.75
    txt = f"{f(low)}/{f(high)}" if frac in (0.25, 0.75) else f(v)
    return f"{team} -{txt}"


def ah_line_to_text(ref):
    """兼容旧字段：等价于 fmt_ah"""
    return fmt_ah(ref)


def compute_ah(companies):
    """让球分歧：盘口一致性 + 主赢(去水)概率离散度"""
    lines = [c["live"][1] for c in companies]
    med = sorted(lines)[len(lines) // 2]
    line_std = (sum((x - sum(lines) / len(lines)) ** 2 for x in lines) / len(lines)) ** 0.5

    probs, aligned = [], []
    for c in companies:
        wh, wa = c["live"][0], c["live"][2]
        p = (1 / wh) / (1 / wh + 1 / wa)      # 主队赢盘的公平概率（含盘口差异）
        probs.append(p)
        aligned.append(abs(c["live"][1] - med) < 1e-9)

    m, sd, cv_all = stats(probs)
    maj = [p for p, a in zip(probs, aligned) if a]
    cv_maj = stats(maj)[2] if len(maj) >= 3 else None
    open_probs = [(1 / c["open"][0]) / (1 / c["open"][0] + 1 / c["open"][2]) for c in companies]
    cv_open = stats(open_probs)[2]

    detail = []
    for c, p, a in zip(companies, probs, aligned):
        z = abs(p - m) / (sd or 1e-9)
        detail.append({
            "name": c["name"], "alias": c.get("alias"), "cid": c["cid"],
            "open": c["open"], "live": c["live"],
            "open_txt": [c["open"][0], ah_line_to_text(c["open"][1]), c["open"][2]],
            "live_txt": [c["live"][0], ah_line_to_text(c["live"][1]), c["live"][2]],
            "prob": round(p, 6), "off_line": (not a),
            "line_diff": round(c["live"][1] - med, 3),
            "z": round(z, 2), "is_outlier": z > 2.0 or (not a),
            "updated": c["updated"],
        })
    return {
        "companies_used": len(companies),
        "companies_total": len(companies),
        "median_line": med,
        "median_txt": ah_line_to_text(med),
        "line_std": round(line_std, 4),
        "off_line_count": sum(1 for a in aligned if not a),
        "cv_all": round(cv_all, 6),
        "cv_majority": round(cv_maj, 6) if cv_maj is not None else None,
        "cv_open": round(cv_open, 6),
        "mean_prob": round(m, 6),
        "std_prob": round(sd, 6),
        "detail": detail,
        "consensus": f"{ah_line_to_text(med)}（主水概率 {(m*100):.0f}%）",
    }


# ---------------------------------------------------------------- 赛果验证

OU_LABEL = {"胜": "主胜", "平": "平局", "负": "客胜"}


def validate_ouzhi(data, hg, ag):
    margin = hg - ag
    actual = "胜" if margin > 0 else ("平" if margin == 0 else "负")
    consensus = data["consensus"]          # 分歧最小方向
    labels = ["胜", "平", "负"]
    agree = sum(1 for d in data["detail"]
                if labels[max(range(3), key=lambda i: d["fair"][i])] == actual)
    # 对照组：市场「看好」方向 = 平均概率最高项（≠ 分歧最小方向）
    means = [it["mean_prob"] for it in data["items"]]
    fav = labels[means.index(max(means))]
    cvs = [it["cv"] for it in data["items"]]
    return {"market": "ouzhi", "score": f"{hg}-{ag}", "margin": margin,
            "actual": OU_LABEL[actual], "actual_key": actual,
            "consensus": OU_LABEL[consensus], "consensus_key": consensus,
            "hit": consensus == actual, "agree": agree, "total": len(data["detail"]),
            "fav": OU_LABEL[fav], "fav_key": fav, "fav_hit": fav == actual,
            "cv": min(cvs), "cv_fav": cvs[means.index(max(means))],
            "agree_rate": round(agree / len(data["detail"]), 3) if data["detail"] else None}


def validate_ah(data, hg, ag):
    margin = hg - ag
    med = data["median_line"]
    res = margin + med                      # 主队视角赢盘值
    actual = "主赢盘" if res > 0 else ("走盘" if res == 0 else "客赢盘")
    pred = "主赢盘" if data["mean_prob"] > 0.5 else "客赢盘"
    hit = None if actual == "走盘" else (pred == actual)
    agree = 0
    for d in data["detail"]:
        r = margin + (d["live"][1] - 0)     # 用该公司自己的即时盘口
        fav_home = d["prob"] > 0.5
        if (r > 0 and fav_home) or (r < 0 and not fav_home):
            agree += 1
    return {"market": "ah", "score": f"{hg}-{ag}", "margin": margin,
            "actual": actual, "actual_key": actual,
            "consensus": f"{data['median_txt']} → {pred}", "consensus_key": pred,
            "hit": hit, "agree": agree, "total": len(data["detail"]),
            "fav": pred, "fav_key": pred, "fav_hit": (None if hit is None else pred == actual),
            "cv": data.get("cv_majority") if data.get("cv_majority") is not None else data["cv_all"],
            "cv_fav": data["cv_all"],
            "agree_rate": round(agree / len(data["detail"]), 3) if data["detail"] else None}


# ---------------------------------------------------------------- API

@app.route("/api/matches")
def api_matches():
    date = request.args.get("date") or today_str()
    try:                                   # 非法日期统一回退到今天，返回值也不会是 "abc"
        datetime.date.fromisoformat(date)
    except Exception:
        date = today_str()
    full = request.args.get("full") == "1"
    try:
        ms = get_matches(date, full=full)
    except Exception as e:
        return jsonify({"error": f"赛事列表抓取失败：{e}", "date": date, "matches": []}), 502
    leagues = sorted({m["league"] for m in ms if m["league"]})
    return jsonify({"date": date, "source": f"https://live.500.com/?e={date}", "leagues": leagues, "matches": ms})


@app.route("/api/divergence")
def api_divergence():
    fid = request.args.get("fid")
    trim = request.args.get("trim") == "1"
    market = request.args.get("market", "ouzhi")   # ouzhi=欧赔 | ah=让球(亚盘)
    if not fid or not fid.isdigit():
        return jsonify({"error": "缺少有效的 fid"}), 400
    if market == "ah":
        url = f"https://odds.500.com/fenxi/yazhi-{fid}.shtml"
        try:
            html = get(url)
        except Exception as e:
            return jsonify({"error": f"亚盘页抓取失败：{e}", "fid": fid}), 502
        title, companies = parse_yazhi(html)
        if len(companies) < 3:
            return jsonify({"error": f"该场可解析的亚盘公司不足 3 家（仅有 {len(companies)} 家）",
                            "fid": fid, "companies": len(companies)}), 422
        data = compute_ah(companies)
        save_snapshot(fid, {"items": [{"cv": data["cv_all"]}], "companies_used": data["companies_used"]},
                      prefix="snap_ah")
        _d = request.args.get("date") or today_str()
        _pool = load_cvpool(_d, "ah")
        data["pct"] = pct_rank_of(data.get("cv_majority") if data.get("cv_majority") is not None
                                  else data["cv_all"], _pool)
        data["pct_n"] = len(_pool)
        data.update({"fid": fid, "title": title, "source": url,
                     "trend": load_snapshot(fid, prefix="snap_ah")})
        hg, ag = request.args.get("hg", type=int), request.args.get("ag", type=int)
        if hg is not None and ag is not None:
            data["validation"] = validate_ah(data, hg, ag)
        return jsonify(data)

    url = f"https://odds.500.com/fenxi/ouzhi-{fid}.shtml"
    try:
        html = get(url)
    except Exception as e:
        return jsonify({"error": f"赔率页抓取失败：{e}", "fid": fid}), 502
    title, companies = parse_ouzhi(html)
    if len(companies) < 3:
        return jsonify({"error": f"该场可解析的公司不足 3 家（仅有 {len(companies)} 家）",
                        "fid": fid, "companies": len(companies)}), 422
    data = compute_divergence(companies, trim_outlier=trim)
    save_snapshot(fid, data)
    snap = load_snapshot(fid)
    _d = request.args.get("date") or today_str()
    _pool = load_cvpool(_d, "ouzhi")
    data["pct"] = pct_rank_of(min(it["cv"] for it in data["items"]), _pool)
    data["pct_n"] = len(_pool)
    data.update({"fid": fid, "title": title, "source": url, "trend": snap})
    hg, ag = request.args.get("hg", type=int), request.args.get("ag", type=int)
    if hg is not None and ag is not None:
        data["validation"] = validate_ouzhi(data, hg, ag)
    return jsonify(data)


# ---------------------------------------------------------------- 走势快照
# 每次查询自动留一个快照，手机端即可看到当天分歧是如何变化的

def snap_path(fid, prefix="snap"):
    return os.path.join(CACHE_DIR, f"{prefix}_{fid}.json")


def save_snapshot(fid, data, max_keep=400, prefix="snap"):
    # 30 秒一个桶：同分钟内多次刷新也能积累走势点（赔率变化慢，过密意义不大）
    now = time.time()
    bucket = time.strftime("%H:%M", time.localtime(now)) + ("A" if int(now) % 60 < 30 else "B")
    p = snap_path(fid, prefix)
    rows = []
    if os.path.exists(p):
        try:
            rows = json.load(open(p, encoding="utf-8"))
        except Exception:
            rows = []
    if not rows or rows[-1].get("b") != bucket:
        rows.append({
            "b": bucket,
            "t": time.strftime("%H:%M", time.localtime(now)),
            "ts": int(now),
            "cv": [round(i["cv"], 6) for i in data["items"]],
            "n": data["companies_used"],
        })
        atomic_json_write(p, rows[-max_keep:], ensure_ascii=True)
    return rows


def load_snapshot(fid, prefix="snap"):
    p = snap_path(fid, prefix)
    if not os.path.exists(p):
        return []
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return []


RANK_CACHE = {}   # date -> (ts, rows)


# ---------------------------------------------------------------- 当日分歧分布（分位基线）
# 「0.08 算高还是低？」——绝对阈值说不清，用同日其他比赛的实际分布做基准。
# rank 每次计算都会落盘一份 cv 池，之后单场详情即可换算出「今日分位」。

def _cvpool_path(date, market):
    return os.path.join(CACHE_DIR, f"cvpool_{market}_{date}.json")


def save_cvpool(date, market, ranks):
    try:
        rows = [{"fid": r["fid"], "cv": r.get("cv_min")} for r in ranks if r.get("cv_min") is not None]
        atomic_json_write(_cvpool_path(date, market),
                         {"date": date, "market": market, "ts": int(time.time()), "rows": rows})
    except Exception:
        pass


def load_cvpool(date, market):
    p = _cvpool_path(date, market)
    if not os.path.exists(p):
        return []
    try:
        d = json.load(open(p))
        return [r["cv"] for r in d.get("rows", []) if r.get("cv") is not None]
    except Exception:
        return []


def pct_rank_of(cv, pool):
    """返回 0-100：池中有百分之多少的比赛分歧「小于等于」该值。
    数值越小 = 越一致（例如 12 表示比当日 88% 的比赛更一致）。样本 <5 场时返回 None。"""
    vs = sorted(v for v in pool if v is not None)
    if len(vs) < 5 or cv is None:
        return None
    le = sum(1 for v in vs if v <= cv)
    return int(round(le / len(vs) * 100))


@app.route("/api/rank")
def api_rank():
    """列表排序用：批量计算每场分歧（欧赔=最小三项CV；让球=主流盘口内水位CV），供前端排序"""
    from concurrent.futures import ThreadPoolExecutor
    date = request.args.get("date") or today_str()
    market = request.args.get("market", "ouzhi")
    ck = f"{date}|{market}"
    now = time.time()
    hit = RANK_CACHE.get(ck)
    if hit and now - hit[0] < 120:
        return jsonify({"date": date, "market": market, "ranks": hit[1], "cached": True})
    try:
        ms = get_matches(date, full=False)
    except Exception as e:
        return jsonify({"error": f"赛事列表抓取失败：{e}"}), 502

    ms = [m for m in ms if m.get("time", "").startswith(date[5:10])]

    def one(m):
        try:
            if market == "ah":
                title, cs = parse_yazhi(get(f"https://odds.500.com/fenxi/yazhi-{m['fid']}.shtml", ttl=180))
                if len(cs) < 3:
                    return None
                data = compute_ah(cs)
                cv = data["cv_majority"] if data.get("cv_majority") is not None else data["cv_all"]
                return {"fid": m["fid"], "cv_min": cv,
                        "consensus": "主赢盘" if data["mean_prob"] > 0.5 else "客赢盘",
                        "line": data["median_txt"], "companies": data["companies_used"]}
            title, cs = parse_ouzhi(get(f"https://odds.500.com/fenxi/ouzhi-{m['fid']}.shtml", ttl=180))
            if len(cs) < 3:
                return None
            data = compute_divergence(cs)
            cvs = [it["cv"] for it in data["items"]]
            i = cvs.index(min(cvs))
            return {"fid": m["fid"], "cv_min": min(cvs), "consensus": data["items"][i]["label"],
                    "companies": data["companies_used"]}
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        ranks = [r for r in ex.map(one, ms) if r]
    RANK_CACHE[ck] = (now, ranks)
    save_cvpool(date, market, ranks)      # 落盘：为「今日分位」提供基准分布
    return jsonify({"date": date, "market": market, "ranks": ranks})


@app.route("/api/backtest")
def api_backtest():
    """整日复盘：把当天所有已完场比赛的分歧方向与实际赛果对比"""
    from concurrent.futures import ThreadPoolExecutor
    date = request.args.get("date") or today_str()
    try:
        ms = get_matches(date, full=False)
    except Exception as e:
        return jsonify({"error": f"赛事列表抓取失败：{e}"}), 502
    dstr = date[5:10]
    done = [m for m in ms if m.get("hg") is not None and m.get("time", "").startswith(dstr)]

    def one(m, market):
        try:
            url = (f"https://odds.500.com/fenxi/yazhi-{m['fid']}.shtml" if market == "ah"
                   else f"https://odds.500.com/fenxi/ouzhi-{m['fid']}.shtml")
            title, cs = parse_yazhi(get(url)) if market == "ah" else parse_ouzhi(get(url))
            if len(cs) < 3:
                return None
            data = compute_ah(cs) if market == "ah" else compute_divergence(cs)
            v = validate_ah(data, m["hg"], m["ag"]) if market == "ah" else validate_ouzhi(data, m["hg"], m["ag"])
            return {"no": m["no"], "league": m["league"], "home": m["home"], "away": m["away"],
                    "time": m["time"], **v}
        except Exception:
            return None

    tasks = [(m, mk) for m in done for mk in ("ouzhi", "ah")]
    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = [r for r in ex.map(lambda t: one(*t), tasks) if r]

    def summ(mk):
        rs = [r for r in rows if r["market"] == mk and r["hit"] is not None]
        return {"hit": sum(1 for r in rs if r["hit"]), "total": len(rs),
                "agree_avg": round(sum(r["agree"] / r["total"] for r in rs if r["total"]) / len(rs), 3) if rs else None}

    save_history(date, rows)          # 落盘，累计成战绩库
    return jsonify({"date": date, "finished": len(done),
                    "summary": {"ouzhi": summ("ouzhi"), "ah": summ("ah")}, "rows": rows})


# ---------------------------------------------------------------- 历史战绩库
# 「分歧越小越容易打出」是这工具的全部前提。单日样本太小说明不了问题，
# 因此每次复盘都落盘一份当日明细，累计多天后才能做分档检验：
# 一致性最好的那一档，命中率是否真的更高？以及它是否打得过「直接押市场看好」？

def _hist_path(date):
    return os.path.join(CACHE_DIR, f"hist_{date}.json")


REDIS_URL = os.environ.get("REDIS_URL")   # 可选：填了就把战绩库存到 Redis，重启不丢
_R = [None]


def _redis():
    """没有配置 REDIS_URL 或没装 redis 包时返回 None，自动退回磁盘方案"""
    if not REDIS_URL:
        return None
    try:
        if _R[0] is None:
            import redis
            _R[0] = redis.from_url(REDIS_URL, decode_responses=True)
        return _R[0]
    except Exception:
        return None


def save_history(date, rows):
    try:
        keep = []
        for r in rows:
            if r.get("cv") is None:
                continue
            keep.append({"market": r["market"], "league": r.get("league"), "home": r.get("home"),
                         "away": r.get("away"), "score": r.get("score"),
                         "consensus": r.get("consensus_key") or r.get("consensus"),
                         "actual": r.get("actual_key") or r.get("actual"),
                         "hit": r.get("hit"), "fav": r.get("fav_key") or r.get("fav"),
                         "fav_hit": r.get("fav_hit"), "cv": round(r["cv"], 6),
                         "agree_rate": r.get("agree_rate")})
        # 分位：在同日同市场的样本内排序（一致性越好 pct 越小）
        for mk in ("ouzhi", "ah"):
            sub = [r for r in keep if r["market"] == mk and r["cv"] is not None]
            vs = sorted(x["cv"] for x in sub)
            for x in sub:
                x["pct"] = int(round(sum(1 for v in vs if v <= x["cv"]) / len(vs) * 100)) if vs else None
        payload = {"date": date, "ts": int(time.time()), "rows": keep}
        r = _redis()
        if r is not None:
            try:
                r.set(f"hist:{date}", json.dumps(payload))
                return
            except Exception:
                pass
        atomic_json_write(_hist_path(date), payload)
    except Exception:
        pass


def load_history():
    """战绩库 = 仓库基线(history/) + 运行期新增(.cache)，或 Redis（若配置）"""
    r = _redis()
    if r is not None:
        try:
            out = []
            for k in r.keys("hist:*"):
                d = json.loads(r.get(k))
                if d.get("rows"):
                    out.append(d)
            out.sort(key=lambda d: d["date"])
            return out
        except Exception:
            pass
    acc = {}
    for d in (SEED_DIR, CACHE_DIR):      # 后者覆盖前者：运行期数据比仓库基线新
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            if not (fn.startswith("hist_") or fn.startswith("all")):
                continue
            try:
                j = json.load(open(os.path.join(d, fn), encoding="utf-8"))
                for day in _day_objects(j):   # 兼容：单天文件 / 多天合并文件
                    if day.get("rows"):
                        acc[day["date"]] = day
            except Exception:
                continue
    return [acc[k] for k in sorted(acc)]


def _day_objects(j):
    """把战绩文件统一成「按天」的列表：
    支持 单天文件 {"date":..,"rows":[..]}、多天合并文件 {"days":[..]}、以及裸列表"""
    if isinstance(j, list):
        return j
    if isinstance(j, dict):
        if isinstance(j.get("days"), list):
            return j["days"]
        if j.get("rows"):
            return [j]
    return []


@app.route("/api/history")
def api_history():
    """累计战绩库：检验「分歧越小 → 越容易打出」以及是否优于「押市场看好」"""
    days = load_history()
    rows = [r for d in days for r in d["rows"]]

    def rate(rs, key="hit"):
        vs = [r[key] for r in rs if r.get(key) is not None]
        return {"hit": sum(1 for v in vs if v), "total": len(vs),
                "rate": round(sum(1 for v in vs if v) / len(vs), 3) if vs else None}

    out = {}
    for mk in ("ouzhi", "ah"):
        sub = [r for r in rows if r["market"] == mk]
        # 分档：按一致性分位切成 4 档，看命中率是否随「更一致」单调上升
        bands = []
        for lo, hi, name in ((0, 25, "最一致 P0-25"), (25, 50, "较一致 P25-50"),
                             (50, 75, "分歧中 P50-75"), (75, 101, "分歧大 P75-100")):
            b = [r for r in sub if r.get("pct") is not None and lo <= r["pct"] < hi]
            bands.append({"band": name, **rate(b), "fav": rate(b, "fav_hit"),
                          "cv_avg": round(sum(r["cv"] for r in b) / len(b), 4) if b else None})
        # 重合场次：最小分歧方向 == 市场看好方向。两者撞一起时信号最强，
        # 单独统计它的命中率，才能判断「重合」是否真的更值得跟。
        ov = [r for r in sub if r.get("consensus") == r.get("fav")]
        nov = [r for r in sub if r.get("consensus") != r.get("fav")]
        out[mk] = {"total": len(sub), "consensus": rate(sub), "fav": rate(sub, "fav_hit"),
                   "bands": bands, "overlap": rate(ov), "non_overlap": rate(nov),
                   # 冲突时押「市场看好」会怎样——用来判断最小分歧方向是不是反向指标
                   "non_overlap_fav": rate(nov, "fav_hit"), "overlap_fav": rate(ov, "fav_hit"),
                   # 最佳子集：重合 + 最一致档，两个条件交叉后的命中率
                   "sweet": rate([r for r in sub if r.get("consensus") == r.get("fav")
                                  and r.get("pct") is not None and r["pct"] < 25]),
                   "worst": rate([r for r in sub if r.get("consensus") != r.get("fav")
                                  and r.get("pct") is not None and r["pct"] >= 75])}

    by_day = [{"date": d["date"], "ouzhi": rate([r for r in d["rows"] if r["market"] == "ouzhi"]),
               "ah": rate([r for r in d["rows"] if r["market"] == "ah"])} for d in days]
    return jsonify({"days": len(days), "matches": len({(r.get("home"), r.get("away")) for r in rows}),
                    "stats": out, "by_day": by_day, "updated": days[-1]["ts"] if days else None})


@app.route("/api/trend")
def api_trend():
    fid = request.args.get("fid", "")
    return jsonify({"fid": fid, "trend": load_snapshot(fid) if fid.isdigit() else []})


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/download")
def download():
    """直接下载部署包（浏览器打开该地址即可把 zip 存到电脑/手机）"""
    p = os.path.join(BASE_DIR, "deploy.zip")
    if not os.path.exists(p):
        return "部署包不存在，请先在服务器上生成 deploy.zip", 404
    # 文件名用 ASCII，避免个别浏览器把中文名吞掉变成 "-.zip"
    return send_from_directory(BASE_DIR, "deploy.zip", as_attachment=True,
                               download_name="fqzs-deploy.zip")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8777))
    print(f"启动：http://0.0.0.0:{port}  （手机同 WiFi 访问本机局域网 IP）")
    app.run(host="0.0.0.0", port=port, debug=False)
