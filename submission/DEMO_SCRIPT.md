# Local Memory RAG 演示脚本

目标时长：90–120 秒。录屏前开启勿扰模式，关闭含私人文件名的侧栏，不展示 Token、绝对路径或完整笔记正文。

## 已取得的宿主截图

- `assets/evidence/qoder-local-memory-rag-operations.png`：Qoder 识别 Skill 并执行本地客户端操作链。
- `assets/evidence/qoder-local-memory-rag-success.png`：Qoder 显示两轮 `hybrid` 与相对 citation。

两张图只遮挡本机路径，未改动 Qoder 的调用结果。正式录屏仍可按下述脚本复现，以获得更完整的传播素材。

## 镜头 1：问题与隐私边界（10 秒）

画面展示架构图，口播：

> 生产力 Agent 很聪明，但默认不知道我过去的项目决策和个人知识。把整个笔记库上传云端又不适合隐私资料。Local Memory RAG 把模型、索引和检索都留在本机，只把带相对引用的证据交给 Agent。

## 镜头 2：服务健康（10 秒）

在终端运行：

```bash
skills/local-memory-rag/scripts/run.sh health --json
```

只展示以下字段：

```json
{
  "status": "ok",
  "runtime_ready": true,
  "index_ready": true,
  "semantic_ready": true,
  "network_scope": "loopback-only",
  "model_network": "offline-only"
}
```

## 镜头 3：生产力 Agent 调用（45 秒）

在 Qoder、WorkBuddy 或 TRAE Work 新会话中输入：

> 请使用 local-memory-rag 从我的本地知识库回答：模型越来越强以后，什么样的能力包仍然值得长期保留？不要联网搜索。请报告检索 mode，并为结论给出相对 Markdown 引用。

录到以下完整证据链：

1. 宿主识别或加载 `local-memory-rag`。
2. 宿主通过 Skill 实际调用打包内客户端搜索。
3. 工具结果显示 `mode=hybrid`。
4. 第一条语义结果引用：`03_Knowledge Blocks/KB-20260714-0021-Skill价值来自项目知识反馈环持久状态和风险升级.md`。
5. Agent 用自己的话总结：值得保留的是能带入项目知识、连接反馈环、保存跨会话状态或触发高风险审查的窄能力包。

若宿主没有实际调用工具、返回 `keyword_fallback`、出现绝对路径，或引用并非来自工具输出，本次录制作废并排查。

## 镜头 4：离线与降级诚实性（20 秒）

演示其一：

- 断开外网后重复语义查询，仍返回 `hybrid`；或
- 暂时移开本地向量索引，显示 `keyword_fallback`，说明系统不会把关键词兜底伪装成 RAG。

优先录制第一种。第二种涉及修改派生状态，只在可恢复副本或临时配置上操作。

## 镜头 5：收束（15 秒）

画面回到架构图，口播：

> 这里 Markdown 仍是人可读、可 Git 管理的事实源；SQLite 处理精确检索，EmbeddingGemma 与 Zvec 处理只记得大意的查询。宿主可替换，私人知识与本地模型不出机。

## 录屏验收

- [x] 截图能看出使用的是官方认可的 Qoder 宿主。
- [x] 截图能看出 Skill 被真实调用，不是手工在终端伪造结果。
- [x] `mode=hybrid`、相对 citation 和结论同时入镜。
- [x] 截图没有 Token、Cookie、账号凭证、绝对路径或不必要的私人正文。
- [x] 没有声称当前尚未实现的 OpenVINO/GPU/NPU 加速。
