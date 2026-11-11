import akshare as ak
import pandas as pd
import os
import re
from datetime import datetime, timedelta
from pyecharts import options as opts
from pyecharts.charts import Line, Tab

# ==========================================
# 核心配置与缓存目录
# ==========================================
CACHE_DIR = "data_cache"
os.makedirs(CACHE_DIR, exist_ok=True) # 自动创建 data_cache 文件夹

# ==========================================
# 核心函数 1：带缓存的通用数据获取器
# ==========================================
def get_data_with_cache(symbol_name, index_code, is_stock=False, etf_code=None):
    """
    获取数据，优先读取当天的本地 Excel 缓存，如果没有则调接口并保存。
    """
    # 1. 确定缓存文件路径
    if is_stock:
        file_name = f"{index_code}_stock.xlsx"
    elif etf_code:
        file_name = f"{etf_code}_etf.xlsx"
    else:
        file_name = f"{index_code}_index.xlsx"
        
    file_path = os.path.join(CACHE_DIR, file_name)
    today_str = datetime.now().strftime('%Y-%m-%d')

    # 2. 检查本地是否有今天的缓存
    if os.path.exists(file_path):
        file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d')
        if file_mtime == today_str:
            print(f"✅ 读取本地缓存: {symbol_name} ({file_name})")
            df = pd.read_excel(file_path)
            df['日期'] = pd.to_datetime(df['日期'])
            return df

    # 3. 如果没有缓存或缓存过期，则调用接口
    print(f"🌐 正在请求接口拉取: {symbol_name} ...")
    try:
        if is_stock:
            df = ak.stock_zh_valuation_baidu(symbol=index_code, indicator="市盈率(TTM)", period="全部")
            df = df.rename(columns={'date': '日期', 'value': '滚动市盈率'})
        elif etf_code:
            df = ak.fund_etf_hist_em(symbol=etf_code, period="daily", adjust="qfq")
            df = df.rename(columns={'收盘': '滚动市盈率'}) # 为了统一处理，把ETF收盘价映射为PE列
        else:
            df = ak.stock_index_pe_lg(symbol=index_code)
            
        df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期')
        
        # 4. 成功获取后，立刻保存到 Excel 缓存，明天之前不再调接口
        df.to_excel(file_path, index=False)
        print(f"💾 接口拉取成功，已缓存到: {file_path}")
        return df
        
    except Exception as e:
        print(f"❌ 接口拉取失败 {symbol_name}: {e}")
        # 接口失败时，尝试读取旧缓存（哪怕不是今天的，也比没有强）
        if os.path.exists(file_path):
            print(f"⚠️ 接口失败，降级读取旧缓存: {symbol_name}")
            df = pd.read_excel(file_path)
            df['日期'] = pd.to_datetime(df['日期'])
            return df
        return None

# ==========================================
# 核心函数 2：画图逻辑（只负责计算和画图，不负责拿数据）
# ==========================================
def generate_chart_from_df(df, symbol_name, years):
    if df is None or df.empty:
        return None
    try:
        df_filtered = df[df['滚动市盈率'] > 0].copy()
        start_date = df_filtered['日期'].max() - timedelta(days=365 * years)
        df_filtered = df_filtered[df_filtered['日期'] >= start_date]

        x_data = df_filtered['日期'].dt.strftime('%Y-%m-%d').tolist()
        y_data = df_filtered['滚动市盈率'].tolist()

        mean_val = round(df_filtered['滚动市盈率'].mean(), 2)
        high_val = round(df_filtered['滚动市盈率'].quantile(0.8), 2)
        low_val = round(df_filtered['滚动市盈率'].quantile(0.2), 2)

        mean_line = [mean_val] * len(x_data)
        high_line = [high_val] * len(x_data)
        low_line = [low_val] * len(x_data)

        line = (
            Line(init_opts=opts.InitOpts(width="100%", height="600px"))
            .add_xaxis(xaxis_data=x_data)
            .add_yaxis(series_name="数据", y_axis=y_data, is_symbol_show=False, itemstyle_opts=opts.ItemStyleOpts(color="#107C41"), linestyle_opts=opts.LineStyleOpts(width=2), label_opts=opts.LabelOpts(is_show=False), markline_opts=opts.MarkLineOpts(is_silent=True, data=[]))
            .add_yaxis(series_name=f"均值({mean_val})", y_axis=mean_line, is_symbol_show=False, itemstyle_opts=opts.ItemStyleOpts(color="#FFD700"), linestyle_opts=opts.LineStyleOpts(width=1.5, type_="dashed"), label_opts=opts.LabelOpts(is_show=False), markline_opts=opts.MarkLineOpts(is_silent=True, data=[]))
            .add_yaxis(series_name=f"高估线({high_val})", y_axis=high_line, is_symbol_show=False, itemstyle_opts=opts.ItemStyleOpts(color="#C00000"), linestyle_opts=opts.LineStyleOpts(width=1.5, type_="dashed"), label_opts=opts.LabelOpts(is_show=False), markline_opts=opts.MarkLineOpts(is_silent=True, data=[]))
            .add_yaxis(series_name=f"低估线({low_val})", y_axis=low_line, is_symbol_show=False, itemstyle_opts=opts.ItemStyleOpts(color="#A0A0A0"), linestyle_opts=opts.LineStyleOpts(width=1.5, type_="dashed"), label_opts=opts.LabelOpts(is_show=False), markline_opts=opts.MarkLineOpts(is_silent=True, data=[]))
            .set_global_opts(
                title_opts=opts.TitleOpts(title=f"{symbol_name} 估值 (近{years}年)", pos_left="center"),
                tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
                legend_opts=opts.LegendOpts(pos_bottom="0%"),
                xaxis_opts=opts.AxisOpts(type_="category", boundary_gap=False),
                yaxis_opts=opts.AxisOpts(type_="value", splitline_opts=opts.SplitLineOpts(is_show=False)),
                datazoom_opts=[opts.DataZoomOpts(range_start=0, range_end=100)]
            )
        )
        return line
    except Exception as e:
        print(f"❌ 画图计算出错 {symbol_name}: {e}")
        return None

# ==========================================
# 辅助函数：注入返回按钮 + 全局图标 (暴力版)
# ==========================================
def inject_back_button(filename, update_time):
    if not os.path.exists(filename): return
    with open(filename, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 1. 清理旧按钮
    content = re.sub(r'<div style="position: fixed; top: 20px; right: 30px;.*?</div>', '', content, flags=re.DOTALL)
    
    # 2. 注入图标（暴力替换所有闭合标签）
    icon_html = '<link rel="icon" href="images/logo.png" type="image/png">'
    if 'rel="icon"' in content:
        # 如果已经有旧的图标代码，直接替换掉旧的
        content = re.sub(r'<link rel="icon".*?>', icon_html, content)
    else:
        # 如果没有，强行塞在 </title> 后面
        content = content.replace("</title>", f"</title>\n    {icon_html}")
    
    # 3. 注入返回按钮
    btn = f"""<div style="position: fixed; top: 20px; right: 30px; z-index: 99999; display: flex; align-items: center; gap: 15px;">
    <span style="color: #666; font-size: 14px; background: rgba(255,255,255,0.8); padding: 5px 10px; border-radius: 15px;">更新于: {update_time}</span>
    <a href="index.html" style="padding: 10px 20px; background: #ff4d4f; color: #fff; text-decoration: none; border-radius: 30px; box-shadow: 0 4px 12px rgba(255, 77, 79, 0.4); font-weight: bold; transition: all 0.3s;">🏠 返回主页</a>
    </div>"""
    content = content.replace("</body>", f"{btn}\n</body>")
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

# ==========================================
# 主流程
# ==========================================
def main():
    print("开始生成全景看板 (缓存加速版)...")
    
    # 获取北京时间
    bj_time = datetime.utcnow() + timedelta(hours=8)
    update_time = bj_time.strftime('%Y-%m-%d %H:%M:%S')

    targets = [
        {"name": "沪深300", "code": "沪深300", "is_stock": False, "filename": "hs300.html"},
        {"name": "中证500", "code": "中证500", "is_stock": False, "filename": "zz500.html"},
        {"name": "五粮液", "code": "000858", "is_stock": True, "filename": "wly.html"}
    ]
    
    etf_targets = [
        {"name": "科创50 (ETF)", "code": "588000", "filename": "kc50.html"},
        {"name": "恒生科技 (ETF)", "code": "513130", "filename": "hstech.html"}
    ]

    nav_links = []
    all_success = True

    # 1. 处理 PE 指数和个股
    for t in targets:
        # 【关键】：这里只调用一次获取数据，不管是画 10 年还是 3 年
        df = get_data_with_cache(t['name'], t['code'], is_stock=t['is_stock'])
        
        tab = Tab()
        tab_success = True
        for years in [10, 5, 3]:
            chart = generate_chart_from_df(df, t['name'], years)
            if chart:
                tab.add(chart, f"近 {years} 年")
            else:
                tab_success = False
        
        if tab_success and df is not None:
            tab.render(t['filename'])
            nav_links.append(f'<li><a href="{t["filename"]}" target="_blank">{t["name"]} (10/5/3年切换)</a></li>')
            inject_back_button(t['filename'], update_time)
            print(f"✅ {t['name']} 网页生成成功")
        else:
            all_success = False
            print(f"⚠️ {t['name']} 数据异常，保留旧网页。")

    # 2. 处理 ETF
    for etf in etf_targets:
        df = get_data_with_cache(etf['name'], "", etf_code=etf['code'])
        # ETF 只画全历史或近10年
        chart = generate_chart_from_df(df, etf['name'], years=10)
        
        if chart:
            chart.render(etf['filename'])
            nav_links.append(f'<li><a href="{etf["filename"]}" target="_blank">{etf["name"]} (价格分位)</a></li>')
            inject_back_button(etf['filename'], update_time)
            print(f"✅ {etf['name']} 网页生成成功")
        else:
            all_success = False
            print(f"⚠️ {etf['name']} 数据异常，保留旧网页。")

    # 3. 生成带炫酷 UI 的主页
    if all_success:
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>个人全资产监控驾驶舱</title>
            <link rel="icon" href="images/logo.png" type="image/png">
            <style>
                body {{ font-family: -apple-system, 'Microsoft YaHei', sans-serif; background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%); min-height: 100vh; margin: 0; padding: 40px 20px; display: flex; justify-content: center; align-items: center; color: #fff; }}
                .container {{ width: 100%; max-width: 600px; background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(16px); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 24px; padding: 40px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); }}
                h1 {{ text-align: center; color: #f8fafc; font-size: 28px; margin-bottom: 40px; }}
                ul {{ list-style: none; padding: 0; margin: 0; }}
                li {{ margin-bottom: 16px; }}
                a {{ display: flex; align-items: center; padding: 20px 24px; background: rgba(255, 255, 255, 0.03); color: #e2e8f0; text-decoration: none; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; font-size: 18px; transition: all 0.3s; }}
                a:hover {{ background: rgba(255, 255, 255, 0.1); border-color: rgba(255, 255, 255, 0.3); transform: translateY(-4px) scale(1.02); box-shadow: 0 10px 25px -5px rgba(59, 130, 246, 0.4); color: #ffffff; }}
                .footer {{ text-align: center; margin-top: 40px; color: #94a3b8; font-size: 13px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📊 个人大A监控驾驶舱</h1>
                <ul>{''.join(nav_links)}</ul>
                <div class="footer">数据来源: akshare | <b>最后更新时间: {update_time}</b></div>
            </div>
        </body>
        </html>
        """
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        print("🎉 所有数据更新成功！主页已刷新。")
    else:
        print("❌ 部分数据获取失败，为了安全起见，保留上次成功的数据和主页。")

if __name__ == "__main__":
    main()