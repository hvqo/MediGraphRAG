# MediGraphRAG

面向医学教育的资料检索、依据问答和试题工作台。支持本地 Ollama 与云端
OpenAI-compatible 模型，在页面设置中切换。

> 改造工作在 `refactor/medigraphrag` 分支进行。阶段记录见
> [改造进度](docs/PROGRESS.md)，范围和验收条件见 [改造计划](docs/PLAN.md)。
> main 已按用户授权备份后同步源码整理版；0.4.0 新功能继续提交到改造分支。

## 可以做什么

- **医学资料库**：导入 PDF、DOCX、TXT、Markdown 或粘贴文本；保留原文件、
  页码或段落位置；自动分块和去重，可回看和删除。
- **依据问答**：检索原文后生成回答，每段附片段引用和原文短句；校验引用后
  再由模型复核。无资料、引用不匹配或复核失败时不展示未经通过的答案。
- **智能出题**：单选、多选、病例单选；基础、进阶、综合三档要求；每批 1–10 题。
  结构、引用和模型审题检查通过后进入人工待审。
- **题库审核**：编辑、通过、驳回和操作记录；编辑后重新待审；JSON/CSV 导出。
  默认仅导出原文仍有效、已人工审核通过的题目。
- **知识图谱**：查看资料中医学概念的原文共现；可独立浏览已有 Neo4j 图谱。
  共现不代表因果关系；无文献来源的历史关系不作为生成依据。
- **模型设置**：本地/云端切换、连接检查、检索参数、可选向量索引与重排序。
  密钥保存在本机或环境变量中，接口不返回密钥明文。
- **资料阅读与版本**：PDF 页内引句高亮、选择原文问答/出题、表格保留、资料出处、分块调整和新旧版本影响核对。
- **医学关系审核**：模型提取或手工录入带引句、条件的关系，人工通过后参与路径与融合检索；可同步有效关系到 Neo4j。
- **蓝图与病例**：按章节/考点/认知层次组织试卷，查看覆盖矩阵；共享经审核病例，分别配置生成和审题模型，保留各干扰项依据。
- **学习与评测**：先作答后看解析、错题回到知识点、真实首次作答统计；固定集检索对照、人工评价、模型调用追踪和回放。

详细操作、验收边界及中文软件对照数据见 [V2 使用说明](docs/V2_GUIDE.md)。

## 先运行起来

在项目根目录执行。默认安装只包含新工作台运行所需的依赖，关键词检索不需要
下载 BGE，也不需要先启动 Neo4j。

```powershell
python -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
python main.py
```

打开 **http://127.0.0.1:8000**。API 文档位于 **http://127.0.0.1:8000/docs**。
前端构建后由后端直接提供页面，不必同时启动两个服务。

当前 Windows 工作区的虚拟环境位于项目上一层，使用：

```powershell
& ..\.venv\Scripts\python.exe main.py
# 或：
.\scripts\start.ps1
```

环境适配记录见 [Windows 环境说明](ENVIRONMENT-WINDOWS.md)。新核心应用不依赖
MetaGPT；仓库保留旧工具与完整 Windows 依赖锁供追溯和兼容使用。

## 第一次使用

1. 在“医学资料库”导入有使用权限的教材、指南或学习笔记。扫描 PDF 需先完成 OCR。
2. 在“模型与设置”选择模型方式。本机已有 Ollama 模型时填写准确模型名，保存并测试。
3. 在“依据问答”先尝试“只查原文”；模型可用后再生成回答。
4. 在“智能出题”设置考点、题型、难度和数量，查看持久化任务进度。
5. 在“题库与审核”核对题干、答案、解析和原文，编辑或审核后导出。

云端模式填写服务商的接口基址（通常以 `/v1` 结尾）、模型 ID 和 API 密钥。
服务需要支持 Chat Completions 和 `response_format: json_object`。
连接检查使用 `/models`；不提供该接口的服务可能无法通过连接检查，实际生成
是否支持仍取决于该服务。**云端请求会发送检索到的资料片段，调用由服务商计费。**

## 配置与本地数据

可复制 `.env.example` 为 `.env`，填写本机环境变量：

| 变量 | 用途 |
| --- | --- |
| `MEDIGRAPH_DATA_DIR` | 运行数据目录，默认项目下 `.runtime` |
| `MEDIGRAPH_CLOUD_API_KEY` | 云端密钥，优先于页面保存的密钥 |
| `MEDIGRAPH_NEO4J_URI` | Neo4j 地址，默认 `bolt://localhost:7687` |
| `MEDIGRAPH_NEO4J_USER` | Neo4j 用户，默认 `neo4j` |
| `MEDIGRAPH_NEO4J_PASSWORD` | Neo4j 密码；缺少时不会连接数据库 |
| `MEDIGRAPH_EMBEDDING_PATH` | BGE 嵌入模型目录 |
| `MEDIGRAPH_RERANKER_PATH` | BGE 重排模型目录 |
| `MEDIGRAPH_ORIGINS` | 开发前端允许来源，以逗号分隔 |

`.runtime` 保存 SQLite、原文件、设置和新向量索引，已排除 Git 上传。
备份时请保留整个目录。删除资料会删除原文件与检索片段，已有题目仍保留，
但失去原文的题目不能审核通过或导出。并发生成任务串行处理，避免本地模型同时争用资源。

默认绑定本机地址，首版面向单人使用；不包含账号权限或面向公网部署的访问控制。
不要直接把本地工作台作为无保护的公网服务。

## 可选：语义检索和重排序

先安装适合显卡与 Python 版本的 PyTorch，再安装：

```powershell
python -m pip install -r requirements-retrieval.txt
hf download BAAI/bge-large-zh-v1.5 --local-dir model/bge-large-zh-v1.5
hf download BAAI/bge-reranker-v2-m3 --local-dir model/bge-reranker-v2-m3
```

需要完整权重和真实分词器文件；仓库中的小文件或 Git LFS 指针不能替代它们。
然后在设置页面选择运行设备、保存设置、重建向量索引，并启用相关开关。
显存有限时可让检索模型使用 CPU，为 Ollama 保留显存。

新索引基于稳定片段 ID，使用归一化 CLS 向量与 FAISS 内积检索。资料变化后
索引标为过期，需要重建。旧 `data/faiss_index` 不与新资料库混用。
模型或索引不可用时会明确提示使用关键词检索，不将降级称为完整语义检索。

“关系与出处”提供带引句的候选提取、人工审核、两跳路径和 Neo4j 同步。
同步只替换当前工作区拥有的关系，不改历史图谱；过期或未审核的关系不会被写入。
“知识图谱”保留共现与历史图谱浏览，不将无出处的历史关系当作医学事实。

## 开发与验证

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
# 另一个终端，在 frontend 下：
npm run dev
# 接口与工作流测试：
python -m unittest discover -s tests -v
python -m pip check
```

开发前端用 Vite 将 `/api` 转发到后端；构建后的页面使用后端同源 `/api` 别名。
可通过 `VITE_API_BASE_URL` 指定其他 API 地址，跨域来源同时在后端配置。

`scripts/check_ui.py` 使用 Playwright 与已安装的 Chrome 检查六个页面、来源回看、
图谱和手机布局，测试资料和题目会在结束时删除。`scripts/check_local_model.py` 会实际
调用本地 Ollama，使用隔离的非临床软件验收资料检查问答和出题，不调用云端。
这些测试不构成医学准确率评测。
`scripts/check_v2_ui.py` 会启动临时应用与明确标注的模型 HTTP 桩，检查12个页面及完整联动流程；
`scripts/check_reader_ui.py` 验证真实 PDF 页码、文字选择和高亮；
`scripts/benchmark_retrieval.py` 运行固定中文软件验收集，不修改生产资料或调用模型。

## 当前限制

- PDF 最多 500 页、文件 25MB、正文 200 万字、每份最多 5000 个片段；不含扫描 OCR。
- 医学概念共现匹配使用历史图谱实体词表与少量基础词，未匹配到的概念不会出现在图中。
- 题库页面展示最近 500 题，导出读取全部符合条件的题目。
- 问答和题目都需核对原始资料；自动引文检查不能证明语义蕴含或临床正确性。
- 题目难度是生成要求，尚未通过真实考生答题数据校准。
- Docling 是可选适配器，当前环境未安装；BGE 完整权重、Neo4j 服务和真实云端仍未做整体验收。
- 学习档案是本机记录分类，没有账户权限；样本不足时统计显示空值。
- 未包含多用户、医学图像理解、完整多跳图推理、生产部署或正式医学评测。

## 目录

```text
backend/app/     Python 后端、API 与领域模块
frontend/        Vue 工作台（按页面拆分）
tests/           来源、检索、模型协议、任务和审核回归测试
scripts/         启动、环境适配、浏览器与本地模型检查
docs/            改造计划与逐阶段进度
legacy/          历史 Python 工具和实验源码，非新版默认启动链路
pyproject.toml   Python 包元数据与正式命令行入口
```

## 源码规范与下一轮方案

本分支已将全部三个 Notebook 的代码迁为 Python 文件，后端在 `backend/app`，
前端在 `frontend`。详见 [源码整理记录](docs/SOURCE_LAYOUT.md)。
`python -m pip install -e .` 可安装正式的 `medigraphrag` 命令；
`python -m backend.app.cli --help` 可查看导入、检索和索引等离线操作。

调研 RAGFlow、LightRAG、Dify、Docling 和 MedRAG 后的创意、优先级及验收条件，
见 [改造方案](docs/V2_PROPOSAL.md)。核心功能已实现，实际验收和未验收项见 [V2 使用说明](docs/V2_GUIDE.md)。
