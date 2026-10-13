---
version: 3
watermark:
  enabled: false
preferred_type: conceptual
preferred_palette: mono
preferred_rendering: flat-vector
preferred_text: title-only
preferred_mood: balanced
preferred_font: clean
default_aspect: "2.35:1"
language: zh
preferred_image_backend: auto
quick_mode: true
default_output_dir: imgs-subdir
---

本项目按用户要求提供开箱即用的完整公众号制作流程，默认采用这些设置直接出图。
中性浅色背景，使用 #0FDC78 作少量强调；封面标题沿用文章标题。
保存提示词后调用 当前 Agent 可用的原生生图工具（Codex 中为 imagegen），复制产物到当前文章目录的 assets/。
用户本次指定的风格、比例和后端优先。


每篇同时交付 2.35:1 横版和 1:1 正方形小封面。小图使用短标题，独立构图，保存为 assets/cover-square.png。
