"""Render measured public JSON files to an auditable table and standalone figures."""

import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "keyword": "BM25",
    "vector": "BGE vector",
    "graph_mentions": "Mention graph",
    "hybrid": "RRF + mentions",
    "hybrid_rerank": "RRF + reranker",
    "auto_v1": "Auto v1",
    "auto_v2": "Auto v2 (dense fallback)",
}


def wilson(p, n):
    z = 1.96
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return f"{100 * (center - half):.1f}–{100 * (center + half):.1f}%"


def main():
    reports = {
        n: json.loads((ROOT / "benchmarks/results" / f"{n}-real.json").read_text(encoding="utf-8"))
        for n in ["nfcorpus", "medicalretrieval", "pubmedqa"]
    }
    text = [
        "# 真实医学检索与答案实测 · 2026-10-27",
        "",
        "本页由 `scripts/render_medical_report.py` 从逐题 JSON 汇总。它报告本机实验，不是临床准确性认证，也不是官方排行榜成绩。",
        "",
        "## 数据与实验条件",
        "",
        "- **NFCorpus**：BEIR 完整测试集，3,633 篇文档、323 个查询。医学/营养文献相关性，单个查询有多篇相关文献；来源链接形成的相关性标签不代表临床共识。数据仅限其许可允许的学术用途。",
        "- **中文 MedicalRetrieval**：下载原始 100,999 篇语料及全部 1,000 个 dev 查询；本次检索池为 5,000 篇受控子集，包含所有已标注正例及固定种子抽取的干扰文档。**不是十万篇全库评测**，减少干扰项可能提高分数；保留正例使用了标签，因此只能用于开发对照。每题只标注一个正例，P@5 上限为20%。",
        "- **PubMedQA**：下载全部 1,000 条 PQA-L 专家标签记录，从 yes/no/maybe 各抽20题，共60题；检索池为全部1,000段摘要。只索引 CONTEXTS，不索引题目、标题、结论与金标准长答案。该集合含一般生物医学研究，不全是临床问题。",
        "- **真实模型**：中文 BGE-large-zh-v1.5，英文 BGE-small-en-v1.5；归一化 CLS、512 token 截断、FAISS IndexFlatIP；查询加对应BGE指令。中文重排 BGE-reranker-base，英文 MiniLM-L6-v2，重排前20候选。全部权重在本机实际加载；无随机/伪向量。",
        "- **机器与计时**：Windows、Python 3.10.10、PyTorch 2.2.2+cu121、RTX4050 Laptop 6GB；查询并发1，先预热再计时一遍。耗时包含真实查询编码、检索及相应重排，**不包含 HTTP、SQLite 资料读取、冷启动、文档编码、生成/审题**。结果不可当生产完整响应时间。",
        "- **答案生成**：本机 Ollama qwen2.5 7B，温度0，top2候选各取前1,400字符；每批3题，问题与来源ID遮蔽，结构化输出有约束。按专家 yes/no/maybe 标签判分；提示词不含标签。",
        "- `auto_v1` 是旧规则与字面图扩展基线；`auto_v2` 是看到本轮结果后选择的语义优先策略。这三个公共集合没有已审核医学关系图，v2实际走语义回退；**本实验没有证明医学多跳图推理收益，也不是独立留出集验证**。",
        "- BM25/归一化向量/字面提及图及RRF使用同一套语料；实验用字面词图不是GraphRAG、LightRAG或Neo4j框架对比。生产检索另有来源范围、向量阈值和审核图路径，内核成绩不等于完整产品成绩。",
        "",
        "原始来源：[NFCorpus](https://www.cl.uni-heidelberg.de/statnlpgroup/nfcorpus/)、[BEIR](https://github.com/beir-cellar/beir)、[MedicalRetrieval](https://huggingface.co/datasets/mteb/MedicalRetrieval)、[PubMedQA](https://github.com/pubmedqa/pubmedqa)。权重与数据版本、SHA256见 [assets-manifest.json](../benchmarks/assets-manifest.json)。原始测试语料与权重未上传Git，也不灌入用户知识库。",
        "",
        "## 检索对比",
        "",
        "Recall 是已标注相关文档找回比例；Precision 是返回结果中已标注相关文档比例；MRR衡量首个相关结果名次；nDCG衡量相关性等级与排序。表中为按查询平均，R/P/Hit为百分比，MRR/nDCG为0–1。NFCorpus相关文献多，因此R@5通常远低于单正例集合，跨集合不能直接比数值。",
        "",
    ]
    for name, report in reports.items():
        text += [
            f"### {name} · {report['documents']:,}篇 / {report['queries']:,}查询",
            "",
            "| 方案 | R@5 | P@5 | Hit@5 | MRR@5 | nDCG@5 | R@10 | P@10 | MRR@10 | nDCG@10 | P50 ms | P95 ms |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for m in report["methods"]:
            a, b = m["at5"], m["at10"]
            text.append(
                f"| {LABELS[m['method']]} | {100 * a['recall']:.2f} | {100 * a['precision']:.2f} | {100 * a['hit']:.2f} | {a['mrr']:.4f} | {a['ndcg']:.4f} | {100 * b['recall']:.2f} | {100 * b['precision']:.2f} | {b['mrr']:.4f} | {b['ndcg']:.4f} | {m['p50_ms']:.2f} | {m['p95_ms']:.2f} |"
            )
        text += ["", f"[逐题排名、耗时和指标 JSON](../benchmarks/results/{name}-real.json)", ""]
    text += [
        "## 答案对照：不能把检索命中写成答题准确率",
        "",
        "| 方案 | 答对/总数 | 标签准确率 | 95% Wilson区间 | 引句逐字匹配率 | 无效输出率 | 3题一批P50秒 | P95秒 |",
        "|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for m in reports["pubmedqa"]["methods"]:
        a = m.get("answer_eval")
        if not a:
            continue
        rows = a["results"]
        times = [r["batch_seconds"] for r in rows[::3]]
        text.append(
            f"| {LABELS[m['method']]} | {sum(r['correct'] for r in rows)}/{len(rows)} | {100 * a['accuracy']:.2f}% | {wilson(a['accuracy'], len(rows))} | {100 * a['citation_exact_match_rate']:.2f}% | {100 * a['invalid_output_rate']:.2f}% | {statistics.median(times):.2f} | {sorted(times)[math.ceil(0.95 * len(times)) - 1]:.2f} |"
        )
    text += [
        "",
        "每类20题时，“全部猜yes/no/maybe任一类”的准确率为33.33%。60题的区间很宽，1–3题差异不能证明显著优势；相同证据再次生成也可能出现输出差异。引句匹配只检查文字存在，不代表医学语义支持；未匹配仍记为失败，没有改写金标准或清除失败样本。全部逐题标签、混淆矩阵、调用用量、延迟、错误保存在PubMedQA JSON。",
        "v2 Recall@5=100%而答案准确率仍只有56.67%，暴露出证据截断、推理、任务适配和引用生成的问题。不能宣称系统医学准确率达到80.5%或100%。真实多跳医学金标准、专家对答案/题目的语义评价、自然扫描/手写文档OCR质量、多用户负载尚无充分测量。",
        "",
        "## 方案选择",
        "",
        "默认直接提问采用 **语义优先 → 索引不可用时BM25 → 关系意图且有有效审核路径时局部深检索**。中文中重排R@5只比向量高0.5个百分点，却将P50从17.40ms增至126.52ms，而且MRR/nDCG下降，因此日常问答不默认开启。英文NFCorpus重排nDCG@5更好，可供研究/高质量场景选择；不能得出所有医学资料都适合关闭重排。",
        "字面图融合使中文R@5从80.5%降到51.5%，因此不因“有图谱”就自动给共现结果高权重。已审核医学关系用于深查原句；自动保存的字面提及图用于导航，不能冒充因果、治疗或诊断关系。",
        "v2是基于本次结果做出的开发选择。下一轮应冻结方案，在未用于选择的中文医学问答及人工标注多跳集合上确认收益；十万篇全库与并发压测需单独跑，不能由本次子集成绩推算。",
        "",
        "## 复现",
        "",
        "```powershell",
        "python -m pip install -r requirements-benchmark.txt",
        "python scripts/prepare_medical_assets.py",
        "python scripts/benchmark_medical.py --dataset nfcorpus",
        "python scripts/benchmark_medical.py --dataset medicalretrieval",
        "python scripts/benchmark_medical.py --dataset pubmedqa",
        "python scripts/evaluate_medical_answers.py",
        "python scripts/benchmark_auto_v2.py",
        "python scripts/evaluate_medical_answers.py --methods auto_v2",
        "python scripts/check_multimodal_model.py",
        "python scripts/render_medical_report.py",
        "```",
        "",
        "检索脚本需要CUDA；运行前释放其他模型的GPU占用。语料编码缓存首次构建和命中缓存的`index_seconds`不可当索引性能对比；本次索引计时没有统一冷热条件，故不用于方案优劣结论。CPU应用与GPU内核延迟也分开记录。测试使用固定seed=20261027，正文、模型和索引缓存仅存在忽略的`.runtime`。",
        "",
    ]
    mm = ROOT / "benchmarks/results/multimodal-real.json"
    if mm.exists():
        r = json.loads(mm.read_text(encoding="utf-8"))
        text += [
            "## 本机真实多模态流程",
            "",
            f"视觉模型 `{r['vision_model']}`，文本模型 `{r['generation_model']}`。输入同一公开摘要的机器打印PNG、扫描PDF、含内嵌图片的Word，各1份；这不是自然文档OCR评测集。",
            f"前台处理 {r['foreground_seconds']:.2f} 秒，生成 {r['generated_questions']} 道题，请求状态 `{r['request_status']}`，归档状态 `{r['archive_status']}`，向量索引就绪 `{r['index_ready']}`。",
            f"单次真实问答API用时 {r.get('single_question_api_seconds', 0):.2f} 秒，包含检索、生成、自动核验，HTTP {r.get('single_question_http_status')}，结果状态 `{r.get('single_question_answer_status')}`；仅一个样本，不报告P95。",
            "",
            "| 文件 | 状态 | 识别字符错误率 |",
            "|---|---|---:|",
        ]
        text += [
            f"| {f['filename']} | {f['status']} | {100 * f.get('character_error_rate', 1):.2f}% |" for f in r["files"]
        ]
        text += [
            "",
            "字符错误率对已知渲染原文做小写、去标点/空白后的编辑距离；Word仅统计内嵌图识别部分，避免原生正文掩盖OCR错误。一个干净样本不代表手写、照片、复杂表格或医学影像效果。原文件和识别结果在临时隔离资料库验收，不写入用户个人库。[真实记录](../benchmarks/results/multimodal-real.json)",
            "",
        ]
    text += ["## 多模态优化过程与失败保留", "", "| 运行 | 前台秒数 | 请求状态 | 生成题数 |", "|---|---:|---|---:|"]
    for filename, label in [
        ("multimodal-vision-baseline.json", "视觉基线"),
        ("multimodal-cache-attempt.json", "重复识别复用，出题被拦截"),
        ("multimodal-real.json", "文字优先OCR"),
    ]:
        file = ROOT / "benchmarks/results" / filename
        if not file.exists():
            continue
        item = json.loads(file.read_text(encoding="utf-8"))
        text += [
            f"| [{label}](../benchmarks/results/{filename}) | {item['foreground_seconds']:.2f} | {item['request_status']} | {item['generated_questions']} |"
        ]
    text += [
        "",
        "整批时长包含知识点生成、出题与审题，模型随机性和修复次数不同，不能把三次总耗时之差全部归为OCR加速。文字优先这次实际视觉调用0次；视觉基线实际运行过本机VL模型。被拦截的运行保留为partial，不通过放宽审查换取成功。",
        "",
    ]
    (ROOT / "docs/MEDICAL_BENCHMARK.md").write_text("\n".join(text), encoding="utf-8")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    methods = ["keyword", "vector", "graph_mentions", "hybrid", "hybrid_rerank", "auto_v1", "auto_v2"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), layout="constrained")
    for ax, name in zip(axes, ["medicalretrieval", "nfcorpus"]):
        values = {m["method"]: m for m in reports[name]["methods"]}
        ax.barh(
            [LABELS[m] for m in methods],
            [100 * values[m]["at5"]["recall"] for m in methods],
            color=["#95a6ac", "#19786e", "#b4c1c5", "#96aaa5", "#dcab56", "#869998", "#146356"],
        )
        ax.invert_yaxis()
        ax.set_xlabel("Recall@5 (%)")
        ax.set_title(
            "Chinese: 1,000 queries / 5,000 docs"
            if name == "medicalretrieval"
            else "NFCorpus: 323 queries / 3,633 docs"
        )
        ax.spines[["top", "right"]].set_visible(False)
        for i, m in enumerate(methods):
            ax.text(
                100 * values[m]["at5"]["recall"] + 0.3,
                i,
                f"{100 * values[m]['at5']['recall']:.2f}",
                va="center",
                fontsize=9,
            )
        ax.set_xlim(0, 95 if name == "medicalretrieval" else 17)
    fig.savefig(ROOT / "docs/images/medical-recall.svg")
    plt.close(fig)


if __name__ == "__main__":
    main()
