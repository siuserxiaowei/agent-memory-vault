# 参赛证据清单

## 已取得

- [x] 官方比赛 API：截止时间 `2026-08-31 23:59:00 CST`。
- [x] 官方推荐场景包含个人笔记 RAG、本地私人知识库问答、私有第二大脑。
- [x] SQLite 真实索引：15,446 篇 Markdown，155 个 open loops。
- [x] ModelScope 固定模型 revision：`480ee9b0e4761c35cf4f8295236b7b01b256b8cf`。
- [x] 17 个模型文件逐项 SHA-256 验证通过，manifest 权限 `0600`。
- [x] 强制 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 时模型加载成功，输出 768 维有限向量。
- [x] 26 个高价值 Knowledge Blocks 建立 54 个向量 chunk。
- [x] 语义改写命中正确 Knowledge Block，返回 `mode=hybrid`。
- [x] 两个并发语义查询均返回 `hybrid`，无 Zvec 锁降级。
- [x] 服务仅监听 `127.0.0.1`，Bearer Token 与配置权限 `0600`。
- [x] 对外结果不含绝对路径，私人查询不进入两层子进程参数。
- [x] `info.json`、`meta.json`、`agents/openai.yaml` 和 Skill validator 已通过。
- [x] 全量 79 项 unittest 通过，无 skip。
- [x] Skill 编排/服务 5 个脚本分支覆盖率 `82.4%`，质量门为 `80%`；内嵌索引后端另由原仓库全量回归覆盖，并有字节一致性测试防止副本漂移。
- [x] `compileall`、`agent_memory_check.py --skip-state-db` 通过。
- [x] 公开包泄漏扫描通过。
- [x] self-contained 确定性 zip 内含固定 `run.ps1`、SQLite/Zvec 后端、统一管理入口与包内测试。
- [x] zip 在临时目录解包后，不依赖外部仓库完成配置、Markdown 建库、loopback 服务启动、health 与关键词检索。
- [x] Zvec 跨进程锁同时具备 POSIX `fcntl` 与 Windows `msvcrt` 后端；真实 Windows 机器尚待复验。
- [x] Apple M4 / 24 GB / macOS 15.7.1 上预热后 5 次端到端混合检索中位数 `4.83s`，范围 `3.77–9.47s`。
- [x] Qoder 真实识别 `Skill local-memory-rag`，执行健康检查和两轮本地搜索。
- [x] Qoder 最终回答显示两轮 `mode=hybrid`，包含 SQLite + Zvec 与目标相对 citation。
- [x] Qoder 日志记录三次 `run_in_terminal`，最终 `chat_finish:success:200`。
- [x] 两张宿主截图已遮挡本机绝对路径，未包含 Token 或账号凭证。

## 宿主硬门槛

- [x] 至少一个 Qoder / WorkBuddy / TRAE Work 的真实成功调用截图或录屏。
- [x] 截图中能看到宿主调用、`mode=hybrid` 和相对 citation。

## 其他宿主状态（非投稿阻碍）

- Qoder：2026-08-11 已真实跑通，使用 `Qwen3.8-Max` 完成 4 个操作并生成带引用回答。
- WorkBuddy：桌面应用可启动，但当前未登录；真实 CLI session 返回 `Authentication required`。比赛只要求至少一个认可宿主完成指令测试，Qoder 证据已满足该项。
- TRAE Work：本机未安装，尚未单独验证。

不得把 Qoder 的成功扩大表述为“所有宿主均已跑通”。

## 发布前人工复核

- [ ] GitHub 仓库链接公开可访问且分支内容已合并或明确指定。
- [ ] 魔搭 Skill 添加“AI PC”标签。
- [ ] 研习社文章添加“Intel AI PC”专题标签。
- [ ] 文章、Skill 页和提交表单中的名称、作者、链接一致。
- [ ] 未上传模型权重、私人 vault、SQLite、向量库、Token 或绝对路径。
