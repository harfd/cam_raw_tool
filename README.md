# AI RAW Studio

本地优先的 Windows 摄影后期助手。NEF → 本地技术分析 → DeepSeek 视觉决策 → 受约束参数引擎 → Camera Raw XMP 预设。

仓库包含源码、测试与构建脚本。原始 NEF、个人 XMP、API Key、本地历史、模型权重、依赖环境和构建产物不随源码提交。首次使用需安装依赖并运行模型下载脚本；需要样片的集成测试请自行在项目根目录准备 `DSC_0002.NEF` 和 `DSC_0002.xmp`。分割模型的来源及许可证保留在 `backend/assets/segformer` 中。

## 0.8.0：高精度预览与 ACR 对照验证

- RAW先解码为16位线性sRGB，再明确应用sRGB传递函数，避免把LibRaw默认BT.709传递曲线误标为sRGB。参数依据：[rawpy Params](https://letmaik.github.io/rawpy/api/rawpy.Params.html)。
- 普通调色预览改为16位 sRGB 解码后缩小到最长边1600，缓存浮点数组；所有调色和效果检查使用该高精度输入，最终显示输出为带 sRGB ICC 的无损8位 PNG。避免先压成8位 JPEG再调色；不承诺额外恢复 LibRaw 已剪裁的高光。AI发送仍是缩小JPEG。
- 已有任务按需从原片副本建立缓存，不清除参数、蒙版或AI分析。旧效果检查报告会因渲染器版本变化而过期，应重新检查。
- “查看原尺寸局部”按需生成全尺寸16位 sRGB缓存，点击缩略图选位置，显示640×640原尺寸像素；处理带边界余量，局部蒙版按图像坐标采样，暗角使用全图坐标。首次使用需要解码和额外磁盘空间（5600×3728样片约120MB）；删除该照片任务时缓存一起删除。高频质感和颗粒依然可能随处理分辨率变化。
- “冻结当前方案”保存参数、蒙版版本依据、源文件/XMP校验值、本地浮点参考及验证包；包中包含原片副本、XMP、参考PNG、快照JSON与使用说明。不覆盖用户原图；所有操作本地完成，不调用AI。
- 解压验证包，在 ACR 打开副本并载入同包XMP，关闭额外自动调整、裁切、旋转及几何变形，以 sRGB 原始画幅导出 JPEG/PNG/TIFF；推荐嵌入 ICC。记录实际ACR版本和相机配置文件，再导入此快照的实际成片。
- 图像先依 ICC 转为 sRGB 的8位显示像素，再缩小到本地参考尺寸；不支持无依据地把未知色域当作sRGB。无ICC须由用户明确确认sRGB。拒绝比例不符和小于参考尺寸的成片；不自动配准，也无法证明照片内容或设置相同。
- 支持分界线对比、参考像素100%滚动查看、ΔE76色差热图、全图/暗部/中间调/亮部的平均绝对差、亮度偏差、RGB偏差、RMSE和色差分布；报告可另存JSON。数值用于发现偏差，不作审美评分、不作Adobe兼容性认证。
- 参数、AI分析或选区改变后提示快照过期；原快照仍可继续对照，重开照片恢复最近一次快照及报告。新快照不会修改旧快照；同一快照重新导入成片会更新其当前报告。
- 两套引擎的相机配置文件、基础曲线、白平衡、局部色彩算法等仍不同。本版本建立测量流程，未根据未经验证的样本自动拟合补偿曲线。
- 开发验证覆盖真实NEF解码和100%局部、精度保留、冻结快照、回环差异计算、ICC/尺寸拒绝、界面导入导出和过期提示。回环测试不是Adobe实际渲染验证；真实ACR成片必须另行导入对照。

开发时可生成中性、曝光、曲线、颜色四组对照案例（不覆盖旧结果）：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/acr-validation.py prepare --source DSC_0002.NEF --template DSC_0002.xmp --output work/acr-cases
```

输出 `cases.json` 记录快照目录。将实际ACR成片与对应快照比较：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/acr-validation.py compare --snapshot "快照目录" --image "ACR成片路径" --acr-version "实际版本" --camera-profile "实际配置文件"
```

## 0.7.0：独立胶片模拟

- 内置20款胶片、8款相纸／印片；反转片直接扫描，不应用相纸或冲印曝光。默认启用引擎自动曝光，可按需关闭。
- 胶片模拟由 spektrafilm 0.3.4 驱动，固定上游提交 `3bb2c2d2801ff68b92019cf1dbcbb133d60832bc`。内置胶片／相纸选择、胶片与冲印曝光、自动曝光、颗粒和高光晕染。首次里程碑不包含 AI 自动挑选胶片或 LUT 导出。
- NEF 重新解码为 16 位线性 ProPhoto RGB，再浮点模拟胶片、冲印、扫描，输出带 sRGB ICC 的 JPEG 或真实 16 位 RGB TIFF。缩图预览最长边 960；成片使用 NEF 全尺寸；从完整成片缩小生成对比图。预览与成片的颗粒、光晕和随机效果可能不同。
- 与 Camera Raw 调色并行保存：上方的 XMP 调色不叠加到胶片成片，也不声称 XMP 能还原该效果。使用拍摄白平衡。可单独沿用已启用选区的局部曝光（包含画笔修正和羽化）；其他局部参数不沿用。任务提交时固定参数和选区快照。
- 引擎使用独立 Python 3.13 进程，无需 API Key，全程本地。提供任务进度、取消、失败提示、重启恢复与历史结果；关闭主服务时引擎随之结束。一次只运行一个胶片任务，渲染期间保护原片不被删除。
- 源码运行先执行 `.venv\Scripts\python.exe -X utf8 scripts/prepare-film.py`，首次需要下载 Python 和依赖；哈希锁定依赖在 `requirements-film.lock`。Windows 便携版已自带运行环境，用户无需安装 Python。
- 本项目源码以 GPLv3 提供；spektrafilm 代码同为 GPLv3，胶片数据采用 CC BY-SA 4.0。保留署名、原始许可及匹配源码；见 `THIRD-PARTY-NOTICES.md`。模型权重另受原模型许可约束。

## 0.6.0：白平衡、完整色彩分级与暗角

- 白平衡提供跟随 AI、保持当前、拍摄设置、自定义四种选择。自定义色温 2000–50000 K、色调 -150–150，照片专属 XMP 使用 WhiteBalance=Custom 与 Temperature/Tint；拍摄设置使用 As Shot；保持当前省略白平衡。通用风格不固定白平衡。
- 白平衡是照片纠正，不随风格强度缩放。预览优先使用随照片导入的 XMP 中 As Shot 色温/色调作参考；旧记录也会从已存模板读取。缺少可用参考时使用明确标记的5500K/0估计值，不称作相机实测值。自定义预览只近似模拟冷暖与色偏，不复刻 Adobe 相机色彩配置。
- 色彩分级补齐阴影、中间调、高光与全局的色相、饱和度、明度共12项，以及混合和平衡。色相角、混合、平衡不随强度缩放，饱和度与明度按强度缩放。预览现在响应混合与平衡，保持中性设置不改变画面。
- 裁切后暗角提供数量、中点、圆度、羽化、高光保护与高光优先/颜色优先/绘制叠加三种样式。负数量压暗、正数量提亮边缘；只有数量按风格强度缩放。高光保护用于负暗角且不适用于绘制叠加。
- AI 分析支持 correction.white_balance、look 的明度/中间调/混合字段和 look.vignette。增量修改支持启用/恢复白平衡，以及只改色温、中间调或暗角；所有新字段参与预览、检查、保存、撤销和 XMP 导出。
- 旧分析缺少新字段时保持白平衡、分级明度0、暗角数量0；重新分析后让 AI 评估新参数。已有蒙版和照片数据不重建。
- 字段依据：Adobe Camera Raw 命名空间 https://developer.adobe.com/xmp/docs/xmp-namespaces/crs/ ，色彩分级说明 https://helpx.adobe.com/camera-raw/desktop/using/make-color-tonal-adjustments-camera.html ，暗角说明 https://helpx.adobe.com/lightroom-classic/desktop/process-and-develop-photos/retouch-photos.html ，ExifTool 的原生 CRS 字段及暗角样式枚举 https://github.com/exiftool/exiftool/blob/master/lib/Image/ExifTool/XMP.pm 。
- 不使用只适用于 RGB 图片的 IncrementalTemperature/IncrementalTint 冒充 NEF 的绝对色温；也不将光学面板 VignetteAmount 当作裁切后暗角。

## 0.5.2：应用图标重绘

- 重绘六叶实心光圈标识，去除旧 SVG 的交叉折线与多余圆环，保留深绿底和浅色主体，提升任务栏小尺寸辨识度。
- 程序 ICO、各尺寸 PNG、界面标识和浏览器图标统一从 `src-tauri/icons/source.svg` 生成；`npm run icons:generate` 可重新生成图标资源。
- 图标包含多种尺寸，构建后核对 Windows 可执行文件内嵌图标；更新桌面快捷方式到新版本路径，避免继续显示旧程序图标。

## 0.5.1：选区预览刷新修复

- 修复预览请求更新时提前释放仍在使用的图片地址，导致 AI 分析、局部选区更新后出现“选区预览加载失败”。现在图片地址在被新图替换或组件关闭后才释放，取消请求不再销毁当前画面。
- 选区预览请求支持取消，忽略过期响应；真正加载失败时显示明确原因，并提供“重试选区预览”。未加载成功时暂停画笔，避免在旧画面上误绘。
- AI 更新局部参数后，同步刷新当前选区滑块。保留原片、蒙版和已保存参数。
- 增加延迟刷新时图片地址仍可读取、替换后及时释放、损坏选区响应重试恢复的回归测试。

## 0.5.0：效果检查与有限自动修正

- 在本机对照原始显示预览和实际参数渲染结果，检测新增接近纯白、接近纯黑、高饱和像素及暗部较大提亮；全图与启用的人物选区分别检查。不将原图既有的暗调或白色区域直接当成错误。
- 指标不是传感器诊断或审美评分。亮部 RGB 最小通道 ≥0.98 且原始最小通道 <0.96；暗部最大通道 ≤0.02 且原始最大通道 >0.04；饱和度 ≥0.97 且原始 <0.90、当前最大通道 >0.25；原始线性预览亮度在 0.003–0.12 且提亮 >1.5 EV。提示阈值分别为范围内像素的 0.5%、0.5%、1%、5%。
- 修正使用有限候选搜索、重新渲染和检测，不调用 AI，不消耗 API 额度。在最长边640像素的预览搜索并复用解码图和选区，每轮接受当前最好的候选，最终在完整预览复核；完整预览未改善则全部回退。最多 4 步和 33 次评估；没有改善就停止，剩余风险明确显示。
- 限制单次累计改动：全局/局部曝光 0.3 EV，高光20、白色15、阴影20、黑色/对比度/整体饱和度12、HSL 饱和度10，RGB 总曲线纵坐标8。只降低风险相关控制，不改色相、校准、RGB 单色通道曲线或蒙版像素。
- 默认保护手动覆盖的全局参数、手动点曲线和手动局部调整；可取消保护后再明确点击“检查并自动修正”。保护的是参数数值，不意味着其他控制的修正完全不影响该区域的画面表现。
- 接受修正需风险分数下降，并且各风险指标不得明显恶化；全图容许的统计变化为0.2个百分点，人物选区为0.5个百分点。不是对所有视觉特征不变的承诺。
- 手动检查、修正前后指标、变化明细、单次整体撤销和已过期提示均已接通；参数、选区或分析改变后，旧报告不再作为当前结果。
- AI 整图分析后默认自动检查并可勾选自动修正。自然语言增量修改后只自动检查，不自动重写“背景不变”等用户要求；需要时显式执行修正。检查失败不取消已成功的 AI 方案。
- 自动修正作为单条修改记录保存，沿用最近20条与撤销机制。撤销恢复提交时参数，不恢复后来的选区画笔；修改报告随当前方案保存在本地。
- 所有检测基于近似预览，不能证明 Camera Raw 最终不溢出、不偏色，也不承诺恢复 RAW 饱和细节；不包含肤色专门识别、实际噪声测量或审美评分。

## 0.4.0：自然语言增量修改

- “用一句话修改当前效果”基于提交时实际生效的全局参数、四条曲线、已启用选区和局部参数；向 AI 发送最长边 1280 的原图、当前效果和编号选区示意。
- AI 只返回需要修改的最终绝对值，不重新生成整套决策。参数、曲线、区域 ID 及组合范围经校验后原子合并，未返回项目保持原值，不再乘风格强度。
- 支持连续修改：后续请求使用上次结果、当前手动参数以及最近五次修改摘要。局部修改沿用原选区，不重分割，不修改掩码文件。
- 修改明细显示前后数值；保留最近 20 次成功修改及提交时快照，可以逐次撤销。撤销恢复提交时全局状态和当次涉及的局部参数，不撤销画笔、羽化或边界编辑。涉及选区已删除时明确拒绝撤销。
- 成功提交的增量方案与历史保存在原有 SQLite 任务中，重开照片可恢复。失败不修改参数或成功历史；结构错误最多自动纠错一次。
- 局部调整只允许当前照片专属模式下启用的选区。要提亮没有识别到的主体，应先框选/手绘并启用；不通过全局曝光冒充局部提亮。
- 提交前先应用曲线草稿和局部滑块，未应用的草稿不属于当前效果。处理期间暂停相关编辑，防止返回结果覆盖并行操作。
- 增量方案是当前强度下的最终值；这些修改与手动覆盖一样，不随强度再次缩放。切换风格、AI 全局计划或导出模式会清除当前全局覆盖；重新完整分析成功后会清除增量历史并生成新方案。
- 这是参数级增量编辑，不支持移动/生成选区、替换天空、裁切或添加未开放的参数。选区与近似预览的原有限制仍适用。

## 0.3.0：HSL、校准和曲线面板

- 按 Camera Raw 分组增加基本、颜色混合器（HSL）、曲线、校准、色彩分级和颗粒面板。HSL 八色的色相、饱和度、明亮度共 24 项均可用滑块及数值输入编辑。
- 校准包括阴影色调和红、绿、蓝三原色色相/饱和度共 7 项（-100 到 100）。这是 Adobe 校准字段，并非 HSL 的别名；处理版本沿用模板，未提供相机配置文件选择。
- 曲线包括 RGB、红、绿、蓝四条点曲线（2–12 点，0–255，保持单调），支持拖动、数值输入、添加/删除点、直线和恢复方案。编辑后点击“应用曲线”。参数曲线包括高光、亮调、暗调、阴影及三个分界点。
- AI 计划可返回 calibration、red_curve、green_curve、blue_curve、parametric，经校验后参与预览和 XMP；旧记录缺失字段使用中性值，重新分析后才会评估新增参数。
- AI 和模板的风格参数随强度缩放；手动参数和点曲线优先，不随强度再次缩放。校准的色相是有符号偏移，随强度缩放；色彩分级的色相角与曲线分界点不缩放。
- XMP 使用 Adobe 原生 ShadowTint、RedHue/RedSaturation 等校准字段，Parametric* 参数曲线字段，以及 ToneCurvePV2012 / Red / Green / Blue 四个点序列。映射参考 Adobe 官方示例：https://github.com/AdobeDocs/cis-photoshop-api-docs/blob/main/sample-code/lr-sample-app/crs.xml 。
- 预览近似模拟新增参数；校准依赖 Adobe 的相机配置文件，参数曲线与点曲线插值也可能和 Adobe 不同。导出为标准参数，不声称本地渲染与 Camera Raw 像素一致。
- 0.3.0 当时未加入光学、几何、降噪、相机配置文件等完整面板；色彩分级中间调和明度已在0.6.0补齐。

## 0.2.1：AI 返回校验修复

真实 DeepSeek 响应中的局部 `whites` 在 0.2 中被误判为未知字段。现已补齐局部白色、黑色色阶与纹理的校验、界面、预览和 XMP 映射。增加完整 JSON 格式示例；结构校验失败或输出截断时最多自动纠错一次。API Key、余额、连接错误不会自动重试，所有参数仍需通过范围、曲线和区域 ID 校验。

具体字段错误保存在当前任务目录的 `ai-validation.json`，只记录字段路径、错误类型与校验结果，不记录 Key、图片或完整请求。第二次仍失败时界面会指出具体字段，保留本地结果和上一次成功分析。成功后可直接生成预览和 XMP。

## 0.2：AI 参数计划与本地局部处理

- AI 分析增加 `editing_plan`：基础曝光与高光/阴影纠正、八色 HSL、曲线、色彩分级、质感和逐区域调整目标。界面可以查看每个参数的最终值、来源和依据。
- 本地 ONNX SegFormer 识别人像、天空、植被、水面和地面。人物进一步在裁切区域重新识别，再用 GrabCut 对齐边界；支持其他主体的框选、手绘添加、擦除、边缘细化和单步撤销。
- 每个选区独立设置曝光、高光、阴影、白色色阶、黑色色阶、对比度、冷暖、色调、饱和度、蓝色曲线、清晰度、纹理和去雾。修改滑块后点击“应用局部调整”。
- 蓝色曲线改变的是已选区域的蓝通道，不会自动替换天空；白云、白色画板等应检查选区和染色强度。各选区可能重叠，重叠部分会叠加处理。
- 点击“识别本地选区”可离线使用；AI 分析会自动识别选区并发送区域 ID、面积、边界框及预览亮度摘要。真实 AI 请求仍需用户在设置中提供 Key。
- 照片专属 XMP 使用 `MaskGroupBasedCorrections → CorrectionMasks → Mask/Aggregate → Masks → Mask/Paint` 写入固定选区。结构依据本机 ACR 17.3 实际保存的普通笔刷；局部曝光按 EV/4，其他滑块通常按百分值/100 编码。
- 通用风格 XMP 不包含固定坐标选区，以免应用到其他照片时发生位置错配。开启/关闭局部调整影响预览与导出。
- 局部分割不是逐像素真值；画笔导出以圆形笔触重建预览选区，边缘与羽化存在近似。手指、发丝、透明物体和相邻支架尤其需要检查和修正。本版不声称精确复现 Adobe 的局部色彩算法。
- 基础曝光不再从偏暗的 LibRaw 预览机械增加到 +0.8 EV；使用显示亮度参考预览，并保守限制自动提亮。旧版历史请重新 AI 分析，获得新版计划与选区。
- 分割权重采用 NVIDIA SegFormer 自身许可证，仅限研究和评估；见便携版的 `MODEL-LICENSE.txt`。源码与模型权重分开保留相应许可，商业发布前需替换或另外取得模型授权。

## 直接使用

便携版位于 `E:\Prj\camera_raw_tool\release\AI RAW Studio 0.8.0`，运行里面的 `AI RAW Studio.exe`。也可解压 `release\AI-RAW-Studio-0.8.0-win-x64.zip` 后运行。必须保留同目录的 `server` 文件夹。无需 Python 或 Node；Windows 需要 WebView2。

1. 在「模型与 API 设置」填写 DeepSeek API Key。默认地址 `https://api.deepseek.com`，模型 `deepseek-flash`（DeepSeek V4.1 Flash 官方接口名）。
2. 导入 NEF；可同时选择 XMP。支持拖入文件。本版针对提供的 Nikon Z 30 样片验证。
3. 本地解码结束后可查看直方图、传感器近饱和采样和预览暗部占比。
4. 点击「AI 分析」，获取主题、主体、构图、光影、情绪、建议风格和理由。可以输入风格意向并重新分析。
5. 选择自然通透、电影感或复古胶片，调整强度和滑块，拖动对比分界线。
6. 选择照片专属或通用风格，导出 `.xmp`，在 Camera Raw 预设面板导入。

不配置 Key 时可使用本地分析、三种风格和导出；界面明确标注尚未使用 AI。

## MVP 范围与边界

- RAW：rawpy/LibRaw，用相机白平衡解码为16位 sRGB，保留浮点预览缓存并生成用于分析的显示亮度参考图（不等同于 ACR 校准渲染）；保留源文件，内部仅处理副本。
- 技术指标：传感器黑白电平归一化、各通道近饱和比例、RGB 直方图、线性化预览亮度分布、饱和度和边缘重心。预览暗部占比不是传感器动态范围；边缘重心不是主体检测或构图评分。
- AI：原生图像输入，结构化 JSON 经 Pydantic 验证，异常或额度不足会显示明确错误，不伪造 AI 分析结果。模型输出经过范围校验的明暗、颜色、曲线和局部目标；独立引擎映射并生成 XMP。
- 参数：照片基础纠正和风格层分离；限制高光、曝光、高 ISO 提亮和肤色色相。第一版使用规则与模板，没有训练模型或复杂优化求解。
- 预设：模板版本取自提供的 XMP，ACR 17.3 / ProcessVersion 15.4。源 XMP 是 sidecar；导出增加 PresetType、UUID、名称与分组，独立生成预设，移除相机序列号、历史、原照片 ID 和镜头配置文件绑定。
- 照片专属模式：含当前照片曝光、高光、阴影、白色色阶纠正和风格。仍为可导入的预设文件，不覆盖同名 sidecar。
- 通用风格模式：省略照片专属曝光、高光、阴影、白色色阶和白平衡；保留风格对比度、黑色色阶、色彩等。
- 强度仅缩放风格层；照片基础纠正不随风格强度消失。重新选风格、切换导出模式或切换 AI 全局计划会清除全局手动微调；改变强度保留手动值。
- 白平衡可保持当前、拍摄设置或自定义；缺少准确参考时明确标记预览估计值，不声称由 RGB 精确反推色温。裁切仅提供建议。
- 预览近似模拟基础明暗、HSL、校准、四条点曲线、参数曲线、分离色调、质感和颗粒。LibRaw 与 Adobe 的相机配置文件和色调映射不同，预览不保证与 ACR 一致。
- 批处理、审美学习和相机配置文件编辑不在本版范围。

## 隐私与数据

原始 NEF 不上传。点击 AI 分析时，将最长边 1280 像素的 JPEG、技术指标和用户输入的风格意向发送到已配置的服务。发送前不保留 JPEG EXIF，不发送文件路径、设备序列号或源 XMP。

API Key 默认仅在后端内存保留，可选写入 Windows 凭据管理器。也支持 `DEEPSEEK_API_KEY` 环境变量；环境变量优先于凭据管理器，使用环境变量时需在程序外取消它才能清除。普通配置文件不存储 Key。界面查询只返回 `has_key`。

程序监听 `127.0.0.1` 随机端口，使用随机会话令牌；关闭桌面程序时终止子服务。数据位于 `%LOCALAPPDATA%\AI RAW Studio`，包括 NEF 副本、预览、SQLite 分析历史与不含 Key 的配置。侧边栏显示最近 30 条记录，可逐项删除副本；源文件不受影响。

## 开发

需要 Windows、Python 3.11、Node.js、Visual Studio C++ 工具和 Rust。当前电脑已在项目 `.tools` 内准备独立 Rust，不修改系统 PATH。

```powershell
cd E:\Prj\camera_raw_tool
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/desktop.ps1 -Mode dev
```

浏览器开发预览：`npm run dev`，访问 `http://127.0.0.1:5173`。浏览器预览和桌面窗口使用同一 UI 和后端模块；开发服务器限定本机。

重新构建便携版：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/desktop.ps1 -Mode build
```

便携版打包 PyInstaller 服务，Tauri 负责启动、随机端口发现、文件保存和退出回收。可选 `npm run desktop:installer` 构建 NSIS 安装包，需要网络下载安装器组件；本次该下载超时，交付便携版。

依赖：`package-lock.json`、`requirements.lock.txt` 和 `src-tauri/Cargo.lock` 记录本次版本。复现 Python 环境可安装 `requirements.lock.txt`。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -q --basetemp work/test-temp
npx playwright install chromium
npm run test:ui
.\.venv\Scripts\python.exe scripts/smoke-packaged.py
```

测试使用项目根目录 `DSC_0002.NEF` 和 `DSC_0002.xmp`。前两类测试数据分别放在 `work/test-data` 和 `work/ui-test-data`，打包服务检查放在 `work/packaged-test`，不会写入正常工作区。

已检查：真实 NEF 解码，三种风格 × 两种模式的预览与 XML 导出，源文件哈希保持不变，参数范围、敏感字段移除、缺少 Key、AI 请求格式与错误处理，界面导入与导出。早期接口测试使用模拟响应；0.3.0 新增字段与 0.4.0 连续两轮增量编辑另用真实接口验证。初版笔刷未被 ACR 识别；按照 ACR 实际保存的组合蒙版层级修正后，用户已确认蒙版能够显示。用户随后指出边界误选，已增加人物局部重识别和边界细化；v3 经用户在 ACR 中确认明显改善，剩余细节可手动修正。边缘、羽化与调色仍应按照片检查。

## 结构

```text
frontend/              React + TypeScript UI
backend/raw_decoder.py RAW 解码与技术指标
backend/ai_engine.py   DeepSeek 图像分析与结果校验
backend/parameter_engine.py 风格模板与参数约束
backend/preview.py     全局与局部近似预览
backend/segmentation.py 本地语义分割、选区修正
backend/mask_export.py  固定选区转 ACR 组合笔刷
backend/xmp.py         预设生成与模板信息提取
backend/main.py        FastAPI 与异步任务
backend/settings.py    会话 Key 与 Windows 凭据管理器
backend/store.py       SQLite 历史
src-tauri/             Windows 桌面壳
scripts/               启动、打包、验证
tests/                 核心与界面测试
release/               便携版交付
```

## 接口依据

- DeepSeek Vision：https://api-docs.deepseek.com/guides/vision/
- DeepSeek JSON Output：https://api-docs.deepseek.com/guides/json_mode/
- Adobe 预设结构示例：https://github.com/AdobeDocs/cis-photoshop-api-docs/blob/main/sample-code/lr-sample-app/crs.xml
- rawpy：https://letmaik.github.io/rawpy/api/rawpy.RawPy.html
- Tauri Windows 环境：https://v2.tauri.app/start/prerequisites/
