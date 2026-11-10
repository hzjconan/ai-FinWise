# 训练流程可视化

直接用浏览器打开 `robot-training-flow.html`，不需要 Node、网络或项目后端。包含单 batch 更新回放、30 轮真实曲线、完整恢复 / 重置 Adam 对照。所有数值来自 L13 实测；浏览器只回放记录，不执行模型训练。

`robot-training-flow.svg` 是同一概念流程的静态版本，`robot-training-flow-preview.png` 是浏览器渲染预览，适合直接查看或分享。

## 文档交互验收

本目录属于教学文档，不修改管理端或客户端应用。用真实浏览器直接打开本地文件检查交互，不需要数据库或服务。测试依赖 Node >=18、Playwright 1.59.1 和本机 Google Chrome；网页本身不依赖这些测试工具。

```bash
cd docs/ai-agent-learning/visuals
npm install
npm test
```

本机默认 PATH 的 Node 版本较旧，可用 `/usr/local/bin/node robot-training-flow.test.cjs`。测试默认使用本机 Chrome，可通过 `VISUAL_BROWSER_CHANNEL` 调整为已安装的 Playwright 浏览器通道。

检查参数更新顺序（backward 不改权重、step 后需重新前向）、末步与重置、自动回放、31 条实测轮次、checkpoint 模式、键盘切换、手机无横向溢出，以及页面无需任何 HTTP 请求。截图默认输出系统临时目录；显式设置 `VISUAL_SCREENSHOT_DIR` 可重新生成预览图。
