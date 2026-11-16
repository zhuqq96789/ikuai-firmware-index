# 爱快固件历史索引

汇总三个公开项目中爱快 3.x / 4.x 的 BIN 和 ISO 条目，按完整固件文件名去重。保留不同型号、架构、版本与 Build；同一个文件的多个公开来源会保留在同一行。仓库只维护索引和更新脚本。

- [下载 history.txt](https://raw.githubusercontent.com/zsz520/ikuai-firmware-index/main/history.txt)
- [更新运行记录](https://github.com/zsz520/ikuai-firmware-index/actions/workflows/update-index.yml)

GitHub Actions 每天北京时间 **03:17** 检查更新（GitHub 的实际调度时间可能延后），也可在 Actions 页面手动运行。有内容变化才提交。单个上游不可用时保留它上次的记录；全部失败时保留原索引。

索引是 UTF-8 文本。每个数据行是“完整文件名、Tab、来源列表（JSON）”。来源编号依次为 0、1、2；第二列的各来源为 `[编号, 索引或 Release 标签, 可选资产文件名, 可选 SHA-256]`，未指定资产名时使用第一列文件名。日期是最近一次内容变更的北京时间。

来源与致谢：

- [LucienShui/ikuai-firmware](https://github.com/LucienShui/ikuai-firmware)：项目索引结构的参考，提供 x86 历史 Build 文本。
- [LOVECHEN/ikuai-release](https://github.com/LOVECHEN/ikuai-release/releases)：已发布资产及归档报告。
- [shiniuniu/ikuai-firmware-public](https://github.com/shiniuniu/ikuai-firmware-public/releases)：公开设备固件及校验资料。

运行校验：`python scripts/update_index.py --check`。本地刷新：`python scripts/update_index.py`。
