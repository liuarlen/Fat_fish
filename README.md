# 肥鱼译文 · 原位对照翻译

一个用 **Qt 6 / PySide6** 开发的 Windows 桌面 PDF 翻译工具。

左边保留原文 PDF，右边把译文写回**同一页的同一个位置**：不重排、不另起一页，
图片、表格线、页眉页脚和整体版式都不动。

默认接入 **B站 Index-Translate 免费接口**，无需注册、无需 API Key、联网即用；
也可以选择 **Google 翻译**（网页免费接口，视网络环境），或配置百度、有道、腾讯云、
阿里云，以及 DeepSeek / 通义千问 / 智谱等大模型。
同时内置术语库与翻译记忆库，已经翻过的句子会沉淀成你自己的翻译资产。

![主界面](docs/screenshot.png)

翻到第 2 页时左右栏仍保持同步，页码、滚动位置和缩放一致：

![第 2 页](docs/screenshot_page2.png)

## 1. 功能一览

| 能力 | 说明 |
| --- | --- |
| 左右对照 | 左右两栏显示同一份 PDF，滚动、翻页、缩放保持同步 |
| 原位覆盖 | 译文按段落的原始坐标覆盖原文；右侧是实时预览，导出时由 PyMuPDF 精确写回 |
| 版式不变 | 只替换文字，图片/矢量图形/表格线保留；支持删除原文或底色覆盖两种导出模式 |
| 免费在线 | **B站 Index-Translate**（默认）与 **Google 翻译**网页接口，免注册、免 Key；公共接口，建议轻量使用 |
| 国内翻译 | 百度翻译开放平台、有道智云、腾讯云 TMT、阿里云机器翻译 |
| 大模型 | OpenAI 兼容接口：DeepSeek、通义千问（百炼）、智谱 GLM、Kimi，也可自定义 |
| 本地翻译库 | SQLite 术语库 + 翻译记忆库；精确/模糊命中；保存位置可在设置中更换 |
| 自动积累 | 在线翻译结果自动写入记忆库；双击任意段落可人工校对，修正后写回记忆库 |
| 离线演示 | 附带两页示例 PDF 和 29 条中文演示语料，无网络、无 API Key 也能完整查看效果 |
| 导出 | 原位译文 PDF、左右对照 PDF、中英对照 CSV |
| 隐私 | 密钥用 Windows DPAPI 加密；只发送待翻译的文本段落，不上传 PDF 文件 |
| 体验 | 拖拽打开、异步解析、按需栅格化、进度与停止、浅色现代界面、快捷键 |

默认免费在线的实际运行效果（30/30 段，无需任何 Key）：

![默认免费在线](docs/free_online.png)

### 界面截图

| 欢迎页 | 设置 |
| --- | --- |
| ![欢迎页](docs/empty.png) | ![设置](docs/settings.png) |

| 本地翻译库 | 单段校对 |
| --- | --- |
| ![翻译库](docs/library.png) | ![校对](docs/correction.png) |

## 2. 快速开始

### 环境要求

- Windows 10 / 11
- Python 3.9 – 3.12
- 系统自带中文字体（微软雅黑 / 等线 / 宋体之一）

### 安装与启动

```bat
:: 第一次使用：创建 .venv 并安装依赖（需联网，约 1–3 分钟）
install.bat

:: 启动
run.bat
```

也可以手动运行：

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py

:: 打开指定 PDF 并自动开始翻译
.venv\Scripts\python app.py 文档.pdf --auto
```

双击 `demo.bat` 会直接打开示例文档，自动用本地演示库翻译，适合第一次体验。
遇到启动问题可运行 `debug.bat`（保留控制台和错误输出）。

> 如果本机已经有可用的 PySide6 / PyMuPDF 环境，`run.bat` 会优先使用项目下的
> `.venv`，其次兼容同一工作区已存在的运行环境；全新机器请先执行 `install.bat`。

### 第一次体验

- **免费在线（默认）**：双击 `run.bat` 后，把任意 PDF 拖进窗口，点「开始翻译」。
  使用 B站 Index-Translate 公共免费接口，不需要填写任何 Key，但需要联网。
- **完全离线**：双击 `demo.bat` 会打开示例并强制使用本地演示库，不产生网络请求。
- 也可以点「查看示例文档」；默认会调用免费在线翻译，若网络不可用可切到「本地演示库」。

1. 等待右栏逐段覆盖中文译文；
2. 选「导出 → 译文 PDF」即可得到成品；
3. 要翻译自己的文件：把 PDF 拖进窗口或点「打开 PDF」。

## 3. 如何配置翻译服务

在右上角打开「设置 → 翻译服务」。付费云服务需要自己的账号和密钥，应用本身不内置密钥；
B站与 Google 的免费网页接口不需要填写。

| 服务 | 需要填写 | 申请入口 |
| --- | --- | --- |
| **B站 Index-Translate（免费）** | 无需填写 | <https://github.com/bilibili/Index-Translate> |
| **Google 翻译（网页免费）** | 无需填写 | <https://translate.google.com/> |
| 百度翻译开放平台 | APP ID、密钥 | <https://fanyi-api.baidu.com/> |
| 有道智云 | 应用 ID、应用密钥 | <https://ai.youdao.com/> |
| 腾讯云机器翻译 TMT | SecretId、SecretKey、地域 | <https://cloud.tencent.com/product/tmt> |
| 阿里云机器翻译 | AccessKey ID、AccessKey Secret、地域 | <https://help.aliyun.com/product/30313.html> |
| 大模型 | Base URL、模型名、API Key | 见下方预设 |

大模型预设：

| 预设 | Base URL | 默认模型 |
| --- | --- | --- |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 通义千问（百炼） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |

设置页提供「测试连接」，会发送一句很短的测试文本验证密钥和网络。
大模型会整页合并请求，能保留上下文，术语一致性也更好；常规文本翻译服务按页批量请求。

> B站与 Google 接口都是公共网页接口，不是带 SLA 的付费云 API；可能限流、排队或临时变更。
> Google 在中国大陆通常需要代理，B站免费接口在境内一般可直连。它们适合试译、个人轻量
> 文档和紧急使用；重要或大批量文档建议配置付费服务或大模型。

![Google 翻译选项](docs/google_settings.png)

### 选择建议

- **免费 / 先试**：使用默认的「B站免费翻译」，不需要任何 Key。
- **能直连 Google**：选「Google 翻译（网页免费）」；大陆网络不通时会提示换线。
- **完全离线**：选「本地演示库」。示例文档可以完整翻译；其他文档只有命中你自己的
  术语库/记忆库时才会出现译文，其余段落会保留原文。
- **日常快速翻译**：百度或腾讯云 TMT，国内访问稳定，按量计费。
- **正式文档 / 术语一致性要求高**：大模型 + 本地术语库，质量最好。
- **先试再决定**：任何在线服务都可以先点「测试连接」，不会产生大段消费。

## 4. 本地翻译库：让软件越用越懂你

数据保存在 SQLite 中，设置页和「翻译库」按钮都可以管理。保存位置也可以自定义：
**设置 → 本地翻译库 → 更改位置…**，选择一个目录即可，库文件名固定为 `library.sqlite`。

- 目标目录没有库时，会把当前库**复制**过去并切换；原文件保留作备份；
- 目标目录已有库时，可以选择「使用目标库」或「迁移当前库并覆盖」；
- 切换在保存设置后立即生效，不需要重启；下次启动会继续使用新位置；
- 配置文件里的路径写入 `settings.json` 的 `library_dir`。

默认位置仍是 `%APPDATA%\YiPagePDF\library.sqlite`。

![翻译库保存位置](docs/library_settings.png)

### 工作顺序

翻译每一段时：

1. **术语库精确命中**（整段与术语条目完全一致）；
2. **记忆库精确命中**（同一原文、同一目标语言）；
3. **记忆库模糊命中**（相似度高于阈值，默认 0.84）；
4. 以上都没有，才请求在线服务；
5. 在线译文自动写入记忆库（可关闭）。

因此重复内容、重复文档和多人长期使用会越来越快。选择「本地演示库」时，还会额外读取
随应用附带的 29 条示例译文，它们不会混进你的正式记忆库。

批量翻译时如果大模型/网页接口返回的条数与原文不一致，程序会自动二分重试，仍不一致
则逐段翻译，避免因为 23/25 这种数量对不上而整页失败。

### 校对与积累

在右侧译文上**双击任意段落**，可以修改译文；保存后会：

- 立即更新当前页面的原位预览；
- 以 `manual` 质量写入记忆库，下一次优先使用；
- 无需重新翻译整篇文档。

### 术语表导入 / 导出

「翻译库 → 导入 CSV」支持带表头的 UTF-8 CSV：

```csv
source,target,source_lang,target_lang,note
calm technology,安静的技术,en,zh-CN,核心术语
Urban Systems Lab,城市系统实验室,en,zh-CN,机构名
```

也可以从界面导出当前术语库或记忆库，方便备份和迁移。

> 术语库目前会在整段精确匹配以及大模型/B站免费翻译的提示词中生效；如果使用百度/有道等
> 通用接口，建议把术语写进记忆库句子，或使用大模型以获得稳定的术语控制。

## 4.1 Windows 便携版

如果拿到的是 `Fat_fish-Windows便携版-v1.2.1.zip`：

1. 解压**整个压缩包**，得到 `Fat_fish` 文件夹；
2. 双击 `Fat_fish.exe`，不需要安装 Python；
3. `_internal` 目录是运行库，不能单独删除或只拷贝 exe；
4. 详细使用说明在包内 `使用说明.txt`。

便携版已实测：启动、默认免费在线翻译 30/30 段、中文原位渲染、导出 PDF；
本地演示库和离线模式也通过测试。B站免费接口不需要 Key；百度/有道/腾讯/阿里/大模型
仍需填写你自己的账号密钥。

![打包版运行截图](docs/packaged.png)

## 5. 原位替换是怎么做的

1. **抽取**：PyMuPDF 以 `dict` 模式读取文字，按字号、行距、横向重叠等几何规则，
   把很多 PDF 里“一行一个 block”的内容重新合并成段落。行距阈值会跟随版面的实际
   行距节奏自适应，因此双倍行距、宽松行距、首行缩进和悬挂缩进不会再被切成一行
   一块；只有明显空行或真正换段才分开。双栏仍然不会串栏。
2. **翻译**：逐页交给本地库或在线服务；整页共享上下文，避免逐词碎片化。
3. **预览**：右栏直接绘制原文位图，再按文字块坐标覆盖译文；覆盖色从页面位图中采样，
   因此浅色卡片、米色引用框上不会出现突兀的白块。中文字体会根据原文区域自动换行、
   居中/右对齐，并在必要时缩小字号。
4. **导出**：用 PyMuPDF 的 redaction 精确删除原文字符（保留图片和矢量图形），
   再用 `TextWriter` 把译文写到原来的基线上；最后子集化中文字体，生成可搜索、可复制的 PDF。

右栏预览与导出的 PDF 使用同一份段落坐标和字号策略，因此版式基本一致；
预览是实时绘制的，导出文件则由 PDF 引擎重新落字，个别极窄区域可能有细微差异。

## 6. 快捷键

| 快捷键 | 功能 |
| --- | --- |
| `Ctrl+O` | 打开 PDF |
| `Ctrl+Enter` | 开始翻译 |
| `Ctrl+S` | 导出原位译文 PDF |
| `Ctrl+L` | 打开翻译库 |
| `Ctrl+,` | 打开设置 |
| `Ctrl+滚轮` / `Ctrl+=` / `Ctrl+-` | 缩放 |
| `Ctrl+0` | 适应宽度 |
| `PageUp` / `PageDown` | 上一页 / 下一页 |
| 拖拽 PDF 到窗口 | 打开文件 |

## 7. 数据与隐私

默认数据目录：

```
%APPDATA%\YiPagePDF\
├─ settings.json      设置；API 密钥经 DPAPI 加密，library_dir 记录翻译库位置
├─ library.sqlite     术语库 + 翻译记忆库（可在设置中改到其它目录）
└─ app.log           运行日志
```

- PDF 文件本身永远不会上传。
- B站/Google 免费接口会收到待翻译的**段落文本**；其它在线服务同理，只发送文本。
- 使用「本地演示库」时全程不联网。
- 偏好设置里的密钥在当前 Windows 用户下加密，换用户或换电脑无法直接解密。
- 想清空本地资产，关闭应用后删除 `library.sqlite` 即可；删除 `settings.json` 会重置配置。

## 8. 项目结构

```
pdf-translator-qt/
├─ app.py                 入口（GUI / --demo / --check）
├─ core/
│  ├─ extract.py          段落抽取、逐行合并、字体/坐标分析
│  ├─ render.py           原位写回、对照 PDF、字体子集化
│  ├─ providers.py        百度 / 有道 / 腾讯 / 阿里 / 大模型
│  ├─ pipeline.py         本地库优先 → 在线翻译 → 记忆沉淀
│  ├─ library.py          SQLite 术语库与翻译记忆
│  └─ config.py           路径、配置、DPAPI
├─ ui/
│  ├─ main_window.py      主窗口、工作线程、导出、快捷键
│  ├─ pdf_view.py         连续页面视图、异步渲染、译文覆盖
│  ├─ settings_dialog.py  设置
│  ├─ library_dialog.py   翻译库管理 / CSV
│  ├─ segment_dialog.py   单段校对
│  ├─ widgets.py          通用组件
│  ├─ icons.py            内联 SVG 图标与品牌图形
│  └─ theme.py            配色与 Qt 样式表
├─ resources/demo/        示例 PDF 与演示语料
├─ resources/app.ico      exe 多尺寸图标
├─ packaging/使用说明.txt  随便携版附带的用户说明
├─ YiPagePDF.spec         PyInstaller 打包配置
├─ version_info.txt       Windows 文件版本信息
├─ build_windows.bat      一键打包便携版
├─ tools/                 截图、图标、示例生成、UI/打包冒烟测试
└─ tests/test_core.py     核心单元测试
```

## 9. 开发与自测

```bat
:: 环境自检
.venv\Scripts\python app.py --check

:: source / package 自检：翻译示例并导出 PDF
.venv\Scripts\python app.py --smoke C:\Temp\yipage_smoke.pdf

:: 核心测试
.venv\Scripts\python -m unittest discover -s tests -v

:: UI 端到端冒烟测试（离屏）
.venv\Scripts\python tools\smoke_ui.py

:: 打包后的无界面自检：翻译示例并导出 PDF
dist\Fat_fish\Fat_fish.exe --smoke C:\Temp\yipage_smoke.pdf

:: 重新生成演示 PDF / 图标 / 截图
.venv\Scripts\python tools\make_sample.py
.venv\Scripts\python tools\make_icon.py
.venv\Scripts\python tools\capture_ui.py --demo --output docs\screenshot.png
```

已验证环境：Windows 10/11、Python 3.9.13、PySide6 6.10.3、PyMuPDF 1.24.14。

### Windows 便携版打包

```bat
build_windows.bat
```

产物在 `dist\Fat_fish\`，入口为 `Fat_fish.exe`，`_internal` 目录必须一起分发。
打包配置见 `YiPagePDF.spec`，包含 PyMuPDF 运行库、Qt 插件、示例文档和演示语料。
发布前建议执行一次 `--smoke`，它会真实跑通“抽取 → 演示翻译 → 原位写回 → 校验 PDF”。

## 10. 已知限制

- **扫描件**没有文字层，无法直接抽取翻译；需要先用 OCR（如 OCRmyPDF）加文字层。
- 竖排 / 旋转文本默认跳过，状态栏会在结果中提示。
- 原文表格极窄的单元格可能出现折行；可把「译文字号」调到 0.9×，或缩小到下一档。
- 源语言抽取以拉丁文字为默认路径；带文字层的中文 PDF 翻英文也已支持，但需要在设置里
  指定源语言为中文。复杂混排文档建议先试译一页。
- 免费额度、限流、计费以各服务商控制台为准；本应用只做客户端适配。
- 预览覆盖色从页面位图采样，若原文下层是复杂的照片纹理，覆盖区域可能有轻微色差；
  导出的 PDF 使用 redaction 删除原文，不受这个预览策略影响。
- 目前只提供浅色主题和中文界面。

## 11. 为什么选择这些实现

- **Qt**：原生桌面体验、跨平台窗口管理、稳定的双栏/滚动/缩放交互。
- **PyMuPDF**：同时具备高质量页面栅格化、精确文字坐标、redaction 与字体嵌入能力，
  是实现“原位替换”而不是“重新排版”的关键。
- **SQLite**：零部署、可备份、支持几万条记忆仍能快速检索；不需要额外数据库服务。
- **国内服务适配**：不把用户绑定到单一平台，密钥和译后数据都留在本机。

---

如果这份工具帮你省下时间，最值得先做的一件事是：**在「翻译库」里攒下自己的术语和
句式**。它们会优先于任何在线引擎，也让你在断网时依然能翻译已经处理过的内容。
