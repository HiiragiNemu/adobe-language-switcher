# Adobe Language Switcher

[![Tests](https://github.com/HiiragiNemu/adobe-language-switcher/actions/workflows/tests.yml/badge.svg)](https://github.com/HiiragiNemu/adobe-language-switcher/actions/workflows/tests.yml)

**Windows 上可预览、备份和恢复的 Adobe 界面语言切换工具。**

面向已安装的官方版本与第三方打包版本，按实际文件结构检测兼容性，而不是根据安装来源决定是否放行。支持中文图形界面和命令行，运行时只用 Python 标准库。

> **v0.1.0 是首版，不是全 Adobe 系列的通用汉化补丁。** Premiere 26.5.2.5 的兼容映射方法已获得实机中文主菜单确认；通用程序的应用、失败恢复、回滚已通过自动化测试。其他产品的实机验证范围见下表。仓库不包含 Adobe 程序、词典、语言包或用户备份。

## 两种模式

| 模式 | 做什么 | 适用情况 |
|---|---|---|
| 常规设置 `native` | 修改 Premiere 用户偏好 `ApplicationLanguage` 和当前用户注册表的 `Language` | 本机已包含目标语言，且该语言能正常启动 |
| 兼容映射 `mapped` | 按相同字符串键，把本机目标语言文字填入一个已验证可启动的非英文语言资源；Premiere 内部语言保持承载语言 | 单独安装包、第三方打包版等，直接改目标语言不能正常工作但资源齐全 |

例如：`zh_CN → fr_FR` 表示**界面显示中文，内部语言标识仍为法语**。不会更换软件版本；部分首页、插件、快捷键或日期格式可能保留原语言。映射模式仅处理匹配的文本词典和三个已知 UXP 字符串目录，不改可执行文件、DLL、`AMT/application.xml`、订阅或激活组件，也不下载语言包。

这不是 Adobe 官方功能或授权切换工具。Adobe 官方的安装语言流程仍是 [Creative Cloud 设置安装语言，随后重装现有应用](https://helpx.adobe.com/ae_en/creative-cloud/apps/manage-apps/creative-cloud-apps/change-language-for-creative-cloud-apps.html)。本项目提供保留当前安装的本地方案，不承诺处理订阅语言不匹配等启动问题。

## 兼容范围

| 产品 | 常规设置 | 兼容映射 | 实际验证 |
|---|---|---|---|
| Premiere Pro | 已实现 | 已实现 | 26.5.2.5：方法实机确认中文主菜单；部分首页仍为法文 |
| After Effects | 未实现 | 实验性 | 合成目录测试，未做实机启动验收 |
| Media Encoder | 未实现 | 实验性 | 合成目录测试，未做实机启动验收 |
| Audition | 未实现 | 实验性 | 合成目录测试，未做实机启动验收 |
| Photoshop / Illustrator / 其他 | 未实现 | 未实现 | 没有对应适配器 |

- 官方与第三方安装均支持自动发现或手动选目录；**不是所有安装包都包含可复用的语言资源**。
- Premiere 首次运行后需存在对应主版本的 `Debug Database.txt`。语言列表从 `Dictionaries` 实际目录读取。
- 非 Premiere 的实验适配器仅映射安装元数据中唯一的安装语言，不猜测产品的活动语言、不写其注册表。
- `en_US` 不作为映射承载语言，因为应用可能优先使用内置英文而忽略外部词典。
- 目前检测产品根目录或 `Support Files` 中的已知 EXE；便携启动器或完全不同的目录结构不作自动推断。

## 快速开始：双击启动

1. 安装 **Python 3.10+（含 Tkinter）**。本版提供源码启动器，尚无独立 EXE。
2. 点击 GitHub **Code → Download ZIP** 并解压整个目录。
3. 保存并关闭要切换的 Adobe 应用，双击 **`Start.cmd`**。
4. 自动检测或选择安装目录，选择目标语言与模式。
5. 先“预览变更”，再“一键切换”。兼容映射需勾选确认：你已经验证承载语言能正常启动。
6. 如出现 Windows 管理员提示，由你确认；切换后“启动应用检查”。显示“文件操作完成”不等同于应用启动成功。

### 恢复

保存并退出对应应用，在记录下拉框选择事务，点击“一键恢复”。每次切换前备份原文件，写入后回读校验；中途失败尝试恢复，若仍有异常会保留 `recovery_required` 记录。

备份仅存于本机 `%LOCALAPPDATA%\AdobeLanguageSwitcher`。**不要删除此目录，也不要把它或 Adobe 资源上传到 GitHub。** 更换管理员账户会被拒绝，应使用原 Windows 用户的提权确认。

切换不同语言前先恢复上一次事务。更新或重装 Adobe 后，如资源校验发生变化，工具会停止恢复，以免旧备份覆盖新版本。已有手工汉化不自动接管：本工具只恢复它自己创建事务时的基线。

## 命令行

在解压后的目录运行（替换为自己的安装路径）：

```powershell
python switcher.py discover
python switcher.py inspect "C:\Program Files\Adobe\Premiere Pro 2026"

# 只预览；不修改 Adobe 文件或注册表
python switcher.py plan "C:\Program Files\Adobe\Premiere Pro 2026" --target zh_CN

# 常规偏好切换；应用必须已退出
python switcher.py apply "C:\Program Files\Adobe\Premiere Pro 2026" --target zh_CN --yes

# 本机资源映射：承载语言需事先实测可启动
python switcher.py plan "C:\Program Files\Adobe\Premiere Pro 2026" --mode mapped --target zh_CN --carrier fr_FR --carrier-confirmed
python switcher.py apply "C:\Program Files\Adobe\Premiere Pro 2026" --mode mapped --target zh_CN --carrier fr_FR --carrier-confirmed --yes

python switcher.py history
python switcher.py restore TRANSACTION_ID --yes
```

命令行不自动提权；写安装目录时可由用户以管理员身份运行。也可 `python -m pip install .` 后使用 `adobe-language-switcher gui` 或 `python -m adobe_language_switcher gui`。

## 技术与验证

- 文本词典：保留键、顺序、UTF-8 BOM 和换行；保留缺失键与占位符不匹配的原值。
- JSON：保留对象结构、键与非字符串值，重新排版；使用原 BOM 与 LF/CRLF 风格。
- 首选项：只改 `ApplicationLanguage` 的当前值列，保留默认值列及其他选项；支持 LF、CRLF、CR 与历史 CRCRLF。
- 事务：备份、SHA-256、原子替换、应用进程检测、操作锁、失败恢复和更新冲突检测。
- 无网络调用、无遥测、无强制结束应用；CLI 输出及事务日志含本机路径，分享前请自行脱敏。

```powershell
python -m unittest discover -v
python tools/demo_roundtrip.py
```

第二个命令只在临时目录创建自制测试资源和模拟注册表，执行“英文基线 → 中文映射 → 恢复”，不启动或改写真实 Adobe 应用。

详见 [验证范围](docs/VALIDATION.md)、[实现说明](docs/ARCHITECTURE.md) 和 [贡献指南](CONTRIBUTING.md)。

## English summary

A Windows, Chinese-first GUI/CLI for reversible local Adobe UI localization. Supports Premiere preference switching and dictionary/UXP string mapping into a known-working non-English carrier locale. Both official and third-party-packaged installations are inspected by their actual resource layout. AE, AME and Audition adapters are experimental; Photoshop and Illustrator are not implemented. Runtime confirmation exists for the mapping method on one Premiere 26.5.2.5 installation, not every Adobe build. Requires local target-language resources and Python 3.10+ with Tkinter. No Adobe assets, licensing modifications or network downloads are included. MIT-licensed independent project, not affiliated with Adobe.
