# 爱快固件版本索引

每行一个 `版本_Build日期`，新版在前。同一版本的不同 Build 分开记录。

| x86 | 3.x | 4.x |
| --- | --- | --- |
| 免费版 | [版本列表](version_list.txt) | [版本列表](version_4_list.txt) |
| 企业版 | [版本列表](version_enterprise_list.txt) | [版本列表](version_4_enterprise_list.txt) |

[官方设备](devices/) 按型号各建一个 TXT，同型号的 3.x 和 4.x 放在一起。各设备以本型号列表为准。

[自动更新](https://github.com/zsz520/ikuai-firmware-index/actions/workflows/update-index.yml)在北京时间每天 **08:00、21:00** 查询爱快官方接口，追加新 Build，并为新型号创建 TXT。已有历史保留。

爱快小工具使用 [catalog.json](data/catalog.json) 获取完整索引。

[官方历史更新日志](official-history.md)按免费版、企业版收录官网发布的更新正文，每天北京时间 **08:30** 更新。没有 Build 的官网日志也会保留。

官网日志：[免费版](https://www.ikuai8.com/index.php?option=com_content&view=article&id=331) · [企业版](https://www.ikuai8.com/index.php?option=com_content&view=article&id=447) · [仅有日志、未验证下载的版本](release-notes-only.md)

历史对照：[LucienShui](https://github.com/LucienShui/ikuai-firmware) · [LOVECHEN](https://github.com/LOVECHEN/ikuai-release) · [shiniuniu](https://github.com/shiniuniu/ikuai-firmware-public) · [iKuaiPatch](https://github.com/iKuaiPatch/firmware_archive) · [bikefly](https://github.com/bikefly/ikuaifw)
