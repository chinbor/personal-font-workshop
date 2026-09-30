# 构建与坐标

## 环境与运行

先发现本机的 Python 和 FontForge，不复制作者的磁盘路径。计划工具只需 Python 3.8+；构建工具必须在带 Python 支持的 FontForge 中运行。普通 Python 的 `import fontforge` 失败，不等于只需安装同名 pip 包。

以下从技能目录运行，项目目录使用新的路径：

```sh
python scripts/project.py init /path/to/my-font --family "My Personal Font" --postscript MyPersonalFont-Regular --nbsp
python scripts/project.py check /path/to/my-font/project.json
fontforge -lang=py -script scripts/build_font.py /path/to/my-font/project.json /path/to/my-font/build-v01
```

Windows PowerShell 给含空格的路径加引号，用 `& "FontForge实际路径" -lang=py -script ...`。工具缺失时保留 SVG 和计划，明确尚未生成 TTF；不要静默改用收费服务。

`init` 只建计划，不画字。初始 `target_bounds: null` 故意不能通过构建检查；这是“待设计”，不是需要随意补数的程序错误。

小样可以加 `--characters "HOnog01l,{}"`。默认完整可打印 ASCII；`--nbsp` 额外添加 U+00A0。默认等宽、advance=600、em=1000 只是试验起点。用 `--spacing proportional` 创建比例字体计划，再逐字调整 advance；不能一边要求比例字体一边强迫所有字等宽。

## project.json：构建契约

- `family`：用户看到的字体家族名；`postscript_name`：安全 ASCII 名，例如 `MyPersonalFont-Regular`。
- `version`：例如 `0.100`；本工具输出单个静态 Regular 款，其他字重、斜体、连字和变量字体需要额外实现。
- `em = ascent + descent`：字面坐标单位。`line_ascent/line_descent/line_gap`：行框指标，descent 在计划里为正数。不要为“看起来居中”移动所有基线。
- `spacing`、`default_advance`、各字 `advance`：前进宽度，不是轮廓宽度。
- `required_codepoints`：本轮承诺的字符范围；缺字时修文件，不要偷偷删减此列表。
- `glyphs`：每个字符的 codepoint、character、相对 SVG 路径、target_bounds 和 advance。SPACE/NBSP 无轮廓，file/bounds 都是 null。

一个已完成的条目示例：

```json
{
  "codepoint": 72,
  "character": "H",
  "file": "glyphs/U0048.svg",
  "target_bounds": [50, 0, 550, 700],
  "advance": 600
}
```

`target_bounds` 是**字形实际轮廓在最终字体坐标中的外接矩形** `[xmin,ymin,xmax,ymax]`：向右 x 增大，向上 y 增大，基线 y=0。这不是每个字都塞进去的统一格子；H、n 和逗号本来就应有不同高度。

## 坐标来源：不可猜的部分

源 SVG 若使用共同坐标系，向下为正，基线为 `B`，全套缩放为 `s`，则源路径边界 `[x0,y0,x1,y1]` 对应：

```text
target_bounds = [s*x0, s*(B-y1), s*x1, s*(B-y0)]
```

边界是路径实际边界，不是 SVG viewBox。源路径有变换时先展平并计算最终边界。

如果每张 SVG 都被单独裁紧，只剩宽高：先找原稿的公共基线、原始比例或可靠的逐字定位表。找不到时制作明确标记的定位试样，交用户判断；不能声称自动恢复了原始布局。特别不要按“全部缩放到 700 高”处理逗号、小写 n、连字符。

构建器读取 FontForge 导入后的实际边界，按每个字**已设计的** target_bounds 做等比还原和平移；若纵横比例差超过 0.5% 就拒绝拉伸。导入器可能改变原始画布原点，所以最后还要重开 TTF 检查边界和预览方向。它不会识别“这个字应该长什么样”。

## SVG 子集与文件名

工具接受简化的黑色填充、闭合 path，可包含无变换的 g、title、desc。将 styles、transforms、描边、文字、基本形状等展平成黑色路径；每个子路径明确 Z 闭合。拒绝 image、text、use、外链、DTD、滤镜和嵌入脚本。此预检不是完整 SVG 解析器或几何自交检查，后续 FontForge 校验与目视检查仍必需。

编码文件名避免 Windows 上 `A.svg` 与 `a.svg` 的大小写冲突，也避免 `? * / \\ : " < > |`。用户若想便于查找，可提供 character → filename 对照表，不必把真实字符当文件名。

## 输出与失败

新输出目录内有 `.sfd`、`.ttf`、`build-report.json`。源 SVG 不改动。构建器校验重新打开的 TTF 的覆盖、宽度、空格、边界、轮廓状态与名称；报告为 `structural-pass` 才代表这部分通过。

遇到错误，保存日志和中间文件用于诊断；不要把失败的 TTF 当成通过。输出已存在就换版本目录，不覆盖。`autohint` 默认 false，只有实际对照说明有帮助时才开启。工具不自动安装到系统。

手动路径：FontForge 新建字体 → 打开对应字符格 → File / Import 导入单字 SVG → 调整度量 → 保存 SFD → File / Generate Fonts 输出 TTF。界面名称随语言版本不同；手动流程同样遵守字符映射和验收要求。
