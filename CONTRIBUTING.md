# 贡献指南

**简体中文** | [English](CONTRIBUTING.en.md)

感谢贡献！本仓库采用「数据与展示分离」的架构：

- [`data.yaml`](data.yaml) —— 数据入口，包含元信息、分类定义，并通过 `includes` 引用各分类文件
- [`data/`](data/) —— 论文条目按分类拆分存放（`driving.yaml` / `embodied.yaml` / `general.yaml`）
- [`README.md`](README.md) / [`README.en.md`](README.en.md) —— 中英文主页，由脚本同时生成，**请勿手动编辑**

## 添加/修改条目

1. 编辑对应分类的文件 `data/<category>.yaml`（如自动驾驶条目放入 `data/driving.yaml`），
   在 `papers` 列表中按如下格式添加条目：

```yaml
- title: "论文完整标题"        # 必填
  short: 简称                  # 可选，用于表格中加粗显示
  org: 机构名                  # 可选
  org_en: Organization name    # org 含中文时必填；org 已为英文时可省略
  year: 2025                   # 必填，首次发表年份（表格中统一以 (year) 显示）
  venue: 会议/期刊名           # 必填，未正式发表填 arXiv；无需带年份
  category: driving            # 必填，见下方分类 id
  links:
    arxiv: "2501.00000"        # arXiv 编号（不含域名）
    project: "https://..."     # 项目主页，可选
    code: "https://..."        # 代码仓库，可选
    demo: "https://..."        # 在线演示，可选
  features:                    # 交互能力，按实际情况填写，可留空 {}
    action: true               # 动作条件生成
    realtime: true             # 实时推理
    closedloop: true           # 闭环支持
    longhorizon: true          # 长时序一致性
  tags: [标签1, 标签2]          # 可选，自由关键词
  note: 一句话中文点评          # 必填，说明该工作的核心贡献与交互特性
  note_en: English summary     # 必填，与中文点评保持相同信息、数字与限定条件
```

2. 把 `data.yaml` 里 `meta.updated` 改成今天的日期（README 的「最后更新」读这一行，不要用 git 提交日）。

3. 本地同时重新生成中英文 README：

```bash
pip install pyyaml   # 首次需要
python scripts/generate_readme.py
```

4. 将修改的 `data/*.yaml`、`data.yaml`、`README.md` 与 `README.en.md` 一并提交 PR。CI 会检查两版是否与数据同步；缺少英文点评或机构翻译时，生成脚本会指出对应条目。

首页介绍的英文翻译位于 `data.yaml` 的 `meta.subtitle_en` 和 `meta.description_en`；分类英文名使用 `name_en`。更新介绍或点评时，请同步修改对应译文。

如需更新两版的每月论文统计图，运行：

```bash
pip install matplotlib
python scripts/generate_monthly_chart.py
```

月份取自 arXiv 编号，截止月份取自 `meta.updated`。将生成的两张 `assets/monthly-paper-counts*.png` 一并提交。

## 自动扫描维护

每日扫描逐个抓取配置中的 arXiv Atom 分类订阅源。达到 2,000 条上限的分类会标为覆盖不完整。扫描器在本地用 `feed_keywords` 匹配完整标题和摘要，组内为 OR、组间为 AND，分类筛选包含交叉分类。请求串行发送，间隔至少 5 秒，并遵守 `Retry-After`。[检索配置](scripts/arxiv_config.yaml) · [arXiv 订阅说明](https://info.arxiv.org/help/rss.html) · [限流规则](https://info.arxiv.org/help/api/tou.html#rate-limits)

每次运行将有效分类的原始 XML 上传为 `arxiv-atom-snapshot-${{ github.run_attempt }}` artifact，保留 90 天。覆盖记录按分类分别保存，从每个分类的首份有效非空快照开始，跟踪美国东部时间周一至周五的潜在缺期。空订阅或过期订阅不会推进覆盖日期。节假日也可能列为待核查项。[覆盖记录](data/arxiv_scan_coverage.json) · [Atom 日期定义](https://info.arxiv.org/help/atom_specifications.html#atom-entry-elements)

运行摘要分别展示扫描覆盖和发布结果。覆盖有待核查项时，工作流仍会发布已取得的有效候选。抓取全部失败、快照归档失败、候选发布失败或扫描状态保存失败时，运行标为失败。

用 `--dry-run` 预览结果，预览不会写入状态。用 `--replay PATH` 只读回放已保存的原始 Atom XML，可重复传入该参数以一起回放多个分类快照。修改关键词时，保持 `feed_keywords` 和手动 API 补扫使用的 `search` 条件同步。可以运行测试并回放快照来验证改动。

```bash
python3 -m unittest discover -s tests
python3 -u scripts/fetch_arxiv.py --replay /path/to/atom.xml
python3 -u scripts/fetch_arxiv.py --dry-run
```

手动补扫同时传入 `--backfill-from YYYY-MM-DD` 和 `--backfill-to YYYY-MM-DD`。分页按 UTC 提交日期检索，包含首尾两天，最多 14 天。周一公告可能包含上周四、周五提交的论文，选补扫区间时要覆盖相应的提交期。补扫结束后，公告缺口仍需独立核查。独立核对某日所有待核查分类或确认该日休刊后，可用 `--reviewed-date YYYY-MM-DD` 确认该日期。该参数作用于同一天所有待核查分类，可重复传入以复核多天。[arXiv 公告时程](https://info.arxiv.org/help/availability.html#announcement-schedule)

更新推送后，通过 **Actions → Daily arXiv scan → Run workflow → main** 新建运行。手动补查填写 `backfill_from` 和 `backfill_to`，复核日期填写 `reviewed_dates`，多天用空格分隔。重新运行旧任务仍使用原提交，抓取步骤会打印实际提交号。

## 收录标准

- 工作需以**可学习的动态模型**对世界进行预测/生成，并服务于自动驾驶或具身智能
- 优先收录支持**动作条件**或**交互式控制**的工作；纯视频预测工作请在 `note` 中说明其与交互性的关系
- 请确保 arXiv 编号、venue 等信息准确；不确定时宁缺毋滥

## 分类说明

| category id | 范围 |
| :--- | :--- |
| `driving` | 面向自动驾驶的世界模型（数据引擎、神经仿真、预测规划） |
| `embodied` | 面向机器人/具身智能体的世界模型 |
| `general` | 通用世界模型、世界基础模型、神经游戏引擎等 |
