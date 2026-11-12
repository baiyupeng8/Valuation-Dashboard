# -*- coding: utf-8 -*-
"""
估值温度计 —— 每日估值看板生成器
=================================

结构分成四层，改样式时只动第 4 层：

  1. 取数层   fetch_*        —— 带当日缓存的 akshare 调用
  2. 序列层   build_series   —— 月线 / 日线两套口径
  3. 指标层   window_stats   —— 均值、分位、区域标签
  4. 渲染层   page_index / page_detail —— 一个页面一个模板

日线口径说明：
  指数与个股的日频市盈率公开接口只给最近 20 个交易日（中证指数）。
  因此日线用「最近一期月度估值锚点 × 当日收盘 / 锚点日收盘」推算，
  再用中证指数的真实 20 日做一次整体校准。页面底部会写明这一点。
"""

import json
import os
from datetime import datetime, timedelta, timezone

import akshare as ak
import pandas as pd

# ==========================================
# 配置
# ==========================================
CACHE_DIR = "data_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

TARGETS = [
    {
        "key": "hs300", "name": "沪深300", "short": "沪深", "code": "000300", "page": "hs300.html",
        "kind": "index", "lg": "沪深300", "cs": "000300", "tx": "sh000300",
        "metric": "市盈率 TTM", "unit": "倍", "tag": "大盘蓝筹",
    },
    {
        "key": "zz500", "name": "中证500", "short": "中证", "code": "000905", "page": "zz500.html",
        "kind": "index", "lg": "中证500", "cs": "000905", "tx": "sh000905",
        "metric": "市盈率 TTM", "unit": "倍", "tag": "中盘成长",
    },
    {
        "key": "wly", "name": "五粮液", "short": "五粮", "code": "000858", "page": "wly.html",
        "kind": "stock", "metric": "市盈率 TTM", "unit": "倍", "tag": "白酒",
    },
    {
        "key": "kc50", "name": "科创50", "short": "科创", "code": "588000", "page": "kc50.html",
        "kind": "etf", "metric": "场内价格", "unit": "元", "tag": "硬科技",
    },
    {
        "key": "hstech", "name": "恒生科技", "short": "恒生", "code": "513130", "page": "hstech.html",
        "kind": "etf", "metric": "场内价格", "unit": "元", "tag": "港股科技",
    },
    {
        "key": "szzs", "name": "上证指数ETF", "short": "上证", "code": "510980", "page": "szzs.html",
        "kind": "etf", "metric": "场内价格", "unit": "元", "tag": "汇添富 · 沪市宽基",
    },
]

# 视觉槽位（唯一 4 个彩色 + 中性阶）
COLORS = {
    "canvas": "#F7F5EF",
    "shell": "#FFFDF8",
    "ink": "#1B211C",
    "ink_soft": "#4C554E",
    "ink_muted": "#8A948C",
    "line": "#E3DFD3",
    "accent": "#C03A2B",
    "accent_soft": "#F0DCD6",
    "cold": "#2F6A55",
    "cold_soft": "#DDE9E2",
    "mid": "#A9A296",
}

TODAY = datetime.now()
TODAY_STR = TODAY.strftime("%Y-%m-%d")


# ==========================================
# 1. 取数层
# ==========================================
def _cache_path(name):
    return os.path.join(CACHE_DIR, name)


def _read_cache(path):
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_excel(path)
        df["日期"] = pd.to_datetime(df["日期"]).astype("datetime64[ns]")
        return df
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 缓存读取失败 {path}: {exc}")
        return None


def _fresh(path):
    # CI 上 git checkout 会把所有文件 mtime 刷成“现在”，
    # 所以由工作流显式设置 FORCE_REFRESH=1 来强制走一次网络，失败再降级读缓存。
    if os.environ.get("FORCE_REFRESH"):
        return False
    if not os.path.exists(path):
        return False
    mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")
    return mtime == TODAY_STR


def fetch_cached(file_name, label, fetch_fn, normalize, max_age_days=None):
    """当日缓存优先；失败降级到旧缓存（可选按天数判定是否过期）。"""
    path = _cache_path(file_name)
    if _fresh(path):
        df = _read_cache(path)
        if df is not None and not df.empty:
            print(f"✅ 缓存 {label}")
            return df

    try:
        raw = fetch_fn()
        df = normalize(raw)
        df["日期"] = pd.to_datetime(df["日期"]).astype("datetime64[ns]")
        df = df.dropna(subset=["日期"])
        df = df.sort_values("日期").reset_index(drop=True)
        df.to_excel(path, index=False)
        print(f"🌐 拉取 {label} → {len(df)} 行")
        return df
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 拉取失败 {label}: {type(exc).__name__} {exc}")
        df = _read_cache(path)
        if df is not None and not df.empty:
            if max_age_days:
                age = (TODAY - df["日期"].max()).days
                if age > max_age_days:
                    print(f"⚠️ 旧缓存 {label} 已过期 {age} 天，仍使用")
            print(f"⚠️ 降级读取旧缓存 {label}")
        return df


def _norm_monthly(raw):
    """统一成 日期 / 数值 两列（月线估值）。"""
    df = raw.copy()
    if "滚动市盈率" not in df.columns and "市盈率1" in df.columns:
        df = df.rename(columns={"市盈率1": "滚动市盈率"})
    if "date" in df.columns:
        df = df.rename(columns={"date": "日期"})
    df["日期"] = pd.to_datetime(df["日期"])
    keep = ["日期", "滚动市盈率"]
    extra = [c for c in df.columns if c in ("指数", "股息率1", "股息率2", "滚动市盈率中位数")]
    return df[keep + [c for c in extra if c not in keep]]


def index_monthly(t):
    """指数月线市盈率（乐咕乐股）。"""
    name = f"{t['lg']}_index.xlsx"
    return fetch_cached(
        name, f"{t['name']} 月线估值",
        lambda: ak.stock_index_pe_lg(symbol=t["lg"]),
        _norm_monthly,
        max_age_days=45,
    )


def stock_monthly(t):
    """个股月线市盈率（百度股市通）。"""
    name = f"{t['code']}_stock.xlsx"

    def fetch():
        df = ak.stock_zh_valuation_baidu(symbol=t["code"], indicator="市盈率(TTM)", period="全部")
        df = df.rename(columns={"date": "日期", "value": "滚动市盈率"})
        return df

    return fetch_cached(name, f"{t['name']} 月线估值", fetch, _norm_monthly, max_age_days=45)


def etf_daily(t):
    """ETF 日线收盘（ETF 用价格分位，不用 PE）。"""
    name = f"{t['code']}_etf.xlsx"

    def fetch():
        df = ak.fund_etf_hist_em(symbol=t["code"], period="daily", adjust="qfq")
        return df.rename(columns={"收盘": "价格"})

    def norm(raw):
        df = raw.copy()
        df["日期"] = pd.to_datetime(df["日期"])
        return df[["日期", "价格"]]

    df = fetch_cached(name, f"{t['name']} 日线价格", fetch, norm)
    # 兼容老缓存（历史上 ETF 的收盘列曾被命名为「滚动市盈率」）
    if df is not None and "价格" not in df.columns and "滚动市盈率" in df.columns:
        df = df.rename(columns={"滚动市盈率": "价格"})
    return df


def index_close(t):
    """指数日线收盘（腾讯源，一次请求拿全历史）。"""
    name = f"{t['code']}_idxpx.xlsx"

    def fetch():
        return ak.stock_zh_index_daily_tx(symbol=t["tx"])

    def norm(raw):
        df = raw.copy()
        df["日期"] = pd.to_datetime(df["date"])
        return df[["日期", "close"]].rename(columns={"close": "收盘"})

    return fetch_cached(name, f"{t['name']} 日线收盘", fetch, norm)


def stock_close(t):
    """个股日线收盘（前复权）。"""
    name = f"{t['code']}_px.xlsx"

    def fetch():
        return ak.stock_zh_a_hist(symbol=t["code"], period="daily", adjust="qfq")

    def norm(raw):
        df = raw.copy()
        df["日期"] = pd.to_datetime(df["日期"])
        return df[["日期", "收盘"]]

    return fetch_cached(name, f"{t['name']} 日线收盘", fetch, norm)


def csindex_daily_pe(t):
    """中证指数官方最新 20 日市盈率。

    注意：官方口径（市盈率1）与乐咕乐股的「滚动市盈率」不是同一套算法
    （同一交易日相差约 18%），所以只存不用，不做跨源校准 ——
    日线一律从自己的月线锚点推算，保证页面上的大数字与曲线是同一条口径。
    """
    if t["kind"] != "index":
        return None
    name = f"{t['lg']}_daily.xlsx"

    def fetch():
        return ak.stock_zh_index_value_csindex(symbol=t["cs"])

    def norm(raw):
        df = raw.rename(columns={"市盈率1": "滚动市盈率"}).copy()
        df["日期"] = pd.to_datetime(df["日期"])
        return df[["日期", "滚动市盈率"]]

    return fetch_cached(name, f"{t['name']} 官方日线估值", fetch, norm)


# ==========================================
# 2. 序列层
# ==========================================
def _clean(df, col="滚动市盈率"):
    if df is None or df.empty or col not in df.columns:
        return None
    out = df[["日期", col]].dropna().copy()
    out = out[out[col] > 0]
    out = out.drop_duplicates(subset="日期", keep="last").sort_values("日期")
    return out.reset_index(drop=True)


def build_series(t):
    """返回 dict：monthly / daily / calibrated / note"""
    out = {"monthly": None, "daily": None, "note": ""}

    if t["kind"] == "etf":
        daily = etf_daily(t)
        daily = _clean(daily, "价格")
        if daily is None:
            return out
        daily = daily.rename(columns={"价格": "数值"})
        # 月线由日线按月取最后一个交易日
        monthly = (
            daily.set_index("日期")["数值"]
            .resample("ME").last().dropna().reset_index()
            .rename(columns={"日期": "日期"})
        )
        out.update(monthly=monthly, daily=daily, note="ETF 用场内收盘价做价格分位")
        return out

    monthly = _clean(stock_monthly(t) if t["kind"] == "stock" else index_monthly(t))
    if monthly is None:
        return out
    monthly = monthly.rename(columns={"滚动市盈率": "数值"})

    close = stock_close(t) if t["kind"] == "stock" else index_close(t)
    daily = None
    if close is not None and len(close) > 30:
        anchors = monthly.rename(columns={"数值": "pe"})
        anchors["锚点日期"] = anchors["日期"]
        merged = pd.merge_asof(
            close.sort_values("日期")[["日期", "收盘"]].rename(columns={"收盘": "px"}),
            anchors[["日期", "锚点日期", "pe"]].sort_values("日期"),
            on="日期", direction="backward",
        ).dropna()
        px_lookup = close.set_index("日期")["收盘"].sort_index()
        idx = px_lookup.index
        anchor_px = []
        for a in merged["锚点日期"].values:
            pos = idx.searchsorted(a, side="right") - 1
            anchor_px.append(px_lookup.iloc[pos] if pos >= 0 else float("nan"))
        daily = pd.DataFrame({
            "日期": merged["日期"].values,
            "数值": merged["pe"].values * merged["px"].values / pd.Series(anchor_px).values,
        }).dropna()
        out["note"] = "日线为推算值：最近一期月度估值 × 当日收盘 / 锚点日收盘"
        daily = daily[daily["数值"] > 0].reset_index(drop=True)
    else:
        out["note"] = "日线收盘数据缺失，本次只出月线"

    out.update(monthly=monthly, daily=daily)
    return out


# ==========================================
# 3. 指标层
# ==========================================
def window(df, years):
    if df is None or df.empty:
        return None
    start = df["日期"].max() - timedelta(days=int(365.25 * years))
    out = df[df["日期"] >= start].copy()
    return out if len(out) >= 2 else None


def window_stats(df):
    if df is None or df.empty:
        return None
    v = df["数值"].astype(float)
    cur = float(v.iloc[-1])
    return {
        "cur": round(cur, 2),
        "mean": round(float(v.mean()), 2),
        "med": round(float(v.median()), 2),
        "p20": round(float(v.quantile(0.2)), 2),
        "p80": round(float(v.quantile(0.8)), 2),
        "hi": round(float(v.max()), 2),
        "lo": round(float(v.min()), 2),
        "pct": round(float((v < cur).mean() * 100), 0),
        "vs_mean": round((cur / float(v.mean()) - 1) * 100, 1),
    }


def zone_of(pct):
    if pct is None:
        return ("数据不足", "mid")
    if pct < 20:
        return ("偏冷", "cold")
    if pct < 40:
        return ("偏低", "cool")
    if pct < 60:
        return ("中枢", "mid")
    if pct < 80:
        return ("偏热", "warm")
    return ("偏贵", "hot")


def sparkline(values, width=140, height=38, accent=COLORS["accent"]):
    """服务端生成迷你走势线，避免为每张卡片再引一个图表实例。"""
    vals = [float(v) for v in values]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    n = len(vals) - 1
    pts = [
        (round(1 + i / n * (width - 2), 1), round(height - 4 - (v - lo) / span * (height - 8), 1))
        for i, v in enumerate(vals)
    ]
    d = " ".join(f"{x},{y}" for x, y in pts)
    last = pts[-1]
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'width="{width}" height="{height}" aria-hidden="true">'
        f'<polyline points="{d}" fill="none" stroke="{COLORS["ink_muted"]}" stroke-width="1.4" '
        f'stroke-linecap="round"/>'
        f'<circle cx="{last[0]}" cy="{last[1]}" r="2.6" fill="{accent}"/>'
        f"</svg>"
    )


# ==========================================
# 4. 渲染层：公共样式
# ==========================================
BASE_CSS = f"""
:root {{
  --canvas: {COLORS['canvas']};
  --shell: {COLORS['shell']};
  --ink: {COLORS['ink']};
  --ink-soft: {COLORS['ink_soft']};
  --ink-muted: {COLORS['ink_muted']};
  --line: {COLORS['line']};
  --accent: {COLORS['accent']};
  --accent-soft: {COLORS['accent_soft']};
  --cold: {COLORS['cold']};
  --cold-soft: {COLORS['cold_soft']};
  --mid: {COLORS['mid']};
  --r-shell: 28px;
  --r-card: 16px;
  --r-control: 10px;
  --r-pill: 999px;
  --font-serif: "Songti SC", "STSong", "Noto Serif CJK SC", "Source Han Serif SC", "SimSun", serif;
  --font-sans: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", system-ui, sans-serif;
  --font-mono: "SF Mono", "JetBrains Mono", "IBM Plex Mono", "Consolas", ui-monospace, monospace;
  --shadow-card: 0 1px 2px rgba(27,33,28,.04), 0 10px 22px -8px rgba(27,33,28,.08),
                 0 30px 60px -30px rgba(27,33,28,.10);
}}
* {{ box-sizing: border-box; }}
html {{ -webkit-text-size-adjust: 100%; }}
body {{
  margin: 0; background: var(--canvas); color: var(--ink);
  font-family: var(--font-sans); font-size: 16px; line-height: 1.65;
  -webkit-font-smoothing: antialiased;
  background-image: radial-gradient(120% 70% at 78% -10%, rgba(192,58,43,.05), transparent 60%);
  background-repeat: no-repeat;
}}
a {{ color: inherit; text-decoration: none; }}
.wrap {{ width: 100%; max-width: 1180px; margin: 0 auto; padding: 0 clamp(20px, 4vw, 32px); }}
.meta {{
  font-family: var(--font-mono); font-size: 11px; letter-spacing: .1em;
  text-transform: uppercase; color: var(--ink-muted);
}}
.kicker {{
  font-family: var(--font-mono); font-size: 11px; letter-spacing: .16em;
  text-transform: uppercase; color: var(--accent); margin: 0 0 18px;
}}
hr.rule {{ border: 0; border-top: 1px solid var(--line); margin: 0; }}
:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 4px; }}
"""

SHARED_JS = """
(function () {
  // 只负责在允许动效时打开 .motion（主视觉的轻微浮动）；
  // 正文永远默认可见 —— 关掉动效或脚本失败都不会出现空白段落。
  if (!window.matchMedia) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  document.documentElement.classList.add('motion');
})();
"""


def head(title, extra_css="", extra_head=""):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="个人估值温度计：{('、'.join(t['name'] for t in TARGETS))}的估值分位与走势">
<link rel="icon" href="images/logo.png" type="image/png">
<style>{BASE_CSS}{extra_css}</style>
{extra_head}
</head>
<body>
"""


# ==========================================
# 4.1 首页
# ==========================================
INDEX_CSS = """
.masthead {
  display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 6px 16px;
  padding: 26px 0 18px; border-bottom: 1px solid var(--line);
}
.masthead .brand { display: flex; align-items: center; gap: 10px; font-size: 14px; letter-spacing: .02em; }
.masthead .brand .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
.masthead .brand em { font-style: normal; color: var(--ink-muted); font-size: 12px; }

.hero { position: relative; padding: clamp(44px, 7vw, 84px) 0 clamp(28px, 4vw, 44px); }
.hero .copy { position: relative; z-index: 3; max-width: 620px; }
.hero h1 {
  font-family: var(--font-serif); font-weight: 700;
  font-size: clamp(2.5rem, 6.3vw, 6rem); line-height: 1.06; margin: 0 0 22px;
  letter-spacing: .01em;
}
.hero h1 b { font-weight: 700; color: var(--accent); }
.hero .lede { margin: 0; max-width: 44ch; font-size: 17px; color: var(--ink-soft); }
.hero .lede strong { color: var(--ink); font-weight: 600; }
.hero .art {
  position: absolute; right: -3%; top: clamp(-30px, -2vw, 0px); width: min(540px, 43vw);
  z-index: 1; pointer-events: none; opacity: .92;
}
.hero .art img { width: 100%; height: auto; display: block; }
.motion .hero .art img { animation: drift 9s ease-in-out infinite; }
@keyframes drift {
  0%, 100% { transform: translate3d(0, 0, 0); }
  50% { transform: translate3d(0, -10px, 0); }
}

.gauge { padding: clamp(26px, 4vw, 40px) 0 clamp(30px, 4vw, 46px); border-top: 1px solid var(--line); }
.gauge .head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 20px; }
.gauge .head h2 { font-size: 15px; font-weight: 600; margin: 0; letter-spacing: .02em; }
.gauge .head .meta { display: flex; gap: 14px; }
.gauge-scale { position: relative; height: 124px; }
.gauge-scale .track {
  position: absolute; left: 0; right: 0; top: 62px; height: 10px; border-radius: var(--r-pill);
  background: linear-gradient(90deg, #D8E7DE 0%, #EFEDE0 46%, #F6E2DD 74%, #EFCEC7 100%);
}
.gauge-scale .band {
  position: absolute; top: 56px; height: 22px; border-radius: var(--r-pill);
  border: 1px dashed rgba(27,33,28,.2);
}
.gauge-scale .tick { position: absolute; top: 76px; width: 1px; height: 12px; background: var(--line); }
.gauge-scale .tick span {
  position: absolute; top: 16px; left: 50%; transform: translateX(-50%);
  font-family: var(--font-mono); font-size: 10px; color: var(--ink-muted); white-space: nowrap;
}
.mark { position: absolute; top: 61px; transform: translate(-50%, 0); }
.mark .pin {
  width: 12px; height: 12px; border-radius: 50%; background: var(--ink);
  box-shadow: 0 0 0 3px rgba(247,245,239,.92), 0 2px 6px rgba(27,33,28,.26);
}
.mark .pin.hot { background: var(--accent); }
.mark .pin.cold { background: var(--cold); }
.mark .tag {
  position: absolute; bottom: calc(18px + var(--lane, 0) * 17px); left: 50%;
  transform: translateX(-50%); white-space: nowrap;
  font-size: 12px; color: var(--ink-soft); display: flex; align-items: center; gap: 6px;
}
.mark .tag i { font-style: normal; font-family: var(--font-mono); font-size: 11px; color: var(--ink-muted); }
.mark .tag .short { display: none; }
.mark .tag.l { transform: none; left: -8px; }
.mark .tag.r { transform: none; left: auto; right: -8px; }
.gauge .summary { display: flex; flex-wrap: wrap; gap: 22px; margin-top: 8px; }
.gauge .summary span { font-size: 13px; color: var(--ink-soft); }
.gauge .summary b { font-family: var(--font-mono); font-size: 13px; color: var(--ink); font-weight: 600; margin-left: 4px; }

.list-head { display: flex; justify-content: space-between; align-items: baseline; padding: 34px 0 12px; }
.list-head h2 { font-size: 15px; font-weight: 600; margin: 0; }
.rows { list-style: none; margin: 0 0 8px; padding: 0; }
.row {
  display: grid; grid-template-columns: minmax(150px, 240px) minmax(150px, 1fr) 100px 132px 24px;
  align-items: center; gap: 18px; padding: 22px 4px; border-top: 1px solid var(--line);
  transition: background-color .25s ease, padding .25s ease;
}
.rows .row:last-child { border-bottom: 1px solid var(--line); }
.row:hover { background: rgba(255,253,248,.75); padding-left: 12px; padding-right: 12px; }
.row .name { display: flex; flex-direction: column; gap: 3px; }
.row .name b { font-size: 17px; font-weight: 600; letter-spacing: .01em; }
.row .name small { font-family: var(--font-mono); font-size: 11px; color: var(--ink-muted); letter-spacing: .06em; }
.row .spark { opacity: .8; }
.row .trend { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; }
.row .delta { font-family: var(--font-mono); font-size: 11px; color: var(--ink-muted); letter-spacing: .02em; }
.row .delta.up { color: var(--accent); }
.row .delta.down { color: var(--cold); }
.row .delta-m { display: none; font-family: var(--font-mono); }
.row .delta-m.up { color: var(--accent); }
.row .delta-m.down { color: var(--cold); }
.row .val { font-family: var(--font-mono); font-size: 22px; font-weight: 600; letter-spacing: -.01em; text-align: right; }
.row .val em { font-style: normal; font-size: 11px; color: var(--ink-muted); margin-left: 3px; letter-spacing: 0; }
.row .badge {
  justify-self: start; display: inline-flex; align-items: center; gap: 8px;
  padding: 5px 12px; border-radius: var(--r-pill); border: 1px solid var(--line);
  font-size: 12px; color: var(--ink-soft); background: var(--shell);
}
.row .badge .pct { font-family: var(--font-mono); font-size: 11px; color: var(--ink-muted); }
.row .badge.hot { border-color: var(--accent-soft); background: var(--accent-soft); color: var(--accent); }
.row .badge.hot .pct { color: rgba(192,58,43,.7); }
.row .badge.cold { border-color: var(--cold-soft); background: var(--cold-soft); color: var(--cold); }
.row .badge.cold .pct { color: rgba(47,106,85,.7); }
.row .go { color: var(--ink-muted); justify-self: end; transition: transform .25s ease, color .25s ease; }
.row:hover .go { transform: translateX(4px); color: var(--accent); }
.row .bar { height: 2px; background: var(--line); position: relative; margin-top: 4px; }

footer.site { padding: 30px 0 54px; border-top: 1px solid var(--line); margin-top: 40px; }
footer.site .note { font-size: 13px; color: var(--ink-soft); max-width: 62ch; margin: 0 0 10px; }
footer.site .fine { font-family: var(--font-mono); font-size: 11px; color: var(--ink-muted); letter-spacing: .04em; }

@media (max-width: 900px) {
  .hero .art { position: static; width: min(320px, 68%); margin: 4px auto -18px; opacity: .7; order: 2; }
  .hero { display: flex; flex-direction: column; }
  .masthead .brand em { display: none; }
  .masthead .stamp { font-size: 10px; letter-spacing: .06em; }
  .row { grid-template-columns: 1fr auto; grid-template-areas: "name val" "meta meta" "badge go"; gap: 10px 14px; }
  .row .name { grid-area: name; }
  .row .val { grid-area: val; }
  .row .trend { display: none; }
  .row .delta-m { display: inline; }
  .row .badge { grid-area: badge; }
  .row .go { grid-area: go; }
  /* 窄屏刻度标签改用简称，避免叠字 */
  .mark .tag span:not(.short) { display: none; }
  .mark .tag .short { display: inline; }
  .mark .tag { font-size: 11px; gap: 4px; bottom: calc(18px + var(--lane, 0) * 16px); }
}
"""


def build_gauge_marks(items):
    """把分位映射到 0–100 的刻度上；挨得近的标签分到不同「行」，避免叠字。"""
    lanes = []  # 每行已经占用的 x 位置
    marks = []
    for it in sorted(items, key=lambda x: x["pct"]):
        p = max(2, min(98, float(it["pct"])))
        lane = 0
        while True:
            if lane >= len(lanes):
                lanes.append([])
                break
            if all(abs(x - p) >= 13 for x in lanes[lane]):
                break
            lane += 1
        lanes[lane].append(p)

        cls = "hot" if p >= 80 else ("cold" if p < 20 else "")
        align = " l" if p < 9 else (" r" if p > 91 else "")
        marks.append(
            f'<div class="mark" style="left:{p:.1f}%;--lane:{lane}">'
            f'<div class="pin {cls}"></div>'
            f'<div class="tag{align}"><span>{it["name"]}</span>'
            f'<span class="short">{it.get("short") or it["name"][:2]}</span>'
            f'<i>{p:.0f}%</i></div></div>'
        )
    return "".join(marks)


def cn_count(n):
    """3–10 的中文数目，用于「六个标的」这类文案。"""
    words = {3: "三个", 4: "四个", 5: "五个", 6: "六个", 7: "七个", 8: "八个", 9: "九个", 10: "十个"}
    return words.get(n, f"{n} 个")


def render_index(items, updated):
    avg = sum(i["pct"] for i in items) / len(items) if items else 50
    counts = {}
    for i in items:
        counts[i["zone"]] = counts.get(i["zone"], 0) + 1

    if avg < 25:
        mood, mood_txt = "偏凉", "整体还在低位，耐心比手速值钱。"
    elif avg < 45:
        mood, mood_txt = "温和", "价格不算贵，但也谈不上便宜。"
    elif avg < 65:
        mood, mood_txt = "微暖", "多数标的回到中枢附近，看估值不如看结构。"
    elif avg < 80:
        mood, mood_txt = "在升温", "越往上，越该问自己凭什么。"
    else:
        mood, mood_txt = "烫手", "这里是牛市的尾巴，也是最容易忘事的地方。"

    summary_bits = []
    for key, text in (("偏贵", "偏贵"), ("偏热", "偏热"), ("中枢", "中枢"), ("偏低", "偏低"), ("偏冷", "偏冷")):
        if counts.get(key):
            summary_bits.append(f"<span>{text}<b>{counts[key]}</b></span>")

    rows = []
    for i in items:
        z_cls = "hot" if i["pct"] >= 80 else ("cold" if i["pct"] < 20 else "")
        rows.append(f"""
        <a class="row" href="{i['page']}">
          <div class="name"><b>{i['name']}</b><small>{i['code']} · {i['tag']}<span class="delta-m {i['delta_cls']}">　近30日 {i['delta']}</span></small></div>
          <div class="trend">{i['spark']}<span class="delta {i['delta_cls']}">近30日 {i['delta']}</span></div>
          <div class="val">{i['cur']:.2f}<em>{i['unit']}</em></div>
          <div class="badge {z_cls}"><span>{i['zone']}</span><span class="pct">{i['pct']:.0f}%</span></div>
          <div class="go" aria-hidden="true">→</div>
        </a>""")

    html = head(
        "估值温度计 · BYP",
        INDEX_CSS,
    )
    html += f"""
<main class="wrap">
  <div class="masthead">
    <div class="brand"><span class="dot"></span>BYP 估值温度计 <em>／ 每日收盘后更新</em></div>
    <div class="meta">{updated}</div>
  </div>

  <section class="hero">
    <div class="copy">
      <p class="kicker">A 股 · 近十年估值分位</p>
      <h1>今天，<br>市场<b>{mood}</b>。</h1>
      <p class="lede">{cn_count(len(items))}标的平均处在近十年 <strong>{avg:.0f}%</strong> 分位。{mood_txt}</p>
    </div>
    <div class="art"><img src="images/bull-ink.png" alt="线描公牛" width="540" height="540"></div>
  </section>

  <section class="gauge">
    <div class="head">
      <h2>温度刻度 · 分位 0–100</h2>
      <div class="meta">虚线区间 = 20–80 分位</div>
    </div>
    <div class="gauge-scale">
      <div class="track"></div>
      <div class="band" style="left:20%; right:20%"></div>
      <div class="tick" style="left:0"><span>0</span></div>
      <div class="tick" style="left:20%"><span>20</span></div>
      <div class="tick" style="left:50%"><span>50</span></div>
      <div class="tick" style="left:80%"><span>80</span></div>
      <div class="tick" style="left:100%"><span>100</span></div>
      {build_gauge_marks(items)}
    </div>
    <div class="summary">{''.join(summary_bits)}</div>
  </section>

  <div class="list-head"><h2>逐标的读数</h2><div class="meta">分位取近十年 · 不足十年按全史</div></div>
  <ul class="rows">{''.join(rows)}</ul>

  <footer class="site">
    <p class="note">指数与个股用市盈率（TTM），ETF 用场内收盘价——ETF 没有可靠的每日披露盈利，价格分位更诚实。</p>
    <p class="fine">DATA · AKSHARE / 中证指数 / 乐咕乐股 / 百度股市通　|　UPDATE · {updated}</p>
  </footer>
</main>
<script>{SHARED_JS}</script>
</body>
</html>
"""
    return html


# ==========================================
# 4.2 详情页
# ==========================================
DETAIL_CSS = """
.topbar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 6px 16px; padding: 22px 0; border-bottom: 1px solid var(--line); }
.back { display: inline-flex; align-items: center; gap: 8px; font-size: 14px; color: var(--ink-soft); }
.back:hover { color: var(--accent); }
.back .arrow { transition: transform .2s ease; }
.back:hover .arrow { transform: translateX(-3px); }

.readout { display: grid; grid-template-columns: 1.1fr .9fr; gap: clamp(24px, 4vw, 56px); padding: clamp(32px, 5vw, 56px) 0 clamp(24px, 3vw, 36px); align-items: end; }
.readout h1 { font-family: var(--font-serif); font-size: clamp(1.75rem, 3vw, 2.5rem); margin: 0 0 6px; font-weight: 700; letter-spacing: .01em; }
.readout .sub { margin: 0; font-size: 13px; color: var(--ink-muted); }
.readout .big { display: flex; align-items: baseline; gap: 8px; margin: 18px 0 6px; }
.readout .big .num { font-family: var(--font-mono); font-size: clamp(2.6rem, 5vw, 4rem); font-weight: 600; letter-spacing: -.02em; line-height: 1; font-variant-numeric: tabular-nums; }
.readout .big .unit { font-size: 13px; color: var(--ink-muted); }
.readout .zone { margin: 0; font-size: 14px; color: var(--ink-soft); }
.readout .zone b { color: var(--accent); font-weight: 600; }
.readout .reading { margin: 16px 0 0; max-width: 34ch; font-size: 14px; line-height: 1.75; color: var(--ink-soft); }
.kv { list-style: none; margin: 0; padding: 0; border-top: 1px solid var(--line); }
.kv li { display: flex; justify-content: space-between; align-items: baseline; padding: 12px 0; border-bottom: 1px solid var(--line); }
.kv li span { font-size: 13px; color: var(--ink-soft); }
.kv li b { font-family: var(--font-mono); font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }

.card {
  background: var(--shell); border-radius: var(--r-shell); box-shadow: var(--shadow-card);
  padding: clamp(20px, 3vw, 30px); margin-bottom: 26px;
}
.card-head { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 6px; }
.card-head h2 { font-size: 15px; margin: 0; font-weight: 600; }
.tabs { display: flex; gap: 4px; background: rgba(27,33,28,.04); padding: 4px; border-radius: var(--r-pill); }
.tabs button {
  appearance: none; border: 0; background: transparent; cursor: pointer;
  font-family: var(--font-sans); font-size: 13px; color: var(--ink-soft);
  padding: 7px 15px; border-radius: var(--r-pill); transition: background-color .2s ease, color .2s ease;
}
.tabs button:hover { color: var(--ink); }
.tabs button[aria-selected="true"] { background: var(--ink); color: #F6F4EC; }
#chart { width: 100%; height: 420px; margin-top: 10px; }
.chart-note { margin: 2px 0 0; font-size: 12px; color: var(--ink-muted); }
.chart-empty { height: 420px; display: flex; align-items: center; justify-content: center; color: var(--ink-muted); font-size: 14px; }

.cells { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--line); border-radius: var(--r-card); overflow: hidden; margin: 22px 0 0; }
.cells > div { background: var(--shell); padding: 16px 16px 14px; }
.cells .k { font-size: 12px; color: var(--ink-muted); margin: 0 0 6px; }
.cells .v { font-family: var(--font-mono); font-size: 17px; font-weight: 600; margin: 0; font-variant-numeric: tabular-nums; }

.tables { display: grid; grid-template-columns: 1fr 1fr; gap: 26px; margin-bottom: 10px; }
.tbl-wrap { border-top: 1px solid var(--line); }
.tbl-wrap h3 { font-size: 13px; font-weight: 600; margin: 16px 0 8px; color: var(--ink-soft); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; font-weight: 500; color: var(--ink-muted); font-size: 12px; padding: 6px 0; border-bottom: 1px solid var(--line); }
td { padding: 7px 0; border-bottom: 1px solid var(--line); }
td.n, th.n { text-align: right; font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
tr:last-child td { border-bottom: 0; }
tbody td { color: var(--ink-soft); }
tbody tr:first-child td { color: var(--ink); font-weight: 600; }

@media (max-width: 880px) {
  .readout { grid-template-columns: 1fr; align-items: start; }
  .cells { grid-template-columns: 1fr 1fr; }
  .tables { grid-template-columns: 1fr; gap: 6px; }
  #chart { height: 320px; }
  .card-head { flex-direction: column; align-items: flex-start; gap: 10px; }
  .tabs { width: 100%; overflow-x: auto; scrollbar-width: none; }
  .tabs::-webkit-scrollbar { display: none; }
  .tabs button { flex: 0 0 auto; white-space: nowrap; font-size: 12.5px; padding: 7px 12px; }
}
"""


def _table(rows, head_col):
    body = "".join(f"<tr><td>{d}</td><td class='n'>{v}</td></tr>" for d, v in rows)
    return f"<table><thead><tr><th>{head_col}</th><th class='n'>数值</th></tr></thead><tbody>{body}</tbody></table>"


def render_detail(t, series, updated):
    monthly = series["monthly"]
    daily = series["daily"]

    ranges = {}
    seen_starts = set()
    for key, yrs in (("10y", 10), ("5y", 5), ("3y", 3), ("1y", 1)):
        w = window(monthly, yrs)
        if w is None:
            continue
        start = w["日期"].iloc[0]
        # 历史不足时，多个窗口会落到同一个起点，只保留第一个（最长的那一档）
        if start in seen_starts:
            continue
        seen_starts.add(start)
        st = window_stats(w)
        if st is None:
            continue
        ranges[key] = {
            "labels": [d.strftime("%Y-%m") for d in w["日期"]],
            "values": [round(float(v), 2) for v in w["数值"]],
            "stats": st,
        }

    if daily is not None:
        w = window(daily, 1)
        st = window_stats(w) if w is not None else None
        if st is not None:
            ranges["day"] = {
                "labels": [d.strftime("%Y-%m-%d") for d in w["日期"]],
                "values": [round(float(v), 2) for v in w["数值"]],
                "stats": st,
                "daily": True,
            }

    base_key = "10y" if "10y" in ranges else next(iter(ranges), None)
    if base_key is None:
        empty = f"""<main class="wrap"><div class="topbar"><a class="back" href="index.html"><span class="arrow">←</span> 全部标的</a><div class="meta">{updated}</div></div>
        <section class="readout"><div><h1>{t['name']}</h1><p class="sub">{t['code']} · {t['metric']}</p><div class="chart-empty">本次没有取到有效数据，明天再试。</div></div></section></main>"""
        return head(f"{t['name']} · 估值温度计", DETAIL_CSS) + empty + f"<script>{SHARED_JS}</script></body></html>"

    base = ranges[base_key]
    cur = base["stats"]["cur"]
    pct = base["stats"]["pct"]
    zone, zcls = zone_of(pct)
    vs_mean = base["stats"]["vs_mean"]

    # 近 30 日变化
    chg30 = None
    if daily is not None and len(daily) > 30:
        prev = float(daily["数值"].iloc[-31])
        if prev:
            chg30 = round((float(daily["数值"].iloc[-1]) / prev - 1) * 100, 1)

    updated_short = updated.split(" ")[0]

    span_years = len(base["labels"]) / 12.0
    span_word = "十年" if span_years >= 9 else {
        1: "一年", 2: "两年", 3: "三年", 4: "四年", 5: "五年",
        6: "六年", 7: "七年", 8: "八年",
    }.get(max(1, round(span_years)), f"{max(1, round(span_years))}年")

    if pct >= 80:
        reading = "站在 80 分位以上，这个位置往上靠的是情绪，不是业绩。"
    elif pct >= 60:
        reading = "高于历史中枢，但还没到极端。这时候该看的是持仓结构，不是估值数字。"
    elif pct >= 40:
        reading = "贴着历史中枢走，定价大体公允。没有便宜可捡，也没有非卖不可的理由。"
    elif pct >= 20:
        reading = "低于中枢，估值还有一层安全垫。剩下的问题是基本面会不会继续往下修。"
    else:
        reading = "处在区间底部。便宜是真的，冷也是真的——先问自己能不能等。"

    # 月线表（最近 12 期）
    last_m = monthly.tail(12).iloc[::-1]
    t1 = _table([(d.strftime("%Y-%m"), f"{v:.2f}") for d, v in zip(last_m["日期"], last_m["数值"])], "月份")

    t2 = ""
    if daily is not None and len(daily):
        last_d = daily.tail(10).iloc[::-1]
        t2 = _table([(d.strftime("%m-%d"), f"{v:.2f}") for d, v in zip(last_d["日期"], last_d["数值"])], "交易日")

    tabs = [
        ("10y", f"近{span_word}"), ("5y", "近五年"), ("3y", "近三年"), ("1y", "近一年"),
    ]
    if "day" in ranges:
        tabs.append(("day", "日线 · 近一年"))
    tabs = [x for x in tabs if x[0] in ranges]

    tab_btns = "".join(
        f'<button role="tab" data-range="{k}" aria-selected="{"true" if i == 0 else "false"}">{lab}</button>'
        for i, (k, lab) in enumerate(tabs)
    )

    payload = {
        k: {
            "labels": v["labels"],
            "values": v["values"],
            "stats": v["stats"],
            "daily": v.get("daily", False),
        }
        for k, v in ranges.items()
    }
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    legend_note = "虚线：20 / 80 分位与区间均值　·　点：最新值"
    if series["note"]:
        legend_note += f"　·　{series['note']}"

    html = head(
        f"{t['name']} · 估值温度计",
        DETAIL_CSS,
        '<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script>',
    )
    html += f"""
<main class="wrap">
  <div class="topbar">
    <a class="back" href="index.html"><span class="arrow">←</span> 全部标的</a>
    <div class="meta">{updated}</div>
  </div>

  <section class="readout">
    <div>
      <p class="kicker">{t['tag']} · {t['metric']}</p>
      <h1>{t['name']}</h1>
      <p class="sub">{t['code']} · 更新至 {updated_short}</p>
      <div class="big"><span class="num">{cur:.2f}</span><span class="unit">{t['unit']}</span></div>
      <p class="zone">近{span_word} <b>{pct:.0f}%</b> 分位 · <b>{zone}</b>　较均值 {vs_mean:+.1f}%</p>
      <p class="reading">{reading}</p>
    </div>
    <ul class="kv">
      <li><span>{span_word}区间</span><b>{base['stats']['lo']:.2f} – {base['stats']['hi']:.2f}</b></li>
      <li><span>均值 / 中位</span><b>{base['stats']['mean']:.2f} / {base['stats']['med']:.2f}</b></li>
      <li><span>20 / 80 分位</span><b>{base['stats']['p20']:.2f} / {base['stats']['p80']:.2f}</b></li>
      <li><span>近 30 个交易日</span><b>{f"{chg30:+.1f}%" if chg30 is not None else "—"}</b></li>
    </ul>
  </section>

  <section class="card">
    <div class="card-head">
      <h2>估值走势</h2>
      <div class="tabs" role="tablist">{tab_btns}</div>
    </div>
    <div id="chart" role="img" aria-label="{t['name']} 估值走势图"></div>
    <p class="chart-note">{legend_note}</p>
    <div class="cells" id="cells"></div>
  </section>

  <div class="list-head"><h2>区间数据</h2><div class="meta">最新在前</div></div>
  <div class="tables">
    <div class="tbl-wrap"><h3>月线 · 最近 12 期</h3>{t1}</div>
    <div class="tbl-wrap"><h3>日线 · 最近 10 个交易日</h3>{t2 or '<p class="chart-note">无日线数据</p>'}</div>
  </div>

  <footer class="site">
    <p class="note">数据来源 akshare：指数月线取乐咕乐股，个股估值取百度股市通，ETF 取东方财富场内行情；日线不取外部日频估值，而是用「最近一期月度估值 × 当日收盘 / 锚点日收盘」推算。分位 = 当前值在过去窗口内的位置。</p>
    <p class="fine">UPDATE · {updated}　|　本页仅用于自我提醒，不构成任何投资建议</p>
  </footer>
</main>
<script>window.__SERIES__ = {data_json};</script>
<script>
(function () {{
  var C = {json.dumps({
      "ink": COLORS["ink"], "line": COLORS["line"], "muted": COLORS["ink_muted"],
      "accent": COLORS["accent"], "cold": COLORS["cold"], "shell": COLORS["shell"],
      "soft": COLORS["ink_soft"], "accentSoft": COLORS["accent_soft"],
  }, ensure_ascii=False)};
  var S = window.__SERIES__;
  var unit = {json.dumps(t['unit'], ensure_ascii=False)};
  var el = document.getElementById('chart');
  var cells = document.getElementById('cells');

  function cellHtml(st, key) {{
    var f = function (n) {{ return (n === undefined || n === null) ? '—' : Number(n).toFixed(2); }};
    var items = [
      ['区间均值', f(st.mean)],
      ['20 分位', f(st.p20)],
      ['80 分位', f(st.p80)],
      ['区间分位', Math.round(st.pct) + '%']
    ];
    return items.map(function (it) {{
      return '<div><p class="k">' + it[0] + '</p><p class="v">' + it[1] + '</p></div>';
    }}).join('');
  }}

  if (!window.echarts) {{
    el.outerHTML = '<div class="chart-empty">图表脚本没有加载成功，请刷新页面</div>';
    return;
  }}
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var chart = echarts.init(el, null, {{ renderer: 'canvas' }});

  function optionFor(rel) {{
    var d = S[rel];
    var st = d.stats;
    var isDay = !!d.daily;
    return {{
      animation: !reduce,
      animationDuration: 620,
      animationEasing: 'cubicOut',
      grid: {{ left: 6, right: 30, top: 16, bottom: 26, containLabel: true }},
      tooltip: {{
        trigger: 'axis',
        axisPointer: {{ type: 'line', lineStyle: {{ color: C.line, width: 1 }} }},
        backgroundColor: C.shell,
        borderColor: C.line,
        borderWidth: 1,
        padding: [8, 12],
        textStyle: {{ color: C.ink, fontFamily: 'ui-monospace, SF Mono, Consolas, monospace', fontSize: 12 }},
        extraCssText: 'border-radius:10px;box-shadow:0 8px 20px -10px rgba(27,33,28,.25);',
        formatter: function (ps) {{
          var p = ps[0];
          return '<div style="color:#8A948C;font-size:11px;margin-bottom:3px">' + p.axisValue + '</div>' +
                 '<div style="font-weight:600">' + Number(p.value).toFixed(2) + ' ' + unit + '</div>';
        }}
      }},
      xAxis: {{
        type: 'category',
        data: d.labels,
        boundaryGap: false,
        axisLine: {{ lineStyle: {{ color: C.line }} }},
        axisTick: {{ show: false }},
        splitLine: {{ show: false }},
        axisLabel: {{
          color: C.muted, fontSize: 11, fontFamily: 'ui-monospace, SF Mono, Consolas, monospace',
          hideOverlap: true, margin: 12,
          formatter: function (v) {{ return isDay ? v.slice(5) : v.replace('-', '.'); }}
        }}
      }},
      yAxis: {{
        type: 'value', scale: true,
        axisLine: {{ show: false }}, axisTick: {{ show: false }},
        splitLine: {{ show: true, lineStyle: {{ color: C.line, type: 'dashed', width: 1 }} }},
        axisLabel: {{ color: C.muted, fontSize: 11, fontFamily: 'ui-monospace, SF Mono, Consolas, monospace', margin: 10 }},
        axisPointer: {{ label: {{ show: false }} }}
      }},
      series: [{{
        type: 'line',
        data: d.values,
        showSymbol: false,
        smooth: isDay ? 0.32 : 0.18,
        lineStyle: {{ width: isDay ? 1.4 : 1.6, color: C.ink, opacity: isDay ? .78 : 1 }},
        areaStyle: {{
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            {{ offset: 0, color: 'rgba(27,33,28,0.10)' }},
            {{ offset: 1, color: 'rgba(27,33,28,0.01)' }}
          ])
        }},
        markArea: {{
          silent: true,
          itemStyle: {{ color: 'rgba(192,58,43,0.045)' }},
          data: [[{{ yAxis: st.p20 }}, {{ yAxis: st.p80 }}]]
        }},
        markLine: {{
          silent: true, symbol: 'none',
          label: {{ show: false }},
          data: [
            {{ yAxis: st.p80, lineStyle: {{ color: C.accent, type: 'dashed', width: 1, opacity: .8 }} }},
            {{ yAxis: st.p20, lineStyle: {{ color: C.cold, type: 'dashed', width: 1, opacity: .8 }} }},
            {{ yAxis: st.mean, lineStyle: {{ color: C.muted, type: 'dashed', width: 1, opacity: .7 }} }}
          ]
        }},
        markPoint: {{
          symbol: 'circle', symbolSize: 9,
          itemStyle: {{ color: C.accent, borderColor: '#F7F5EF', borderWidth: 2 }},
          label: {{
            show: true, position: 'left', distance: 9,
            color: C.accent, fontSize: 12, fontWeight: 600,
            fontFamily: 'ui-monospace, SF Mono, Consolas, monospace',
            formatter: String(Number(d.values[d.values.length - 1]).toFixed(2))
          }},
          data: [{{ coord: [d.labels.length - 1, d.values[d.values.length - 1]] }}]
        }}
      }}]
    }};
  }}

  function render(rel) {{
    chart.setOption(optionFor(rel), true);
    cells.innerHTML = cellHtml(S[rel].stats, rel);
  }}

  var wanted = (location.search.match(/range=([a-z0-9]+)/) || [])[1];
  var activeBtn = document.querySelector('.tabs button[aria-selected="true"]');
  var initial = (wanted && S[wanted]) ? wanted
    : (activeBtn ? activeBtn.dataset.range : Object.keys(S)[0]);
  Array.prototype.forEach.call(document.querySelectorAll('.tabs button'), function (b) {{
    b.setAttribute('aria-selected', b.dataset.range === initial ? 'true' : 'false');
  }});
  render(initial);

  Array.prototype.forEach.call(document.querySelectorAll('.tabs button'), function (btn) {{
    btn.addEventListener('click', function () {{
      Array.prototype.forEach.call(document.querySelectorAll('.tabs button'), function (b) {{
        b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
      }});
      render(btn.dataset.range);
    }});
  }});

  var t;
  window.addEventListener('resize', function () {{
    clearTimeout(t); t = setTimeout(function () {{ chart.resize(); }}, 120);
  }});
}})();
</script>
<script>{SHARED_JS}</script>
</body>
</html>
"""
    return html


# ==========================================
# 主流程
# ==========================================
def main():
    print("=== 估值温度计 开始生成 ===")
    updated = datetime.now(timezone.utc) + timedelta(hours=8)
    updated_str = updated.strftime("%Y-%m-%d %H:%M")

    cards = []
    ok_count = 0

    for t in TARGETS:
        print(f"\n▶ {t['name']}")
        try:
            series = build_series(t)
        except Exception as exc:  # noqa: BLE001
            print(f"❌ 序列构建失败 {t['name']}: {type(exc).__name__} {exc}")
            series = {"monthly": None, "daily": None, "note": ""}

        try:
            html = render_detail(t, series, updated_str)
            with open(t["page"], "w", encoding="utf-8") as f:
                f.write(html)
            print(f"✅ 生成 {t['page']}")
        except Exception as exc:  # noqa: BLE001
            print(f"❌ 页面渲染失败 {t['name']}: {type(exc).__name__} {exc}")
            continue

        st = window_stats(window(series["monthly"], 10))
        if st is not None:
            ok_count += 1
            zone, _ = zone_of(st["pct"])
            if series["daily"] is not None:
                spark_vals = series["daily"]["数值"].tail(60).tolist()
                chg = None
                if len(series["daily"]) > 30:
                    prev = float(series["daily"]["数值"].iloc[-31])
                    if prev:
                        chg = (float(series["daily"]["数值"].iloc[-1]) / prev - 1) * 100
            else:
                spark_vals = series["monthly"]["数值"].tail(24).tolist()
                chg = None
                if len(series["monthly"]) > 2:
                    prev = float(series["monthly"]["数值"].iloc[-2])
                    if prev:
                        chg = (float(series["monthly"]["数值"].iloc[-1]) / prev - 1) * 100

            if chg is None:
                delta, delta_cls = "—", ""
            else:
                delta = f"{chg:+.1f}%"
                delta_cls = "up" if chg > 0 else ("down" if chg < 0 else "")

            cards.append({
                "name": t["name"], "code": t["code"], "page": t["page"], "tag": t["tag"],
                "cur": st["cur"], "pct": st["pct"], "zone": zone,
                "unit": "元" if t["kind"] == "etf" else "倍",
                "spark": sparkline(spark_vals),
                "delta": delta, "delta_cls": delta_cls,
            })

    if cards:
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(render_index(cards, updated_str))
        print(f"\n🎉 首页与 {len(cards)} 个详情页已刷新")
    else:
        print("\n❌ 没有任何标的取到数据，首页保持原样")


if __name__ == "__main__":
    main()
