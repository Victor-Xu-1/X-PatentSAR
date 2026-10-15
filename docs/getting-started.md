# X-PatentSAR：开始使用

当前支持 Linux / WSL2 x86-64，主程序使用 Python 3.12。源码构建还需 Git、uv 0.11.31 与 Node.js 24.21.x。

在 Linux 原生目录中执行：

```bash
git clone https://github.com/Victor-Xu-1/X-PatentSAR.git
cd X-PatentSAR
uv sync --frozen --extra web
npm --prefix frontend ci
npm --prefix frontend run build
uv run python tools/build_frontend.py
uv run x-patentsar serve --port 8765
```

打开 <http://127.0.0.1:8765>。服务仅支持回环地址；不要让多个服务共用一个正在使用的状态目录。已构建的 Web wheel 包含界面，运行时无需 Node.js。

在顶栏打开“环境管理”，审阅依赖、下载内容与许可证，确认“一键部署全部环境”。软件检查并复用合格组件，将缺失的 PDF/OCR/RDKit、DECIMER、受限手性兜底和 ADMET 组件安装到独立私有环境，全部验证通过后才启用新配置。

这一步需要网络、磁盘空间和模型运行资源。仓库与应用 wheel 不包含科学模型权重；安装器不配置 WSL、系统软件、GPU/CUDA 或付费服务。DECIMER/TensorFlow 与主程序使用不同 Python 环境，不应混装。

环境就绪后，在新任务页选择原始 PDF，点击“开始提取”。详细安装、配置和恢复方法见 [使用与运维说明](OPERATIONS.md)。

## 命令行

科学环境配置完成后，可先运行检查，再处理一份 PDF：

```bash
uv run x-patentsar check-envs
uv run x-patentsar health --no-gpu --output /tmp/patentsar-health.json
uv run x-patentsar run \
  --pdf /path/to/patent.pdf \
  --output /path/to/dedicated-output \
  --patent-id YOUR_PATENT_ID \
  --gpu-mode off
```

每份专利使用独立输出目录。完整参数见 `uv run x-patentsar --help` 和 `uv run x-patentsar run --help`。


## 配置与隐私

常规解析不调用外部 LLM。可选 API 默认关闭，启用前需明确授权局部证据外发并确认费用；保存密钥本身不代表允许发送专利材料。真实密钥与运行数据应保存在仓库外。

配置优先级为环境变量、外部 `*.local.yaml`、外部 `*.yaml`、打包默认值。模板见[环境变量示例](../.env.example)与[配置示例](../examples/config/)。未使用的解释器覆盖变量应保持空值，以免覆盖环境管理保存的有效配置。

## 输出与验收

默认严格失败关闭。`--allow-partial` 仅保留复核材料，不代表通过 QA；阶段工具与诊断命令不替代正式主链。Excel 可以保留待复核记录，SDF 仅含合格分子；文件已生成不代表科学验收通过。

不要让多个进程写同一结果目录，也不要把专利、模型、缓存、日志或凭据提交到 Git。中断恢复、运行资源与构建 wheel 的完整说明见[使用与运维文档](OPERATIONS.md)。
