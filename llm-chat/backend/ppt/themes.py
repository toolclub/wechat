"""
PPT 主题配置 — 预设配色 + 字体方案
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeColors:
    primary: str        # 主色（标题、强调）
    secondary: str      # 辅色（副标题）
    accent: str         # 点缀色（图标、装饰线）
    bg: str             # 背景色
    text: str           # 正文色
    text_light: str     # 浅文字（备注、辅助）


@dataclass(frozen=True)
class Theme:
    name: str
    label: str          # 中文名
    colors: ThemeColors
    title_font: str     # 标题字体
    body_font: str      # 正文字体


THEMES: dict[str, Theme] = {
    "tech_blue": Theme(
        name="tech_blue", label="科技蓝",
        colors=ThemeColors(
            primary="#1A73E8", secondary="#5F6368",
            accent="#00AEEC", bg="#FFFFFF",
            text="#202124", text_light="#9AA0A6",
        ),
        title_font="Microsoft YaHei", body_font="Microsoft YaHei",
    ),
    "biz_dark": Theme(
        name="biz_dark", label="商务深色",
        colors=ThemeColors(
            primary="#FFFFFF", secondary="#B0BEC5",
            accent="#FF6D00", bg="#1E1E2E",
            text="#E0E0E0", text_light="#78909C",
        ),
        title_font="Microsoft YaHei", body_font="Microsoft YaHei",
    ),
    "fresh_green": Theme(
        name="fresh_green", label="清新绿",
        colors=ThemeColors(
            primary="#2E7D32", secondary="#66BB6A",
            accent="#81C784", bg="#FFFFFF",
            text="#1B5E20", text_light="#A5D6A7",
        ),
        title_font="Microsoft YaHei", body_font="Microsoft YaHei",
    ),
    "minimal_white": Theme(
        name="minimal_white", label="极简白",
        colors=ThemeColors(
            primary="#18191C", secondary="#61666D",
            accent="#00AEEC", bg="#FFFFFF",
            text="#18191C", text_light="#9499A0",
        ),
        title_font="Microsoft YaHei", body_font="Microsoft YaHei",
    ),
    "bilibili_pink": Theme(
        name="bilibili_pink", label="B站粉蓝",
        colors=ThemeColors(
            primary="#00AEEC", secondary="#FB7299",
            accent="#FB7299", bg="#FFFFFF",
            text="#18191C", text_light="#9499A0",
        ),
        title_font="Microsoft YaHei", body_font="Microsoft YaHei",
    ),
}

DEFAULT_THEME = "tech_blue"


def get_theme(name: str) -> Theme:
    return THEMES.get(name, THEMES[DEFAULT_THEME])
