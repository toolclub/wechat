"""
PPT HTML 预览生成器 — 将 slide JSON 转为 HTML 页面（每页一个 HTML 字符串）

用于前端 iframe 预览，不需要安装 LibreOffice。
"""
from ppt.themes import get_theme


def generate_slides_html(ppt_data: dict) -> list[str]:
    """将 PPT JSON 转为 HTML 字符串列表（每页一个），供前端 iframe 渲染。"""
    theme_name = ppt_data.get("theme", "tech_blue")
    theme = get_theme(theme_name)
    c = theme.colors
    slides = ppt_data.get("slides", [])

    result = []
    for i, slide in enumerate(slides):
        layout = slide.get("layout", "content")
        html = _render_slide(slide, layout, c, theme)
        result.append(html)
    return result


def _base_style(c) -> str:
    return f"""
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{
        width:100%; height:100vh; overflow:hidden;
        background:{c.bg}; color:{c.text};
        font-family:'Microsoft YaHei','PingFang SC','Helvetica Neue',sans-serif;
        display:flex; flex-direction:column; justify-content:center;
        padding:40px 60px;
    }}
    h1 {{ color:{c.primary}; font-size:32px; font-weight:700; line-height:1.3; margin-bottom:16px; }}
    h2 {{ color:{c.primary}; font-size:24px; font-weight:600; line-height:1.3; margin-bottom:12px; }}
    .subtitle {{ color:{c.secondary}; font-size:18px; margin-top:8px; }}
    .accent-line {{ width:80px; height:4px; background:{c.accent}; border-radius:2px; margin:12px 0 20px; }}
    ul {{ list-style:none; padding:0; }}
    ul li {{ padding:8px 0 8px 20px; font-size:16px; color:{c.text}; position:relative; line-height:1.6; }}
    ul li::before {{ content:''; position:absolute; left:0; top:16px; width:8px; height:8px; border-radius:50%; background:{c.accent}; }}
    .page-num {{ position:fixed; bottom:16px; right:24px; font-size:11px; color:{c.text_light}; }}
    """


def _render_slide(slide: dict, layout: str, c, theme) -> str:
    renderers = {
        "title": _render_title,
        "content": _render_content,
        "two_column": _render_two_column,
        "image_text": _render_image_text,
        "chart": _render_chart,
        "quote": _render_quote,
        "ending": _render_ending,
    }
    fn = renderers.get(layout, _render_content)
    body = fn(slide, c)
    return f"<!DOCTYPE html><html><head><style>{_base_style(c)}</style></head><body>{body}</body></html>"


def _render_title(s, c) -> str:
    title = s.get("title", "")
    subtitle = s.get("subtitle", "")
    return f"""
    <div style="text-align:left;">
        <h1 style="font-size:40px;">{title}</h1>
        <div class="accent-line"></div>
        {f'<div class="subtitle">{subtitle}</div>' if subtitle else ''}
    </div>"""


def _render_content(s, c) -> str:
    title = s.get("title", "")
    bullets = s.get("bullets", [])
    items = "".join(f"<li>{b}</li>" for b in bullets)
    return f"""
    <h2>{title}</h2>
    <div class="accent-line"></div>
    <ul>{items}</ul>"""


def _render_two_column(s, c) -> str:
    title = s.get("title", "")
    left = s.get("left", {})
    right = s.get("right", {})
    lh = left.get("heading", "")
    rh = right.get("heading", "")
    lb = "".join(f"<li>{b}</li>" for b in left.get("bullets", []))
    rb = "".join(f"<li>{b}</li>" for b in right.get("bullets", []))
    return f"""
    <h2>{title}</h2>
    <div class="accent-line"></div>
    <div style="display:flex;gap:40px;margin-top:10px;">
        <div style="flex:1;">
            <h3 style="color:{c.accent};font-size:18px;margin-bottom:10px;">{lh}</h3>
            <ul>{lb}</ul>
        </div>
        <div style="flex:1;">
            <h3 style="color:{c.accent};font-size:18px;margin-bottom:10px;">{rh}</h3>
            <ul>{rb}</ul>
        </div>
    </div>"""


def _render_image_text(s, c) -> str:
    title = s.get("title", "")
    text = s.get("text", "")
    prompt = s.get("image_prompt", "图片")
    return f"""
    <h2>{title}</h2>
    <div class="accent-line"></div>
    <div style="display:flex;gap:30px;margin-top:10px;">
        <div style="flex:1;background:{c.accent}11;border:2px dashed {c.accent}44;border-radius:12px;display:flex;align-items:center;justify-content:center;min-height:200px;">
            <span style="color:{c.text_light};font-size:14px;">[{prompt}]</span>
        </div>
        <div style="flex:1;font-size:16px;line-height:1.8;color:{c.text};">{text}</div>
    </div>"""


def _render_chart(s, c) -> str:
    title = s.get("title", "")
    cd = s.get("chart_data", {})
    cats = cd.get("categories", [])
    series = cd.get("series", [])
    if not cats or not series:
        return f"<h2>{title}</h2><div class='accent-line'></div><p style='color:{c.text_light};'>图表数据不足</p>"
    # 简单柱形图 HTML
    vals = series[0].get("values", []) if series else []
    max_v = max(vals) if vals else 1
    bars = ""
    for j, cat in enumerate(cats):
        v = vals[j] if j < len(vals) else 0
        h = int(v / max_v * 160) if max_v else 0
        bars += f"""<div style="display:flex;flex-direction:column;align-items:center;gap:6px;">
            <div style="width:40px;height:{h}px;background:{c.accent};border-radius:4px 4px 0 0;"></div>
            <span style="font-size:11px;color:{c.text_light};">{cat}</span>
            <span style="font-size:12px;font-weight:600;color:{c.text};">{v}</span>
        </div>"""
    return f"""
    <h2>{title}</h2>
    <div class="accent-line"></div>
    <div style="display:flex;align-items:flex-end;gap:20px;justify-content:center;margin-top:20px;padding:20px;">{bars}</div>"""


def _render_quote(s, c) -> str:
    quote = s.get("quote", s.get("text", ""))
    author = s.get("author", "")
    return f"""
    <div style="text-align:center;padding:40px 60px;">
        <span style="font-size:64px;color:{c.accent};line-height:1;">\u201C</span>
        <p style="font-size:22px;line-height:1.8;color:{c.text};margin:10px 0 20px;">{quote}</p>
        {f'<p style="color:{c.secondary};font-size:16px;">—— {author}</p>' if author else ''}
    </div>"""


def _render_ending(s, c) -> str:
    title = s.get("title", "Thanks")
    subtitle = s.get("subtitle", "")
    return f"""
    <div style="text-align:center;">
        <div class="accent-line" style="width:100px;margin:0 auto 20px;"></div>
        <h1 style="font-size:44px;">{title}</h1>
        {f'<div class="subtitle" style="margin-top:12px;">{subtitle}</div>' if subtitle else ''}
    </div>"""
