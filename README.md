# 爱快固件版本索引

版本文件参考 LucienShui/ikuai-firmware：每行一个 `版本_Build日期`，新版本在前，同版本的不同 Build 分开。列表不含下载链接、来源字段或表头。

| 类型 | 3.x | 4.x |
| --- | --- | --- |
| x86 免费版 | [version_list.txt](version_list.txt) | [version_4_list.txt](version_4_list.txt) |
| x86 企业版 | [version_enterprise_list.txt](version_enterprise_list.txt) | [version_4_enterprise_list.txt](version_4_enterprise_list.txt) |

官方设备按型号拆分：[devices/](devices/)。例如 [Q3000](devices/Q3000.txt)、[Q6000](devices/Q6000.txt)，一个文件同时记录该型号的 3.x 与 4.x。不要用其他型号或 x86 的 Build 代替。

GitHub Actions 每天北京时间 **03:17** 查询爱快 3.x 公开清单和 4.x 版本接口，当发现新版本或新 Build 时追加到历史目录。上游不再列出旧版本时，仓库已有历史仍保留。可在 [Actions](https://github.com/zsz520/ikuai-firmware-index/actions/workflows/update-index.yml) 手动运行。

设备型号从官方清单的固件文件名发现。3.x 清单或 4.x 汇总清单新增型号时会自动生成对应 TXT；4.x 也会继续查询汇总清单发现的型号和已知机型的专用清单。

小工具通过 [data/catalog.json](https://raw.githubusercontent.com/zsz520/ikuai-firmware-index/main/data/catalog.json) 一次获取完整目录和镜像来源；TXT 用于直接浏览、比较或复用版本号。仓库没有上传固件文件。日更不需要客户端下载证书或令牌。

历史列表也对照[爱快免费版更新日志](https://www.ikuai8.com/index.php?option=com_content&view=article&id=331)和[企业版更新日志](https://www.ikuai8.com/index.php?option=com_content&view=article&id=447)。只有日志记录、未找到可验证下载的版本列在 [release-notes-only.json](data/release-notes-only.json)，仅用于 TXT，不会在小工具里列为下载项。

历史来源与致谢：

- [LucienShui/ikuai-firmware](https://github.com/LucienShui/ikuai-firmware)
- [LOVECHEN/ikuai-release](https://github.com/LOVECHEN/ikuai-release/releases)
- [shiniuniu/ikuai-firmware-public](https://github.com/shiniuniu/ikuai-firmware-public/releases)

本地核对生成文件：`python scripts/update_index.py --check`。
