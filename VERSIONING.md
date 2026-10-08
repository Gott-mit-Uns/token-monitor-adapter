# Adapter 版本与发布规则

- 本仓库维护 Windows/macOS Token Monitor Adapter，公开仓库地址为 https://github.com/Gott-mit-Uns/token-monitor-adapter。
- 应用版本取自 `desktop.py` 的 `VERSION`，必须与 `macos_service.py` 一致，采用三段数字，例如 `0.1.8`。Git tag 与 Release 沿用 `adapter-v<版本>`，例如 `adapter-v0.1.7`；下一版为 `adapter-v0.1.22`。
- Adapter 版本独立于 Token Monitor 官方版本及 NAS 版本。不要在本仓库发布 NAS Docker 镜像，也不要把 Adapter 更新推送到 `token-monitor-nas`。
- 发布前运行所有 `test_*.py` 测试、`check_release.py` 和 `scripts/check-publication-safety.py`。Windows CI 必须完成单文件 EXE 构建及冻结程序自检，才可发布。
- 推送版本 tag 后，工作流创建包含 `TokenMonitorAdapter.exe`、`TokenMonitorAdapter-macOS.tar.gz` 与合并的 `SHA256SUMS.txt` 的草稿 Release；确认构建成功后发布并设为 Latest。已公开发布的程序与固定 tag 不覆盖。
- 发布包不包含个人配置、凭据、缓存、用量、日志或本机数据。程序升级继续复用现有 LocalAppData 路径，不因仓库迁移改变用户数据目录。
- 本仓库的历史源码通过原 `windows-adapter/` 目录拆分而来，保留相关提交历史；历史 Release 的二进制文件直接迁移，未重建。
