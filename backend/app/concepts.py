"""Bounded, distributed concept coverage; avoid extracting file front matter as teaching facts."""

from collections import defaultdict, deque
import re

FRONT_MATTER = re.compile(
    r"^(?:source\s*:|来源[：:]|https?://|doi[：:]|pmid[：:]|pubmed abstract,|"
    r"for software demonstration|本资料仅用于.{0,12}(?:演示|验收)|版权|copyright|目录\s*$)",
    re.I,
)


def select_evidence(chunks, limit=120):
    groups = defaultdict(list)
    for chunk in chunks:
        text = chunk["text"].strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines or all(FRONT_MATTER.search(line) for line in lines):
            continue
        if len(text) < 300 and text.endswith(("?", "？")):
            continue
        groups[chunk["document_id"]].append(chunk)
    # Cover every document first; within each document spread sampling across its full extent.
    eligible = sum(len(items) for items in groups.values())
    if eligible <= limit:
        return [chunk for items in groups.values() for chunk in items], eligible
    queues = []
    quota = max(1, (limit + len(groups) - 1) // max(1, len(groups)))
    for items in groups.values():
        size = min(len(items), quota)
        positions = [round(i * (len(items) - 1) / max(1, size - 1)) for i in range(size)]
        queues.append(deque(items[i] for i in positions))
    selected = []
    while len(selected) < limit and any(queues):
        for queue in queues:
            if queue and len(selected) < limit:
                selected.append(queue.popleft())
    if len(selected) < limit:
        used = {c["id"] for c in selected}
        for items in groups.values():
            for chunk in items:
                if chunk["id"] not in used and len(selected) < limit:
                    selected.append(chunk)
                    used.add(chunk["id"])
    return selected, eligible
