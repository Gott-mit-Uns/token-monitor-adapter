# Token Monitor Adapter 0.1.8

新增 macOS 后台缓存服务：默认每 5 分钟压缩下载与上传，客户端实时连接本机缓存，远端 SSE 不订阅。提供可回退安装、用户 LaunchAgent、凭据按需读取、状态页和正文流量计量。macOS 包需要 Python 3.9+，不需要额外依赖。

Windows 继续提供单文件 EXE，现有默认频率、DPAPI 凭据与运行数据路径保持兼容。

下载对应平台文件并核对 SHA256SUMS.txt；macOS 安装和卸载见 README.macos.md。发布物仅包含源码和程序，不含运行配置、凭据、缓存或用量。
