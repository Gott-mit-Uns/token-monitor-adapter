# Token Monitor Adapter for Windows / macOS

保持 Token Monitor 原界面和多设备用量查看，使用本机缓存减少热点下载。此工具不是 Token Monitor 采集器，需同时运行原客户端。

Windows/macOS Adapter 的独立仓库为 `Gott-mit-Uns/token-monitor-adapter`。NAS Docker Agent 位于 [token-monitor-nas](https://github.com/Gott-mit-Uns/token-monitor-nas)，两者分别维护和发布。历史 `adapter-v0.1.0` 至 `adapter-v0.1.7` 已迁入本仓库；迁移保留原 EXE 与校验值。后续版本规则见 [VERSIONING.md](VERSIONING.md)。

## macOS

macOS 提供用户级后台缓存服务，默认压缩下载和上传均为 5 分钟。无需第三方 Python 依赖；安装、状态页、恢复连接与卸载见 [macOS 文档](README.macos.md)。Windows 默认周期保持不变。

## Windows 使用

从本仓库的 [Releases](https://github.com/Gott-mit-Uns/token-monitor-adapter/releases) 下载 `TokenMonitorAdapter.exe` 和 `SHA256SUMS.txt`。支持 Windows 10/11 x64，需要 Microsoft Edge WebView2 Runtime 及系统 .NET Framework 4.7.2 以上，不需要 Python。首次运行打开设置，填写 HTTPS Hub 地址与同步密钥。密钥留空可加密复用当前用户 Token Monitor 的已有密钥，保存后不回显。

默认压缩下载 10 分钟、远端上报 30 分钟。两个周期均由 Adapter 控制，支持 1/5/10/15/30 分钟。客户端实时向本机提交最新快照，持久化后确认接收；本地确认不表示远端已收到。勾选“接入 Token Monitor”会先备份配置，再将原客户端 Hub 地址设为本机地址并设为实时本地提交；需要重启原客户端使设置生效。取消勾选时不调整原客户端；Adapter 仍按自身周期发送已收到的新快照，客户端提交较慢时不能保证每周期都有新数据。

关闭窗口立即释放独立界面及其 WebView2 子进程，托盘和同步继续运行；最小化保留窗口。未保存设置关闭前会询问是否丢弃。托盘可打开窗口、手动同步或退出整个适配器。重复运行 EXE 会打开已有窗口。开启登录启动后，EXE 被复制到 `%LOCALAPPDATA%\Programs\TokenMonitorAdapter`，以 `--background` 运行；关闭开关移除当前用户启动项。

配置与运行数据在 `%LOCALAPPDATA%\TokenMonitorHotspotAdapter`。升级时从托盘退出，替换 EXE 后重新运行；若使用登录启动，再保存设置以更新固定目录中的 EXE。移动原始下载文件不会破坏已设置的登录启动。

## 流量与可靠性

界面使用固定底部导航。概览同时展示累计与今日上传、下载和总流量，今日按本机自然日计算。流量统计与同步历史默认显示最近 30 天，支持本月、上月、全部与自定义日期，每页 30 条；汇总覆盖整个筛选范围，只显示有记录的日期。筛选和翻页只读取本机记录，不产生远端请求。接口流量明细位于流量统计页；计量说明和原始诊断位于设置页“帮助与诊断”。

计量按接口累计记录请求正文与收到的响应正文；gzip 下载按压缩大小记录，不含 HTTP 头、TLS、重传和其他进程流量。失败次数是历史累计；“无待上报”不是每一条历史数据均已送达的证明。

待上报数据写入本地 pending 文件，只保留最新快照；无新数据跳过上传。上传互斥与快照代次防止旧成功清除新上报，正常退出与重启保留缓存和计量。网页轮询只读本地状态，本地 SSE 不订阅远端 SSE。普通读取在缓存到期时可能合并发起该端点应有的一次下载。

远端凭据与本地客户端认证分离。密钥使用当前 Windows 用户 DPAPI 加密，不能复制到其他账号后解密。仅监听 127.0.0.1。设置桥接仅在内嵌窗口提供，普通浏览器不能修改设置。程序不自动更新、不发送遥测。

## 后台恢复（0.1.7）

缓存只在更新时保存；快照逐次原子保存，磁盘失败返回本地保存失败并保留最新内存数据，不误报网络故障。请求计量与结果合并保存，升级兼容原文件格式。

同步线程记录心跳和阶段。内部异常按 5/10/20/40/60 秒退避，死线程在确认结束后重建。120 秒没有进展时停止后台，20 秒不能退出才终止旧进程；主进程按 2/5/10/30/60 秒重启，稳定五分钟后复位。重启可能幂等重传最新快照，不承诺跨文件严格一次发送。诊断区提供脱敏健康摘要。

后台主进程不加载 WebView2；独立 UI 通过限当前用户、拒绝远程连接的命名管道读写设置，主进程核对已登记 UI 进程身份。仅提供读取设置、保存设置和退出应用三类调用，未增加 HTTP 设置接口。

## 构建与测试

在 Windows x64 Python 3.12 独立环境执行：

```powershell
python -m pip install -r requirements-build.txt
python -m unittest discover -p "test_*.py"
python -m PyInstaller --clean --noconfirm TokenMonitorAdapter.spec
.\dist\TokenMonitorAdapter.exe --self-test --root "$env:TEMP\adapter-smoke"
```

自检在指定目录产生 JSON 回执，必须包含 `ok=true`、`frozen=true`。`--root` 用于隔离测试；默认本地端口不自动改变，被占用时不会终止其他程序。

源码、合成测试与通用资源采用仓库 MIT 许可。依赖沿用各自许可。发布工作流仅打包明确列出的页面与图标，不纳入本机配置、凭据、缓存、测试回执、审计文件或个人截图。Windows EXE 暂未进行代码签名。

## 回退

迁移前保留旧适配器程序、启动项及数据目录备份。回退先退出 EXE，再恢复旧程序和原启动项，保留最新缓存与计量；必要时恢复 `backups` 中接入前的 Token Monitor 设置并重启原客户端。旧版读取客户端密钥，新版加密密钥不改变原凭据。不要在旧版与新版同时占用同一端口时启动。

## Windows Hub 地址切换（0.1.9）

有待上报数据时明确询问是否迁移，取消保留原地址。确认后验证目标 Hub 并自动备份，保留最新快照切换。验证失败不保存地址或密钥；保存成功前检查后台已加载新地址。设置页显示后台实际地址。备份在数据目录 backups/hub-switch-*。

## Token Monitor 0.67 额外同步（0.1.14）

支持会话标题、模型别名与分组、自定义单价的额外同步协议；在 Token Monitor 设置中自行开启需要的项目，不会自动共享标题。标题共享仍需远端 Hub 允许。额外读取首次按需下载，随后按 Adapter 下载周期使用缓存；重复权限请求合并，不连接远端 SSE。明确修改共享设置和标题权限是即时远端操作，不等待用量上传周期，因此会产生少量额外请求；历史上报次数仍仅统计用量 POST，所有接口正文流量均计入接口计量。

共享设置保留服务器版本冲突，冲突时重新读取并由客户端确认，不自动强制覆盖。缓存可能在下一个下载周期后才显示其他设备的修改。老 Hub 未支持时会返回不支持，并按周期限制探测。兼容与测试范围见 COMPATIBILITY.md。
