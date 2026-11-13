"""界面回归：解题助手的引导措辞是否跟着班级提示词的人设走。

缺陷来源：B 班（英语写作课）教师配了自己的提示词，学生问「议论文开头段怎么写」，
收到的引导却是「已知条件是什么」「把公式或定理写出来」——那是数学场景写死的兜底
模板。老师看见保存成功、学生拿到另一套东西，中间断在哪双方都看不见。

判据：同一套 ``local_stream``，换提示词就换措辞；改了提示词时还要如实说明
「这是通用模板、要接模型才生效」，不能让人以为配置丢了。

运行：``python scripts/check_ui_tutor.py``（不需要数据库、不需要网络）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from campusclaw.tutor import guide_domain, local_stream  # noqa: E402
from campusclaw.tutor_db import DEFAULT_PROMPT  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("[PASS] " if ok else "[FAIL] ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


ENGLISH_PROMPT = (
    "你是 B 班英语写作课的辅导助手。学生提问时，先判断问题属于结构、语言还是论据层面："
    "结构问题引导学生对照三段式自查（开头是否亮观点、结尾是否只总结）；"
    "语言问题提示连接词的恰当使用，不要直接替学生改写句子；"
    "论据问题引导学生检验例子与论点的关联。"
)
QUESTION = "议论文的开头段应该怎么写？"
HITS = [
    {
        "title": "英语写作课讲义（B 班）",
        "chunk_index": 0,
        "_chunk_text": "# 第一单元\n## 三段式\n议论文分为开头、主体、结尾；开头段要亮出论点。",
    }
]
GENERIC_SKILL = {"name": "通用解题引导", "subject": "通用", "description": ""}
MATH_SKILL = {"name": "方程解题引导", "subject": "数学", "description": ""}

MATH_WORDS = ("已知条件", "公式", "定理", "审题", "求解")


def render(prompt: str, skill: dict | None, mode: str = "guide") -> str:
    return "".join(
        local_stream(prompt, skill, HITS, QUESTION, {"class_name": "B"}, None, mode)
    )


# 1. 英语人设 → 通用措辞，不出数学词
out_en = render(ENGLISH_PROMPT, GENERIC_SKILL)
check("英语人设判为 general", guide_domain(ENGLISH_PROMPT, GENERIC_SKILL) == "general")
check(
    "英语人设的引导不含数学措辞",
    not any(word in out_en for word in MATH_WORDS),
    "命中：" + "、".join(w for w in MATH_WORDS if w in out_en),
)

# 2. 结构上仍是「复述 → 找讲义 → 自己动笔」三步，不是空话
check("仍是三步引导", all(f"第{n}步" in out_en for n in ("一", "二", "三")))
check("引导指向本班讲义", "本班讲义" in out_en)

# 3. 默认提示词（数学向）保留原有数学措辞，不能反向改坏
out_math = render(DEFAULT_PROMPT, GENERIC_SKILL)
check("默认提示词判为 math", guide_domain(DEFAULT_PROMPT, GENERIC_SKILL) == "math")
check("默认提示词仍给数学措辞", "已知条件" in out_math and "公式或定理" in out_math)

# 4. 人设优先于技能自带学科：技能写「数学」，但班级是英语课
out_mixed = render(ENGLISH_PROMPT, MATH_SKILL)
check(
    "提示词人设优先于技能学科",
    not any(word in out_mixed for word in MATH_WORDS),
    "命中：" + "、".join(w for w in MATH_WORDS if w in out_mixed),
)

# 5. 改过提示词就要说明「这是通用模板」，否则老师以为配好了
check("改过提示词时说明模板来源", "通用引导模板" in out_en)
check("说明里点明要接模型才生效", "接入模型" in out_en or "接模型" in out_en)
check("未改提示词时不加该说明", "通用引导模板" not in out_math)

# 6. 回归：直接回答模式仍清洗 markdown，不把 ## / ** 吐到页面
out_direct = render(ENGLISH_PROMPT, GENERIC_SKILL, mode="direct")
check("直接回答不含 markdown 标题号", "##" not in out_direct and "**" not in out_direct)
check("直接回答说明是原文照录", "原文照录" in out_direct)

print()
print("结果：" + ("全部通过" if not FAILED else f"{len(FAILED)} 项失败"))
raise SystemExit(0 if not FAILED else 1)
