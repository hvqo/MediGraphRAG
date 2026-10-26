# 源码与语言整理记录

日期：2026-10-27。工作分支：`refactor/medigraphrag`。

## 为什么显示 Jupyter Notebook

原仓库的三个 Notebook 总计约 2.12MB，而改造分支整理前的 Python 源码约
215KB、Vue 源码约 52KB。Notebook 文件体积含大量执行输出和元数据，
不能由语言占比判断应用后端的运行方式。原应用后端已经是 Python/FastAPI，前端是 Vue。

GitHub 通过 Linguist 统计语言，而且仓库统计在推送到**默认分支**后更新。
本次仅修改改造分支，不合并 main、不更改默认分支；所以仓库首页仍可能显示旧统计。
参见 [GitHub 官方说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-repository-languages)。

## 已进行的真实迁移

| 原位置 | 新位置 |
| --- | --- |
| `medigraph/*.py` 与 API 实现 | `backend/app/*.py` |
| `web/frontend` | `frontend` |
| `utils`、`agent` | `legacy/utils`、`legacy/agent` |
| `docx/process` 中的 Python 原型 | `legacy/prototypes` |
| `docx` 中的开发说明与图片 | `docs/legacy` |
| `dataProcess.ipynb` | `legacy/experiments/data_pipeline.py` |
| `dataProcess_tex.ipynb` | `legacy/experiments/textbook_pipeline.py` |
| `ragProcess.ipynb` | `legacy/experiments/rag_pipeline.py` |

三份 Notebook 的 61 个代码单元全部迁出，包括 56 个有内容的单元；
说明文字单独保存，执行输出和 kernel 状态不复制进代码。原文件仍能从 Git 历史恢复。
记录原文件、代码单元和导出文件 SHA256 的清单见 `legacy/notebook_migration.json`。

历史实验中原有的硬编码路径、模型调用和无限重试不作为新版任务执行方式。
迁出的代码放在 `historical_pipeline()` 中，不会因导入模块自动执行。
两处通配导入展开为显式导入，以保证函数是合法 Python。其余原代码保留作研究参考，
并不宣称旧实验已全部改造成生产流水线。正式离线任务由后端 CLI 提供。

## 正式启动与命令

```powershell
python -m pip install -e .
cd frontend
npm ci
npm run build
cd ..
medigraphrag serve
# 也可以直接从仓库根目录执行：
python main.py
python -m backend.app.cli import-documents ./my-medical-documents --recursive
python -m backend.app.cli search "医学关键词"
python -m backend.app.cli build-index
```

数据目录仍默认是根目录 `.runtime`，本次整理不搬走或删除本地知识库、模型和密钥。
`web.api.main` 和 `web.backend.app` 暂时保留为兼容导入别名，不含重复业务实现。
根目录不再有 `docx` Python 包，避免遮蔽第三方 `python-docx`。

## 规范与检查

- Python 包元数据及 CLI：`pyproject.toml`。
- Python 后端 `.py`；Vue 页面 `.vue`，辅助逻辑 `.js`，样式 `.css`。这些都保留真实语言。
- `.gitattributes` 仅规范换行与资料/模型属性，不把 Notebook JSON 冒充 Python。
- 移除未使用的 Vite 欢迎页和示例图标，新增格式检查与 GitHub Actions。
- `python scripts/check_repository.py` 检查零 Notebook、Python 语法和完整源码迁出。
- 后端测试、前端格式与构建、浏览器检查继续独立运行。

GitHub 的正式语言占比未在本地用 Linguist 重新计算，因此不承诺具体百分比。
修改默认分支或合并 main 需要用户另行指示，本次不执行。
