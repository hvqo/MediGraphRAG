# Windows 本地环境

项目目录：`E:\chatgpt\rag\MediGraphRAG\MediGraphRAG`

虚拟环境：`E:\chatgpt\rag\MediGraphRAG\.venv`

## Python 版本

初次使用原有 Python 3.12.6 安装 MetaGPT 0.8.2，pip 明确报错：

```text
0.8.2 Requires-Python <3.12,>=3.9
No matching distribution found for metagpt==0.8.2
```

因此按仓库推荐切换为 Python 3.10.10。原有 3.12 环境保存在上一层的
`.venv-py312-backup`，没有删除。

## 依赖适配

- 原 `requirements.txt` 保留。Windows 使用 `requirements-windows.txt` 和锁定文件。
- `yaml` 是导入名称，对应安装包为 `PyYAML`。
- Windows 使用 `faiss-cpu==1.7.4`；PyTorch 独立使用 NVIDIA 显卡。
- MetaGPT 0.8.2 将 typing-extensions 锁定为 4.9.0，与 PyTorch 2.6.0 的
  `typing-extensions>=4.10.0` 冲突，因此选择 CUDA 12.1 版 PyTorch 2.2.2。
- MetaGPT 锁定的 `lancedb==0.4.0` 已无法从 PyPI 获取。本地兼容包
  `metagpt==0.8.2+medigraphrag.1` 仅将依赖改为可获取的 `lancedb==0.14.0`，
  不修改 MetaGPT Python 源码。项目使用 Neo4j 和 FAISS，未使用 LanceDB 检索。
  此适配不代表 MetaGPT 的所有其他功能均已验证。
- `scripts/prepare_windows_metagpt.py` 可从官方 wheel 重新生成本地兼容包。
- 火山引擎 SDK 的源码构建会触发 Windows 路径长度限制，因此先从短目录
  构建官方源码为 wheel。`scripts/prepare_windows_sdk.py` 可重复执行此步骤，
  并核对 PyPI 提供的源码 SHA256。

## 重新安装

在项目目录打开 PowerShell：

```powershell
$python = '..\.venv\Scripts\python.exe'
& $python -m pip download --no-deps metagpt==0.8.2 --dest .environment-wheels
& $python scripts/prepare_windows_metagpt.py
& $python -m pip install setuptools==65.6.3 wheel==0.45.1
& $python scripts/prepare_windows_sdk.py
& $python -m pip install torch==2.2.2 --index-url https://download.pytorch.org/whl/cu121
& $python -m pip install --find-links .environment-wheels -r requirements-windows.lock.txt
& $python -m pip check
& $python scripts/check_environment.py
Push-Location frontend
npm.cmd ci
npm.cmd run build
Pop-Location
```

无需激活环境，直接使用完整解释器路径即可。PyCharm 应选择
`E:\chatgpt\rag\MediGraphRAG\.venv\Scripts\python.exe`；旧环境显示名称
可能仍含 Python 3.12，应重新选择解释器以刷新显示。

## 改造后的启动与可选能力

新版工作台直接运行 `..\.venv\Scripts\python.exe main.py` 即可打开。
资料导入、关键词检索不依赖 BGE、Neo4j 或旧索引。可选能力需要：

1. 下载 BGE 嵌入模型和重排模型的完整权重及真实分词器文件。
2. 启动 Neo4j 5.26，配置数据库连接并导入图谱。
3. 在设置页面为当前资料库重建新向量索引，不复用旧数据库的内部节点映射。
4. 在页面设置实际使用的 Ollama 或云端模型。旧工具配置中的原作者云端凭据已移除，
   默认改为本地 Ollama。当前机器已有 qwen2.5 模型。

`config/config.yaml` 为旧工具保留，基础目录为相对路径。新版应用配置集中在
`backend/app/config.py`、本地 `.env` 与页面设置中；缺少索引不会阻止后端启动。

## 已完成的验证（2026-10-23）

- `pip check`：No broken requirements found。
- PyTorch 2.2.2+cu121：已在 RTX 4050 Laptop GPU 上实际执行矩阵运算。
- FAISS 1.7.4：小规模向量写入和查询通过。
- MetaGPT Team、Action、Role，以及项目知识清洗和出题模块导入通过。
- LangChain、Transformers、Gensim、FastAPI、Uvicorn、Neo4j 驱动导入通过。
- 前端 `npm ci` 和 `npm run build` 成功。
- 完整结果见 `environment-check.json`，实际安装清单见 `environment-packages.json`。

以上为改造前环境验证记录。改造后的接口、浏览器和真实本地模型验证见
`docs/PROGRESS.md`；机器检查报告保留本地，不上传到 Git。
