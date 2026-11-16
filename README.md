# WeSnip — 微信风格截图工具

仿微信（Windows）截图交互的本地截图工具。Python + Tk + Pillow 实现，**除 Pillow 外零依赖**，
单文件 `wechat_snip.py`，无需安装、无需联网。

![自检渲染效果](_selftest/selftest_overlay.png)

## 功能

| 类别 | 说明 |
| --- | --- |
| 触发 | 全局热键 `Alt+A`（可配置），备用 `Ctrl+Alt+X`；也可双击脚本立即截图 |
| 冻结 | 触发瞬间 BitBlt 抓取整个虚拟桌面，画面冻结不闪屏 |
| 遮罩 | 全屏压暗 55%，选区内恢复原亮度（真 alpha 合成，非抖动模拟） |
| 吸附 | 鼠标悬停自动高亮所在窗口（跳过自身进程，按 z 序取最上层） |
| 选区 | 拖拽框选；8 向控制点调整大小；选区内拖动整体位移；`Ctrl+A` 全屏 |
| 标注 | 矩形 / 椭圆 / 箭头 / 画笔 / 马赛克 / 文字，8 色调色板循环切换 |
| 细节 | 尺寸标签 `宽 × 高`、跟随放大镜（像素网格 + 中心标记）、十字辅助线 |
| 输出 | 复制到剪贴板（CF_DIB + PNG 双格式）、另存为 PNG/JPG |
| 主题 | `--theme dark`（默认，微信 4.x 风格）/ `--theme light` |

## 快捷键

| 按键 | 动作 |
| --- | --- |
| `Alt+A` | 全局呼出截图 |
| `Ctrl+Alt+Q` | 退出常驻进程（全局生效） |
| `Esc` / 右键(无选区) | 取消退出 |
| `Enter` / `Ctrl+C` / 双击选区 | 复制到剪贴板并退出 |
| `Ctrl+S` | 另存为 |
| `Ctrl+Z` | 撤销上一步标注 |
| `Ctrl+A` | 全屏选择 |
| 选区内拖动 | 移动选区；控制点上拖动 | 调整大小 |
| 右键(有选区) | 菜单：复制 / 另存为 / 退出 |

## 运行

### 方式一：exe（推荐）

从 [Releases](https://github.com/tigerhe1995/WeSnip/releases) 下载 `WeSnip.exe` → 双击后台常驻（右下角弹"已就绪"提示）→ `Alt+A` 随时截图，`Ctrl+Alt+Q` 退出。
任务管理器里进程名显示为 `WeSnip.exe`，描述"微信截图工具"。

开机自启：双击 `开机自启管理.bat` → 自动检测并显示当前状态（英文菜单）→ 输入 `1` 开启/覆盖自启，输入 `2` 取消（写入 `HKCU\...\Run`，参数 `--daemon`）。
注意 bat 与 `WeSnip.exe` 需在同一目录（自启记录的是安装时的路径，移动 exe 后需重新设置）。该 bat 内容为纯 ASCII，任意语言环境均可直接运行。

重新打包（改动源码后）：

```powershell
pip install pyinstaller
python _make_icon.py        # 可选，重新生成图标
python -m PyInstaller --onefile --noconsole --name WeSnip --icon WeSnip.ico `
  --version-file version_info.txt --distpath . --workpath _build --specpath . wechat_snip.py
```

exe 默认行为 = `--daemon`（双击即常驻）；`WeSnip.exe --once` 也可显式传参。

### 方式二：源码

```powershell
python wechat_snip.py            # 立即截一次，之后常驻监听热键
python wechat_snip.py --once     # 截一次就退出（双击 微信截图.bat）
python wechat_snip.py --daemon   # 不立即截图，只等热键（双击 微信截图-常驻AltA.bat）
python wechat_snip.py --hotkey ctrl+alt+a --theme light
python wechat_snip.py --selftest out_dir   # 渲染自检，输出预览图
```

### 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--hotkey alt+a` | `alt+a` | 主热键，逗号分隔多个，如 `--hotkey ctrl+alt+a,f9` |
| `--once` / `--exit-after` | 关 | 完成一次截图后退出进程 |
| `--daemon` | 关 | 启动不截图，仅监听热键 |
| `--delay N` | 0 | 启动后延迟 N 秒再截图（截图倒计时用） |
| `--theme dark\|light` | dark | 工具栏主题 |
| `--save-dir PATH` | 我的图片 | 另存为对话框默认目录 |
| `--no-window-detect` | 关 | 关闭窗口悬停吸附 |
| `--no-hotkey` | 关 | 不注册全局热键 |
| `--selftest DIR` | - | 渲染自检：输出覆盖层/成品预览图并跑 32 项断言 |

> 若 `Alt+A` 被正在运行的微信占用，注册会失败并回落到 `Ctrl+Alt+X`；日志会打印注册结果。

### 关闭后台进程

按 `Ctrl+Alt+Q` 即可退出常驻进程（全局热键，任何界面下生效）。

命令行方式（按命令行精确匹配，不误伤其它 Python 进程）：

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*wechat_snip*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

提示：常驻 bat 重复双击会启动多个监听实例（第二个起 `Alt+A` 注册会失败、只有 `Ctrl+Alt+X` 生效），
建议只保留一个，多余的用 `Ctrl+Alt+Q` 或上面的命令清掉。

## 自检

```powershell
python wechat_snip.py --selftest _selftest
```

自动构造一次完整会话：渲染像素断言（遮罩亮度/边框/标注颜色/马赛克像素化）+
交互断言（框选/工具切换/绘制/撤销/取色/文字提交/收尾），共 32 项，全过输出 `EXIT=0`。

## 实现要点

- **抓屏**：`BitBlt(SRCCOPY|CAPTUREBLT)` + `GetDIBits` 直接取虚拟桌面物理像素，
  Per-Monitor V2 DPI 感知保证画布坐标 == 屏幕像素。
- **显示**：底层一张压暗全屏 `PhotoImage`，选区内叠一张合成裁剪图（原图 + 2x 超采样标注层），
  拖拽时仅重建选区裁剪图（~2-7ms），工具栏/放大镜/尺寸标签全部 alpha 合成，无 stipple 抖动。
- **导出**：标注以 2x 超采样 RGBA 层渲染后 LANCZOS 缩回，所见即所得；马赛克按块 NEAREST 像素化。
- **剪贴板**：`GlobalAlloc + SetClipboardData` 同时写 `CF_DIB` 与注册格式 `PNG`，
  旧版 Office 与新式应用都能粘贴。
- **热键**：独立线程 `RegisterHotKey` + `GetMessage` 消息泵，`PostThreadMessage(WM_QUIT)` 干净退出。

## 已知限制

- 多显示器且副屏位于主屏左侧（虚拟桌面负坐标）时窗口定位走 `SetWindowPos`，未在混合 DPI 下验证。
- 文字标注用内嵌 Entry，依赖系统输入法；极少数 IME 与无边框窗口组合可能有焦点时序问题。
- 滚动截图、OCR、二维码识别等微信在线功能不在范围。

## 文件

- `wechat_snip.py` — 全部实现（约 1200 行）
- `微信截图.bat` — 双击立即截一次
- `微信截图-常驻AltA.bat` — 双击常驻，Alt+A 呼出
- `_selftest/` — 自检输出的渲染预览图
