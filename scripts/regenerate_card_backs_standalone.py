#!/usr/bin/env python3
"""重新生成卡背，使用正确的人物名作为主标题（独立版本，无数据库依赖）"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# 从 fill_cards_from_source.py 复制的完整配置
CARD_CONFIG = [
    # === 普通 (12) ===
    (1, "羊角酒馆的甜酿师／玛卡巴卡.jpg", "common", "羊角酒馆的甜酿师", "玛卡巴卡"),
    (2, "月蓝狼契／熊猫.jpg", "common", "月蓝狼契", "熊猫"),
    (3, "血月霜羽术士／莹.jpg", "common", "血月霜羽术士", "莹"),
    (6, "墓园蓝焰骑士／匠爱.jpg", "common", "墓园蓝焰骑士", "匠爱"),
    (7, "月下触魂妖／唯.jpg", "common", "月下触魂妖", "唯"),
    (9, "灵灯炼金师／小岛.jpg", "common", "灵灯炼金师", "小岛"),
    (10, "晴穹弦歌者／小林.jpg", "common", "晴穹弦歌者", "小林"),
    (11, "龙骸余烬侍女／月落.jpg", "common", "龙骸余烬侍女", "月落"),
    (12, "赤潮回旋女巫／江祁.jpg", "common", "赤潮回旋女巫", "江祁"),
    (13, "金瞳酒窖游荡者／睦头人.jpg", "common", "金瞳酒窖游荡者", "睦头人"),
    (14, "寒星秘仪导师／饼干.jpg", "common", "寒星秘仪导师", "饼干"),
    (27, "霜刃酒歌剑士／霜寒.jpg", "common", "霜刃酒歌剑士", "霜寒"),
    # === 稀有 (11) ===
    (4, "月灯蜜誓／nim&萤.jpg", "rare", "月灯蜜誓", "nim&萤"),
    (5, "赤喉龙灾下的远征／cz&克兰.jpg", "rare", "赤喉龙灾下的远征", "cz&克兰"),
    (15, "绯樱狐巫／月绪.jpg", "rare", "绯樱狐巫", "月绪"),
    (16, "星渊蓝焰术士／星林.jpg", "rare", "星渊蓝焰术士", "星林"),
    (17, "霓虹酒窖魅影／染水.jpg", "rare", "霓虹酒窖魅影", "染水"),
    (18, "云上百花猎手／苏彍.jpg", "rare", "云上百花猎手", "苏彍"),
    (19, "锁链圣痕天使／墨雪.jpg", "rare", "锁链圣痕天使", "墨雪"),
    (20, "静默白袍牧师／辞白.jpg", "rare", "静默白袍牧师", "辞白"),
    (21, "倒悬囚笼的献祭者／熙饯.jpg", "rare", "倒悬囚笼的献祭者", "熙饯"),
    (22, "冰晶秘典师／米拉.jpg", "rare", "冰晶秘典师", "米拉"),
    (23, "深海宝箱怪／麟鲤.jpg", "rare", "深海宝箱怪", "麟鲤"),
    # === 史诗 (6) ===
    (8, "千眼玻璃囚徒／唯.jpg", "epic", "千眼玻璃囚徒", "唯"),
    (24, "熔脉斩首者／雪大王.jpg", "epic", "熔脉斩首者", "雪大王"),
    (25, "赤晶锁座女王／迦百璃.jpg", "epic", "赤晶锁座女王", "迦百璃"),
    (26, "焚心赤刃魔女／莉莉娅.jpg", "epic", "焚心赤刃魔女", "莉莉娅"),
    (28, "三相幻胶／梦&五&蕾米莉亚.jpg", "epic", "三相幻胶", "梦&五&蕾米莉亚"),
    (29, "翡翠星矢德鲁伊／玲.jpg", "epic", "翡翠星矢德鲁伊", "玲"),
    # === 传说 (3) ===
    (30, "暗炉三人密会／玛卡&熊猫&萤.jpg", "legendary", "暗炉三人密会", "玛卡&熊猫&萤"),
    (31, "血月亡军统领／简拉基茨德.jpg", "legendary", "血月亡军统领", "简拉基茨德"),
    (32, "倒悬霜翼／寒酥.jpg", "legendary", "倒悬霜翼", "寒酥"),
]


def generate_card_back(character_name: str, season_name: str = "龙与地下城") -> Image.Image:
    """生成个性化卡背，主标题=人物名，副标题=赛季名"""
    # 加载卡背模板
    back_template = Image.open("/kmua/data/cards/card_back_template.png").convert("RGBA")
    draw = ImageDraw.Draw(back_template)

    # 字体设置
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 72)
        subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 36)
    except:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()

    # 获取图片尺寸
    width, height = back_template.size

    # 绘制主标题（人物名） - 居中靠上
    title_bbox = draw.textbbox((0, 0), character_name, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (width - title_width) // 2
    title_y = height // 3

    # 添加文字阴影效果
    shadow_offset = 3
    draw.text((title_x + shadow_offset, title_y + shadow_offset), character_name,
              font=title_font, fill=(0, 0, 0, 180))
    draw.text((title_x, title_y), character_name,
              font=title_font, fill=(255, 255, 255, 255))

    # 绘制副标题（赛季名） - 居中靠下
    subtitle_text = f"—— {season_name} ——"
    subtitle_bbox = draw.textbbox((0, 0), subtitle_text, font=subtitle_font)
    subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
    subtitle_x = (width - subtitle_width) // 2
    subtitle_y = height * 2 // 3

    draw.text((subtitle_x + shadow_offset // 2, subtitle_y + shadow_offset // 2),
              subtitle_text, font=subtitle_font, fill=(0, 0, 0, 150))
    draw.text((subtitle_x, subtitle_y), subtitle_text,
              font=subtitle_font, fill=(220, 220, 220, 255))

    return back_template.convert("RGB")


def main():
    season_id = 1
    season_dir = Path(f"/kmua/data/cards/season_{season_id}")
    season_dir.mkdir(parents=True, exist_ok=True)

    print(f"正在为赛季 {season_id} 重新生成 {len(CARD_CONFIG)} 张个性化卡背...")

    for card_number, source_filename, rarity, card_name, character_name in CARD_CONFIG:
        # 生成卡背
        back_img = generate_card_back(character_name, "龙与地下城")
        back_path = season_dir / f"card_{card_number:02d}_back.png"
        back_img.save(back_path, "PNG")

        print(f"✅ card_{card_number:02d}_back.png - {character_name} ({card_name})")

    print("\n✨ 所有卡背重新生成完成！")


if __name__ == "__main__":
    main()
