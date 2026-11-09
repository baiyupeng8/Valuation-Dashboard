import akshare as ak
import pandas as pd
from pyecharts import options as opts
from pyecharts.charts import Line, Page, Tab
from datetime import datetime, timedelta

# ==========================================
# 核心计算函数：根据传入的年数，动态画图
# ==========================================
def generate_pe_chart(symbol_name, index_code, is_stock, years):
    print(f"正在计算 {symbol_name} - 近 {years} 年数据...")
    try:
        # 1. 获取数据
        if is_stock:
            df = ak.stock_zh_valuation_baidu(symbol=index_code, indicator="市盈率(TTM)", period="全部")
            df = df.rename(columns={'date': '日期', 'value': '滚动市盈率'})
        else:
            df = ak.stock_index_pe_lg(symbol=index_code)
            
        df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期')
        
        # 过滤有效数据并计算起始时间
        df = df[df['滚动市盈率'] > 0]
        start_date = df['日期'].max() - timedelta(days=365 * years)
        df_filtered = df[df['日期'] >= start_date].copy()

        x_data = df_filtered['日期'].dt.strftime('%Y-%m-%d').tolist()
        y_data = df_filtered['滚动市盈率'].tolist()

        # 2. 动态计算当前窗口的分位数
        mean_val = round(df_filtered['滚动市盈率'].mean(), 2)
        high_val = round(df_filtered['滚动市盈率'].quantile(0.8), 2)
        low_val = round(df_filtered['滚动市盈率'].quantile(0.2), 2)

        mean_line = [mean_val] * len(x_data)
        high_line = [high_val] * len(x_data)
        low_line = [low_val] * len(x_data)

        # 3. 画图
        line = (
            Line()
            .add_xaxis(xaxis_data=x_data)
            .add_yaxis(
                series_name="滚动PE", y_axis=y_data, is_symbol_show=False,
                itemstyle_opts=opts.ItemStyleOpts(color="#107C41"),
                linestyle_opts=opts.LineStyleOpts(width=2),
                label_opts=opts.LabelOpts(is_show=False), markline_opts=opts.MarkLineOpts(is_silent=True, data=[])
            )
            .add_yaxis(
                series_name=f"均值({mean_val})", y_axis=mean_line, is_symbol_show=False,
                itemstyle_opts=opts.ItemStyleOpts(color="#FFD700"),
                linestyle_opts=opts.LineStyleOpts(width=1.5, type_="dashed"),
                label_opts=opts.LabelOpts(is_show=False), markline_opts=opts.MarkLineOpts(is_silent=True, data=[])
            )
            .add_yaxis(
                series_name=f"高估线({high_val})", y_axis=high_line, is_symbol_show=False,
                itemstyle_opts=opts.ItemStyleOpts(color="#C00000"),
                linestyle_opts=opts.LineStyleOpts(width=1.5, type_="dashed"),
                label_opts=opts.LabelOpts(is_show=False), markline_opts=opts.MarkLineOpts(is_silent=True, data=[])
            )
            .add_yaxis(
                series_name=f"低估线({low_val})", y_axis=low_line, is_symbol_show=False,
                itemstyle_opts=opts.ItemStyleOpts(color="#A0A0A0"),
                linestyle_opts=opts.LineStyleOpts(width=1.5, type_="dashed"),
                label_opts=opts.LabelOpts(is_show=False), markline_opts=opts.MarkLineOpts(is_silent=True, data=[])
            )
            .set_global_opts(
                title_opts=opts.TitleOpts(title=f"{symbol_name} 滚动PE估值 (近{years}年)", pos_left="center"),
                tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
                legend_opts=opts.LegendOpts(pos_bottom="0%"),
                xaxis_opts=opts.AxisOpts(type_="category", boundary_gap=False),
                yaxis_opts=opts.AxisOpts(type_="value", splitline_opts=opts.SplitLineOpts(is_show=False)),
                datazoom_opts=[opts.DataZoomOpts(range_start=0, range_end=100)]
            )
        )
        return line
    except Exception as e:
        print(f"❌ 计算 {symbol_name} 失败: {e}")
        return None

# ==========================================
# ETF 价格分位图（保持之前的逻辑，拿全历史）
# ==========================================
def generate_price_chart(symbol_name, etf_code):
    print(f"正在获取 {symbol_name} 历史价格数据...")
    try:
        df = ak.fund_etf_hist_em(symbol=etf_code, period="daily", adjust="qfq")
        df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期')
        df_filtered = df[df['日期'] >= "2014-01-01"].copy()

        x_data = df_filtered['日期'].dt.strftime('%Y-%m-%d').tolist()
        y_data = df_filtered['收盘'].tolist()

        mean_val = round(df_filtered['收盘'].mean(), 3)
        high_val = round(df_filtered['收盘'].quantile(0.8), 3)
        low_val = round(df_filtered['收盘'].quantile(0.2), 3)

        mean_line = [mean_val] * len(x_data)
        high_line = [high_val] * len(x_data)
        low_line = [low_val] * len(x_data)

        line = (
            Line()
            .add_xaxis(xaxis_data=x_data)
            .add_yaxis(series_name="收盘价", y_axis=y_data, is_symbol_show=False, itemstyle_opts=opts.ItemStyleOpts(color="#1f77b4"), linestyle_opts=opts.LineStyleOpts(width=2), label_opts=opts.LabelOpts(is_show=False), markline_opts=opts.MarkLineOpts(is_silent=True, data=[]))
            .add_yaxis(series_name=f"均值({mean_val})", y_axis=mean_line, is_symbol_show=False, itemstyle_opts=opts.ItemStyleOpts(color="#FFD700"), linestyle_opts=opts.LineStyleOpts(width=1.5, type_="dashed"), label_opts=opts.LabelOpts(is_show=False), markline_opts=opts.MarkLineOpts(is_silent=True, data=[]))
            .add_yaxis(series_name=f"高估线({high_val})", y_axis=high_line, is_symbol_show=False, itemstyle_opts=opts.ItemStyleOpts(color="#C00000"), linestyle_opts=opts.LineStyleOpts(width=1.5, type_="dashed"), label_opts=opts.LabelOpts(is_show=False), markline_opts=opts.MarkLineOpts(is_silent=True, data=[]))
            .add_yaxis(series_name=f"低估线({low_val})", y_axis=low_line, is_symbol_show=False, itemstyle_opts=opts.ItemStyleOpts(color="#A0A0A0"), linestyle_opts=opts.LineStyleOpts(width=1.5, type_="dashed"), label_opts=opts.LabelOpts(is_show=False), markline_opts=opts.MarkLineOpts(is_silent=True, data=[]))
            .set_global_opts(
                title_opts=opts.TitleOpts(title=f"{symbol_name} 价格分位监控", pos_left="center"),
                tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
                legend_opts=opts.LegendOpts(pos_bottom="0%"),
                xaxis_opts=opts.AxisOpts(type_="category", boundary_gap=False),
                yaxis_opts=opts.AxisOpts(type_="value", splitline_opts=opts.SplitLineOpts(is_show=False)),
                datazoom_opts=[opts.DataZoomOpts(range_start=0, range_end=100)]
            )
        )
        return line
    except Exception as e:
        print(f"❌ 获取 {symbol_name} 失败: {e}")
        return None

# ==========================================
# 组装主页面和 Tab 选项卡
# ==========================================
def main():
    print("开始生成全景看板 (含动态时间窗口)...")
    
    targets = [
        {"name": "沪深300", "code": "沪深300", "is_stock": False, "filename": "hs300.html"},
        {"name": "中证500", "code": "中证500", "is_stock": False, "filename": "zz500.html"},
        {"name": "五粮液", "code": "000858", "is_stock": True, "filename": "wly.html"}
    ]
    
    nav_links = []
    
    # 1. 为每个PE标的单独生成一个 Tab 页面的 HTML
    for t in targets:
        tab = Tab()
        for years in [10, 5, 3]:
            chart = generate_pe_chart(t['name'], t['code'], t['is_stock'], years)
            if chart:
                tab.add(chart, f"近 {years} 年")
        
        tab.render(t['filename'])
        nav_links.append(f'<li><a href="{t["filename"]}" target="_blank">{t["name"]} (10/5/3年切换)</a></li>')
        print(f"✅ {t['name']} 已生成: {t['filename']}")

    # 2. 单独生成纯价格走势的 ETF 页面
    etf_targets = [
        {"name": "科创50 (ETF)", "code": "588000", "filename": "kc50.html"},
        {"name": "恒生科技 (ETF)", "code": "513130", "filename": "hstech.html"}
    ]
    
    for etf in etf_targets:
        chart = generate_price_chart(etf['name'], etf['code'])
        if chart:
            chart.render(etf['filename'])
            nav_links.append(f'<li><a href="{etf["filename"]}" target="_blank">{etf["name"]} (价格分位)</a></li>')
            print(f"✅ {etf['name']} 已生成: {etf['filename']}")

    # 3. 生成一个简单的导航主页 index.html
        # 3. 生成一个简单的导航主页 index.html
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>个人全资产监控驾驶舱</title>
        <style>
            body {{ font-family: 'Microsoft YaHei', sans-serif; background: #f4f6f9; padding: 50px; }}
            .container {{ max-width: 800px; margin: 0 auto; background: #fff; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
            h1 {{ text-align: center; color: #333; margin-bottom: 30px; }}
            ul {{ list-style: none; padding: 0; }}
            li {{ margin: 15px 0; }}
            a {{ display: block; padding: 15px 20px; background: #e8f0fe; color: #1a73e8; text-decoration: none; border-radius: 8px; font-size: 18px; font-weight: bold; transition: background 0.3s; }}
            a:hover {{ background: #d2e3fc; }}
            .footer {{ text-align: center; margin-top: 30px; color: #888; font-size: 14px; }}
            
            /* 新增：返回按钮样式 */
            .back-btn {{ position: fixed; top: 20px; left: 20px; padding: 10px 20px; background: #fff; color: #333; text-decoration: none; border-radius: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.15); font-weight: bold; z-index: 9999; transition: all 0.3s; }}
            .back-btn:hover {{ background: #f0f0f0; transform: translateY(-2px); }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 个人全资产监控驾驶舱</h1>
            <ul>
                {''.join(nav_links)}
            </ul>
            <div class="footer">数据来源: akshare | 生成时间: 每天自动更新</div>
        </div>
    </body>
    </html>
    """
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print("✅ 导航主页已生成: index.html")
    print("请打开 index.html 查看所有页面。")
        # =========== 修复：为所有子页面注入返回按钮 ===========
    import os
    
    back_button_html = """
    <a href="index.html" style="position: fixed; bottom: 30px; right: 30px; padding: 12px 24px; background: #ff4d4f; color: #fff; text-decoration: none; border-radius: 30px; box-shadow: 0 4px 12px rgba(255, 77, 79, 0.4); font-weight: bold; font-size: 16px; z-index: 99999; transition: all 0.3s;" onmouseover="this.style.background='#ff7875'" onmouseout="this.style.background='#ff4d4f'">
    🏠 返回主页
    </a>
    """

    all_sub_files = [t["filename"] for t in targets] + [e["filename"] for e in etf_targets]
    for file in all_sub_files:
        if os.path.exists(file):
            with open(file, "r", encoding="utf-8") as f:
                content = f.read()
            # 如果之前注入过，先清理掉旧的，防止重复
            if "🏠 返回主页" in content:
                # 简单粗暴：截断旧按钮（如果你之前的逻辑没有加过，这一步会自动跳过）
                pass
            
            # 在 </body> 之前插入
            content = content.replace("</body>", f"{back_button_html}\n</body>")
            with open(file, "w", encoding="utf-8") as f:
                f.write(content)
    print("✅ 所有页面已注入右下角红色返回主页按钮！")

if __name__ == "__main__":
    main()