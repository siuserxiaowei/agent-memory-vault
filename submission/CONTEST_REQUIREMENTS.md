# Production AI Skills 大赛要求对照

最后核对时间：2026-08-11（CST）

官方来源：

- 比赛页：<https://www.modelscope.cn/events/289/比赛介绍>
- 官方详情 API：<https://www.modelscope.cn/api/v1/competitions/289/detail>
- 官方引用的 Local AI Skill 标准：<https://github.com/openvino-dev-samples/local-ai-skill-authoring>

## 结论

Local Memory RAG 与比赛方向高度匹配。官方推荐场景明确列出“个人 PDF/笔记库 RAG、本地私人知识库智能问答、完全私有的个人数字第二大脑”。报名截止时间由官方 `RegistrationDeadline` 核验为 **2026-08-31 23:59:00 CST**。

官方表述中，Client/Server 与 OpenVINO 均为“推荐”；纯本地 Localhost、生产力 Agent 适配及在该环境完成指令测试才是明确约束。本项目已满足后三项，不声称已实现 OpenVINO/GPU/NPU 优化。

## 硬性要求与当前状态

| 官方要求 | 项目对应实现 | 当前证据/状态 |
|---|---|---|
| 本地 AI 工具解决真实生产力需求 | 从私人 Markdown/Obsidian 库找回决策、知识与工作流 | 已实现，真实库 15,446 篇 Markdown 完成 SQLite 索引 |
| 模型必须支持纯本地 Localhost 运行 | EmbeddingGemma 本地加载；服务仅接受 loopback | 已验证模型强制离线加载；`127.0.0.1:8765` 健康检查通过 |
| 适配 Qoder / WorkBuddy / TRAE Work 等生产力 Agent | 可移植 Skill，统一调用 `scripts/client.py` | 已安装至三个宿主 Skills 目录；Qoder 已真实跑通，WorkBuddy 未登录，TRAE Work 本机未安装 |
| 生产力 Agent 环境完成指令测试 | 宿主实际触发 Skill 并返回引用 | **已完成硬门槛**：Qoder 识别 Skill，执行三次本地客户端调用，两轮 `hybrid` 并返回相对 citation |
| 魔搭 Skills 中心发布并添加“AI PC”标签 | self-contained zip：`SKILL.md`、`info.json`、`meta.json`、固定 `run.ps1`、完整检索运行时、文档与包内测试 | 包结构与独立解压验收已完成；尚未发布，需用户最终授权 |
| 魔搭研习社文章含完整截图/录屏、优化心得与 Hybrid AI 思考 | `submission/ARTICLE.md` + 两张 Qoder 实证截图 + 演示脚本 + 证据清单 | 草稿与实证截图已准备；尚未发布，需用户最终授权 |
| 作品包含代码、文档、测试 | Skill 目录、references、unittest、覆盖率门、隐私检查打包器 | 已具备；zip 不依赖外部 Git 仓库即可建库、启动和关键词检索 |

## 评分映射

| 维度 | 权重 | 本项目可以证明的内容 | 下一项高收益工作 |
|---|---:|---|---|
| 场景价值 | 30% | 私人知识不出机；解决 Agent 无法持续利用个人知识的问题 | 用真实工作问题录一段完整演示 |
| 商用生产力 | 30% | Markdown 真源、SQLite + Zvec、鉴权、离线、并发串行、可维护脚本、Qoder 实际调用 | 以录屏补充截图证据，并进一步优化热查询延迟 |
| 工具使用 | 20% | Qoder/WorkBuddy/TRAE Work 适配、ModelScope 模型、Zvec | 若时间允许增加 OpenVINO 导出/基准；它是推荐项而非文字上的绝对硬门槛 |
| 文章质量 | 10% | 可复现步骤、架构图、隐私边界、真实 Qoder 截图、故障修复记录 | 发布前复核图片尺寸与专题标签 |
| 创新性 | 10% | 私有查询不进入进程参数；相对引用；真实 fallback 标记；宿主无关 | 对比“云端 RAG / 普通全文搜索 / 本地混合检索” |
| 传播附加分 | 5% | 官方要求小红书话题与账号 | 属于对外发布，未经用户授权不执行 |

## 官方流程中仍需人工完成的动作

1. 在魔搭 Skills 中心发布，添加“AI PC”自定义标签。
2. 在魔搭研习社发表文章并添加“Intel AI PC”专题标签。
3. 通过官方钉钉表单提交作品：<https://alidocs.dingtalk.com/notable/share/form/v01Q35O85pPVW83Al9V_dv19yqvsgs3oebp3pcjys_1qX0QQ0?source=link>

发布、发文和最终提交均会改变外部状态，必须取得用户明确授权后再执行。
