"""
PPT 脚本生成器 — 生成可在沙箱中独立运行的 Python 渲染脚本

HTML-first 方案：
  1. 每页 HTML 用 base64 编码嵌入脚本（避免引号/转义问题）
  2. 使用 Playwright 截图每页 HTML（960x720）
  3. 将截图嵌入 PPT 幻灯片（全页铺满）
  4. Playwright 不可用时自动降级为 python-pptx 文本渲染

兼容旧方案（generate_render_script）保留。
"""
import json
import base64

from ppt.themes import get_theme


def generate_html_render_script(slides_html: list[str], output_filename: str) -> str:
    """
    生成 HTML→截图→PPT 的自包含渲染脚本。

    关键：HTML 用 base64 编码后嵌入，彻底避免三引号/转义冲突。
    """
    encoded_slides = []
    for html in slides_html:
        b64 = base64.b64encode(html.encode("utf-8")).decode("ascii")
        encoded_slides.append(b64)
    slides_b64_json = json.dumps(encoded_slides)

    return f'''#!/usr/bin/env python3
"""HTML→截图→PPT 渲染脚本（沙箱执行）"""
import json, base64, os, sys, re

# ── 解码 HTML（base64 编码，避免引号冲突）──
SLIDES_B64 = json.loads('{slides_b64_json}')
SLIDES_HTML = [base64.b64decode(b).decode("utf-8") for b in SLIDES_B64]
OUTPUT = "{output_filename}"

print(f"  📄 共 {{len(SLIDES_HTML)}} 页幻灯片")

# ── 写入 HTML 文件 ──
html_dir = "slide_html"
os.makedirs(html_dir, exist_ok=True)
for i, html in enumerate(SLIDES_HTML):
    path = os.path.join(html_dir, f"slide_{{i}}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ 第 {{i+1}} 页 HTML 已写入")

# ── 尝试 Playwright 截图（效果最好）──
use_playwright = False
try:
    from playwright.sync_api import sync_playwright
    use_playwright = True
except ImportError:
    print("  ⚠️ Playwright 未安装，降级为文本渲染")

if use_playwright:
    print("  📸 正在启动浏览器截图...")
    screenshots = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={{"width": 960, "height": 720}})
        for i in range(len(SLIDES_HTML)):
            html_path = os.path.abspath(os.path.join(html_dir, f"slide_{{i}}.html"))
            page.goto(f"file://{{html_path}}")
            page.wait_for_timeout(500)
            img_path = f"slide_{{i}}.png"
            page.screenshot(path=img_path)
            screenshots.append(img_path)
            print(f"  📸 第 {{i+1}} 页截图完成")
        browser.close()

    print("  📦 正在组装 PPT...")
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)
    for i, img_path in enumerate(screenshots):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_picture(img_path, 0, 0, prs.slide_width, prs.slide_height)
        print(f"  ✅ 第 {{i+1}} 页已嵌入 PPT")
    prs.save(OUTPUT)
    print(f"\\n📊 PPT 已生成: {{OUTPUT}} ({{len(screenshots)}} 页)")

else:
    # ── 降级：从 HTML 提取文本 + python-pptx 渲染 ──
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN

    def strip_tags(html):
        text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.S)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.S)
        text = re.sub(r'<br\\s*/?>|</(?:p|div|h[1-6]|li|tr)>', '\\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'&amp;', '&', text)
        text = re.sub(r'&lt;', '<', text)
        text = re.sub(r'&gt;', '>', text)
        return [l.strip() for l in text.split('\\n') if l.strip()]

    def extract_title(html):
        m = re.search(r'<h[12][^>]*>(.*?)</h[12]>', html, re.S)
        return re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else ""

    def hex2rgb(h):
        h = h.lstrip("#")
        return RGBColor(int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))

    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)

    for i, html in enumerate(SLIDES_HTML):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        bg = slide.background; bg.fill.solid(); bg.fill.fore_color.rgb = RGBColor(255,255,255)
        title = extract_title(html)
        lines = strip_tags(html)
        if title:
            tb = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(8.4), Inches(1))
            tf = tb.text_frame; tf.word_wrap = True
            r = tf.paragraphs[0].add_run(); r.text = title
            r.font.size = Pt(28); r.font.bold = True; r.font.color.rgb = RGBColor(26,115,232)
            r.font.name = "Microsoft YaHei"
        content_lines = [l for l in lines if l != title][:15]
        if content_lines:
            top = Inches(1.6) if title else Inches(0.8)
            tb = slide.shapes.add_textbox(Inches(0.8), top, Inches(8.4), Inches(5.5))
            tf = tb.text_frame; tf.word_wrap = True
            for j, line in enumerate(content_lines):
                p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
                p.space_before = Pt(4); p.space_after = Pt(4)
                r = p.add_run(); r.text = line; r.font.size = Pt(16)
                r.font.name = "Microsoft YaHei"; r.font.color.rgb = RGBColor(51,51,51)
        print(f"  ✅ 第 {{i+1}} 页: {{title or '(无标题)'}}")

    prs.save(OUTPUT)
    print(f"\\n📊 PPT 已生成: {{OUTPUT}} ({{len(SLIDES_HTML)}} 页)")
'''


def generate_render_script(ppt_data: dict, output_filename: str) -> str:
    """旧方案：从结构化 JSON 直接渲染 PPT。"""
    theme_name = ppt_data.get("theme", "tech_blue")
    theme = get_theme(theme_name)
    clean_data = _clean_for_serialization(ppt_data)
    data_json = json.dumps(clean_data, ensure_ascii=False, indent=2)
    colors = {
        "primary": theme.colors.primary, "secondary": theme.colors.secondary,
        "accent": theme.colors.accent, "bg": theme.colors.bg,
        "text": theme.colors.text, "text_light": theme.colors.text_light,
    }
    colors_json = json.dumps(colors)

    return f'''#!/usr/bin/env python3
"""PPT 渲染脚本（结构化 JSON 方案）"""
import json, sys
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.chart import XL_CHART_TYPE

PPT_DATA = json.loads("""{data_json}""")
COLORS = json.loads('{colors_json}')
TITLE_FONT = "{theme.title_font}"
BODY_FONT = "{theme.body_font}"
OUTPUT = "{output_filename}"

def hex2rgb(h):
    h = h.lstrip("#"); return RGBColor(int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))
def add_textbox(slide, left, top, w, h, text, size=18, color="", bold=False, align=PP_ALIGN.LEFT, font=""):
    tb = slide.shapes.add_textbox(left, top, w, h); tf = tb.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; p.alignment = align; r = p.add_run(); r.text = text; r.font.size = Pt(size)
    r.font.bold = bold; r.font.name = font or BODY_FONT
    if color: r.font.color.rgb = hex2rgb(color)
    return tb
def add_bullets(slide, left, top, w, h, items, size=16, color=""):
    tb = slide.shapes.add_textbox(left, top, w, h); tf = tb.text_frame; tf.word_wrap = True
    c = color or COLORS["text"]
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_before = Pt(6); p.space_after = Pt(4); r = p.add_run()
        r.text = "  " + str(item); r.font.size = Pt(size); r.font.name = BODY_FONT; r.font.color.rgb = hex2rgb(c)
def accent_line(slide, left, top, w):
    s = slide.shapes.add_shape(1, left, top, w, Pt(3)); s.fill.solid()
    s.fill.fore_color.rgb = hex2rgb(COLORS["accent"]); s.line.fill.background()
def set_bg(slide, color=""):
    fill = slide.background.fill; fill.solid(); fill.fore_color.rgb = hex2rgb(color or COLORS["bg"])
def blank(prs): return prs.slides.add_slide(prs.slide_layouts[6])

def render_title(prs, d):
    s = blank(prs); set_bg(s); accent_line(s, Inches(1.5), Inches(3.2), Inches(3))
    add_textbox(s, Inches(1.5), Inches(1.8), Inches(7), Inches(1.5), d.get("title",""), size=36, bold=True, color=COLORS["primary"], font=TITLE_FONT)
    if d.get("subtitle"): add_textbox(s, Inches(1.5), Inches(3.5), Inches(7), Inches(0.8), d["subtitle"], size=18, color=COLORS["secondary"])
def render_content(prs, d):
    s = blank(prs); set_bg(s)
    add_textbox(s, Inches(0.8), Inches(0.4), Inches(8.4), Inches(0.8), d.get("title",""), size=28, bold=True, color=COLORS["primary"], font=TITLE_FONT)
    accent_line(s, Inches(0.8), Inches(1.15), Inches(1.5))
    if d.get("bullets"): add_bullets(s, Inches(0.8), Inches(1.5), Inches(8.4), Inches(5), d["bullets"], size=18)
def render_quote(prs, d):
    s = blank(prs); set_bg(s); q = d.get("quote", d.get("text",""))
    add_textbox(s, Inches(1.5), Inches(1.5), Inches(1), Inches(1), "\\u201C", size=72, color=COLORS["accent"], bold=True)
    add_textbox(s, Inches(1.5), Inches(2.5), Inches(7), Inches(2.5), q, size=24, color=COLORS["text"])
    if d.get("author"): add_textbox(s, Inches(1.5), Inches(5.2), Inches(7), Inches(0.5), "—— "+d["author"], size=16, color=COLORS["secondary"], align=PP_ALIGN.RIGHT)
def render_ending(prs, d):
    s = blank(prs); set_bg(s); accent_line(s, Inches(3.5), Inches(3), Inches(3))
    add_textbox(s, Inches(1), Inches(2), Inches(8), Inches(1), d.get("title","Thanks"), size=44, bold=True, color=COLORS["primary"], font=TITLE_FONT, align=PP_ALIGN.CENTER)
    if d.get("subtitle"): add_textbox(s, Inches(1), Inches(3.3), Inches(8), Inches(0.6), d["subtitle"], size=16, color=COLORS["secondary"], align=PP_ALIGN.CENTER)

RENDERERS = {{"title": render_title, "content": render_content, "quote": render_quote, "ending": render_ending}}
prs = Presentation(); prs.slide_width = Inches(10); prs.slide_height = Inches(7.5)
for i, sd in enumerate(PPT_DATA.get("slides", [])):
    fn = RENDERERS.get(sd.get("layout","content"), render_content)
    try: fn(prs, sd); print(f"  ✅ 第 {{i+1}} 页: {{sd.get('title','')}} ({{sd.get('layout','content')}})")
    except Exception as e: print(f"  ⚠️ 第 {{i+1}} 页失败: {{e}}"); render_content(prs, {{"title":"渲染失败","bullets":[str(e)]}})
prs.save(OUTPUT); print(f"\\n📊 PPT 已生成: {{OUTPUT}}")
'''


def _clean_for_serialization(data: dict) -> dict:
    clean = {}
    for k, v in data.items():
        if isinstance(v, bytes): continue
        if isinstance(v, dict): clean[k] = _clean_for_serialization(v)
        elif isinstance(v, list):
            clean[k] = [_clean_for_serialization(i) if isinstance(i, dict) else i for i in v if not isinstance(i, bytes)]
        else: clean[k] = v
    return clean
