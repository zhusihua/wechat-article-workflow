# 本地运行与产物约定

工作区：仓库根目录。Agent 完成安装与执行，无需用户逐条输入命令。首次运行见根目录 README。下列命令以 macOS/Linux 为例，Windows 使用 `.venv/Scripts/python.exe`。

```bash
workflow/.venv/bin/python workflow/wechat.py doctor
workflow/.venv/bin/python workflow/wechat.py new --topic "把 AI 写作工具接成公众号工作流"
workflow/.venv/bin/python workflow/wechat.py new --input "/绝对路径/文章.md"
workflow/.venv/bin/python workflow/wechat.py render "/本篇绝对路径"
```

`new` 返回本篇绝对路径。不复用其他文章状态；原 Markdown 字节不变，复制本地图片，提取 front matter 标题与摘要。
读取全部输入后再写。`source.md`、`draft.md`、`humanized.md` 与 `final.md` 角色分明；后两者由 当前 Agent 写作编辑生成，CLI 不会假装自动生成。

任务书和主张清单按上游 WeWrite schema 写入本篇，来源账本记录 URL、支持的主张、发布方、核对时间和证据类型。
风格没有本人样本时按项目默认语气，不把调研报告或其他人的文章认作用户文风。只读相关上游模块，不运行热点选题或另启全流程。

## 审核文件

先完成正文及图位，再获取 SHA-256：

```bash
shasum -a 256 "/本篇绝对路径/final.md"
```

`assessment.yaml` 结构：

```yaml
decision: pass
pass_number: 1
reviewed_sha256: "这里填写刚刚实际计算的终稿哈希"
dimensions:
  accuracy: 4
  viewpoint: 4
  usefulness: 4
  voice: 4
  readability: 4
blockers: []
major_issues: []
notes: "描述实际检查与修正；不宣称独立审核"
```

示例分数仅展示格式；依据实际编辑判断填写。配图或新增内容改了 `final.md`，必须重新审阅并更新哈希。
图片内容与表达关系也要检查，不把文字审核分数当作视觉验收。

## 图片与排版

默认封面 `assets/cover.png`，提示词 `assets/prompts/01-cover-话题.md`。选定生图后端完成后从返回路径复制到本篇，再实际打开检查。
原文里的本地 PNG/JPEG/WEBP/GIF 自动复制，HTML 通过路径映射引用副本；原文不被覆盖。远程图片只保留链接，不后台下载。
SVG、图片缺失或其他格式要明确处理，不生成占位图冒充完成。

终稿可以保留 Mermaid 代码块；`render` 用安装好的 Mermaid 和 Chromium 转成 PNG，正文用图片替换，不把图的源码展示给读者。
图太宽或字太小时重排图，不能缩小字体来掩盖。正文代码须保持内容不变，默认表格最多 4 列、正文图最多 10 张是本地制作约束。

`render` 产物：

- `final.md`：权威终稿，保持不变。
- `rendered.md`：Mermaid 已替换为图片的中间稿。
- `article.html`：WeWrite 内联样式正文，图片用相对路径。
- `preview.html`：自包含本地预览，嵌入图片，提供富文本复制按钮。
- `review.json`：由实际编辑判断生成的报告，绑定终稿哈希。
- `delivery.json`：图片、正文哈希、兼容性结果、就绪状态与未验证边界。
- `publish.zip`：标题/摘要说明、终稿、HTML、预览及图片，另含已解析本地图片和流程图的 `article.md`。

使用目标 Agent 的文件预览工具或浏览器打开预览。复制标题、摘要与排版正文后在公众号编辑器设置封面；正文图若粘贴未导入，上传文件包内图片。

## 可选草稿接口

用户明确要求送草稿箱才执行：

```bash
workflow/.venv/bin/python workflow/wechat.py draft "/本篇绝对路径"
```

可本地配置 `workflow/state/config.yaml`（不写入版本记录或交付包，权限 600），或设置 `WECHAT_APPID`、`WECHAT_SECRET`、`WECHAT_AUTHOR`。
`doctor` 只报告环境变量是否存在，不输出值；草稿命令也可从秘密文件读取。后台 API 权限及出口 IP 需要在实际账号核对，不根据本地检查宣称可用。
`draft-receipt.json.status=created` 且返回 media_id 才能说草稿已创建；未知状态不得重发。
