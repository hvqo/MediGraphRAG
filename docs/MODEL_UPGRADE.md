# 0.7 模型与本地运行时升级

0.7已从 `refactor/medigraphrag` 合入main；升级前的main保存在 `backup/main-before-v07-20261117`。正式医学对照评测按用户要求后置，下面区分已实现能力与未启用方案。

## 已实现的主路线

- 默认视觉模型升级为 **Qwen3-VL-8B-Instruct，Q4_K_M**。
- 支持三种模型来源：Ollama、本地OpenAI兼容服务（llama.cpp / LM Studio）、云端兼容接口。
- 文字、视觉、审题分别配置服务、模型和密钥；视觉不再强制使用Ollama。审题默认仍可沿用生成模型，这不等同于独立模型质量保障。
- Windows提供项目内、固定版本的llama.cpp CUDA12.4服务；复用同一份GGUF与视觉投影文件，无需重复保存8B权重。文字与视觉共享一个实例。
- 继续采用原生正文 → CPU OCR → 需要时视觉模型的分级解析；图片尺寸、视觉上下文/输出/超时可配置。输出被截断会报错，不把半页结果当完整识别。
- BGE-M3以**稠密向量**模式接入，未安装时自动模式沿用旧BGE；未声称启用M3的稀疏/ColBERT全套检索。
- 新重排优先使用 **BGE-reranker-v2-m3**；启用重排后，自动快速检索也会重排候选，不再仅限手动融合模式。
- 知识点按正文片段分批提炼，筛除纯来源/版权说明；最多120片段，超量分散采样并返回覆盖信息。仍不声称穷尽整本教材。
- 原文引用校验、独立审题步骤、人工审核和审核关系路径继续保留。

本轮没有接入页面级视觉向量索引、PaddleOCR-VL专用版面服务或Qwen3-Embedding。这些需要各自适配和资源准备，不是更改视觉模型名称后自动获得的能力。当前图片先识别成带出处的文本再进入文本检索。

## Windows本机准备与启动

在仓库根目录打开PowerShell，沿用现有Python3.10环境：

```powershell
Set-Location 'E:\chatgpt\rag\MediGraphRAG\MediGraphRAG'
& '..\.venv\Scripts\python.exe' scripts/prepare_llama.py
& '..\.venv\Scripts\python.exe' scripts/prepare_vision_model.py --directory 'E:\'
& '..\.venv\Scripts\python.exe' scripts/prepare_retrieval_models.py
```

`E:\` 是本机历史Ollama模型目录（其中有blobs/manifests），不是把代码存到盘根目录。其他机器指定自己的模型目录。下载工具固定版本/摘要，支持分块续传；只有所有文件校验成功才发布模型清单。模型及运行时留在忽略目录，不上传Git。

启动模型窗口：

```powershell
.\scripts\start_llama.ps1 -ModelsDirectory 'E:\'
```

已有个人库若仍使用默认旧本地模型，可在模型服务启动后运行一次：

```powershell
& '..\.venv\Scripts\python.exe' scripts/configure_local_runtime.py
```

该工具备份已有设置，迁移默认Qwen2.5本地配置到新服务，保留自定义生成端点与密钥，启用已安装的向量/重排并重建非空库的索引；适用于本机升级，不必每次启动都执行。

启动网页窗口：

```powershell
.\scripts\start.ps1
```

网页为 `http://127.0.0.1:8000`；llama.cpp兼容API为 `http://127.0.0.1:8081/v1`。

模型启动脚本生成 `.runtime/local-inference.json`，`python main.py` / 项目CLI的serve入口读取它，为新设置提供本地兼容服务默认值。已经保存的个人设置优先；已有档案可在设置页切换。直接执行 `uvicorn backend.app.main:app` 会跳过该CLI默认值加载，所以推荐使用上述启动入口。

本机6GB显存默认部分GPU卸载26层，视觉投影在CPU，8K上下文、单并发；可通过 `-GpuLayers` 调整。不保证8B完全放入显卡，也不把能够启动等同于达到特定速度。不要同时在多个运行时加载同一大模型。

## 设置页怎么填

| 项目 | llama.cpp | LM Studio | Ollama |
| --- | --- | --- | --- |
| 来源 | 本地兼容服务 | 本地兼容服务 | 本地Ollama |
| 文字接口 | `http://127.0.0.1:8081/v1` | 常用 `http://127.0.0.1:1234/v1` | `http://127.0.0.1:11434` |
| 视觉接口 | 同文字接口 | 同文字接口，须加载视觉模型/投影 | 同Ollama地址 |
| 模型 | `qwen3-vl:8b-instruct`（脚本alias） | 填LM Studio实际暴露的模型ID | `qwen3-vl:8b-instruct` |
| 密钥 | 默认不需要 | 未启用认证时不需要 | 不需要 |

保存并分别检查文字、视觉、审题连接；连接检查不代表已经通过真实图片或医学质量评测。
LM Studio使用其官方OpenAI兼容端点，本轮没有安装或控制其GUI；协议适配和llama.cpp部署独立。

## Ollama仍可使用

项目附带Ollama0.40.16便携准备脚本，不修改系统永久环境变量，也不覆盖原Ollama安装：

```powershell
.\scripts\prepare_ollama.ps1
.\scripts\start_ollama.ps1 -ModelsDirectory 'E:\'
```

如果 `.runtime/local-inference.json` 仍存在，CLI会继续提供llama.cpp默认值；在设置页选择Ollama即可使用已保存的个人配置。普通Ollama下载命令为 `ollama pull qwen3-vl:8b-instruct`，项目也提供从官方registry下载、按SHA256校验的准备脚本，供下载器与代理DNS不兼容时使用。没有关闭下载器的安全校验或修改网络防护设置。

## 配置与数据兼容

- Python版本保持3.10.10，模型运行时是独立程序；没有为新视觉模型强行升级旧MetaGPT环境。
- 原版BGE与旧索引保留；切换嵌入模型后旧索引会被判定不适用于新模型，重建前回退关键词检索。
- 更换嵌入模型后先保存设置、再重建索引。新上传的任务会继续在后台建立索引。
- 新嵌入/重排使用CPU作为默认设备，为8B推理保留显存。安装资产不会把公开评测语料自动灌入个人库。
- 三类密钥不出现在GET设置返回值或运行回放中；视觉回放记录图片数量，不保存base64图片。
- 旧医学评测JSON、图表和环境清单原样保留，它们仍对应0.6的旧模型和旧参数，不能作为新版成绩。

## 验证范围

本轮只进行软件验证与少量真实模型启动/调用检查，不做医学准确率、完整召回或新旧速度排名。
复现软件检查：

```powershell
& '..\.venv\Scripts\python.exe' -m unittest discover -s tests -v
& '..\.venv\Scripts\ruff.exe' check backend tests scripts main.py
& '..\.venv\Scripts\python.exe' scripts/check_repository.py
& '..\.venv\Scripts\python.exe' scripts/check_v2_ui.py
```

后者使用明确标注的模型桩验证页面和流程。真实启动/图片调用与资源摘要另保存在 `.runtime`，不作为公开医学评测数据。

官方参考：[llama.cpp多模态](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)、[LM Studio兼容接口](https://lmstudio.ai/docs/developer/openai-compat)、[Qwen3-VL](https://github.com/QwenLM/Qwen3-VL)、[BGE-M3](https://huggingface.co/BAAI/bge-m3)、[BGE重排](https://huggingface.co/BAAI/bge-reranker-v2-m3)。

## 2026-11-17 本机验收

- llama.cpp b12359/CUDA12.4已实际加载同一份Qwen3-VL-8B-Instruct与视觉投影；本机6GB GPU采用26层卸载，服务监听8081。
- 真实调用完成文字JSON和非临床图片验收卡识别，结果保存在 `.runtime/upgrade-real-runtime.json`。
- 真实BGE-M3建索引与BGE-reranker-v2-m3查询成功，返回 `vector+reranker`，无回退警告；报告 `.runtime/upgrade-retrieval-smoke.json`。仅验证可用性，不据此宣称召回改善。
- 46项后端测试通过；前端格式、类型检查、生产构建通过；12页面/8条隔离浏览器流程及手机布局通过。模型桩流程和真实模型检查分开记录。
- 前端锁定依赖更新至Vue3.5.45、Vite6.4.6、ECharts6.1.0，并修复图谱隐藏/零尺寸时的图形库兼容错误；npm依赖审计本轮返回0项。
- Python保持3.10.10；旧原文件、个人题库、模型和公开评测结果未删除。Ollama0.40.16作为可选便携后端保留；LM Studio完成协议兼容，未安装其GUI或宣称已实跑。
- 页面级视觉索引、PaddleOCR-VL和Qwen3-Embedding不在本轮已交付清单；正式医学对照、延迟和资源排名后续进行。
