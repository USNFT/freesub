# freesub 改进版 — 部署清单（DEPLOYMENT.md）

> 基于博主"小何爱分享"教程（2026-09-06）的 freesub 方案，已修复 3 个确凿缺陷并强化 10+ 处。
> 所有改动已通过编译 + 14 项单元测试 + 真实抓源 dry-run 验证。
> 教程原文三部分（改名字/加订阅源/调间隔）的位置全部变了，以下标出新位置。

---

## 〇、本版改了什么（先看这个）

| 级别 | 改动 | 原版问题 |
|---|---|---|
| 必修 | **hy2 真测活**：引入 sing-box 内核，428 个 hysteria2 节点真实测活后才出库 | 原版 L474 直接跳过 hy2，"支持 hysteria2 测活"是假的 |
| 必修 | **README 的 Cloudflare Worker 代码修复** | 原版 URL 拼接混入 markdown 语法，私仓订阅必 404 |
| 必修 | **Xray/sing-box 版本动态获取**（GitHub API 拉最新，失败用兜底） | 原版锁死 Xray 1.8.24（2024 年旧版） |
| 必修 | **Windows 本机可跑**：自动下载对应平台内核 | 原版只下 Linux 版，本机"一键部署"必失败 |
| 重要 | reality 节点补 `short-id` + `flow` 参数 | 原版丢弃，reality 节点在 Clash 里连不上/断流 |
| 重要 | 延迟过滤（>2500ms 剔除）+ 按延迟排序出库 | 原版乱序、无门槛 |
| 重要 | 测活改多探针（2 次取最快） | 原版单次握手，抖动误杀 |
| 重要 | 出口 IP 探测 4 个 API 兜底 | 原版 2 个，全挂时家宽专区清空 |
| 重要 | workflow 加 concurrency 防重叠 + mmdb 缓存 + 30 分钟超时 | 原版重叠 run 会 git push 冲突 |
| 重要 | 节点名后缀可配置（NODE_SUFFIX 常量） | 原版要改 714 行 f-string |
| 一般 | 国家名表扩充到 55 国 | 原版只有 18 国，其余显示裸代码 |
| 一般 | `--dry-run` 自检模式 + `--suffix` 参数 | 原版无自检，换源只能盲跑 |
| 一般 | README 增加风险提示 + Worker 令牌改 Secrets 注入 | 原版教用户把永久 PAT 写死在代码里 |

---

## 一、部署路径（二选一）

### 路径 A：GitHub Actions 自动更新（博主主推，推荐）

1. **Fork 本仓库**到你自己的 GitHub 账号（网页上点 Fork）。
2. **修改专属名字**：`scripts/main.py` 顶部"可调参数"区（约第 38 行）：
   ```python
   NODE_SUFFIX = "xiaohe"   # 改成你的名字，例如 NODE_SUFFIX = "myname"
   ```
   原教程让你改 714 行附近——现在改这一行就行，效果一样（节点名 = `国旗 地区 序号 - 你的名字`）。
3. **添加订阅源**（可选）：同一文件的 `SOURCE_URLS` 列表（约第 23~34 行），格式、类型、递归解码逻辑与原版完全一致，直接加即可。
4. **调整更新间隔**（可选）：`.github/workflows/update.yml` 第 8 行 cron，默认每 6 小时：
   ```yaml
   - cron: '0 */6 * * *'    # 每 6 小时
   - cron: '0 0 * * *'      # 每天 UTC 0 点
   ```
5. **检查 Actions 权限**：仓库 Settings → Actions → General → Workflow permissions 确认 **Read and write permissions**（默认开）。
6. **手动触发第一次构建**：仓库 Actions 页 → "Update Subscriptions" → Run workflow，看日志直到 `测活完成！真实可用落地节点总数: N`，等 git commit 出现。
7. **验证输出**：确认仓库里出现 `output/v2ray.txt`、`output/clash.yaml`、`output/by-country/` 等，README 表格数字刷新。
8. **订阅链接**：用 README 表格里的 CDN/Raw 直链导入 Clash / v2rayN / sing-box。

### 路径 B：本机跑（临时用 / 换源自检）

Windows / Linux 均可（内核自动按平台下载）：

```bash
cd E:\code\freesub-improved
.venv\Scripts\python.exe scripts\main.py --dry-run    # 只抓源+解析，10 秒级自检
.venv\Scripts\python.exe scripts\main.py --suffix myname   # 完整跑：下载内核→真连测活→出库 output/
```

> 注意：完整测活从本机跑，需要本机网络能直连 `google.com/generate_204`。
> 国内网络不通 Google 时所有节点都会判死（测活 0 节点）——这正是 GitHub Actions（海外）跑的另一个原因。
> 本机环境已验证：dry-run 全过、10 源全通、5639 节点可解析。

---

## 二、部署后验收清单

- [ ] Actions 第一次运行成功（绿色 ✓），日志出现"测活完成！真实可用落地节点总数"
- [ ] 仓库出现 `output/` 且 git 有 `Auto Update:` 提交
- [ ] `output/v2ray.txt` 解开 base64 后节点名带你的 `NODE_SUFFIX`
- [ ] 订阅链接在 Clash Verge / v2rayN 里能拉取、能连通
- [ ] `output/residential.txt` 非空（家宽专区，取决于当期池子，可能很少或为空——正常）
- [ ] 把 `NODE_SUFFIX` 的修改提交到 fork 的分支再观察下一次自动构建

## 三、可选进阶：私有仓库 + Cloudflare Worker（防节点链接泄露）

原 README 的 Worker 代码有 URL bug，本版已修复，且令牌改为 Secrets 注入：
1. 仓库改 Private（或新建私有 fork）。
2. Cloudflare Dashboard → Workers → 新建 Worker → 粘贴 `scripts/main.py` 生成的 README 里那段修复后的代码。
3. Worker → Settings → Variables and Secrets → 添加加密变量 `GITHUB_TOKEN`（私有仓库才需要；公开仓库留空）。
4. 订阅地址：`https://你的域名.workers.dev/v2ray.txt` 等。

**注意**：GITHUB_TOKEN 需为 classic PAT（repo 权限），存进 Secrets 后代码里只读 `env.GITHUB_TOKEN`，永远不要写死在源码里。

## 四、使用红线（务必遵守）

1. **免费节点不可信**：节点运营者理论上可记录流量。**严禁**用免费节点登录网银、邮箱、公司系统、社交账号。
2. 测活 = "海外经该节点通 Google"，≠ 国内实际速度，晚高峰会劣化。
3. 家宽/住宅 IP 是启发式判定（ASN + 反解析），可能误判，不承诺"干净 IP"。
4. 本仓库改动未上传 GitHub，`git push` 与否、是否 fork 部署，由你决定。
