# 检索基准与结果

`functional-v1` 是自建、确定性的非临床数据：明确的软件编号、两跳连接和干扰资料，
用于测量检索路径是否工作。它不是医学试题，也不是独立医学金标准，不能证明路由规则泛化。
`legacy-lookup-v1` 是原仓库医学知识文本的弱标注来源定位测试：从固定采样记录开头取查询，
只知道该记录是一个正例，未穷举其他相关记录。它不是语义问答正确性测试，也不能证明原知识文本可靠。

脚本与结果 JSON 一并公开，固定数据生成方式、样本、源码指纹、种子、配置和指标口径。
真实语义模型缺少权重、没有审核关系或其他前提缺失时，报告未运行，绝不填0分或借用其他模式结果。

```powershell
python scripts/compare_retrieval.py --suite functional --repeats 5 --output benchmarks/results/functional-v1.json
python scripts/compare_retrieval.py --suite legacy --repeats 3 --output benchmarks/results/legacy-lookup-v1.json
# 完整BGE和检索依赖准备好后，用同一数据单独对照真实向量：
python scripts/compare_retrieval.py --suite functional --with-vectors --device cpu --repeats 5 --output .runtime/functional-vectors.json
```

速度只测本机进程内预热后的检索函数，包含 SQLite 读取、分词、路由和关系读取；
不包括导入/建索引、HTTP、模型生成或独立审题，不是网页完整回答速度。多次重复报告P50/P95，重复不增加质量评测独立样本数。
精确数据、局限和下一轮医学金标准方案见 `../docs/RETRIEVAL_EVALUATION.md`。
脚本默认运行轻量基线；`--with-vectors` 会在临时目录建真实索引，建索引时间不计入查询延迟。
失败时明确记录向量未运行；不会下载权重、使用假向量或修改用户已有索引。
