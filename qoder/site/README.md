# Qoder Sites 展示站

「知栈 StudyStack」的项目展示页，已通过 **Qoder Sites** 发布为公开站点：

**https://studystack-ca1ud5cmym8.qoder.zone**

## 结构

```
site/
├── src/            # 源文件：index.html / style.css / app.js / assets（截图 jpg）
├── build.mjs       # 构建：把 src/ 复制到 dist/
└── dist/           # 构建产物（提交时忽略，node build.mjs 可重建）
```

纯静态、零依赖，不需要 npm install。

## 构建与本地预览

```bash
cd qoder/site
node build.mjs
open dist/index.html
```

## 发布记录

| 项目 | 值 |
| --- | --- |
| 站点 URL | https://studystack-ca1ud5cmym8.qoder.zone |
| 访问策略 | public（无痕窗口可直接打开） |
| 发布工具 | Qoder CLI `sites`（`prepare_site` → `publish_site` → `get_publish_status`） |
| actionId | `97181b86-9c6b-456d-b1f7-812e24b9f2c1` |
| siteId | `01a18384-1ce1-70cf-ae31-3f64fc729e4e` |
| projectId | `01a18384-1cdd-7d53-ae87-c60f433ee4cc` |
| 首次发布 | 2026-10-29 |

### 重新发布（内容更新后）

```bash
cd qoder/site
node build.mjs
qoderclicn sites prepare_site --input '{"actionId":"<新 UUID>","projectRoot":"<site 绝对路径>","webDirectory":"dist","displayName":"知栈 StudyStack","slug":"studystack"}'
qoderclicn sites publish_site --input '{"actionId":"<同一个 UUID>"}'
qoderclicn sites get_publish_status --input '{"actionId":"<同一个 UUID>"}'
```

站点目录下会生成 `.知栈 StudyStack.qoder.site` 描述文件（本地绑定记录，不入库）。
