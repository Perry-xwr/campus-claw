"""解题助手生成层：班级提示词 + 技能 + 本班检索结果 → 流式回答。

同一次回答必须同时用上三样输入：教师保存的提示词（规定助手是谁）、命中问题的
已启用技能（规定这一题怎么导）、本班知识库检索片段（提供可回溯的依据）。

生成走 LangChain：提示词用 ``ChatPromptTemplate``（含 ``MessagesPlaceholder`` 承载
多轮历史）组装，配置了 OpenAI 兼容聊天服务时用 ``ChatOpenAI.stream`` 逐段产出；
未配置时用确定性本地回退；设 ``CAMPUSCLAW_TUTOR_STUB=1`` 时换固定响应模型替身
（不发起网络调用，供接口测试离线断言）。三条路径都是流式，并且引导/直接两种模式
结构明显不同，保证无模型环境也能完整演示与验收。
"""

from __future__ import annotations

import re
from typing import Any, Iterator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from campusclaw.retrieval_config import RetrievalConfig
from campusclaw.tutor_db import DEFAULT_PROMPT

#: 技能开启时追加到系统提示的引导约束（解题引导：只给思路，不直接给最终答案）。
SKILL_DIRECTIVE = (
    "【本班技能·{name}（{subject}）】\n{description}\n"
    "执行约束：只给思路和第一步，引用本班材料的标题和位置（用 [编号] 标注），"
    "不得直接给出最终答案；学生卡住时给下一步提示。"
)

#: 有检索命中时追加的引用规则。
CITATION_DIRECTIVE = (
    "【本班资料】下面是检索到的本班材料片段，按 [编号] 引用；"
    "只依据片段内容作答，不得编造片段中不存在的出处；"
    "片段中没有的内容要明说资料中未找到。"
)

#: 无技能时的普通模式说明（与引导模式结构区分）。
DIRECT_DIRECTIVE = (
    "当前没有启用解题引导技能：按常规方式直接回答，"
    "仍然只依据本班资料片段，并用 [编号] 标注依据。"
)

#: 直接回答模式：用户明确要求正面回答时，覆盖技能的「只给思路」约束。
DIRECT_ANSWER_DIRECTIVE = (
    "【本次为直接回答模式】学生要的是明确结论：直接回答问题（数量、名称、结论或"
    "完整的解题结果），用 [编号] 标注依据；资料中没有的内容要明说资料中未找到，"
    "不得编造出处或凭空估算。"
)

IDENTITY_TEMPLATE = (
    "当前用户：{username}（{role_label}），班级：{class_name}。"
    "先确认身份与班级，再开始解题。"
)

#: LangChain 提示词模板：system 由「班级提示词 + 身份 + 技能/直接模式 + 引用规则」
#: 四段拼成；history 占位符承载历史消息；human 携带资料片段与当前问题。
SYSTEM_TEMPLATE = """{prompt_body}

{identity}

{skill_directive}

{citation_directive}"""

HUMAN_TEMPLATE = """{context_block}

问题：{question}"""

PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_TEMPLATE),
        MessagesPlaceholder(variable_name="history"),
        ("human", HUMAN_TEMPLATE),
    ]
)


def role_label(role: str) -> str:
    return "教师" if role == "teacher" else "学生"


def _context_block(hits: list[dict]) -> str:
    return "\n\n".join(
        f"[{i}] 标题：{hit['title']}；切片：{hit['chunk_index']}；"
        f"位置：{hit['start_offset']}-{hit['end_offset']}；"
        f"正文：{hit.get('_chunk_text', hit['excerpt'])}"
        for i, hit in enumerate(hits, 1)
    )


def _template_variables(
    prompt_body: str,
    skill: dict[str, Any] | None,
    hits: list[dict],
    question: str,
    user: dict[str, Any],
    tool_results: list[dict[str, Any]] | None = None,
    answer_mode: str = "guide",
) -> dict[str, Any]:
    """把四项输入翻译成 ChatPromptTemplate 的模板变量。

    工具返回与检索片段同处用户消息：在 ``context_block`` 末尾以
    ``[工具 {ref} 返回的数据]`` 前缀标明来源，**不进系统消息**。
    ``answer_mode="direct"`` 时用直接回答约束覆盖技能的「只给思路」说明。
    """
    if answer_mode == "direct":
        skill_directive = DIRECT_ANSWER_DIRECTIVE
    elif skill:
        skill_directive = SKILL_DIRECTIVE.format(
            name=skill["name"],
            subject=skill["subject"] or "通用",
            description=skill["description"],
        )
    else:
        skill_directive = DIRECT_DIRECTIVE
    if hits:
        context_block = "本班资料片段：\n" + _context_block(hits)
    else:
        context_block = (
            "（本班资料中没有检索到相关片段，"
            "如确实没有依据请明说，不得编造出处。）"
        )
    if tool_results:
        tool_block = "\n\n".join(
            f"[工具 {item['ref']} 返回的数据]\n{item.get('text', '')}"
            for item in tool_results
            if item.get("text")
        )
        if tool_block:
            context_block = f"{context_block}\n\n{tool_block}"
    return {
        "prompt_body": prompt_body.strip() or DEFAULT_PROMPT,
        "identity": IDENTITY_TEMPLATE.format(
            username=user["username"],
            role_label=role_label(user["role"]),
            class_name=user.get("class_name", ""),
        ),
        "skill_directive": skill_directive,
        "citation_directive": CITATION_DIRECTIVE if hits else "",
        "context_block": context_block,
        "question": question,
    }


def build_messages(
    prompt_body: str,
    skill: dict[str, Any] | None,
    hits: list[dict],
    question: str,
    user: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
    tool_results: list[dict[str, Any]] | None = None,
    answer_mode: str = "guide",
) -> list[BaseMessage]:
    """用 ChatPromptTemplate 组装 LangChain 消息（system + 历史 + 当前问题）。"""
    variables = _template_variables(
        prompt_body, skill, hits, question, user, tool_results, answer_mode
    )
    history_messages: list[BaseMessage] = []
    for item in history or []:
        content = item.get("content") or ""
        if not content:
            continue
        if item.get("role") == "assistant":
            history_messages.append(AIMessage(content=content))
        else:
            history_messages.append(HumanMessage(content=content))
    return PROMPT.format_messages(history=history_messages, **variables)


def _chat_model(config: RetrievalConfig) -> ChatOpenAI:
    return ChatOpenAI(
        model=config.chat_model,
        base_url=config.chat_base_url,
        api_key=config.chat_api_key,
        timeout=30,
        max_retries=1,
    )


#: 无模型时「照录原文」的长度上限。整段贴出来既读不下去，也盖住了后面的引用。
LOCAL_EXCERPT_LIMIT = 320


def plain_excerpt(text: str, limit: int = LOCAL_EXCERPT_LIMIT) -> tuple[str, bool]:
    """把 markdown 片段压成一段能读的原文摘录，返回 ``(文本, 是否截断)``。

    无模型配置时「直接回答」只能照录检索片段，而片段是原始 markdown：
    标题号、加粗星号、列表符号会一个字不改地出现在答案正文里。既然生成不了
    摘要，至少不该让人去读符号；而且要让人一眼看出这是**原文照录**，
    不是系统给出的答案——这两件事混在一起时，可靠的那部分也会被怀疑。
    """
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)        # 标题号
        line = re.sub(r"^[>\-*+]\s+", "", line)        # 引用与列表符号
        line = re.sub(r"\*\*|__|`", "", line)          # 加粗与行内代码
        lines.append(line)
    merged = re.sub(r"\s{2,}", " ", " ".join(lines)).strip()
    if len(merged) > limit:
        return merged[:limit].rstrip("，。；、 ") + "……", True
    return merged, False


def local_stream(
    prompt_body: str,
    skill: dict[str, Any] | None,
    hits: list[dict],
    question: str,
    user: dict[str, Any],
    tool_results: list[dict[str, Any]] | None = None,
    answer_mode: str = "guide",
) -> Iterator[str]:
    """无模型配置时的确定性回退：分段产出，引导/直接两种模式结构不同。"""
    for item in tool_results or []:
        yield f"已调用工具 {item['ref']}，返回：{item.get('text', '')}"
    if answer_mode == "direct":
        # 直接回答模式：把命中的片段原文作为答案依据，不做苏格拉底式引导。
        # 没配模型时只能照录，那就把「照录」这件事说清楚：先说明来源，
        # 再把 markdown 符号洗掉，超长就截断。原文 ≠ 答案，不该混着给。
        if hits:
            first = hits[0]
            body, clipped = plain_excerpt(
                first.get("_chunk_text") or first.get("excerpt") or ""
            )
            yield (
                f"我从本班资料《{first['title']}》里找到一段相关内容[1]。"
                f"当前未配置生成模型，下面是原文照录，不是改写后的答案：\n\n"
            )
            yield body
            if clipped:
                yield (
                    "\n\n（原文较长，这里只截取了开头一段；"
                    "完整内容点引用 [1] 查看。）"
                )
        else:
            yield "本班资料中没有找到与该问题相关的内容，无法给出确定答案（未编造出处）。"
        return
    if hits:
        first = hits[0]
        yield (
            f"我先查了你班（{user.get('class_name', '')}）的资料，"
            f"参考《{first['title']}》的第 {first['chunk_index']} 个片段[1]。"
        )
    else:
        yield "我在本班资料里没有找到与这道题直接相关的内容，下面只谈一般方法，不标出处。"
    if skill:
        yield f"当前启用了「{skill['name']}」技能，我们只走思路，不直接给最终答案。"
        yield f"第一步，把题目复述一遍：「{question}」——已知条件是什么，要求的是什么？"
        yield "第二步，想想课本里哪个知识点管这类问题，把对应的公式或定理写出来。"
        yield "第三步，试着迈出求解的第一步；卡住的话，告诉我你代到哪一步，我接着给提示。"
    else:
        yield f"关于「{question}」："
        yield "先审题，把已知条件和所求结论分别列出来。"
        yield "再选择对应知识点逐步求解，每一步都写清依据。"
        yield "需要更具体的帮助，可以把题目完整发给我。"


def stub_stream(
    prompt_body: str,
    skill: dict[str, Any] | None,
    hits: list[dict],
    question: str,
    user: dict[str, Any],
    config: RetrievalConfig,
    history: list[dict[str, Any]] | None = None,
    tool_results: list[dict[str, Any]] | None = None,
    answer_mode: str = "guide",
) -> Iterator[str]:
    """固定响应模型替身：不发起任何网络调用，输出由输入确定性决定。

    提示词组装仍走 LangChain（``build_messages``），只把 ``ChatOpenAI.stream``
    换成固定分段，供接口测试在离线环境断言「技能/检索命中是否真的影响了回答」。
    """
    build_messages(
        prompt_body, skill, hits, question, user, history, tool_results, answer_mode
    )
    for item in tool_results or []:
        yield f"已调用工具 {item['ref']}，返回：{item.get('text', '')}"
    yield "[STUB] "
    if answer_mode == "direct":
        yield "直接回答模式。"
        if hits:
            yield f"依据《{hits[0]['title']}》第 {hits[0]['chunk_index']} 节[1]，资料内容见引用。"
        else:
            yield "本班资料没有相关片段，未编造出处。"
        return
    if hits:
        yield f"命中本班资料《{hits[0]['title']}》[1]。"
    else:
        yield "本班资料没有相关片段。"
    if skill:
        yield f"已启用技能「{skill['name']}」，只给思路："
        yield "第一步，复述题目，列出已知与所求。"
    else:
        yield "未启用解题引导技能，按常规方式回答："
        yield "先审题，再选择对应知识点逐步求解。"


def stream_answer(
    prompt_body: str,
    skill: dict[str, Any] | None,
    hits: list[dict],
    question: str,
    user: dict[str, Any],
    config: RetrievalConfig,
    history: list[dict[str, Any]] | None = None,
    tool_results: list[dict[str, Any]] | None = None,
    answer_mode: str = "guide",
) -> Iterator[str]:
    """流式产出回答文本。优先级：固定替身 → LangChain 聊天服务 → 本地回退。"""
    if config.tutor_stub:
        yield from stub_stream(
            prompt_body, skill, hits, question, user, config, history, tool_results,
            answer_mode,
        )
        return
    if not config.chat_ready:
        yield from local_stream(
            prompt_body, skill, hits, question, user, tool_results, answer_mode
        )
        return
    messages = build_messages(
        prompt_body, skill, hits, question, user, history, tool_results, answer_mode
    )
    model = _chat_model(config)
    for chunk in model.stream(messages):
        text = chunk.content
        if isinstance(text, str) and text:
            yield text
        elif isinstance(text, list):
            for part in text:
                if isinstance(part, str) and part:
                    yield part
                elif isinstance(part, dict) and part.get("text"):
                    yield str(part["text"])


def public_citations(hits: list[dict]) -> list[dict[str, Any]]:
    """由检索命中直接生成引用列表（不依赖模型文本解析）。"""
    return [
        {
            "number": index,
            "material_id": int(hit["material_id"]),
            "title": hit["title"],
            "chunk_index": int(hit["chunk_index"]),
            "start_offset": int(hit["start_offset"]),
            "end_offset": int(hit["end_offset"]),
            "excerpt": hit["excerpt"],
            "material_url": hit["material_url"],
        }
        for index, hit in enumerate(hits, 1)
    ]
