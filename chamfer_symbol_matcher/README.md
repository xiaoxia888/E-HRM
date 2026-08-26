# OpenCV 符号顺序匹配工具

这个独立工具按照目标图中符号从左到右的顺序，在背景图中寻找对应的黑色线稿符号，并输出带编号圆圈的图片及 JSON 匹配数据。

核心流程：

1. Otsu 二值化与垂直投影，自动切分目标图中的符号；
2. Canny、black-hat 和暗线掩膜提取背景候选边缘；
3. 对每个模板执行多尺度、多角度、可选长宽比变换；
4. 使用截断距离变换计算单向 Chamfer Distance；
5. 结合模板笔画区域的暗度得分抑制照片纹理误匹配；
6. 每个符号独立搜索，因此不同符号可以在背景中重叠。

## 安装

建议使用独立虚拟环境：

```bash
cd chamfer_symbol_matcher
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 运行当前样例

```bash
.venv/bin/python chamfer_matcher.py \
  --target /Users/guoxi/Desktop/target.png \
  --background /Users/guoxi/Desktop/background.png \
  --output example_output.png \
  --debug-dir debug
```

参数 `--scales`、`--angles` 支持 `开始:结束:步长`，也支持逗号分隔的离散值。负数角度范围应使用等号形式：

```bash
python chamfer_matcher.py \
  --target target.png \
  --background background.png \
  --output result.png \
  --scales 0.8:2.6:0.1 \
  --angles=-35:35:3 \
  --aspect-ratios 0.7,0.85,1.0,1.15,1.3
```

输出包括：

- `result.png`：按目标顺序绘制红圈和编号；
- `result.json`：坐标、得分、尺度、角度和长宽比；
- `debug/`：目标模板、候选边缘、距离变换和暗线概率图。

Chamfer 得分越低越好，但它不是经过校准的概率。背景差异较大时，优先调整：

- `--scales`：目标符号在背景中的尺寸范围；
- `--angles`：旋转角度范围；
- `--aspect-ratios`：非等比拉伸范围；
- `--dark-threshold`：绝对暗线阈值；
- `--blackhat-size`：局部暗线提取的结构元素大小。

## 测试

```bash
python -m unittest -v test_chamfer_matcher.py
```
