# 智能材料加工分选机

## 项目简介

本项目是一个基于 K1 MUSE Pi Pro / Bianbu 系统开发的多层视觉智能分选系统。系统通过 USB 摄像头采集画面，使用 YOLO ONNX 模型识别红、黄、蓝、绿等不同颜色物料，并通过 Linux PWM 控制 MG90 舵机完成分选动作。

项目采用模块化结构，将摄像头扫描、模型推理、分拣层控制、PWM 舵机控制、日志记录和 Web 控制台拆分为多个模块，方便比赛展示、现场调试和后续扩展。

## 主要功能

- 支持多层分选结构，默认包含四个分拣层。
- 支持红、黄、蓝、绿四种目标颜色识别。
- 支持每层独立绑定摄像头和 PWM 通道。
- 支持摄像头自动扫描和 PWM 通道自动扫描。
- 支持 YOLO ONNX Runtime 推理。
- 支持 SpaceMITExecutionProvider 硬件加速。
- 支持 Web 控制台实时查看状态、日志和视频画面。
- 支持单层启动、暂停、继续、停止和清零。
- 支持全部启动、全部暂停、全部停止和全部清零。
- 支持手动目标位、手动 OTHER 位和舵机复位。
- 支持运行中手动控制舵机。
- 支持 SQLite 保存系统运行日志。

## 项目结构

```text
智能材料加工分选机/
├── app.py                      # FastAPI 后端入口
├── config.yaml                 # 系统配置文件
├── requirements.txt            # Python Web 端依赖
├── run.sh                      # 一键启动脚本
├── README.md                   # 项目说明文档
├── sorter/                     # 后端核心模块
│   ├── config.py               # 配置默认值、读取、校验和保存
│   ├── devices.py              # 摄像头和 PWM 设备扫描
│   ├── layer.py                # 单层分选控制逻辑
│   ├── logstore.py             # SQLite 日志存储
│   ├── system.py               # 多层系统总管理器
│   └── vision.py               # 摄像头采集、YOLO 推理、目标绘制
├── web/                        # Web 控制台页面
│   ├── console.html            # 主控制台页面
│   └── console.html.bak_*      # 备份文件，上传 GitHub 时可忽略
├── models/                     # 模型目录，按实际情况放置
├── data/                       # 运行时数据目录，日志数据库会自动生成
└── deploy/                     # 部署文件，可选
```

> 注意：当前 `web/` 目录中主要页面是 `console.html`，建议运行后优先访问 `/console`。如果要访问根路径 `/`，需要保证 `web/index.html` 存在，或者在 `app.py` 中把根路径改为返回 `console.html`。

## 核心模块说明

### app.py

`app.py` 是后端服务入口，基于 FastAPI 实现，主要负责：

- 初始化 `SorterSystem`
- 挂载 Web 静态文件
- 提供 Web 页面访问
- 提供系统状态接口
- 提供设备扫描接口
- 提供分拣层配置接口
- 提供单层启动、暂停、继续、停止接口
- 提供全部启动、暂停、停止接口
- 提供日志读取接口
- 提供每层视频流接口
- 提供 WebSocket 状态推送
- 提供运行中手动 PWM 舵机控制补丁

主要访问地址：

```text
http://开发板IP:8000/console
```

### config.yaml

`config.yaml` 是系统运行配置文件，保存模型路径、摄像头参数、推理参数、每层目标颜色、摄像头绑定、PWM 绑定和舵机占空比参数。

当前配置中系统主要参数如下：

```yaml
system:
  name: K1 多层视觉分拣系统
  camera_width: 640
  camera_height: 480
  camera_fps: 30
  conf_threshold: 0.15
  nms_iou: 0.45
  topk: 100
  warmup_runs: 10
  camera_scan_max_index: 64
  jpeg_quality: 80
```

当前四层默认配置如下：

| 分拣层 | 目标颜色 | 摄像头 | PWM 芯片 | PWM 通道 | 非目标动作 |
|---|---|---|---|---|---|
| 第一层 | red | `/dev/video20` | `/sys/class/pwm/pwmchip0` | 0 | other |
| 第二层 | yellow | `/dev/video22` | `/sys/class/pwm/pwmchip2` | 0 | other |
| 第三层 | blue | `/dev/video24` | `/sys/class/pwm/pwmchip1` | 0 | other |
| 第四层 | green | `/dev/video26` | `/sys/class/pwm/pwmchip3` | 0 | other |

> 注意：同一个摄像头是否能同时给多层使用，需要根据实际硬件和运行情况确认。正式比赛展示前建议在 Web 控制台中重新扫描设备并保存每层绑定。

### sorter/config.py

负责系统默认配置、配置合并、路径解析、参数校验和配置保存。

该模块限制的颜色类别为：

```text
red
yellow
blue
green
```

支持的非目标动作包括：

```text
pass
other
```

其中：

- `pass` 表示非目标物料直通，舵机不动作。
- `other` 表示非目标物料转向 OTHER 位置。

### sorter/devices.py

负责扫描硬件设备，包括：

- `/dev/video*` 摄像头节点
- `/sys/class/pwm/pwmchip*` PWM 通道

摄像头扫描时会尝试打开设备并读取画面，用于判断该设备是否可用。PWM 扫描时会读取 `pwmchip` 和通道数量，并生成稳定 UID，方便保存和恢复设备绑定。

### sorter/vision.py

负责视觉识别相关功能，包括：

- 摄像头采集线程
- 只保留最新帧，降低延迟
- 强制 USB 摄像头使用 V4L2
- 设置 MJPG、640x480、30fps、小缓冲
- 图像预处理
- ONNX Runtime 推理
- SpaceMITExecutionProvider 加速
- NMS 后处理
- 检测框和类别绘制

### sorter/layer.py

负责单个分拣层的运行逻辑。每层包含：

- 摄像头实例
- 舵机实例
- 推理结果处理
- 目标颜色判断
- 计数统计
- 状态管理
- 画面叠加显示
- 手动动作控制

当前代码中加入了直接颜色触发逻辑：识别到目标颜色后直接发送 `target` 动作；识别到非目标颜色且 `non_target_action` 为 `other` 时发送 `other` 动作，并通过冷却时间避免每一帧重复触发舵机。

### sorter/system.py

负责整个多层分选系统的管理，包括：

- 加载配置
- 初始化日志数据库
- 扫描设备
- 加载 YOLO 模型
- 创建推理调度器
- 创建多层控制器
- 管理所有分拣层状态
- 汇总目标计数、非目标计数和运行层数
- 提供系统温度、CPU、内存等运行指标

### sorter/logstore.py

负责将系统运行日志写入 SQLite 数据库。默认数据库路径为：

```text
data/sorter.db
```

系统运行后会自动创建该文件。

### web/console.html

`console.html` 是 Web 控制台页面，主要功能包括：

- 查看系统在线状态
- 查看故障层数
- 选择第一层、第二层、第三层、第四层
- 选择摄像头
- 选择 PWM 通道
- 设置目标颜色
- 设置非目标动作
- 设置触发线 Y
- 设置控制置信度
- 设置目标 duty、复位 duty、OTHER duty
- 设置舵机保持时间
- 保存参数
- 启动、暂停、继续、停止、清零
- 手动目标位
- 手动 OTHER 位
- 舵机复位
- 查看右侧实时视频
- 查看目标计数、非目标计数、FPS、推理耗时
- 查看系统运行日志

## 环境依赖

`requirements.txt` 中包含以下 Web 端依赖：

```text
fastapi
uvicorn[standard]
PyYAML
psutil
```

在 K1 / Bianbu 系统中，以下硬件相关库通常已经适配完成，不建议通过普通 `pip` 随意覆盖安装：

```text
numpy
cv2
onnxruntime
spacemit_ort
```

## 模型文件放置

当前 `config.yaml` 中模型路径为：

```text
/home/bianbu/1/ai-sdk/models/my_yolov11m/model/best_yolov11n_int8_fix.q.onnx
```

标签文件路径为：

```text
/home/bianbu/1/ai-sdk/models/my_yolov11m/data/label.txt
```

建议模型目录结构如下：

```text
models/
└── my_yolov11m/
    ├── model/
    │   └── best_yolov11n_int8_fix.q.onnx
    └── data/
        └── label.txt
```

`label.txt` 建议内容如下：

```text
red
yellow
blue
green
```

标签顺序必须与模型训练时的类别顺序保持一致。

## 安装方法

进入项目目录：

```bash
cd 智能材料加工分选机
```

安装 Web 端依赖：

```bash
python3 -m pip install -r requirements.txt
```

如果在开发板上已经配置好 OpenCV、ONNX Runtime 和 `spacemit_ort`，不要重新覆盖这些硬件相关库。

## 运行方法

推荐使用启动脚本：

```bash
bash run.sh
```

也可以直接运行：

```bash
python3 app.py --host 0.0.0.0 --port 8000
```

如果 PWM 没有普通用户写权限，可以使用：

```bash
sudo -E python3 app.py --host 0.0.0.0 --port 8000
```

如果需要指定配置文件：

```bash
python3 app.py --config config.yaml --host 0.0.0.0 --port 8000
```

## 访问控制台

开发板本机访问：

```text
http://127.0.0.1:8000/console
```

同一局域网电脑或手机访问：

```text
http://开发板IP:8000/console
```

例如：

```text
http://192.168.1.100:8000/console
```

## Web 控制台使用流程

1. 启动程序。
2. 打开浏览器访问 `/console`。
3. 点击“扫描设备”。
4. 分别进入第一层、第二层、第三层、第四层。
5. 给每层选择摄像头和 PWM 通道。
6. 给每层选择目标颜色。
7. 设置非目标动作：
   - `pass`：非目标直通。
   - `other`：非目标打到 OTHER 位。
8. 设置舵机 duty 参数。
9. 点击“保存参数”。
10. 点击“手动目标位 / 手动 OTHER 位 / 舵机复位”检查机械方向。
11. 点击“启动”或“全部启动”开始分选。
12. 在右侧查看实时画面、FPS、推理耗时和计数结果。

## 分选逻辑

每层都有自己的目标颜色和舵机动作参数。

当摄像头识别到物料颜色后：

1. 如果识别颜色等于当前层目标颜色，则舵机执行 `target` 动作。
2. 如果识别颜色不是当前层目标颜色，并且 `non_target_action` 为 `other`，则舵机执行 `other` 动作。
3. 如果识别颜色不是当前层目标颜色，并且 `non_target_action` 为 `pass`，则舵机不动作。
4. 系统更新目标计数、非目标计数、运行状态和日志。
5. 页面实时刷新显示当前层状态和画面。

## 舵机参数说明

常用 PWM 参数如下：

| 参数 | 说明 |
|---|---|
| `period_ns` | PWM 周期 |
| `min_duty_ns` | 舵机最小安全占空比 |
| `max_duty_ns` | 舵机最大安全占空比 |
| `init_duty_ns` | 初始化占空比 |
| `reset_duty_ns` | 复位位置占空比 |
| `target_duty_ns` | 目标颜色动作占空比 |
| `other_duty_ns` | 非目标 OTHER 动作占空比 |
| `hold_seconds` | 舵机动作保持时间 |
| `smooth_steps` | 平滑移动步数 |
| `smooth_delay` | 平滑移动每步延迟 |

当前主要舵机参数：

```yaml
period_ns: 5000000
reset_duty_ns: 1500000
target_duty_ns: 1630000
other_duty_ns: 1370000
hold_seconds: 2
```

## API 接口说明

| 接口 | 方法 | 功能 |
|---|---|---|
| `/` | GET | 旧首页，需要 `web/index.html` |
| `/console` | GET | Web 控制台 |
| `/api/status` | GET | 获取系统状态 |
| `/api/devices` | GET | 获取摄像头和 PWM 设备 |
| `/api/devices/rescan` | POST | 重新扫描设备 |
| `/api/layers` | GET | 获取所有分拣层状态 |
| `/api/layers/{layer_id}/config` | PUT | 更新指定分拣层配置 |
| `/api/layers/{layer_id}/target-color` | POST | 修改指定分拣层目标颜色 |
| `/api/layers/{layer_id}/start` | POST | 启动指定分拣层 |
| `/api/layers/{layer_id}/pause` | POST | 暂停指定分拣层 |
| `/api/layers/{layer_id}/resume` | POST | 继续指定分拣层 |
| `/api/layers/{layer_id}/stop` | POST | 停止指定分拣层 |
| `/api/layers/{layer_id}/reset-counts` | POST | 清零指定分拣层计数 |
| `/api/layers/{layer_id}/manual/{action}` | POST | 手动控制舵机动作 |
| `/api/system/start` | POST | 启动全部分拣层 |
| `/api/system/pause` | POST | 暂停全部分拣层 |
| `/api/system/stop` | POST | 停止全部分拣层 |
| `/api/system/reset-counts` | POST | 清零全部计数 |
| `/api/logs` | GET | 获取系统日志 |
| `/api/layers/{layer_id}/stream` | GET | 获取指定分拣层实时视频流 |
| `/ws/status` | WebSocket | 实时推送系统状态 |

`manual/{action}` 中的 `action` 可使用：

```text
target
other
reset
```

## 项目亮点

- 使用 K1 MUSE Pi Pro 完成边缘端视觉识别与控制。
- 使用 YOLO ONNX 模型识别不同颜色物料。
- 使用 SpaceMITExecutionProvider 提升推理效率。
- 使用 Web 控制台进行触摸屏式交互。
- 使用多层结构提高分选能力。
- 使用 Linux PWM 直接控制舵机，结构简单、成本低。
- 使用模块化代码结构，便于展示、维护和扩展。
- 支持实时视频、实时日志和实时统计数据。



## 常见问题

### 1. 网页打不开 `/`

当前 `app.py` 中 `/` 默认返回 `web/index.html`，如果项目里没有 `index.html`，访问 `/` 会失败。建议直接访问：

```text
http://开发板IP:8000/console
```

或者把 `app.py` 中的根路径改成返回 `console.html`。

### 2. 摄像头打不开

可以先检查设备：

```bash
ls /dev/video*
```

然后在控制台点击“扫描设备”。如果有多个同型号 USB 摄像头，当前程序会使用 sysfs 路径和 `/dev/videoX` 生成 UID，减少 UID 冲突。

### 3. 舵机不动

检查：

1. PWM 通道是否选对。
2. 是否点击了“保存参数”。
3. 程序是否有写 `/sys/class/pwm` 的权限。
4. 是否需要使用 `sudo -E` 启动。
5. 舵机是否使用独立供电，GND 是否与开发板共地。

### 4. SpaceMITExecutionProvider 不可用

需要确认 `spacemit_ort` 和适配版 ONNX Runtime 已正确安装。不要随意用普通 `pip` 覆盖开发板原本适配好的推理环境。


## 当前项目状态

当前项目已经完成：

- FastAPI 后端服务
- Web 控制台
- 多层分拣配置
- 摄像头和 PWM 扫描
- YOLO ONNX 推理
- SpaceMIT 硬件加速调用
- 实时视频流
- SQLite 日志
- 舵机手动控制
- 目标颜色分选逻辑
