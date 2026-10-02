# 项目范围

此仓库是公开的 Windows/macOS 适配器项目 `Gott-mit-Uns/token-monitor-adapter`。修改、测试、构建和 Release 必须在本仓库完成。Windows EXE 和 macOS 服务共享缓存核心，平台凭据与启动入口分别维护。NAS Docker Agent 的更新属于 `Gott-mit-Uns/token-monitor-nas`，不可混发。

更新前阅读 `README.md` 和 `VERSIONING.md`。保留 Windows 用户的数据目录、DPAPI 凭据和原客户端配置迁移兼容性。仅提交源码与合成测试，不提交本机运行配置、同步密钥、缓存、日志或用量。发布前完成文档列出的测试、历史安全扫描及 Windows EXE 自检；草稿构建失败不得发布。
