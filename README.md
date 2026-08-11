# 浏览器 AI 助手

这是一个 Chrome/Edge 浏览器扩展。点击图标会在浏览器右侧打开 Side Panel，历史对话会自动保存并恢复。浏览器 AI 已封装为 Agent，支持本地长期记忆、读取 Skill 工作流，以及把生成的文本/数据保存到项目 `outputs/` 文件夹。正式发布包已经包含 Python 运行时和服务依赖，普通用户不需要安装 Python、pip 或配置环境变量。

## 普通用户安装

1. 解压发布包。
2. 双击 `install.bat`，等待窗口提示“安装完成”。
3. 在浏览器打开 `chrome://extensions`（Edge 使用 `edge://extensions`），开启“开发者模式”，点击“加载已解压的扩展”，选择包内的 `browser-extension` 文件夹。
4. 点击扩展图标右上角的设置按钮，填写自己的 DeepSeek API Key 并保存。

安装脚本会自动注册 Native Messaging、启动本地服务；以后打开扩展会自动拉起服务。移动整个目录后再次双击 `install.bat` 即可修复路径注册。

macOS 用户在项目目录运行 `bash install.command`（正式 macOS 发布包会自带 `runtime/bin/python3`），安装脚本会自动注册 Chrome、Edge 和 Chromium 的 Native Messaging 清单。

完整的图文使用说明（含安装、配置、首次使用和故障排查截图）见 [使用说明.html](使用说明.html)，直接双击即可离线打开。

如果双击安装脚本窗口立即关闭，请重新下载最新版；也可以在项目文件夹打开命令提示符运行 `install.bat`，脚本会在结束时保留窗口并显示错误原因。

## Manus 风格的复杂任务执行

- **先规划再执行**：当任务包含多个页面操作或需要生成交付物时，Agent 会在侧边栏展示分步计划。
- **实时进度**：每一步会显示待处理、进行中、已完成或失败状态，工具执行过程也会以易读的时间线反馈。
- **随时停止**：长任务执行期间点击侧边栏的“停止”，即可取消当前任务；已保存的文件和浏览器已完成的操作会保留。
- **结果沉淀**：要求导出或保存的报告、CSV、JSON 等文件会写入项目 `outputs/` 文件夹，便于继续处理或分享。

## 开发者构建免环境发布包

```powershell
python scripts/install.py
python scripts/build_release.py
```

`dist/browser-ai-assistant` 就是可直接分发的目录。API Key 只保存在用户本机，不要将包含个人密钥的配置文件提交或打包。

发布脚本使用白名单，只复制扩展、服务、Native Host、安装脚本、运行时和使用说明；日志、测试、长期记忆、`config.local.json`、Skill、`outputs` 及开发缓存都会被排除。

运行发布构建脚本的平台决定运行时平台：macOS 安装包请在 macOS 上构建，不能直接把 Windows 目录复制给 Mac 用户。

如果使用未授权的解压扩展，Native Messaging 还需要把扩展 ID 传给安装脚本：

```powershell
$env:BROWSER_ASSISTANT_EXTENSION_ID = "扩展页面显示的 32 位 ID"
python scripts/install.py
```
