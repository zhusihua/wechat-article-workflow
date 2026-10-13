# 本地制作层

安装、跨 Agent 接入和一句话用法见 [根目录 README](../README.md)。

统一入口：[wechat-article-workflow](skills/wechat-article-workflow/SKILL.md)。

- `wechat.py`：new / render / doctor / draft。
- `download_sources.py`：恢复固定上游快照，按 Git blob SHA-1 校验；`--verify` 仅核对。
- `render_mermaid.mjs`：Mermaid → SVG / PNG。
- `check_preview.mjs`：移动端与桌面布局、图片、复制负载检查。
- `requirements.lock.txt` / `package-lock.json`：Python / Node 依赖锁。
- `preferences.yaml`：文章默认偏好。
- `runtime.json`：本机安装器生成，不进入 Git。

研究、写作、中文编辑与审稿由当前 Agent 完成；脚本不调用第二个写作模型。
