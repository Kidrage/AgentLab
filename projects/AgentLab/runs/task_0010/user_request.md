## 任务：UrbanSound8K 城市声音事件分类模型原型（极简验证版）

### 输出要求
一个 .zip 包含 Jupyter Notebook 文件 .ipynb 和数据集来源说明

### 任务步骤

**步骤一：数据加载**
- 使用 UrbanSound8K 数据集，仅加载 Fold1（位于 /Users/saintpeter/Downloads/UrbanSound8K/audio/fold1/）
- 数据集 metadata 在 /Users/saintpeter/Downloads/UrbanSound8K/metadata/UrbanSound8K.csv
- 音频为 .wav 文件，需统一处理采样率

**步骤二：特征提取 + 模型构建**
- 使用 librosa 将原始音频转为标准梅尔频谱图
- 基于 PyTorch 搭建极简 CNN：2层卷积 + 全连接层
- 10个类别（空调、汽车喇叭、儿童玩耍、狗叫、钻孔、引擎空转、枪声、手提钻、警笛、街头音乐）

**步骤三：Jupyter Notebook 完整工作流**
- 数据加载 → 特征提取 → 模型定义 → 训练过程 → 测试集分类准确率 + 混淆矩阵
- 代码清晰、注释到位
- 象征性迭代 3-5 轮确保代码不报错
- 使用 sklearn 一键生成混淆矩阵图表
- 不追求极致精度，仅跑通整个流程

### 约束
- 输出文件放在 /Users/saintpeter/Desktop/UrbanSound8K_Task3/ 目录
- Jupyter Notebook 命名为 urban_sound_classifier.ipynb
- 数据集来源说明命名为 dataset_readme.txt
- 最终打包为 UrbanSound8K_Task3.zip