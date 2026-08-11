# 照片定位 · Reverse Image Location

[English](README.md) | 简体中文

上传一张照片，视觉模型**只看画面**（EXIF 在进模型之前就被剥掉了）推断它拍摄于世界上的哪个地方，并给出坐标、可信半径和一整条「观察 → 推论」的证据链。

## 下载即用（不需要 Python）

**这是最省事的一条路，也是唯一一条什么都不用装的路。** 打开 [Releases 页面](https://github.com/Beluga-T/photo-locator/releases/latest)，展开 **Assets**，挑你系统对应的那个压缩包，解开，双击里面的程序。浏览器会自己打开——通常是 <http://127.0.0.1:8000/>，但 8000 被占用时它会自动改用下一个空闲端口，所以**以控制台窗口里打印的那个地址为准**。想固定端口或不自动开浏览器，从终端带参数启动：`photo-locator --port 8010`、`photo-locator --no-browser`。

有两件事对所有这些构建都成立，写在这里而不是塞进脚注：

- **它们没有签名。** 背后没有 Apple 开发者证书，也没有 Windows 代码签名证书——那些是按年、按身份收费的东西，而这是一个免费的 MIT 项目。所以第一次启动一定会被系统拦下来，并且弹出一句听上去像是在指控你的话。下面按平台写清楚了它到底会说什么、以及点哪个按钮能过去。**没人提前告诉你的警告，看上去就是病毒**；这一条是预料之中的，你应该能一眼认出来。
- **API Key 仍然要你自己的。** 程序里没有内置任何密钥，也不会去花别人的钱：启动之后点右上角齿轮，把你的 Key 粘进去，「保存并生效」。「API Key 从哪来、一次多少钱」那一节原封不动地适用。

这个构建和其他启动方式一样只绑 `127.0.0.1`，而且**所有接口都没有任何鉴权**——在你想办法把它开出去之前，请先读完「安全边界」。

### 我该下哪一个？

| 你想 | 下这个 | 需要先装 |
| --- | --- | --- |
| 只是想用这个应用 | 你系统对应的开箱即用构建——本节 | 什么都不用 |
| 读代码、改代码、二次开发 | 源码，然后 `python run.py`——见「快速开始」 | Python 3.11+ |
| 跑在服务器 / NAS / 家用小主机上 | 容器镜像——见「用 Docker 启动」 | Docker |

### Windows

1. 下载文件名里带 `windows` 的那个资产——一个 `.zip`，名字形如 `photo-locator-<版本号>-windows-x64.zip`。
2. **先解压。** 右键 →「全部解压缩」。**不要**在还开着 zip 预览窗口的时候直接双击里面的 `.exe`：Windows 会很痛快地从一个临时目录里把它跑起来，而那个目录之后会被删掉——你存的 API Key 和历史记录跟着一起没。
3. 双击解压出来的文件夹里的 `photo-locator.exe`。
4. 会弹出一整块蓝底的框：**「Windows 已保护你的电脑」**（英文界面是 "Windows protected your PC"），而且只给你一个「不运行」按钮。那是 SmartScreen 对一个没有代码签名、它又没见过的可执行文件的反应——它做的是信誉检查，不是病毒报告，根本没扫描任何东西。点**「更多信息」**，再点**「仍要运行」**。每个版本只问一次。

程序运行期间会一直留着一个控制台窗口，关掉它就等于停掉服务。解压出来的文件夹要放在你写得进去的地方——`文档`、`D:\`，你自己的任何目录都行——**别**放进 `C:\Program Files`，那里写文件要管理员权限，而这个应用是紧挨着自己写数据的（见下）。

### macOS

1. 下载文件名里带 `macos` 的那个资产并解压——在 Finder 里双击 `.zip` 就够了。如果列了两个，`arm64` 是 Apple Silicon（M1 及以后），`x64` 是 Intel。
2. **第一次别直接双击。** 因为这个构建既没签名也没公证，Gatekeeper 会一口回绝，只给你一个「移到废纸篓」——那个对话框上根本没有「仍要打开」。正确的走法是：**右键（或按住 Control 点）`photo-locator` →「打开」**，在随后弹出的对话框里再点一次**「打开」**。第二个对话框才是这一整套动作的意义所在：它上面有一个「打开」按钮，而双击永远不会给你看到它。做过一次之后 macOS 就记住这个文件了，以后正常双击即可。
3. **macOS 15 Sequoia 及更新的系统上，苹果把这条右键后门取消了。** 在那里第一次启动无论怎么点都会被拦；去**「系统设置 → 隐私与安全性」**，翻到最下面，在提到 `photo-locator` 的那行旁边点**「仍要打开」**。还是同一次性授权，只是换了个地方给。

更愿意在终端里一行解决？在解压出来的目录里跑一次 `xattr -d com.apple.quarantine ./photo-locator`，它会把触发上面这一整套的隔离属性去掉，之后直接双击就能开。两条路完全等价，区别只在于这一条需要你打开终端，而右键那条不需要。

### Linux

```bash
tar -xzf photo-locator-*-linux-x64.tar.gz
cd photo-locator-*/
chmod +x photo-locator
./photo-locator
```

`tar` 一般会保留可执行位，所以 `chmod +x` 通常是多余的一步——但 `./photo-locator` 要是回你一句 `Permission denied`，就把它补上。这里没有 Gatekeeper / SmartScreen 那一套，文件直接就能跑。

> **glibc 下限：2.39** ——大致对应 Ubuntu 24.04+、Debian 13+、Fedora 40+。二进制动态链接的是构建它的 CI 镜像（`ubuntu-24.04`）里的 glibc，而 glibc 只向前兼容：在更老的系统上起不来，报的是 `/lib/x86_64-linux-gnu/libc.so.6: version 'GLIBC_2.39' not found`。低于这个下限的用户请改用「快速开始」里的 `python run.py` 或「用 Docker 启动」——那两条路不受它影响。

### 数据存在哪里

**就在可执行文件旁边。** 这个构建是刻意做成**便携式**的：它不往注册表、`%APPDATA%`、`~/Library` 或 `~/.config` 里撒任何东西。第一次运行时它在你解压出来的那个文件夹里建一个 `data/`，从此那个文件夹就是整个「安装」。

```
photo-locator/            你解压出来的文件夹
├─ photo-locator(.exe)
└─ data/                  第一次运行时创建
   ├─ config.json         你在设置卡里填的 API Key——明文
   ├─ history.json        最近 20 次分析
   └─ shots/              照片本身
```

- **删掉这个文件夹就是完整的卸载**——API Key、你分析过的每一张照片、整份历史都跟着一起没。这个布局就是为此选的：「解开就能用」理应对应「删掉就没了」。唯一的例外：如果程序当初改存到了用户目录（见本列表最后一条），数据在那边——每次启动控制台都会印出实际位置。
- **同一句话反过来读就是警告**：这个文件夹里有一把明文 API Key 和别人的照片。别把它解压到会同步上云的目录里，别再打包发给别人，别把整个文件夹随手交出去。「服务端存了什么」那一节一字不改地适用。
- **`RIL_DATA_DIR` 依然优先。** 设了它，数据就去那儿——想让几份构建共用一个数据目录，或者想把数据挪出同步盘而不挪动程序本身，就用它。
- **「放在程序旁边」会弄丢数据的场合，程序会主动换地方。** 三种情况会改存到你系统的用户目录（`%LOCALAPPDATA%\photo-locator`、`~/Library/Application Support/photo-locator` 或 `~/.local/share/photo-locator`），并在控制台里说明并印出路径：解压进了一个你没有写权限的目录（`C:\Program Files`）；从临时目录里直接运行（在 zip 预览窗口里直接双击 `.exe`——Windows 会把它解到 `%TEMP%` 下，之后连目录一起清掉）；以及将来如果发过 macOS `.app` 包的话，包内运行的情况。

### 校验下载的文件（checksums）

每个 release 都带一个 `SHA256SUMS.txt`，里面是每个压缩包的 SHA-256。解压之前先和你真正下到磁盘上的那份对一下：

```powershell
Get-FileHash .\photo-locator-*-windows-x64.zip -Algorithm SHA256   # Windows PowerShell
```

```bash
shasum -a 256 photo-locator-*-macos-*.zip          # macOS
sha256sum -c SHA256SUMS.txt --ignore-missing       # Linux —— 一次把下到的几个包全查一遍
```

**这件事证明了什么，要说清楚。** 哈希对得上，说明你手里这份和 release 页面列出的那份逐字节一致，下载被截断、被中间的代理改坏都会当场露馅。但它**不是签名**，说明不了这东西是谁造的：`SHA256SUMS.txt` 和压缩包躺在同一个页面上，能换掉其中一个的人也能换掉另一个。真正给这些二进制背书的，是它们由 GitHub Actions 在公开环境里、从打了 tag 的源码构建出来，而那份 workflow 你可以自己去读。

## 快速开始

```bash
git clone https://github.com/Beluga-T/photo-locator.git
cd photo-locator
python run.py        # macOS / Linux 上通常是 python3 run.py，Windows 上也可用 py -3 run.py
```

浏览器会自己打开 <http://127.0.0.1:8000/>。`run.py` 只用标准库，第一次跑会自建 `.venv`、装好 `requirements.txt` 里那 7 个依赖、再用正确的参数启动服务；之后每次都会先确认一遍环境还完好，确认这件事实测 0.029 秒，不会重跑 pip。需要 **Python 3.11 或更新**（`app/store.py` 用了 3.11 才有的 `datetime.UTC`），版本不够它会直接告诉你。端口被占就 `python run.py --port 8010`。不想自动开浏览器就加 `--no-browser`。

不想用 git？任何一个 release 的资产列表最下面都有 **`Source code (zip)`**，那就是同一份源码树，解开之后同样是 `python run.py`（要解**整包**，只挑几个文件出来它会告诉你缺文件）。注意它不是上面那个开箱即用的构建：这一份是源码，仍然需要 Python。

### 前置条件

只需要 Python 3.11+，其余一切都会自动装进项目内的 `.venv`：

- **Windows** —— `winget install Python.Python.3.12`，或去 [python.org](https://www.python.org/downloads/) 下安装包。注意：新装的 Windows 上直接敲 `python` 可能会打开 **Microsoft Store**（那是个购物别名，不是解释器）——用 `py -3 run.py`，它能找到真正装好的那个。
- **macOS** —— `brew install python`，或 python.org 的安装包。装好之后解释器叫 `python3`。
- **Debian / Ubuntu** —— `sudo apt install python3 python3-venv`。Debian 系里 `venv` 是**单独的包**，缺了它 `run.py` 建虚拟环境会失败。
- **Fedora** —— `sudo dnf install python3`。

### API Key 从哪来、一次多少钱

**API Key 用你自己的，填在网页里，不需要建 `.env`。** 页面右上角齿轮 →「模型」面板 → 把 Anthropic API Key 粘进去 →「保存并生效」。它存在**服务端**的 `data/config.json`（已 gitignore），换浏览器、重启程序都还在。

密钥本身在 [console.anthropic.com](https://console.anthropic.com/) → API Keys 里创建；账户要有**正余额**——没充值的账户，密钥能通过鉴权，到真正分析时才报计费错误。

**一次定位大概多少钱**：默认走 Claude Opus 5，官方价格是输入 $5 / 百万 token、输出 $25 / 百万 token。一张缩到 2000 px 的照片约 4000 个输入 token，加上系统提示词与 schema，输入合计约 8000 token（≈ $0.04）；输出是思考加那份 JSON，通常几千 token。**估下来一次 0.1–0.2 美元左右**，`MAX_TOKENS = 16000` 是硬上限，所以单次输出再离谱也就 $0.40。嫌贵或嫌慢，先把设置卡里的**思考深度**从 `medium` 调到 `low`，那是这个应用里最直接的一个旋钮（见「配置」）。

### 疑难排查

- **8000 端口被占** → `python run.py --port 8010`。
- **pip 太慢** → 指一个近的镜像，pip 会继承环境变量：

  ```bash
  PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple python run.py   # macOS / Linux
  ```

  ```powershell
  $env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"; py -3 run.py   # Windows PowerShell
  ```

- **Python 太旧** → `run.py` 会在动任何东西之前直接退出，打印 `This project needs Python 3.11 or newer. You started it with Python 3.x (...)`，后面跟着各系统的安装命令。装个新的 Python，然后**用它**来跑这个脚本——`.venv` 是从跑 `run.py` 的那个解释器建出来的。

> ### ⚠️ 它只该跑在 127.0.0.1 上
>
> **所有接口都没有任何鉴权**——没有登录、没有 token、没有来源校验。能连上这个端口的人，就能拿你的密钥跑分析（花你的钱）、翻出你分析过的每一张照片和它们的位置，还能用 `PUT /api/settings` 改掉你保存的配置（包括把网关地址指到他自己的机器上）或一条请求删光全部历史。
>
> 默认绑定就是 `127.0.0.1`，**请保持这样**。真敲了 `python run.py --host 0.0.0.0`，它会在起服务之前把同样意思的一整段警告打在终端里，那不是客套话——要开出去，前面得放一个自己做鉴权的反向代理。`compose.yaml` 也只把端口发布到 `127.0.0.1`。细节见「安全边界」。

## 它做什么

后端先用 Pillow 把上传的图解码、转正、缩放并重新编码成 JPEG——这一步会顺带**剥掉全部 EXIF**，只有像素本身会被送进视觉模型。模型扮演一名 OSINT 图像地理定位分析师，从地形植被、建筑形制、道路标线与靠边行驶方向、招牌文字与域名后缀、车牌比例、电线杆横担、阴影方向这些线索一路从大到小收敛，给出**证据撑得住的那一级**（国家 / 一级行政区 / 城市 / 街区）的判断、中心坐标与可信半径、4–8 条「观察 → 推论」的完整证据链、2–3 个备选地点，以及一个 0–100 的置信度。照片里如果本来带了 GPS，那串坐标只会显示给你自己看，绝不进模型——所以屏幕上的结论是货真价实的视觉推断，不是读元数据。

## 界面语言（中 / EN）

界面是中英双语的：

- **切换按钮**在页头、主题切换旁边。页面是中文时它显示 **「EN」**，是英文时显示 **「中」**——写的是你要切**过去**的那种。切换即时生效，不刷新页面。
- **选择会记住**：存在浏览器的 `localStorage` 里（键 `ril-lang`）。第一次打开按浏览器语言定：`navigator.language` 以 `zh` 开头就是中文，否则英文。
- **分析结果跟着界面语言走。** 前端把当前语言作为 `lang` 表单字段随定位请求发出（见「接口」里的 `POST /api/locate`）；后端把它注入提示词，于是散文字段——`summary`、证据的 `observation` / `implication`、备选的 `reason`、`notes`——就用那种语言写。`name_zh` / `name_en` 在两种语言下语义不变；英文模式下标题优先用非空的 `name_en`。
- **服务端的报错在线上永远是中文**（`{code, message}`）。英文模式下前端按 `code` 显示自己的译文，没有对应译文才显示服务端原话——见「错误码」。

## 它是怎么工作的

1. **上传**：前端把文件以 multipart 字段 `image` POST 到 `/api/locate/stream`，并把当前界面语言放进可选的 `lang` 字段（见「界面语言」）；超过 `MAX_UPLOAD_MB` 直接被拒。想要一次拿到完整结果（脚本、curl）就用同参数的 `/api/locate`。
2. **解码与归一化**：`app/imaging.py` 用 Pillow 打开图片，校验格式（JPEG / PNG / WEBP / GIF / BMP / TIFF），按 `ImageOps.exif_transpose` 校正方向，最长边超过 `MAX_IMAGE_EDGE` 则用 LANCZOS 等比缩放，最后统一编码成 quality 88 的 JPEG 并转 base64。
3. **EXIF 只读不传**：解码时会解析 EXIF 中的 GPSInfo，把度分秒换算成十进制经纬度，随结果一起放进 `meta.exifGps` **给用户看**。重新编码后的 JPEG 不含任何元数据，模型收到的只有画面。**因此报告出来的位置是纯视觉推断。**
4. **模型推理**：`app/providers.py` 按 `app/prompt.py` 里的 `RESULT_SCHEMA` 约束输出。Claude 走官方 SDK 的 `output_config.format = json_schema`，OpenAI 兼容网关走 `response_format.json_schema`；网关不支持时自动降级到 `json_object`，再不行就把 schema 直接写进提示词。
5. **边写边报**：模型的输出是流式的，`app/streaming.py` 用一个增量 JSON 扫描器盯着这条还没写完的流，某个顶层字段刚一闭合就把它摘出来，**`evidence` / `alternatives` 这两个数组则是每写完一条就报一条**。`RESULT_SCHEMA` 的字段顺序是特意排的：`precision` 排在最前（它是"模型愿意认到哪一级"的上限，先知道它，前端才不会先写出一个马上要收回去的街道名），然后是 `country` → `region` → `city` → `locality` → `coordinates` → `confidence` → `summary`，最后才是占掉大半篇幅的证据链。实测一次 24 秒的定位（opus-5 / effort=medium）：地名 3.7 秒上屏，坐标 5.9 秒地图开始加载瓦片，摘要 8.0 秒，六条证据从 9.4 秒起每 1.5–2 秒出一条，备选 18.8 秒起——**整段等待里屏幕最长只静止 2.5 秒**。
6. **后端归一化**：`providers.normalize` 把模型返回的 JSON 收敛成前端唯一认识的形状——经纬度夹到合法区间、**精度对账**并按最终 precision 套半径下限（locality 0.5 / city 5 / region 50 / country 200 km，见下一节）、置信度夹到 0–100、`confidence_band` 缺失或非法时按 70 / 40 阈值重算、证据 `weight` 非法时降为 `medium`、备选地点按 `likelihood` 降序排。
7. **前端渲染**：`web/app.js` 先用流里到的字段画一块标着「正在收敛」的临时判定卡，随字段变精确而重排；完整结果一到就整块换成判定标题、置信度仪表盘、证据链与备选清单，并在下面挂一张地图——配置了 `MAPBOX_TOKEN` 就是带不确定半径圈的可交互 Mapbox 地图，否则退回内置的示意地球。图版一侧支持整页拖拽、`Ctrl+V` 粘贴、随时可取消的请求，以及 `Enter` / `R` / `T` / `Esc` 四个快捷键。本次会话分析过的照片留在缩略图轨里可以回看，结果能一键复制结论或下载 JSON，成败都用右下角的 toast 提示。
8. **落盘**：`app/store.py` 把送进模型的那张 JPEG 写进 `data/shots/`，把整个响应体写进 `data/history.json`，只留最近 20 张。界面里保存的配置也写在同一个目录下的 `config.json` 里。详见「服务端存了什么」。

## 精度纪律

这是这个项目现在最要紧的一条行为，由 `app/prompt.py` 和 `app/providers.py` 一前一后钉死：

- **只回答证据撑得住的层级。** 系统提示词要求模型从国家往下逐级收敛，每往下一级都先问一句"画面里有没有具体的东西支撑这一级"；撑不住就把 `name_zh` 填成「未确定」、`name_en` 留空，**不许填一个"最可能"的猜测**。宁可只给国家，也不要给一个随手编的城市。
- **唯一的下限是国家。** 不允许整体回答"无法判断"或"信息不足"；连国家都吃不准时仍然给出最可能的国家，但把 `confidence` 压到 30 以下，并在 `alternatives` 里放上其他候选国家。所以这个应用永远会给你一个答案，只是会明说它到底走到了哪一级。
- **模型自报走到了哪一级。** `RESULT_SCHEMA` 里的 `precision` 字段取 `country` / `region` / `city` / `locality` 之一，填了「未确定」的层级不能出现在这里。
- **后端不信这个自报，会当场对账。** `providers._resolve_precision` 把模型声明的 `precision` 和它实际填出名字的最深层级放在一起，**取更粗的那个**发布（声明缺失或不是合法取值时，直接以实际填写为准）。`normalize` 随后把比这一级更细的所有层级清空成「未确定」+ `known: false`，`locality` 清成空串。于是嘴上说"只到国家"、手上却填了城市的回答，那个城市根本进不了前端；反过来声明了 `city` 却把城市留白，也会被降回 `region` 或 `country`。两者不一致时后端打一条 `precision reconciled: model said ... publishing ...` 的日志。
- **最后套半径下限。** 粗结论不许穿一件细半径的外衣：`RADIUS_FLOOR` 按对账后的 precision 给出最小可信半径，模型报得比它小就被抬上去。

| `precision` | 层级 | 半径下限 |
| --- | --- | --- |
| `country` | 国家 | 200 km |
| `region` | 一级行政区（州 / 省 / 大区） | 50 km |
| `city` | 城市 | 5 km |
| `locality` | 街区 / 道路 / 地标 | 0.5 km |

提示词另外要求模型自报的 `radius_km` 与 precision 相称（locality 1–5、city 10–50、region 100–400、country 几百到两千公里），上表只是后端兜底的硬下限。前端按最终 precision 决定标题显示哪一级，并在只到国家或只到一级行政区时明说"证据只支撑到……"。

## 启动的四种方式

第一种是「下载即用」那一节里的开箱即用构建——什么都不用装，这里不再重复。下面这三种都需要 Python 或 Docker，起的是同一个应用，选一个就行；「快速开始」里的 `python run.py` 就是其中第一种。

### `python run.py`（推荐）

```bash
python run.py                     # 建好 .venv、装依赖、起服务、开浏览器
python run.py --port 8010         # 8000 被占了
python run.py --no-browser        # 不开浏览器
python run.py --reload            # 改 app/ 下的文件就重启（开发用）
python run.py --recreate-venv     # .venv 坏了，删掉重建
python run.py --help              # 全部参数
```

它做的事情都是幂等的：`.venv` 在就不重建，依赖没变（比对 `requirements.txt` 的 sha256 + 解释器版本，再用 `importlib.util.find_spec` 确认那 7 个包真的能 import）就不跑 pip。失败的时候它印的是一段人话而不是 traceback——端口被占、`.venv` 里没有解释器、pip 连不上 pypi、Windows 的 260 字符路径上限（`anthropic` 有超过 100 字符的模块名，克隆到太深的目录里 pip 会报一个看起来像本项目 bug 的 `[Errno 2]`），都各有各的说明和改法。

### 自己开 venv 手动跑

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --no-proxy-headers --reload
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --no-proxy-headers --reload
```

**`--no-proxy-headers` 不是可选的。** uvicorn 默认开着 `--proxy-headers`，会在应用看到请求之前就按 `X-Forwarded-For` 改写来源地址，于是任何人每次换一个伪造的 XFF 就能拿到一份全新的限流额度——那额度保护的是你的钱。实测见「安全边界」。`run.py` 和 `Dockerfile` 里都已经写死了这个参数，只有手敲命令行的时候需要自己记得。

密钥仍然是在网页里填的；`.env` 是可选的，想用就 `cp .env.example .env`（改完 `.env` 要重启进程才生效，改网页里的配置不用）。没配密钥也能起服务，启动日志会打一条 warning，前端右上角状态点变红，点「开始定位」会拿到 `not_configured`。

### 用 Docker 启动

不需要源码——每个发布 tag 都会自动构建一个多架构镜像（amd64 + arm64）发到 GitHub Container Registry：

```bash
docker run -d --name photo-locator -p 127.0.0.1:8000:8000 -v photo-locator-data:/data ghcr.io/beluga-t/photo-locator:latest
```

端口前面的 `127.0.0.1:` 不要去掉——去掉就绑到了所有网卡上，而这个应用没有任何鉴权。有源码的话，`docker compose up --build` 构建并运行同一个东西，且下面那套加固全部生效。

同样是 <http://127.0.0.1:8000>，密钥同样是在页面里填的——它会写进下面那个命名卷，活得过容器重建。想改用 `.env` 也行（`cp .env.example .env`，然后 `docker compose up -d --force-recreate`，不用重建镜像）。

`compose.yaml` 把这个项目的安全姿态固化成了容器属性，而不是 README 里的承诺：

- **端口只发布到 `127.0.0.1`**。这是整个文件里最要紧的一行。写成 `"8000:8000"` 会绑到所有网卡——这个应用没有任何鉴权，而且 `X-RIL-OpenAI-Base` 会让它向调用者指定的地址发起服务端请求，详见「安全边界」。
- **根文件系统只读**（`read_only: true`），`/tmp` 挂一小块 tmpfs。这一条现在的含义是：应用**有且只有一个**能写的地方，就是下面那个卷；代码、venv、`/etc` 在运行时全部不可变。
- **一个可写的命名卷**：`locator-data` 挂在 `/data`，`Dockerfile` 里 `RIL_DATA_DIR=/data`，所以 `config.json`、`history.json` 和 `shots/` 都落在这个卷里。镜像里 `/data` 预先建好并 `chown` 给了 uid 10001——只读根之下，这一步不做的话第一次写就会失败。
- `cap_drop: ALL` + `no-new-privileges`，镜像内以 uid 10001 的非 root 用户运行。

容器里 uvicorn 绑的是 `0.0.0.0`，这是**必须的**——不然容器外根本连不上；"只回环"由上面的端口发布保证，不是靠绑定地址。`--no-proxy-headers` 已经写死在 `CMD` 里；只有当你在前面放了自己可控的反向代理时才该去掉它，并同时把该代理的地址填进 `TRUSTED_PROXIES`。

**命名卷 `locator-data` 活得过 `docker compose down`，也活得过镜像重建**——这正是它存在的理由：发版的构建没有 `.env` 可改，配置只能由应用自己记住。反过来说，**这个卷里有一把明文 API Key 和别人的照片**，请按 `.env` 对待：别随手 `docker cp` 出来，别连着镜像一起分发，`docker compose down -v` 才是真正把它连同照片一起删掉。想在宿主机上直接看到这些文件，把 `locator-data:/data` 换成 `./data:/data` 就行（`compose.yaml` 的注释里已经写了这条），代价是它们从此躺在你的项目目录里——`./data` 已经同时在 `.gitignore` 和 `.dockerignore` 里，别把它移出来。

`.dockerignore` 排除了 `.env` 和 `data/`，密钥和照片都不会被烤进镜像层，构建产物可以随便搬。

## 配置

**生效顺序共四层，从高到低：**

1. **`X-RIL-*` 请求头** —— 只作用于发出它的那一个请求，从不落盘（`app/overrides.py`）。
2. **`data/config.json`** —— 界面里保存下来的那份，写在运行这个服务的机器上（`app/store.py`，见下）。
3. **`.env`** —— `app/config.py` 启动时通过 `python-dotenv` 加载。
4. **`app/config.py` 里写死的默认值**。

第 2 层只能覆盖 `app/store.py:CONFIG_FIELDS` 里的八个字段：`provider`、`anthropic_api_key`、`anthropic_model`、`anthropic_effort`、`openai_base_url`、`openai_api_key`、`openai_model`、`mapbox_token`。下表其余变量（上传上限、边长、限流、超时、`TRUSTED_PROXIES` 等）**只认 `.env`**，界面和请求头都碰不到。

`load_settings(stored)` 的合并是**逐字段**的，规则就三条：

- **空的不算数。** 存进来的值先 `strip()`，空串或纯空白直接当没填过，继续往下落到 `.env`、再落到默认值（`pick()` 就是 `saved.get(field) or _text(env, default)`）。所以「清空这一项并保存」等于回到 `.env`，不是把它变成空。
- **`anthropic_effort` 还要合法。** 存的值不在 `low` / `medium` / `high` / `xhigh` / `max` 之内就整条忽略，回落到 `ANTHROPIC_EFFORT`，再回落到 `medium`。
- **provider 会被重算，存进去的网关凭据一样参与重算。** `provider` 本身也走这四层；合并后如果是 `claude` / `openai`，那就是钉死的（`provider_pinned = True`），否则按 auto 规则重推——合并后的 `openai_base_url` 与 `openai_api_key` **两者都非空**才选 `openai`。这两项来自 `data/config.json` 还是 `.env` 完全等价：在界面里存一套网关凭据，和写进 `.env` 一样会把 auto 推到 `openai`。

**改 `.env` 要重启进程才生效**（`load_dotenv()` 只在 import 时跑一次）；改 `data/config.json` 不用——`PUT` / `DELETE /api/settings` 之后 `app/main.py:_reload_settings()` 会当场重建 `settings`，下一个请求就是新的。

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| `LLM_PROVIDER` | `auto` | `claude` / `openai` / `auto`。取值会被 lowercase，不是前两者之一时一律按 auto 规则处理 |
| `ANTHROPIC_API_KEY` | 空 | Anthropic 官方 API Key。走 claude 时它非空才算「已配置」 |
| `ANTHROPIC_MODEL` | `claude-opus-5` | Claude 模型 id |
| `ANTHROPIC_EFFORT` | `medium` | 思考深度，`low` / `medium` / `high` / `xhigh` / `max`。**这是最直接的快慢开关**。Anthropic 自己的默认是 `high`，这个应用刻意低一档：单次视觉推断不是 `high` 所针对的长程 agentic 任务，Opus 5 在低档位上表现依然很好。填了非法值静默回落，不会启动失败。仅对 Claude 生效——OpenAI 兼容那条路没有对应参数，会忽略它。界面里可以覆盖，见下 |
| `OPENAI_BASE_URL` | 空 | OpenAI 兼容网关地址，**必须写到 `/v1` 为止**，不要带 `/chat/completions`。末尾多余的 `/` 会被自动去掉，代码会拼上 `/chat/completions` |
| `OPENAI_API_KEY` | 空 | 以 `Bearer` 形式发给网关 |
| `OPENAI_MODEL` | `gpt-4o` | 网关侧的模型名（Qwen-VL、GPT-4o、各类中转模型均可） |
| `MAPBOX_TOKEN` | 空 | 结果页画地图用的 Mapbox 令牌，是页面的**默认值**（界面里可覆盖，见下）。留空且浏览器也没填时，前端退回内置示意地球，整页不发任何外部请求。**它会随 `/api/config` 明文下发到浏览器**，所以必须填 `pk.` 开头的公开令牌，并在 Mapbox 后台按域名做 URL 限制；千万不要填 `sk.` 开头的私密令牌 |
| `MAX_UPLOAD_MB` | `12` | 单张图片原始字节上限，超过返回 `too_large` |
| `MAX_IMAGE_EDGE` | `2000` | 送进模型前的最长边像素上限 |
| `REQUESTS_PER_HOUR` | `40` | 单 IP 每小时请求数上限（`/api/locate`、`/api/locate/stream` 与 `/api/verify` 共用同一个桶）；**设为 0 或负数即完全关闭限流** |
| `TRUSTED_PROXIES` | 空 | 逗号分隔的地址列表，只有来自这些地址的请求，其 `X-Forwarded-For` 第一段才会被当作客户端 IP 用于限流。**默认为空＝谁的都不信**，一律按 socket 来源计数。注意这一项不够用：`uvicorn` 自己的 `--proxy-headers` 默认开着，会抢在应用之前改写来源地址，详见「安全边界」 |
| `REQUEST_TIMEOUT_SECONDS` | `240` | 调用模型的超时秒数，同时作用于 Anthropic SDK 与 httpx |
| `REFUSAL_FALLBACK` | `true` | 仅 Claude 生效：先带 `server-side-fallback-2026-07-01` beta 头请求，让服务端在触发安全策略时自动改用备选模型重跑 |

数值型变量解析失败时静默回退到默认值；布尔型接受 `1` / `true` / `yes` / `on`（大小写不敏感），其余一律为 false。

**`LLM_PROVIDER=auto` 的真实规则**：`OPENAI_BASE_URL` 和 `OPENAI_API_KEY` **两者都非空**才选 `openai`，否则一律选 `claude`。只填了 base_url 没填 key 是不会切过去的——这一点和 `.env.example` 里的注释措辞略有出入，以代码为准。

### 地图令牌（`MAPBOX_TOKEN`）：可以不填

**不填也能用。** 没有令牌时，结果页画的是内置的示意地球（`web/globe.js`，纯本地绘制的正射投影经纬网 SVG），判定点在球心，坐标和半径照常显示，整页不发任何外部请求。你要的东西——国家、城市、坐标、证据链——一样不少，只是底图上没有街道。

填了令牌，结果页换成带不确定半径圈、能拖能缩的 Mapbox 交互地图。令牌怎么来：去 [mapbox.com](https://www.mapbox.com/) 注册一个免费账号，Account 页面会给你一个 `pk.` 开头的 **public token**，直接复制。免费额度对自己看照片这种用量绰绰有余。

**填在哪**：页面右上角齿轮 →「地图」面板 → 粘进去 →「保存并生效」。也可以写进 `.env` 的 `MAPBOX_TOKEN=`（改完要重启）。

**只能填 `pk.` 开头的公开令牌。** 它必须明文下发到浏览器才能画图（Mapbox 的设计如此），所以请顺手在 Mapbox 后台给它加 URL 限制。`sk.` 开头的私密令牌前端会当场拒绝，后端的 `/api/config` 也会把它扣下并打一条 warning——那种令牌进了浏览器就等于泄露了。

**代价是坐标会到 Mapbox 手里**（照片不会）：地图渲染时浏览器要带着模型推断出的那对经纬度去请求瓦片。想完全离线，就别填这一项。

#### 在界面里更换地图令牌

Mapbox 令牌只有浏览器用得上，但它和模型密钥存在同一个地方，不必为了换一个而改 `.env` 重启后端。点右上角的设置按钮，切到「地图」面板，把令牌填进去保存即可立即生效：

- 生效顺序是 **`data/config.json` > `.env` 的 `MAPBOX_TOKEN` > 都没有就用内置的示意地球**。
- 保存走的是 `PUT /api/settings` 的 `mapbox_token` 字段，写在服务端磁盘上——**换浏览器、重启程序它都还在**，改的是 `/api/config` 下发给**所有**浏览器的那个值。
- 它在 `GET /api/settings` 里**不打码**，另外两把 API Key 打。公开的 `pk.` 令牌本来就要明文下发给浏览器才能用，打码只会让填的人看不见自己填了什么。
- 清空输入框保存就是删掉它，回到 `.env` 的值。
- 保存后如果屏幕上已经有一份结果，地图会就地重画，不需要重新分析照片。
- 输入 `sk.` 开头的私密令牌会被前端直接拒绝——那种令牌一旦进了浏览器就等于泄露。

### 在界面里更换模型密钥

右上角齿轮打开的是设置卡，分「模型」「地图」「数据」三个面板。模型面板里能改用哪家模型、用谁的密钥、思考深度，点「保存并生效」立刻生效，不用动 `.env`，也不用重启后端。

字段：`PROVIDER` 下拉（`auto` / `claude` / `openai`）、Anthropic 的 API Key / 模型名 / **思考深度**、OpenAI 兼容网关的 Base URL / API Key / 模型名。

两个下拉都**不提供「跟随服务端」这一项**。真实部署里没有 `.env`，把一个不存在的文件摆成选项只会误导。输入框仍然可以留空——留空表示沿用下一层的值，下一层也没有就是没有。

- **存在服务端的磁盘上**：保存就是 `PUT /api/settings`，后端把认识的字段写进 `data/config.json`（`app/store.py:write_config`）。换浏览器、重启程序它都还在——发版的构建没有 `.env` 可改，这一层就是为它存在的。
- **合并，不是整体覆盖**：请求体里没提到的字段保留原值，所以只发用户动过的那几个就够。某个字段填空串（或纯空白）是**明确要求删掉它**，回落到 `.env`；根本不提这个字段才是「没有意见」。
- **读回来只有掩码**：`GET /api/settings` 把两把 API Key 过 `mask()`，`openai_base_url` 只剩 scheme + host。保存后的响应体也是同一份掩码视图。所以设置卡永远显示不出你填过的密钥原文，这是故意的，理由见「安全边界」。
- **改网关地址必须在同一个请求里给该网关的 Key**，否则 400 `bad_override`。
- **「清除已保存的配置」是 `DELETE /api/settings`**：删掉整个 `data/config.json`，回到 `.env` 和默认值。
- **这个端口没有鉴权**：能连上它的人就能改这些设置。所以只绑回环。

**前端不再往 `localStorage` 里存任何凭据。** 早先的版本把七个字段存在浏览器里、每次请求作为 `X-RIL-*` 头发出，那条路已经拆掉了：`web/settings.js` 现在只负责校验用户填的草稿、以及根据 `/api/config` 推算"下一次请求会用什么"，一行存储代码都没有。`web/app.js` 发出的定位请求**不带任何 `X-RIL-*` 头**，服务端用自己保存的配置。旧版本留在浏览器里的 `ril-model-config` 已经没有任何代码会去读它。

**直接调 API 时用 `X-RIL-*` 请求头。** 这组头仍然有效，是给 curl / 脚本这类直接调用方的**逐请求**覆盖通道：后端只在这一个请求的生命周期内使用它们，**不写进 `data/config.json`、不落盘、不写进日志**（日志里只有 `mask()` 后的掩码）。

| 字段 | 请求头 | 覆盖的 `Settings` 字段 |
| --- | --- | --- |
| PROVIDER | `X-RIL-Provider` | `provider` |
| ANTHROPIC · API KEY | `X-RIL-Anthropic-Key` | `anthropic_api_key` |
| ANTHROPIC · MODEL | `X-RIL-Anthropic-Model` | `anthropic_model` |
| ANTHROPIC · EFFORT | `X-RIL-Anthropic-Effort` | `anthropic_effort` |
| 网关 · BASE URL | `X-RIL-OpenAI-Base` | `openai_base_url` |
| 网关 · API KEY | `X-RIL-OpenAI-Key` | `openai_api_key` |
| 网关 · MODEL | `X-RIL-OpenAI-Model` | `openai_model` |

**请求头的生效也是逐字段的**：发了就用发的，没发的字段落到 `data/config.json`，再落到 `.env`，再落到默认值。**不发 / 留空表示「没有意见」，不是「清空」**——它不会抹掉已保存的值（要清就用 `PUT /api/settings` 发一个空串）。单个字段超过 500 字符（`MAX_VALUE_LEN`）、或含非 ASCII / 不可打印字符会被拒绝（前端 `web/settings.js` 拦一道，后端 `overrides._clean` 再拦一道）。

**嫌慢先调「思考深度」（effort）。** 它控制 Claude 回答前想多久，是这个应用里最直接的快慢开关，比换模型有效得多：

| 档位 | 什么时候用 |
| --- | --- |
| `low` | 最快。单张照片的推断通常仍然可用 |
| `medium` | 想提速优先试这一档：明显快于默认，质量损失很小 |
| `high` | Anthropic 的默认值，也是最慢的常用档 |
| `xhigh` | 更细的推理，更慢更贵；这类单次视觉判断收益有限 |
| `max` | 最慢，正确性压倒成本时才用，容易在简单图上过度思考 |

顺带一提，effort 调低还会缓解 `MAX_TOKENS`（16000）的压力——Claude Opus 5 默认开启 thinking，而 `max_tokens` 是**思考加正文的总上限**，`high` 档在这个又要看图又要产出长 JSON 的任务上离上限并不远。撞上限的表现是 `truncated`。

七个字段合并完之后，`app/overrides.py:apply_overrides` 才决定这一次走哪个通道：

| 情况 | 结果 |
| --- | --- |
| `X-RIL-Provider` 是 `claude` 或 `openai` | 用户刚刚选了，直接照办 |
| `X-RIL-Provider` 是 `auto` | 用户要求重新推断 |
| 没发这个头，且服务端的 `provider` 明写了 `claude` / `openai`（`data/config.json` 或 `LLM_PROVIDER`） | 操作者钉死的，照办 |
| 没发这个头，且服务端那一层是 `auto` | 谁都没选过，重新推断 |

「重新推断」用的还是启动时那条规则：合并后的 base URL 与 key **两者都非空**才走 `openai`，否则走 `claude`。最后一行必须重算——启动时 `load_settings` 已经把 `auto` 收敛成了一个具体 provider，若不重算，一个填好了网关但没发 `X-RIL-Provider` 的请求会继续闷头打向 Claude。`Settings.provider_pinned` 存在的唯一意义就是区分这两种「服务端说了算」。界面上的下拉已经不再产生「不发这个头」的情况，但 curl 之类的直接调用仍然会，所以这条规则必须留着。

**「测试连接」按钮**把当前表单的七个头 POST 给 `/api/verify`，后端做一次**免费**的可达性探测：Claude 调 `models.list`（`GET /v1/models`，不计费），网关调 `GET {base}/models`。不花任何 token，可以随便点。它测的是**当前表单**而不是已保存的配置——表单与已存内容不一致而探测又成功时，提示语会追加一句「记得点保存并生效，否则分析仍用旧配置」。

**这些东西请求头和 `/api/settings` 都改不了**（操作者的闸门，只认 `.env`，改完要重启）：`MAX_UPLOAD_MB`、`MAX_IMAGE_EDGE`、`REQUESTS_PER_HOUR`、`REQUEST_TIMEOUT_SECONDS`、`TRUSTED_PROXIES`、`REFUSAL_FALLBACK`。它们不在 `CONFIG_FIELDS` 白名单里，所以 `PUT /api/settings` 塞不进去。`app/main.py` 在做体积与边长校验时刻意读的是模块级的 `settings` 而不是本次请求的 `effective`。（`MAPBOX_TOKEN` 是个例外：它没有对应的 `X-RIL-*` 头，但在 `CONFIG_FIELDS` 里，能用 `/api/settings` 改。）

### 服务端存了什么：`data/`

```
data/
├─ config.json      界面里保存的配置——含明文 API Key，创建时即 0600
├─ history.json     每次分析一条：id、created_at、media_type、size_bytes，以及那次
│                   /api/locate 的完整响应体（payload）。不含图片字节
└─ shots/<id>.jpg   图片本身，一张一个文件
```

- **位置**由 `RIL_DATA_DIR` 决定，默认是项目根目录下的 `data/`（`app/store.py:DEFAULT_DATA_DIR`，和 `.env` 并排——同一台机器、同一条信任边界、同一类秘密）。容器里 `Dockerfile` 把它设成 `/data`。这个值不可用时（含 NUL、`~` 展不开）会记一条日志并回落到默认目录，不会让进程起不来。
- **存的是模型看到的那张**：`imaging.prepare` 缩放、重编码、剥掉全部 EXIF 之后的 JPEG（`PreparedImage.data`）。原图和它的 GPS 都不落盘。
- **只留最近 `HISTORY_CAP = 20` 张**。写第 21 张时最老的那条连同它的图片文件一起删掉；索引若丢失或被改坏，下一次成功写入会把 `shots/` 里所有索引不认识的文件一并回收，否则那些文件永远没人再引用、也永远没人再删。
- **`data/` 同时在 `.gitignore` 和 `.dockerignore` 里**，不会被提交，也不会被烤进镜像层。
- **这个目录里有一把 API Key 和用户的照片。** 它替代的就是 `.env`，请按 `.env` 的规格对待：别拷来拷去，别放在会同步到云盘的路径下，别 tar 进备份就随手发出去。

## 接口

### `GET /api/health`

```json
{ "status": "ok" }
```

### `GET /api/config`

前端启动时调它来渲染右上角的模型状态。这里下发的是**服务端当前生效的那份配置**（`data/config.json` 压过 `.env`），不含请求头那一层。`configured` 为 false 表示对应 provider 的密钥没填齐；`mapboxToken` 是那个公开令牌的原样下发，为空串时前端改用示意地球。

```json
{
  "provider": "claude",
  "providerPinned": false,
  "model": "claude-opus-5",
  "effort": "medium",
  "configured": true,
  "maxUploadMb": 12,
  "hasAnthropicKey": true,
  "hasOpenaiBase": false,
  "hasOpenaiKey": false,
  "mapboxToken": "pk.eyJ1Ijoi…"
}
```

`providerPinned` 是 `provider` 被明写成了 `claude` / `openai`（true），还是 `auto` 只是恰好解析成了它（false）——`data/config.json` 里的 `provider` 和 `.env` 里的 `LLM_PROVIDER` 在这件事上等价。`effort` 是服务端当前的默认思考深度。`hasAnthropicKey` / `hasOpenaiBase` / `hasOpenaiKey` 是服务端这三项**存不存在的布尔值，永远不下发内容**。这四个字段存在的理由只有一个：让浏览器能逐字段复算出下一次请求会落到哪个 provider，否则右上角的芯片会指着一个 provider、请求却打向另一个（`.env` 只填了一半的网关、或密钥属于没被选中的那个通道时就会这样）。

`mapboxToken` 是唯一会明文下发的凭据，且必须是公开令牌：**`sk.` 开头的私密令牌会被这个接口扣下**（返回空串），启动日志同时打一条 warning。

### `GET /api/settings`

读 `data/config.json`。**密钥一律是掩码，这个接口没有任何返回原文的分支。**

```json
{
  "config": {
    "provider": "openai",
    "openai_base_url": "https://gw.example.com",
    "openai_api_key": "sk-oai…b7f2",
    "openai_model": "qwen-vl-max",
    "mapbox_token": "pk.eyJ1Ijoi…"
  },
  "historyCount": 3
}
```

`config` 是 `store.public_config()` 的输出，只包含**实际存了值**的字段：

- `anthropic_api_key` / `openai_api_key` 过 `overrides.mask`：前 6 位 + 后 4 位，长度 ≤ 14 的整个变成 `***`。
- `openai_base_url` 过 `overrides.safe_url`，**只剩 scheme + host（+ 端口）**，路径和 userinfo 全部丢掉。这不是洁癖：不少中转把凭据写在路径里（`https://relay.example/sk-abc…/v1`）或写在 userinfo 里（`https://user:key@host/v1`），把地址原样回显给一个**没有鉴权**的接口，和直接把密钥交出去是一回事。代价是设置卡没法把你填的地址尾巴显示回来。
- `mapbox_token` **不打码**：它是公开的 `pk.` 令牌，本来就要经 `/api/config` 明文下发给浏览器。
- `historyCount` 是 `store.list_shots()` 的条数。

服务端自己的请求路径读的是 `store.read_config()`（原文），那个函数**不允许出现在任何路由里**。

### `PUT /api/settings`

请求体是一个 JSON 对象，**merge patch 语义**：只写你提到的字段。

```bash
curl -X PUT http://127.0.0.1:8000/api/settings \
  -H "Content-Type: application/json" \
  -d '{"provider":"claude","anthropic_api_key":"sk-ant-…"}'
```

- 只有 `CONFIG_FIELDS` 里那八个字段会被存，其余**静默忽略**（只记一条 debug 日志，键名是调用方控制的，不进正常日志）。这是白名单而不是过滤器：这个文件之后要盖在操作者的 `Settings` 上，能塞任意键就等于能改 `max_upload_bytes`、`trusted_proxies` 这些界面本来够不着的闸门。
- 值先 `strip()`；**空串表示删掉这一项**。字符串和数字收下（JSON 里很容易把 `"0"` 写成 `0`），`true` / `null` / 数组 / 对象一律拒，不会被 stringify 成 `"True"` 存进去。超过 500 字符截断；含控制字符整条拒绝——这些值之后要被拼进 HTTP 请求头或 base URL。
- **这一条比 `X-RIL-*` 那条路松一档**：`store._coerce` 只拦控制字符，不拦非 ASCII，所以直接 `curl -X PUT` 塞一个中文模型名会**存下来并返回 200**，然后在调用上游时才失败；同样的值走请求头会被 `overrides._clean` 当场拒掉。设置卡里的 `web/settings.js` 会在保存前拦住它——对界面用户来说那是唯一挡在中间的东西。
- **改 `openai_base_url` 却没在同一个请求里给 `openai_api_key`，返回 400 `bad_override`**（`app/main.py:write_settings`）。这是 `X-RIL-*` 那条路上同一条规矩：只给目的地不给密钥，服务端就会把**已保存的**那把密钥发到调用方指定的地址上。地址和已存的一样时不触发。
- 写完调 `_reload_settings()`，下一个请求就用新配置，不必重启。日志只记**被改动的字段名**，不记值。

返回同样是掩码视图：

```json
{ "config": { "provider": "claude", "anthropic_api_key": "sk-ant…7g2k" } }
```

请求体不是合法 JSON、或不是一个 JSON 对象时返回 400 `bad_json`。这个响应体是**重新读一遍磁盘**得来的（路由自己再调一次 `public_config()`），所以写盘失败时你看到的是磁盘上真实的内容，而不是刚发过去的那份——免得界面报一个其实没存下来的密钥。

### `DELETE /api/settings`

删掉整个 `data/config.json`，连同 `_write_atomic` 可能残留的 `.config.json.*.tmp`（那些临时文件里也是明文密钥），然后重建 `settings`，回到 `.env` 和默认值。

```json
{ "config": {} }
```

删掉的是**这个应用对密钥的记忆**，不是磁盘上的字节：已释放的块在多数文件系统上仍然可读。真怀疑泄露了就去上游轮换密钥。

### `GET /api/history`

```json
{
  "shots": [
    {
      "id": "20260807T041233912345-9f3a1c04",
      "created_at": "2026-08-07T04:12:33Z",
      "media_type": "image/jpeg",
      "size_bytes": 486213,
      "payload": { "result": { }, "meta": { } }
    }
  ]
}
```

**最新的在前**，最多 20 条（`HISTORY_CAP`）。`payload` 就是当初那次 `/api/locate` 的完整响应体，所以回看历史不需要重新请求模型。**图片字节不在这里**——base64 塞进索引会让它膨胀到 4/3，列一次历史就等于把每张照片都下载一遍；图片走下面那个接口。

`id` 是 `%Y%m%dT%H%M%S%f` 的 UTC 时间戳加 4 字节随机尾巴，所以字典序就是时间序。`history.json` 读不出来（缺失、被手改坏、编码不对、嵌套过深）时返回 `{"shots": []}` 而不是报错，下一次成功写入会把这个文件修好。

### `GET /api/history/{id}/image`

返回图片字节本身。`Content-Type` 取索引里记的 `media_type`；索引丢了就按扩展名推；都认不出就是 `application/octet-stream`——**不会把调用方选的类型原样当 Content-Type 发**。响应头带 `Cache-Control: private, max-age=300`。

`id` 只允许 `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`：**没有点就拼不出 `..`，没有 `/` `\` `:` 就拼不出分隔符和盘符**，Windows 的设备名（`NUL`、`CON`、`COM1`…）另外单独挡掉。这一层是真正生效的那道闸——框架交给我们时百分号编码早就解开了，`%2e%2e%2f` 到这里就是 `../`。落到磁盘之前还有一道 `resolve()` + `is_relative_to(shots/)` 兜底，防的是 `shots/` 里的符号链接。id 不合法和照片不存在都返回 404 `not_found`，不作区分。

### `DELETE /api/history/{id}`

```json
{ "deleted": true }
```

`deleted` 说的是**实际发生了什么**：图片文件和索引条目至少动了一个才是 `true`。删第二次是 `false`，不是错误。索引重写失败时也是 `false`——那条记录还在列表里、还占着 `HISTORY_CAP` 的名额，谎报成功会让调用方再也不重试。

### `DELETE /api/history`

清空全部：删掉每个图片文件、把 `shots/` 里剩下的东西（子目录、临时文件都算）一并扫掉、再把索引写成 `[]`。

```json
{ "removed": 20 }
```

`removed` 是**清掉的索引条目数**；索引写失败时返回 0，因为那时列表下次刷新还会原样出现。和 `DELETE /api/settings` 一样，这只是「应用忘了」，不是「磁盘擦了」。

**这三个 DELETE 和 `PUT /api/settings` 一样没有任何鉴权**：能连上这个端口的人可以改掉操作者的密钥、也可以把历史和照片一次删光。详见「安全边界」。

### `POST /api/verify`

设置卡的「测试连接」用的就是它。**没有请求体**，凭据全部走上面那七个 `X-RIL-*` 请求头；一个头都不带时，探测的就是服务端当前生效的凭据（`data/config.json`，其次 `.env`）。探测本身免费：Claude 调 `models.list`，网关调 `GET {base}/models`，都不消耗 token。

```bash
curl -X POST http://127.0.0.1:8000/api/verify \
  -H "X-RIL-OpenAI-Base: http://127.0.0.1:11434/v1" \
  -H "X-RIL-OpenAI-Key: sk-…"
```

探测成功与否都返回 HTTP 200，且形状固定（`ok` 由 `code == "ok"` 推导，不是独立传的，所以 `unconfirmed` 不会被误当成成功）：

```json
{
  "ok": true,
  "provider": "claude",
  "model": "claude-opus-5",
  "code": "ok",
  "message": "密钥可用，将使用 claude-opus-5。",
  "detail": ""
}
```

`code` 的全部取值：

| `code` | `ok` | 含义 |
| --- | --- | --- |
| `ok` | true | 密钥可用 |
| `not_configured` | false | 该通道的凭据没填齐（Claude 缺 key，网关缺地址或 key） |
| `auth` | false | 密钥无效或过期（Anthropic 鉴权失败，或网关返回 401 / 403） |
| `unconfirmed` | false | 仅网关：`/models` 返回 404 / 405，说明地址可达但密钥无从确认（不少中转只代理 `/chat/completions`） |
| `rate_limited` | false | 上游限流（Anthropic `RateLimitError`，或网关返回 429） |
| `timeout` | false | 20 秒内没连上 |
| `network` | false | 连不上上游 |
| `upstream` | false | 其余状态码、地址不合法，以及任何未预料的异常 |

`detail` 是上游返回的原文，先过一遍 `overrides.scrub` 再截到 200 字符（`MAX_DETAIL`）；没有可展示原文时是空串。探测超时固定 20 秒（`PROBE_TIMEOUT`），**不受 `REQUEST_TIMEOUT_SECONDS` 影响**——用户是在盯着设置面板的转圈，不是在等一次视觉推理。请求头不合法返回 400 `bad_override`；**它和 `/api/locate` 共用同一个限流桶**，超了返回 429 `rate_limited`。

### `POST /api/locate`

`multipart/form-data`，字段名固定为 `image`。凭据同样可以用上面那七个 `X-RIL-*` 请求头逐字段覆盖。成功一次就会往 `data/` 里存一张照片和一条历史（见「服务端存了什么」）。

可选的 `lang` 表单字段 ∈ {`zh`, `en`}，默认 `zh`，决定结果里**散文**的语言——`summary`、证据的 `observation` / `implication`、备选的 `reason`、`notes`。网页会自动带上当前界面语言；`name_zh` / `name_en` 的语义在两种语言下都不变（`evidence[].category` 在线上始终是 `app/prompt.py` 里 `RESULT_SCHEMA` 那个固定的中文枚举，英文界面显示的是它的译文）。

```bash
curl -X POST http://127.0.0.1:8000/api/locate -F "image=@photo.jpg"
```

成功返回 200，结构为 `{ result, meta }`。下面这个例子刻意选了一次**只走到国家一级**的判定，用来演示精度纪律：`precision` 是 `country`，于是 `region` / `city` 一律是「未确定」+ `known: false`，`locality` 是空串，半径也被抬到了国家级下限之上。

```json
{
  "result": {
    "country": { "name_zh": "葡萄牙", "name_en": "Portugal", "known": true },
    "region":  { "name_zh": "未确定", "name_en": "", "known": false },
    "city":    { "name_zh": "未确定", "name_en": "", "known": false },
    "locality": "",
    "precision": "country",
    "coordinates": { "lat": 39.6, "lon": -8.2, "radius_km": 260 },
    "confidence": 71,
    "confidence_band": "high",
    "summary": "蓝白 azulejo 贴面、黑白碎石人行道与葡萄牙语店招同时出现，可以判到葡萄牙；但画面里没有任何地名、区号或地标，无法再往城市一级收敛。",
    "evidence": [
      { "category": "建筑风格", "weight": "high",
        "observation": "沿街立面大面积贴蓝白釉面瓷砖，配铸铁小阳台，屋顶为红色筒瓦。",
        "implication": "azulejo 贴面是葡萄牙特征，与西班牙南部的白墙抹灰做法不同。" },
      { "category": "基础设施", "weight": "high",
        "observation": "人行道为黑白两色小方石拼几何图案，路缘石高而窄。",
        "implication": "calçada portuguesa 铺装，葡萄牙全境通用——它能定国家，定不了城市。" },
      { "category": "文字与标识", "weight": "medium",
        "observation": "店招上写着「Pastelaria」，牌面上没有电话、地址或任何地名。",
        "implication": "葡萄牙语拼写确认了语言区，但缺少区号与地名，收敛不到具体城市。" },
      { "category": "车辆与车牌", "weight": "medium",
        "observation": "画面边缘一辆轿车挂白底车牌，左端有蓝色欧盟色条，字符分辨不清。",
        "implication": "欧盟制式车牌可以排除巴西等其他葡语国家，但读不出发牌地区。" }
    ],
    "alternatives": [
      { "country": "西班牙", "region": "", "city": "", "likelihood": 14,
        "reason": "同为伊比利亚半岛的临街小店样式，但瓷砖立面与黑白碎石铺装在西班牙少见得多。" },
      { "country": "巴西", "region": "", "city": "", "likelihood": 6,
        "reason": "葡语招牌与碎石铺装同样成立，但欧盟制式车牌把它排除在外。" }
    ],
    "notes": "只要能拍到任意一块带地名的路牌或一张写了地址的店招，精度就能从国家直接跳到城市。"
  },
  "meta": {
    "elapsedMs": 11842,
    "provider": "claude",
    "model": "claude-opus-5",
    "analyzedSize": [2000, 1500],
    "sourceSize": [4032, 3024],
    "exifGps": { "lat": 38.712014, "lon": -9.129831 },
    "shotId": "20260807T041233912345-9f3a1c04"
  }
}
```

`meta` 各字段：`elapsedMs` 是后端调用模型的耗时（毫秒，不含上传）；`provider` / `model` 是本次实际使用的通道与模型；`analyzedSize` 是缩放后真正送进模型的 `[宽, 高]`；`sourceSize` 是原图 `[宽, 高]`；`exifGps` 是从原图 EXIF 读出的真实坐标，**没有 GPS 信息时为 `null`**，它只用于让你对照模型猜得准不准；`shotId` 是这张照片在服务端历史里的 id，拿去请求 `GET /api/history/{id}/image` 就能取回图片本身，**落盘失败时这个字段整个不出现**（分析结果照常返回，只是没存下来）。

`result` 里几处可能为空的字段：`coordinates` 在经纬度不可解析时为 `null`；`locality` / `notes` 无内容时是空字符串；地名缺失、或该层级比 `precision` 更细而被清空时，`name_zh` 填「未确定」、`name_en` 为空串、`known` 为 `false`。`country` / `region` / `city` 三个对象上的 `known` 就是给前端用的"这一级到底算不算数"的开关，别拿 `name_zh` 去和「未确定」做字符串比较。

出错时返回 `{ "error": { "code": "...", "message": "..." } }`，`message` 是可直接展示给用户的中文。

### `POST /api/locate/stream`

和 `/api/locate` **完全同一件事、同一套参数（含 `lang`）、同一套限流与覆盖头**，区别只在于边算边报。界面用的是这个；`curl` 和脚本用上面那个更省事。

响应是 `text/event-stream`，一共三种事件：

| event | data | 含义 |
| --- | --- | --- |
| `partial` | `{"field": "...", "value": ...}` | 模型刚写完的一个顶层字段，**未经归一化**的原话 |
| `partial` | `{"field": "...", "index": N, "value": ...}` | 某个数组字段的**第 N 个元素**刚写完 |
| `result` | `{ result, meta }` | 和 `/api/locate` 一模一样的完整响应体，**这个才作数** |
| `error` | `{ "code": "...", "message": "..." }` | 出错；此后不再有别的事件 |

```
event: partial
data: {"field": "precision", "value": "city"}

event: partial
data: {"field": "country", "value": {"name_zh": "巴拉圭", "name_en": "Paraguay"}}

event: partial
data: {"field": "coordinates", "value": {"lat": -25.2937, "lon": -57.6089, "radius_km": 12}}

event: partial
data: {"field": "evidence", "index": 0, "value": {"category": "文字与标识", "...": "..."}}

event: result
data: {"result": {...}, "meta": {...}}
```

**有没有 `index` 是唯一的区别**：有就是数组 `field` 的第 N 个元素，客户端把它渲染进第 N 行、替换那一行原来的东西；没有就是整个字段。

会发出 `partial` 的东西分两类：

- **整个字段**：`precision`、`country`、`region`、`city`、`locality`、`coordinates`、`confidence`、`confidence_band`、`summary`。
- **逐条**：`evidence`、`alternatives`。这两个数组**永远不会整体发出**——元素已经把内容都带过去了，而 `evidence` 整体一条就有 4 KB 左右，再发一遍等于让浏览器解析完就扔。

`notes` 不发（收尾的补充说明，单独看没有意义）。`data` 一律 `ensure_ascii`，中文走 `\uXXXX`，免得中途被某个代理把 UTF-8 截断在半个字符上。

**一个例外：数组字段收到不带 `index` 的整体值，意思是「把这个字段已经画出来的行全部丢掉」。** 只有模型在同一个 JSON 里把 `evidence` 写了两遍时才会出现（后一遍作数，前一遍那些行在最终结果里根本不存在）。除此之外这两个字段不会有整体值，所以不歧义。

**三条必须知道的：**

- **`partial` 是模型的原话，`result` 才是结论。** `partial` 没经过 `normalize`：没有精度对账、没有半径下限、没有 `known` 标志。模型常常写出一个街道名，却只肯声明 `precision: "city"`——`result` 里那个 `locality` 就是空的。客户端必须让 `result` 无条件覆盖之前显示的一切。**`precision` 排在 schema 第一位就是为了这个**：前端一上来就知道上限，把更细的层级当作没有，于是标题只会越来越精确，不会先精确后倒退。
- **它省的是"写"的时间，不是"想"的时间。** 模型先思考再输出，思考阶段一个字符都不会流出来。上面那次实测 24 秒里，前 3.7 秒是纯思考，屏幕上只有扫描动效和计时；剩下 20 秒全程有东西在动。effort 越高，思考占比越大，这个功能的收益越小。
- **HTTP 状态码一律 200。** 图片格式不对、限流、覆盖头非法——这些在 `/api/locate` 上是 400/429 的情况，在这里是一条 `error` 事件，因为流已经开始了。客户端只看事件，不要看状态码。

`app/streaming.py` 里的 `PartialJSON` 是这条流的解析器：它只报**已经闭合**的东西，字符串里的 `{` `}` `,` 和转义都不算数，数字要等到分隔符出现才敢报（`95` 有可能是 `951` 的一半），嵌套对象要等自己那个右括号，数组元素要等它自己那一层收口。分块位置不影响结果——逐字符喂和整块喂产出完全相同的报告序列，连 `index` 都一样；这条性质有 300 组随机切分守在 `python -m app.streaming` 的 58 项自检里。解析失败不会连累整条流：那一条丢掉，后面的照常报，而且**下标是数组位置、不是计数**，所以丢掉的那条留下一个洞，不会让后面的行整体前移。结尾还有一次权威的 `json.loads` 兜底。

## 错误码

所有报错的响应体都是 `{ "code": "...", "message": "..." }`，`message` 是可直接展示的中文。英文界面对认识的 `code` 显示自己的译文，不认识的才显示服务端原话；直接调 API 的程序请按 `code` 分支。

| code | HTTP | 触发条件 | 怎么办 |
| --- | --- | --- | --- |
| `rate_limited` | 429 | 本机限流：该 IP 一小时内对 `/api/locate`、`/api/locate/stream` 与 `/api/verify` 的请求合计超过 `REQUESTS_PER_HOUR` 次；流式那条以 200 + 一条 `error` 事件的形式返回 | 等一会儿，或调大 / 关闭 `REQUESTS_PER_HOUR` |
| `bad_override` | 400 | 某个 `X-RIL-*` 头不可用：超过 500 字符、含非 ASCII 或不可打印字符、provider 不是 auto/claude/openai、Base URL 不是 http(s) 完整地址，或**覆盖了 Base URL 却没同时给该网关的 Key**。`PUT /api/settings` 在**改网关地址却没同时给该网关 Key** 时也返回它 | 按 `message` 改对应字段；`/api/locate`、`/api/locate/stream`、`/api/verify`、`PUT /api/settings` 四处都会返回它 |
| `bad_json` | 400 | `PUT /api/settings` 的请求体不是合法 JSON，或不是一个 JSON 对象 | 检查 `Content-Type` 和请求体本身 |
| `not_found` | 404 | `GET /api/history/{id}/image` 的 id 不合法，或这张照片已经不在历史里（被删、被 `HISTORY_CAP` 挤掉） | 重新拉一次 `GET /api/history` |
| `empty` | 400 | 上传体为空 | 重新选文件 |
| `too_large` | 413 | 原始字节超过 `MAX_UPLOAD_MB` | 压缩后再传，或调大上限 |
| `bad_image` | 400 | Pillow 解不开，或格式不在支持列表内 | 换成 JPG / PNG / WebP |
| `not_configured` | 503 | 当前 provider 的密钥没填齐 | 在设置卡里填（`PUT /api/settings`，立刻生效），或填 `.env` 后重启；openai 通道需 base_url 与 key 同时具备 |
| `auth` | 502 | Anthropic 鉴权失败，或网关返回 401 | 检查 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 是否有效未过期 |
| `network` | 502 | 连不上 Anthropic API 或网关（含 Claude 通道的超时） | 检查网络、代理、`OPENAI_BASE_URL` 是否可达 |
| `upstream` | 502 | 上游返回了非 200 且不属于以上情况的状态码 | 看后端日志里的上游原文，多为模型名不存在 |
| `rate_limited` | 503 | 上游模型限流（Anthropic RateLimitError 或网关 429） | 稍后重试；注意它和本机限流同名但 HTTP 状态不同 |
| `timeout` | 504 | 网关在 `REQUEST_TIMEOUT_SECONDS` 内没响应（仅 OpenAI 通道） | 重试，或调大超时、换更快的模型 |
| `refused` | 422 | Claude 因安全策略拒答（`stop_reason == "refusal"`） | 换一张照片；开启 `REFUSAL_FALLBACK` 可让服务端先自动改用备选模型试一次 |
| `truncated` | 502 | Claude 输出被 `max_tokens` 截断 | 直接重试 |
| `billing` | 402 | Anthropic 账户余额不足 | 密钥本身没问题，去 Plans & Billing 充值。**不会重试**——降级救不了计费问题 |
| `forbidden` | 403 | 密钥没有访问该模型的权限 | 换密钥，或把模型名改成该密钥有权访问的 |
| `bad_request` | 502 | Claude 通道的 400，且既不属于上面两种永久性失败，也没提到降级能去掉的参数；或逐级降级到最后一种姿势仍被拒 | 看日志里的原始报错，通常是模型 id 写错、图片超限或 SDK 版本过旧 |
| `bad_response` | 502 | 返回体里挖不出可解析的 JSON，或网关返回了预期外的结构 | 重试；反复出现说明该模型跟不住 JSON schema，换一个 |
| `internal` | 500 | 未预料的异常，堆栈只进日志不返给浏览器 | 查后端日志 |

## 项目结构

```
reverse-image-location/
├─ app/
│  ├─ __init__.py      版本号
│  ├─ config.py        环境变量 → 冻结的 Settings 数据类，provider 自动选择规则
│  ├─ imaging.py       Pillow 解码、EXIF GPS 读取、转正、缩放、转 base64 JPEG
│  ├─ prompt.py        分析师系统提示词、证据分类枚举、RESULT_SCHEMA
│  ├─ overrides.py     X-RIL-* 请求头 → 本次请求的 Settings，provider 重新解析、mask / scrub / safe_url
│  ├─ providers.py     Claude / OpenAI 兼容网关双通道调用，逐级降级、normalize、LocateError、
│  │                   locate_stream（边写边报）
│  ├─ streaming.py     PartialJSON：从还没写完的 JSON 里安全摘出已闭合的顶层字段，
│  │                   以及 evidence / alternatives 的每一个元素；分块位置无关，
│  │                   python -m app.streaming 跑 58 项自检
│  ├─ store.py         data/ 落盘：config.json 的读写与掩码、history.json 与 shots/、
│  │                   CONFIG_FIELDS 白名单、路径校验、原子写（临时文件 → fsync → replace）
│  ├─ verify.py        免费的凭据可达性探测，结果里的每个字符串都先脱敏再截断
│  └─ main.py          FastAPI 应用：全部 API 路由、SSE 封帧、_reload_settings、内存限流、
│                      错误映射、挂载 web/ 静态目录
├─ web/
│  ├─ index.html       单页界面：左图版右读数
│  ├─ styles.css       航图图版视觉系统，深浅双主题由 CSS 自定义属性驱动
│  ├─ extras.css       示意地球、会话缩略图轨、toast 等附加组件的样式
│  ├─ map.css          地图面板样式：细线外框、等宽脚注、洋红定位点
│  ├─ i18n.js          语言层：zh/en 两份词典、t()/apply() 与 data-i18n 标注、
│  │                   页头 中/EN 切换的持久化（localStorage "ril-lang"）
│  ├─ globe.js         内置示意地球：正射投影经纬网 SVG，不画海岸线、不联网
│  ├─ map.js           Mapbox 三级降级：交互地图 → 静态图 → 一行提示，需 MAPBOX_TOKEN
│  ├─ settings.js      设置卡草稿的校验，以及"下一次请求会用什么"的推算；不碰 localStorage
│  ├─ app.js           上传 / 拖拽 / 粘贴、SSE 读取与渐进渲染（临时卡就地改写、证据逐条
│  │                   插入、最终结果接管时复用同一张地图与同一个仪表盘）、扫描动效、
│  │                   历史轨、快捷键、导出、设置卡（模型 / 地图 / 数据三页）
│  ├─ fonts/           IBM Plex Sans / Mono / Condensed 子集 woff2，自托管；
│  │                   OFL 1.1 全文在同目录 LICENSE-IBM-Plex.txt
│  └─ vendor/
│     ├─ motion.min.js    Motion 11.18.2，本地 vendored（MIT），暴露 window.Motion
│     └─ LICENSE-motion.txt
├─ data/               运行时才出现，已 gitignore + dockerignore；位置可用 RIL_DATA_DIR 改
│  ├─ config.json      界面保存的配置，含明文 API Key，创建时 0600
│  ├─ history.json     最近 20 次分析的元数据与完整响应体
│  └─ shots/           对应的 JPEG，一张一个文件
├─ run.py              一条命令从 clone 到跑起来：建 .venv、装依赖、带对参数起 uvicorn、
│                      开浏览器。只用标准库（它在依赖装好之前就要跑）
├─ requirements.txt
├─ LICENSE             MIT
├─ .env.example
├─ .env                可选，你自己建才有；已 gitignore（连同 .env.bak / .env.local 这类副本）
├─ Dockerfile
├─ compose.yaml
├─ .dockerignore
└─ .gitignore
```

前端的所有代码都由 FastAPI 的 `StaticFiles` 从 `web/` 直接提供：**没有 npm、没有构建步骤、没有外部字体**（IBM Plex 的子集就在 `web/fonts/` 里），Motion 也是本地 vendored 的。**唯一从别人服务器上取的东西是 Mapbox**：GL JS 脚本与它的 CSS 从 `api.mapbox.com` 加载，地图瓦片同理——而这两件事都只在配置了 `MAPBOX_TOKEN` 时才发生。留空这一项，整页零外部请求，详见下面一节。

## 安全边界

这是一个**在自己机器上、通过 localhost 使用**的工具，下面每一条都是从这个前提推出来的。把端口开出去之前请把这一节读完。

### 绑回环地址，不要跑在 `0.0.0.0` 上

**所有接口都没有任何鉴权。** 没有登录、没有 token、没有来源校验。能连上这个端口的人，就能用你的密钥、你的额度和你的出网权限。

配置和历史落盘之后，这件事比以前重得多：

- **`PUT /api/settings` 没有鉴权。** 谁能连上这个端口，谁就能改写操作者已保存的凭据——换掉密钥、换掉模型、把 provider 掰到另一条通道，或者把 `openai_base_url` 指到他自己的机器上（他得同时给上自己的 key，见「保护操作者自己那把密钥的锁」）。
- **`DELETE /api/history` 没有鉴权。** 一个请求就能把这台机器上存着的历史和照片全部删光；`DELETE /api/settings` 同理，一个请求删掉全部已保存的配置。
- 这两件事都不可逆，也查不出是谁干的——服务端没有身份可记，日志里只有字段名和条数。

**这是到目前为止最强的一条「只绑回环」的理由。** `uvicorn` 默认只监听 `127.0.0.1`，保持原样；`compose.yaml` 也只把端口发布到 `127.0.0.1`。

### 服务端请求伪造（SSRF）是这个功能的固有代价

`X-RIL-OpenAI-Base` 的作用就是让服务端去请求**调用方指定的那个 URL**。`app/overrides.py:_base_url` 只校验两件事：scheme 是 `http` 或 `https`，以及有 host。**故意不拦私网地址**——这个功能存在的意义就是接自建 / 局域网网关，一份私网黑名单会把 `http://127.0.0.1:11434/v1` 这类正常用法全挡掉。

代价要说明白：能连上这个端口的人，就能拿这台服务器扫它自己的内网。`/api/verify` 返回的 `code` 足以区分「端口开着」（`ok` / `auth` / `unconfirmed` / `upstream`）、「端口关着」（`network`）和「被防火墙丢包」（`timeout`），并且非 200 响应体的前 200 个字符会（脱敏后）出现在 `detail` 里。对一个本机工具，这是接受下来的取舍；对一个别人能连的端口，这是一个开放的探测代理。

### 保护操作者自己那把密钥的锁

`parse_overrides` 会**直接拒绝**只发了 `X-RIL-OpenAI-Base`、却没同时发 `X-RIL-OpenAI-Key` 的请求（400 `bad_override`）。理由很直白：否则调用方只提供目的地，服务端却自动补上当前生效的那把 `openai_api_key`（`data/config.json`，其次 `.env`）——等于替调用方把操作者的密钥送到一个他自己指定的地址上，而他本来根本没有这把密钥。要求两个头同时出现，对设置卡零成本（它本来就一起发），却不需要任何地址黑名单就把这条路堵死了。

Anthropic 那把密钥从来没有这个风险：没有可覆盖的 Anthropic base URL，`X-RIL-Anthropic-Key` 只能换密钥本身，换不了它发去哪里。

**这条规矩对已保存的配置一字不差地成立。** `PUT /api/settings` 在 `openai_base_url` 与已存值不同、而请求体里又没有非空的 `openai_api_key` 时，直接返回 400 `bad_override`（`app/main.py:write_settings`）。差别只在被送出去的是哪一把密钥：请求头那条路上是 `.env` 里的，这条路上是 `data/config.json` 里已经存着的那把——而写这个文件不需要任何凭据。

### 密钥现在躺在磁盘上

`data/config.json` 里存的是**明文** API Key。没有加密，没有主密码，没有任何密钥库。

- 文件在**创建的那一刻**就带上 `0o600`（仅属主读写），不是写完再补 chmod——中间没有哪怕一瞬间是别人可读的。原子写用的临时文件同样以 `O_EXCL` + 0600 创建。
- 但要照直说：**在 Windows 上 `os.chmod` 基本是个空操作**。`app/store.py` 里的原话是——它只切换只读位，**不会限制其他用户**，也没有 umask 这回事；0600 在 POSIX 上当真，在 Windows 上只能当注释看，那里真正生效的是从父目录继承的 NTFS ACL。所以在 Windows 上，数据目录本身必须放在一个私密的位置。
- **删除不等于擦除。** `DELETE /api/settings` 删掉文件（并清掉可能残留的 `.config.json.*.tmp`——那些文件里也是明文密钥），但已释放的块在多数文件系统上仍然可读。认为泄露了就去上游轮换，别指望这个删除。
- 备份、云盘同步、`docker cp`、快照，都会把它一起带走。

### 读出来是掩码，写进去不回显

- `GET /api/settings` **没有任何返回密钥原文的分支**。`store.public_config()` 是路由唯一可以调的读取函数；返回原文的 `store.read_config()` 只给服务端自己的请求路径用，不允许出现在任何路由里。
- `PUT /api/settings` 的响应体是同一份掩码视图——保存完不会把你刚填的东西再念一遍。
- `openai_base_url` 在这两个接口里都只剩 scheme + host：中转把凭据写在路径里或 userinfo 里是常事，原样回显地址本身就是一次泄露。
- 日志里只有被改动的**字段名**和 `mask()` 的输出，没有第二条路径。

### 照片也在磁盘上了

每次成功分析后，送进模型的那张 JPEG 会写进 `data/shots/`。**任何能读这台机器文件系统的人，都能看到分析过的每一张照片**——它们不再只活在内存里，也不再随浏览器关闭而消失。重启程序不清、关浏览器不清、清浏览器数据也不清（数据已经不在浏览器里）；只有 `DELETE /api/history` 或直接删目录才清。

落盘的是 `imaging.prepare` 的产物（缩放 + 重编码 + EXIF 已剥），所以原图里的 GPS 不会跟着上磁盘。

### 限流是礼貌，不是安全措施

两件事同时成立：

- `REQUESTS_PER_HOUR` 按客户端地址计数，而 `X-Forwarded-For` **只有来自 `TRUSTED_PROXIES` 里列出的地址时才会被采信**（默认为空＝谁的都不信）。
- 但 `uvicorn` 自己的 `--proxy-headers` **默认就是开着的**，它会在应用看到这个请求之前，就用 `X-Forwarded-For` 改写来源地址（它自己的默认信任列表是 `127.0.0.1`）。于是从回环地址来的调用方照样能伪造。

实测：`REQUESTS_PER_HOUR=3`，用六个不同的伪造 `X-Forwarded-For` 连发六次——带 `--no-proxy-headers` 时是 `200 200 429 429 429 429`，不带时六次全过。**除非前面真的有一个可信代理，否则一律用 `--no-proxy-headers` 启动**——`run.py` 和 `Dockerfile` 的 `CMD` 里都已经写死了它，只有自己手敲 `uvicorn` 命令行时需要记得。`REQUESTS_PER_HOUR > 0` 且 `TRUSTED_PROXIES` 为空时，启动日志会打一条 warning 提醒这件事。

限流本身也只是进程内存里的滑动窗口：重启清零，多副本各算各的。

### 不带 `X-RIL-*` 头的请求，花的是操作者的密钥

一个空手过来的 `POST /api/locate` 会直接拿服务端当前生效的凭据（`data/config.json`，其次 `.env`）跑一次视觉推理。Claude 通道每次 `MAX_TOKENS = 16000`，思考深度用当前生效的 `anthropic_effort`（默认 `medium`，`app/providers.py`），网关通道每次 `max_tokens: 4096`。既然没有鉴权，就没有任何东西拦着别人替你花这笔钱——顺带还会在你的磁盘上多留一张他的照片。

### 请求头本身没有总量限制

`MAX_VALUE_LEN = 500` 只管 `app/overrides.py:_FIELDS` 里那七个认识的头名（以及 `PUT /api/settings` 那八个字段），别的头一概不看；而 `uvicorn` 在用 httptools（`uvicorn[standard]` 装出来的默认解析器）时，对请求头的大小和数量都不设上限。端口只要可能被不受信任的东西碰到，前面就该放一个反向代理来做这些限制。

### 哪些东西被打码了，哪些没有

- **`overrides.scrub`**（所有上游文本的必经之路）：先折叠空白——上游把密钥拆成两行回显就能躲过逐字匹配，而折叠这一步又会把它拼回来，顺序反了等于白做；匹配**不区分大小写**；去掉全部空白后密钥仍在文本里的，整段文本直接丢弃（返回「上游回显了密钥，内容已丢弃」），因为那种文本已经没法靠编辑救回来，诊断信息不值这个价。此外还会把任何长得像 bearer token 的东西（`sk-` / `pk-` / `rk-` 打头的长串、`Bearer …`）替换成 `[redacted]`，**包括我们手里根本没有副本的密钥**——比如调用方指定的中转站回显出来的操作者那把。截断放在最后一步，免得跨越截断点的密钥被切成半截漏出去。所以一份上游错误体没法把密钥带进日志或浏览器。
- **`overrides.safe_url`**：任何要展示的网关地址都只保留 scheme + host（+ 端口）。有的中转把凭据写在路径里或 userinfo 里，原样回显地址本身就是一次泄露。
- **日志**：出现在日志里的凭据一律是 `mask()` 的输出（前 6 位 + 后 4 位，长度 ≤ 14 的整个变成 `***`），没有第二条路径。
- **它挡不住什么**：打码只保证**这个端口**不吐原文，保证不了磁盘。`data/config.json` 里的那份是明文的，`data/shots/` 里的照片也是原样的——任何能读这台机器文件系统的人，以及任何拿到备份、云盘同步副本或容器卷的人，都能把它们拿走。共享或公网部署时，这台机器上就不该有密钥。（浏览器侧已经不存任何凭据了；从旧版本升上来的话，手动清一次这个 origin 的 `localStorage` 可以把遗留的 `ril-model-config` 抹掉。）

## 边界与隐私

- **照片会存在运行这个服务的机器上**：每次成功分析后，送进模型的那张 JPEG 会写进 `data/shots/`，结论写进 `data/history.json`。保留最近 `HISTORY_CAP`（20）张，超出的连同图片文件一起删除；`DELETE /api/history` 一次清空。**重启程序不清、关浏览器不清、清浏览器数据也不清**——数据已经不在浏览器里了。**这是行为变更**：早先的版本只在内存里处理、用完即弃。
- **密钥也在这台机器上**：界面里保存的凭据明文写进 `data/config.json`（创建时即 0600，但 Windows 上 `chmod` 基本无效，见「安全边界」）。它替代的就是 `.env`，请照 `.env` 对待。`DELETE /api/settings` 只是让应用忘掉它，不擦磁盘。
- **存的是模型看到的那张，不是你上传的原图**：`imaging.prepare` 已经缩放、重编码并剥掉了全部 EXIF，落盘的是那份结果。所以原图里的 GPS 不会进模型，也不会进磁盘。
- **照片的出站去向只有一个**：当前生效的那个模型接口，由 `data/config.json`、`.env` 或本次请求的 `X-RIL-OpenAI-Base` 决定（见「安全边界」）。除此之外不发给任何地方。
- **EXIF 被剥掉**：送进模型的是重新编码的 JPEG，不含 GPS、机型、时间戳等任何元数据。原图里的 GPS 仅回显在 `meta.exifGps` 供你自己对照。
- **但配了 `MAPBOX_TOKEN` 就不再是全离线的**：这是个要自己权衡的取舍，不是脚注。一旦 `/api/config` 下发了非空令牌，浏览器就会去 `api.mapbox.com` 取 Mapbox GL JS（脚本与 CSS，版本写在 `web/map.js` 的 `GL_VERSION` 里），然后带着**模型推断出的那对经纬度**去请求瓦片。GL 脚本万一没到，会退回 Static Images API，那个图片 URL 里同样明文写着坐标和你的令牌（此时地图脚注会标出「静态图 · 不可缩放拖动」，控制台也会打一条 warning）。换句话说：照片不出你的机器，但**结论坐标会到 Mapbox 手里**。

  > 为什么脚本从 CDN 走而不是 vendored 进仓库：GL JS 从 2.0 起就不是开源软件了，它按 Mapbox 的服务条款授权，把那 1.5 MB 提交进一个公开仓库等于在转分发别人的 SDK（Motion 是 MIT，所以留在 `web/vendor/`）。实际上也没什么可惜的——这块面板本来就需要 Mapbox 的瓦片和令牌才画得出东西，`api.mapbox.com` 连不上的话，脚本放在哪儿都一样。实测冷缓存下脚本 116 ms 到位、422 ms 出可交互地图；`GL_TIMEOUT_MS` 那 20 秒是留给比这差得多的网络，以及那种既不拒绝也不回答的请求（门户认证、过滤代理——它们不会触发 error 事件）。超时就降级成静态图，那是**故意**的结果，不是故障。
- **留空 `MAPBOX_TOKEN` 则整页零外部请求**：`web/app.js` 的 `buildLocationView` 拿不到令牌就直接退回内置的示意地球 `web/globe.js`——纯本地绘制的 SVG 经纬网，不发起任何网络请求，坐标不会离开这台浏览器。要完全离线就别填这一项（结果区里的 Google Maps / OSM 是你自己点了才跳转的链接，不点就不外发）。
- **限流**：按客户端 IP 做每小时滑动窗口计数，`/api/locate`、`/api/locate/stream` 与 `/api/verify` 共用一个桶。只有来自 `TRUSTED_PROXIES` 的请求才会改用 `X-Forwarded-For` 的第一段。计数保存在进程内存中，重启即清零，多副本部署时各算各的。**这是防误用的，不是防对手的**——原因见「安全边界」。
- **不做人物识别**：提示词明确禁止识别、命名或推测画面中任何个人的身份、职业与住址。
- **结果是概率判断**：模型给出的位置、坐标与置信度都是基于画面细节的推测，可能自信地出错。请勿将其作为唯一依据用于任何有实际后果的判断。

## 许可

**这个项目本身是 MIT 的**，全文见仓库根目录的 [`LICENSE`](LICENSE)。随便用、随便改、随便再分发，附上那份许可与版权声明即可；不提供任何担保。

第三方的部分各有各的许可，说清楚免得你踩坑：

| 东西 | 许可 | 在哪儿 | 要注意的 |
| --- | --- | --- | --- |
| Mapbox GL JS 3.9.0 | **Mapbox 服务条款**（专有，**不是**开源；1.13 及更早才是 BSD-3-Clause） | 不在仓库里，浏览器从 `api.mapbox.com` 加载 | 用它需要一个状态正常的 Mapbox 账号。所以本仓库不 vendored 它——把那 1.5 MB 提交进公开仓库是在转分发 Mapbox 的 SDK。不填 `MAPBOX_TOKEN` 就完全不会碰到它 |
| Motion 11.18.2 | **MIT** | `web/vendor/motion.min.js`，许可全文在旁边的 `LICENSE-motion.txt` | MIT 允许再分发，条件是带上版权与许可声明——那份文件就是为此存在的 |
| IBM Plex Sans / Mono / Condensed 子集 | **SIL Open Font License 1.1** | `web/fonts/*.woff2`，许可全文在旁边的 `LICENSE-IBM-Plex.txt` | OFL 允许随软件打包与再分发，条件是每份拷贝都带上版权声明和许可全文；改字体的话保留原名会受 Reserved Font Name 条款约束 |
| Python 依赖（fastapi、uvicorn、anthropic、httpx、pillow、python-multipart、python-dotenv） | 各自的开源许可，不在本仓库里 | `requirements.txt`，由 pip 装进 `.venv/` | 它们是被安装的，不是被本项目分发的 |

**Anthropic API 不是这个项目的一部分。** 你用的是你自己的密钥、你自己的账号，账单与用量条款都在你和 Anthropic 之间；本项目只是把图片发过去、把 JSON 接回来。
