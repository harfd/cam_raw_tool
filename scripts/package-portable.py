import shutil
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / 'release' / 'AI RAW Studio 0.5.0'
target.mkdir(parents=True, exist_ok=True)
shutil.copy2(root / 'src-tauri/target/release/ai-raw-studio.exe', target / 'AI RAW Studio.exe')
shutil.copytree(root / 'dist/raw-studio-server', target / 'server', dirs_exist_ok=True)
(target / '使用说明.txt').write_text('''AI RAW Studio 0.5.0 — Windows x64 便携版

完整解压后运行 AI RAW Studio.exe，请保留旁边的 server 文件夹。
无需安装 Python、Node.js 或 Rust。需要 Windows WebView2 运行时。

1. 选择“模型与 API 设置”，填写自己的 DeepSeek API Key。
   服务地址：https://api.deepseek.com；模型名：deepseek-flash。
2. 导入 NEF 照片，可同时选择 Camera Raw XMP 模板。
3. 点击 AI 分析，按需输入风格意向。
4. 在“局部选区与调整”中查看选区，用添加、擦除或框选修正边缘。
   可以点击“细化边缘”，逐区调整曝光、冷暖、饱和度和蓝色曲线，点击“应用局部调整”。
5. 在右侧 Camera Raw 参数面板调整 HSL、曲线、校准等参数。点曲线修改后点击“应用曲线”。
   HSL 提供八色的色相、饱和度、明亮度；校准提供阴影色调与 RGB 三原色。
   曲线提供 RGB、红、绿、蓝通道点曲线，以及参数曲线四区域和三分界。
   手动参数不随风格强度缩放；“恢复方案值”返回当前 AI 或模板参数。
   旧版历史请重新分析，让 AI 评估新增的校准、通道曲线和参数曲线。
6. 在“用一句话修改当前效果”输入如“只提亮人物，背景不变”，点击“修改当前效果”。
   先应用局部滑块和曲线草稿。AI 会发送缩小原图、当前效果图、编号选区示意和当前参数。
   修改明细显示前后值，可“撤销上次 AI 修改”；可连续修改，成功结果与最近 20 次历史保存在本机。
   撤销恢复上次提交时参数，不撤销后来的蒙版画笔；重新完整分析成功后清除增量历史。
7. 在“效果检查与自动修正”中检查当前效果。默认保护手动参数，可取消后点击“检查并自动修正”。
   本地检测调色后新增的近白、近黑、高饱和与较大提亮风险；修正最多4步，可查看前后指标并撤销。
   整图 AI 分析可勾选自动修正；自然语言修改后只检查，不自动改写指令。
   参数或选区变化后，旧报告会标记过期。检查不消耗 API 额度，不代表 Camera Raw 最终效果。
8. 选择风格和强度，导出 XMP；照片专属模式包含固定选区，通用风格不包含固定选区。
9. 在 Camera Raw 的预设面板中选择“导入预设”。

不填 Key 也可以使用本地分析、风格模板和 XMP 导出。
AI 分析会发送缩小的 JPEG 预览和技术指标，NEF 原片留在本机。
Key 默认只保存在后端内存中，可选 Windows 凭据管理器保存。
预览是近似模拟，最终效果以 Camera Raw 为准。
本地选区及 XMP 笔刷边缘有近似，请检查自动分割并按需用画笔修正。
旧版历史需要重新 AI 分析，才能得到完整参数计划与局部调整。

本测试版附带 NVIDIA SegFormer 模型，遵循模型自身许可证，限研究和评估。
完整模型许可证见 MODEL-LICENSE.txt；软件实现与模型权重分别保留各自权利。

本地缓存：%LOCALAPPDATA%\\AI RAW Studio
可以在工作区逐项删除照片副本和历史。
''', encoding='utf-8-sig')
shutil.copy2(root/'backend/assets/segformer/LICENSE.txt',target/'MODEL-LICENSE.txt')
shutil.copy2(root/'backend/assets/segformer/SOURCE.txt',target/'MODEL-SOURCE.txt')
archive = root / 'release/AI-RAW-Studio-0.5.0-win-x64.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=5) as bundle:
    for file in sorted(target.rglob('*')):
        if file.is_file():
            bundle.write(file, file.relative_to(target.parent))
print(f'Portable package: {archive} ({archive.stat().st_size / 1024**2:.1f} MB)')
