"""An explicit routing policy, not a learned probability or medical intent classifier."""

import re

POLICY_VERSION = "dense-first-v2"
DEEP_PATTERN = re.compile(
    r"为什么|机制|路径|关联|关系|联系|比较|区别|差异|联合|综合|跨章节|跨文档|多跳|相互|冲突|版本变化|深度|how .* related|relationship|compare|mechanism",
    re.IGNORECASE,
)


def decide(query, evidence=None):
    if DEEP_PATTERN.search(query):
        return "deep", "relational_intent", "问题涉及关系、比较或跨片段线索，尝试补充已审核关系路径"
    if evidence is not None and not evidence:
        return "deep", "no_fast_evidence", "快速检索没有命中，尝试寻找已审核的原文关系"
    return "fast", "direct_lookup", "优先语义检索；索引未就绪时自动使用关键词，当前问题无需关系深检索"
