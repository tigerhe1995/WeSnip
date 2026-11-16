# -*- coding: utf-8 -*-
"""生成 WeSnip 图标：微信绿圆角底 + 白色虚线选框 + 光标箭头"""
from PIL import Image, ImageDraw

S = 8                       # 超采样
size = 256
big = size * S
img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
u = big / size

# 圆角底（微信绿）
d.rounded_rectangle([8 * u, 8 * u, 248 * u, 248 * u], radius=52 * u,
                    fill=(7, 193, 96, 255))

# 白色虚线选框
d.rounded_rectangle([52 * u, 56 * u, 196 * u, 172 * u], radius=10 * u,
                    outline=(255, 255, 255, 255), width=int(9 * u))
# 四角实心小方块（控制点）
for cx, cy in [(52, 56), (196, 56), (52, 172), (196, 172)]:
    d.rectangle([(cx - 9) * u, (cy - 9) * u, (cx + 9) * u, (cy + 9) * u],
                fill=(255, 255, 255, 255))

# 光标箭头（右下）
arrow = [(150, 138), (150, 218), (172, 197), (188, 226), (205, 217), (189, 189), (218, 188)]
d.polygon([(x * u, y * u) for x, y in arrow], fill=(255, 255, 255, 255),
          outline=(7, 120, 70, 255), width=int(4 * u))

img = img.resize((size, size), Image.LANCZOS)
img.save("WeSnip.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48),
                              (32, 32), (24, 24), (16, 16)])
print("ico saved")
