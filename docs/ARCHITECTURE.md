# 实现说明

`resources.py` 只做字节到字节的语言文本转换。词典需为 UTF-8 的 `"$$$/key=value"` 行；不识别的格式停止处理。目标资源键集合是主结构，来源资源只提供匹配值，基础占位符计数不同则保留原文。JSON 递归合并，仅替换字符串，保留目标的非字符串数据。

`adapters.py` 检测已知 EXE、Dictionaries、可选 UXP 目录。Premiere 使用文件版本主版本定位用户配置；读取但不写 `AMT/application.xml` 的安装语言信息。生成纯预览计划：修改前后哈希、转换统计、注册表目标与只读保护文件。检测不等于实机启动验证。

`transaction.py` 在 `%LOCALAPPDATA%\AdobeLanguageSwitcher` 记录事务。先检查目标进程已退出、资源未变化、无未恢复事务，再备份全部目标，逐个原子替换并回读。发生异常时按备份尝试恢复。恢复前会检查所有目标，拒绝覆盖未知的新内容；只改了其他首选项时，仅恢复语言列，保留其他首选项变化。

这不是跨文件/注册表的操作系统原子事务。断电或进程中止后可能留下 `applying` 或 `recovery_required`，应关闭 Adobe 应用并按事务 ID 恢复。不自动强制关闭应用，不在启动失败后持续尝试其他语言。

`windows.py` 封装只读安装发现、版本读取、进程检查、HKCU 语言值和显式 UAC 提权。图形界面通过子进程及本地回执执行操作；提权前后 Windows SID 必须一致。支持源码 ZIP 和 pip 安装，不要求运行目录内存在 `switcher.py`。

映射成功表示文件变更及回读检查成功。是否能启动、界面翻译完整性、导出与渲染是否正常，仍需要对应产品的真实运行测试。

## 写入范围

- Premiere：当前用户 `%APPDATA%\Adobe\Premiere Pro\<major>.0\Debug Database.txt` 的语言字段，以及 `HKCU\Software\Adobe\Premiere Pro\<major>.0\Language`。
- 映射资源：安装目录中匹配语言的 `Dictionaries/<locale>/*.dat`、`*.dict`。
- UXP：`com.adobe.ccx.start/{locale,cmdn-locale}/<locale>/strings.json`、`com.adobe.unifiedpanel/locale/<locale>/strings.json`。
- 本工具自身的事务文件与回执。

程序、DLL、安装/激活元数据和源语言资源是只读对象，不分发任何产品资源。
