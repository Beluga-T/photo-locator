"""The geolocation analyst prompt and the JSON schema its answer must fit."""

from __future__ import annotations

EVIDENCE_CATEGORIES = [
    "地形地貌",
    "植被",
    "建筑风格",
    "道路与交通",
    "文字与标识",
    "车辆与车牌",
    "气候与光照",
    "基础设施",
    "人文与服饰",
    "其他",
]

SYSTEM_PROMPT = """\
你是一名图像地理定位分析师，兼具 OSINT（公开来源情报）调查员与顶级 GeoGuessr 选手的能力。
给你一张照片，你的唯一任务是判断这张照片拍摄于世界上的哪个位置，并说明你是怎么推断出来的。

# 分析方法

按下面的顺序逐项检视画面，不要跳过任何一类线索：

1. 地形与植被：山形、海岸线、土壤颜色、树种、作物、草木的季相与干湿。这些能把范围缩到大洲和气候带。
2. 建筑：屋顶形制与材料、窗户比例、外墙饰面、阳台与防盗窗、电线入户方式、宗教建筑样式。
3. 道路与交通：靠左还是靠右行驶、车道线颜色与虚实、路缘石与护栏样式、信号灯的悬挂方式、人行道铺装、防撞柱造型。
4. 文字与标识：任何可见的文字——招牌、路牌、车身广告、涂鸦、包装。识别语言与文字系统，并尽量直接读出地名、电话区号、域名后缀、邮政编码。这是最强的单一线索。
5. 车辆与车牌：车牌底色与长宽比、常见车型与品牌在各地区的分布、出租车涂装、公交车样式。
6. 基础设施：电线杆材质与横担形状、变压器、路灯灯头、井盖、消防栓、垃圾桶、公交站牌。这些在各国高度定型化。
7. 光照与天象：阴影方向与长度可推断半球、大致纬度与季节时刻；天空色温、雾霾、云型。
8. 人文细节：服饰、肤色构成、店铺业态、商品价格与货币符号。

# 精度纪律（最重要的一条）

**只回答你的证据能撑住的层级，撑不住的层级就不要回答。** 宁可少说，不要编。

- 从大到小逐级收敛：国家 → 一级行政区（州 / 省 / 大区）→ 城市 → 具体街区或地标。
- 每往下走一级，都要先问自己：画面里有没有具体的东西支撑这一级？如果只是"看起来像"、"这类地方通常在"，那就是撑不住，停在上一级。
- 撑不住的层级，name_zh 和 name_en 一律填「未确定」和空字符串，**不要填一个最可能的猜测**。宁可只给出国家，也不要给一个随手编的城市。
  - 例：只能从植被和电线杆判断这是巴西，但没有任何城市线索 —— country 填巴西，region 和 city 都填「未确定」，precision 填 country。
  - 例：读到了路牌上的街道名并确认了城市 —— 四级全填，precision 填 locality。
- precision 是输出的第一个字段：先定层级，再写名称。它必须如实标出你实际能确定到的最细层级：country / region / city / locality，并与随后各级名称的填写情况一致——填了「未确定」的层级，不能出现在 precision 里；比 precision 更细的层级，一律填「未确定」。
- 唯一的下限：**国家一级必须给出判断**，不允许整体回答"无法判断"或"信息不足"。如果连国家都很不确定，仍然给出最可能的国家，但把 confidence 压到 30 以下，并在 alternatives 里放上其他候选国家。

# 其他纪律

- 区分"看到了什么"和"由此推出什么"。observation 只写画面里客观存在的东西，implication 才写它指向哪里、为什么。
- 若某条线索与你的结论相矛盾，把它写进 evidence 并说明你为何仍维持结论，不要隐藏矛盾证据。
- coordinates 给出你所确定的最细层级的中心坐标，radius_km 必须诚实反映 precision：locality 用 1–5，city 用 10–50，region 用 100–400，country 用能覆盖该国主体的半径（几百到两千公里）。不要用一个小半径去伪装成高精度。
- confidence 是 0–100 的整数，指"**precision 所标层级的判断正确**"的把握 —— 不是城市级，而是你自己声明的那一级。90 以上表示读到了明确地名或认出确切地标；60–89 表示多条独立线索互相印证；30–59 表示只能靠风格与环境判断；30 以下表示基本靠猜。confidence_band 与之保持一致（high ≥ 70，medium 40–69，low < 40）。
- evidence 给 4–8 条，按证据强度从高到低排列。alternatives 给 2–3 个备选，粒度与 precision 一致（若 precision 是 country，备选就给不同国家，city 字段留空），likelihood 之和不必等于 100。

# 边界

- 只对地点作判断。不要识别、命名或推测照片中任何个人的身份、职业或住址；如果画面主体是人物，就分析其背景环境。
- 名称字段中文与英文都要填。地名没有通行中文译名时，用音译并在括号内保留原文。
- 所有叙述性文字用简体中文，简洁、具体、不用套话。

只输出符合给定 JSON schema 的结果，不要输出任何额外说明。
"""

USER_INSTRUCTION = """\
分析这张照片，判断它拍摄于哪里。
在证据允许的范围内尽可能精确：能定到街区就定到街区，只能定到国家就只给国家。
先在 precision 里如实标出你实际确定到了哪一级，再逐级填写名称；撑不住的层级填「未确定」。
按 JSON schema 输出你的判断、推理依据和备选地点。
"""


PRECISION_LEVELS = ["country", "region", "city", "locality"]


def _place(label: str) -> dict:
    return {
        "type": "object",
        "description": f"{label}。证据撑不住这一级时，name_zh 填「未确定」、name_en 填空字符串，不要猜。",
        "properties": {
            "name_zh": {"type": "string", "description": f"{label}的中文名"},
            "name_en": {"type": "string", "description": f"{label}的英文名或当地拉丁转写"},
        },
        "required": ["name_zh", "name_en"],
        "additionalProperties": False,
    }


RESULT_SCHEMA: dict = {
    "type": "object",
    # Property order is wire order: constrained decoding emits the properties in
    # the order they are declared here, and the streaming path shows each one the
    # moment it closes. That is why `precision` comes first.
    #
    # It used to sit fifth, after locality, and the measured cost was a visible
    # walk-back: on a real run the model wrote a country at 7.0s, a city and a
    # street at 7.8s, and only at 8.5s admitted it had only reached city level —
    # so the page had to un-say a street name it had already painted. Declaring
    # the cap first costs the model nothing, because it has finished thinking
    # before it writes its first character (6.3s of that run), and it lets the
    # client hold every later name to a level it already knows.
    #
    # `required` below is left in the old order on purpose: JSON Schema treats it
    # as a set, so it has no effect on what the model emits.
    "properties": {
        "precision": {
            "type": "string",
            "enum": PRECISION_LEVELS,
            "description": "本对象的第一个字段：先声明你实际能确定到的最细层级，再往下填名称。"
            "比它更细的层级一律填「未确定」，填了「未确定」的层级也不能出现在这里。",
        },
        "country": _place("国家"),
        "region": _place("一级行政区，如州、省、大区"),
        "city": _place("城市或最接近的城镇"),
        "locality": {
            "type": "string",
            "description": "更具体的街区、道路、地标或景点名称；撑不住这一级时填空字符串，不要猜。",
        },
        "coordinates": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "纬度，-90 到 90"},
                "lon": {"type": "number", "description": "经度，-180 到 180"},
                "radius_km": {
                    "type": "number",
                    "description": "该坐标的可信半径，单位公里，必须与 precision 一致："
                    "locality 用 1–5，city 用 10–50，region 用 100–400，country 用几百到两千。",
                },
            },
            "required": ["lat", "lon", "radius_km"],
            "additionalProperties": False,
        },
        "confidence": {
            "type": "integer",
            "description": "precision 所标层级的判断正确的把握，0–100 的整数",
        },
        "confidence_band": {"type": "string", "enum": ["high", "medium", "low"]},
        "summary": {
            "type": "string",
            "description": "一到两句话说明结论和最关键的依据。",
        },
        "evidence": {
            "type": "array",
            "description": "4–8 条推理依据，按证据强度从高到低排列。",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": EVIDENCE_CATEGORIES},
                    "observation": {"type": "string", "description": "画面中客观看到的细节"},
                    "implication": {"type": "string", "description": "该细节指向什么地区，为什么"},
                    "weight": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["category", "observation", "implication", "weight"],
                "additionalProperties": False,
            },
        },
        "alternatives": {
            "type": "array",
            "description": "2–3 个备选地点。",
            "items": {
                "type": "object",
                "properties": {
                    "country": {"type": "string"},
                    "region": {"type": "string"},
                    "city": {"type": "string"},
                    "likelihood": {"type": "integer", "description": "该备选成立的可能性，0–100"},
                    "reason": {"type": "string", "description": "为什么它也说得通，以及被排在后面的原因"},
                },
                "required": ["country", "region", "city", "likelihood", "reason"],
                "additionalProperties": False,
            },
        },
        "notes": {
            "type": "string",
            "description": "对结论的补充说明或需要提醒用户的局限；没有则填空字符串。",
        },
    },
    # Unordered by definition — see the note above "properties". Every property
    # is listed, because a structured-output schema with an optional field lets
    # the model omit it and the renderer has no shape to fall back on.
    "required": [
        "country",
        "region",
        "city",
        "locality",
        "precision",
        "coordinates",
        "confidence",
        "confidence_band",
        "summary",
        "evidence",
        "alternatives",
        "notes",
    ],
    "additionalProperties": False,
}


# --------------------------------------------------------------------- self-check

if __name__ == "__main__":
    # python -m app.prompt
    import json

    order = list(RESULT_SCHEMA["properties"])
    print("property order:", " → ".join(order))

    # The whole point of the reordering: the client learns the cap before any
    # name it governs arrives, so it never has to walk a headline backwards.
    assert order[0] == "precision", order
    for finer in ("country", "region", "city", "locality"):
        assert order.index("precision") < order.index(finer), (finer, order)
    print("  ok  precision leads every level it caps")

    # `required` is a set, so its order may differ — its membership may not.
    assert set(RESULT_SCHEMA["required"]) == set(order), set(order) ^ set(RESULT_SCHEMA["required"])
    assert RESULT_SCHEMA["additionalProperties"] is False
    print(f"  ok  all {len(order)} properties required, no extras allowed")

    assert RESULT_SCHEMA["properties"]["precision"]["enum"] == PRECISION_LEVELS
    assert PRECISION_LEVELS == ["country", "region", "city", "locality"]  # coarsest first
    print("  ok  precision enum is PRECISION_LEVELS, coarsest first")

    # Both provider paths json.dumps this schema into a request body.
    encoded = json.dumps(RESULT_SCHEMA, ensure_ascii=False)
    assert '"precision"' in encoded
    assert encoded.index('"precision"') < encoded.index('"country"'), "dumps lost the order"
    print(f"  ok  survives json.dumps in order ({len(encoded)} chars)")

    for label, text in (("SYSTEM_PROMPT", SYSTEM_PROMPT), ("USER_INSTRUCTION", USER_INSTRUCTION)):
        assert "precision" in text and "未确定" in text, label
        assert text.endswith("\n"), label
    # The prompt must not still describe precision as something written last.
    assert "上面各字段" not in SYSTEM_PROMPT, "SYSTEM_PROMPT still says precision comes after the names"
    print("  ok  prompts agree that precision is declared first")

    assert len(EVIDENCE_CATEGORIES) == len(set(EVIDENCE_CATEGORIES))
    assert RESULT_SCHEMA["properties"]["evidence"]["items"]["properties"]["category"]["enum"] == (
        EVIDENCE_CATEGORIES
    )
    print(f"  ok  {len(EVIDENCE_CATEGORIES)} evidence categories, no duplicates")

    print("\nself-check ok")
