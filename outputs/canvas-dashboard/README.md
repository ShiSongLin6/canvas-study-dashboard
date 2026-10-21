# Canvas 学习看板

一个只在本机运行的 Canvas 课程作业看板。首次打开和手动刷新时读取 Canvas 最新状态；页面保持打开时每 3 分钟同步一次，切回页面也会立即更新。

## 使用前准备

需要 Windows、Python 3.10 或更高版本，以及已安装并初始化的 **Canvas Study Assistant** Codex Skill。本看板通过该 Skill 连接 Canvas API；它不会包含任何人的 Canvas Token。

首次连接时，在 Canvas 中依次打开：

`Account → Settings → Approved Integrations → + New Access Token`

生成 Token 后请立刻复制保存。不要把 Token 提交到 GitHub、粘贴到公开问题区，或发送给他人。

## 启动

下载或克隆本项目后，进入 `outputs/canvas-dashboard` 文件夹。双击 **Launch.bat** 启动并打开浏览器；双击 **Stop.bat** 停止本机服务。两者都通过本机安装的 Python 运行。

若浏览器提示 Canvas 连接尚未配置，请继续按下节操作。

## 修复 Canvas 连接

点击顶部 **设置 / 修复 Canvas 连接**，填写自己学校的 Canvas 地址（例如 `https://canvas.yourschool.edu`）和刚生成的 Token；若同步检测到连接问题，页面也会自动展开表单。默认先验证 Token，再保存到 Windows 凭证管理器。如果凭证管理器不可用，可自行勾选“只连接到本次看板运行”；这时 Token 只保存在服务内存，停止或重启看板后需要重新输入。若 Token 属于另一个 Canvas 账户，连接会拒绝覆盖现有账户。

## 看板内容

- **待完成 / 已逾期 / 已完成**：有截止日期的任务按 Canvas 作业提交记录统计。
- **无截止日期 / 历史任务 / 线下确认**：无截止日期不算待办；超过 180 天的逾期任务单独留作核对；无法在线提交的任务需要人工确认。
- **已结束课程**：Canvas 明确标记已结束的课程会收纳起来；若有至少 3 项有截止日期的作业、最近截止日已超过 30 天且这些作业都已完成，也会自动收纳。可用“查看已结束课程”恢复查看。
- **未来一周优先事项**：按最近截止时间列出未完成任务。
- **课程筛选**：查看单门课程的任务。
- **个人学习清单**：用户自建的本地事项，只保存在当前电脑，不会改 Canvas 的提交状态。
- **需线下确认**：对于 Canvas 不跟踪线上提交的任务，应用不会猜测是否完成。

## 数据与安全

- 服务固定绑定 `127.0.0.1`，只能从本机访问；没有外部托管服务、远程访问或第三方前端库。
- 页面连接表单会把 Token 发送到本机服务验证；Token 不会写入浏览器存储或项目文件。默认存入 Windows 凭证管理器；明确勾选临时连接时，只在服务内存中保存，并在服务停止时清除。
- 截止时间按 Canvas 账户设置的时区显示。
- 课程任务从 Canvas API 读取。个人学习清单保存在 `%LOCALAPPDATA%\CanvasStudyDashboard\study_tasks.json`。
- 关闭浏览器不会自动关闭服务；双击 **Stop.bat** 即可关闭。
## 注意

Canvas API 可能因课程权限、学校配置、网络或 Token 过期而返回部分数据。页面会提示无法读取的课程。页面中的任务状态同步自 Canvas；本地清单是个人计划，不会自动向 Canvas 提交作业。需要更新连接时，使用页面顶部的 **设置 / 修复 Canvas 连接**。

## 依赖与致谢

本项目是一个独立的本机学习看板界面。它通过开源项目 [Canvas Study Assistant Skill](https://github.com/hairoom/canvas-study-assistant-skill) 提供 Canvas 数据连接。该 Skill 负责：

- 连接 Canvas API。
- 验证和保存用户自己的 Token。
- 读取课程、作业和提交状态。

Canvas Study Assistant Skill 由社区开发者维护，采用 [MIT License](https://github.com/hairoom/canvas-study-assistant-skill/blob/main/LICENSE)；它不是本项目创建的，也不是 Codex 内置功能。
