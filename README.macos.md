# macOS 缓存适配服务

需要已配置 HTTPS Hub 的 Token Monitor，以及 Python 3.9 或更新版本（建议 Python 3.12）。不需要额外 Python 包。此安装包提供后台服务与浏览器状态页，不包含 Windows 托盘或 WebView2 界面。

从 Release 下载 `TokenMonitorAdapter-macOS.tar.gz` 并校验 `SHA256SUMS.txt`，解压后执行：

```sh
sh scripts/install-macos.sh
```

安装先检查 `127.0.0.1:17322` 端口、客户端凭据和远端统计，再备份并修改客户端连接，安全退出并重新启动 Token Monitor。需要已登录的 macOS 图形会话；不使用 sudo。端口冲突时不结束其他程序。安装需要退出客户端，所以请先保存客户端中未保存的设置。

默认下载与上传均为 5 分钟。Token Monitor 实时向本机提交快照；适配服务只每 5 分钟发送最新待上传数据，无新数据跳过。远端下载主动请求 gzip，不订阅远端 SSE。本地 SSE 和重复读取使用缓存，其他只读接口按需按 5 分钟缓存周期刷新。手动同步在 60 秒内合并重复请求。

打开 <http://127.0.0.1:17322/adapter> 查看缓存年龄、远端成功时间、上传状态和正文流量。默认安装使用内置状态页；浏览器状态页不显示凭据。缓存可用不代表远端刚同步成功；故障时继续显示旧数据并报告过期。

服务与独立 venv 位于 `~/Library/Application Support/TokenMonitorAdapter`，LaunchAgent 为 `~/Library/LaunchAgents/io.github.gott-mit-uns.token-monitor-adapter.plist`。venv 不安装第三方依赖，仍依赖创建它的基础 Python；不要删除基础 Python。LaunchAgent 使用固定绝对路径，登录启动、异常恢复。缓存、待上传和计量保留在该用户目录，目录权限 700、运行文件权限 600。

凭据每次按需读取 `~/Library/Application Support/Token Monitor/credentials.json`，不复制到适配器配置。密钥轮换后重启 Token Monitor 以更新它自己的本地认证；适配器无需复制新密钥。不将凭据、用量、缓存或备份放到源码仓库。

修改频率：先停止 LaunchAgent，再编辑适配服务目录的 `config.json` 中 `interval_seconds` 和 `upload_interval_ms`，之后重新加载服务。客户端的“上传频率”只控制向本机提交，应保持实时。

升级：先 `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/io.github.gott-mit-uns.token-monitor-adapter.plist`，再运行新包安装脚本并传 `--upstream https://你的Hub地址`。原始连接备份不会被后续安装覆盖。

卸载并恢复原连接：

```sh
sh scripts/uninstall-macos.sh
```

也可使用安装后的固定入口：

```sh
"$HOME/Library/Application Support/TokenMonitorAdapter/runtime/bin/python3" \
  "$HOME/Library/Application Support/TokenMonitorAdapter/service/macos_service.py" uninstall
```

卸载保留缓存与备份，仅停止适配服务、移除 LaunchAgent、恢复原客户端连接。恢复只改连接字段，保留后来修改的其他设置；如果用户已自行切换到另一 Hub，则拒绝覆盖，改为手动参考备份。源码测试使用合成数据；发布包仅含 `adapter.py`、`macos_service.py`、安装/卸载脚本、文档和许可证。
