# K1 MUSE Pi Pro 智能材料分拣系统

## 项目简介

本项目是一个基于 K1 MUSE Pi Pro 开发板的多层视觉智能分拣系统，面向比赛场景设计。系统通过摄像头采集物料图像，使用 YOLO 模型进行颜色目标识别，并结合目标跟踪与触发线判断，实现对红、黄、蓝、绿等不同颜色物料的自动识别与分拣。

系统采用模块化设计，支持多路摄像头、多层分拣机构、多路 PWM 舵机控制，并提供 Web 可视化控制界面，方便在触摸屏或局域网设备上进行实时监控、参数配置和手动调试。

## 项目功能

- 支持多路摄像头图像采集
- 支持 YOLO / ONNX Runtime 模型推理
- 支持 SpaceMITExecutionProvider 硬件加速
- 支持红、黄、蓝、绿四类目标识别
- 支持目标跟踪与触发线检测
- 支持多层独立分拣控制
- 支持 Linux sysfs PWM 舵机控制
- 支持 Web 页面实时监控
- 支持系统启动、暂停、停止、计数清零
- 支持手动控制舵机动作
- 支持设备扫描与参数配置

## 项目目录结构

```text
project/
├── app.py                         # FastAPI Web 服务主入口
├── requirements.txt               # Python Web 端依赖
├── run.sh                         # 项目启动脚本
├── README.md                      # 项目说明文档
├── zhengti.py                     # 原始整合版视觉分拣程序
├── servo_mg90_pwm4.py             # PWM4 舵机测试程序
├── servo_mg90_pwm5.py             # PWM5 舵机测试程序
├── servo_mg90_pwm7.py             # PWM7 舵机测试程序
├── servo_mg90_pwm16.py            # PWM16 舵机测试程序
├── sorter/                        # 分拣系统核心模块
├── web/                           # Web 前端页面
├── deploy/                        # 部署相关文件
├── data/                          # 数据与日志目录
├── models/                        # 模型文件目录
└── .venv/                         # Python 虚拟环境，上传 GitHub 时建议忽略

## 核心文件说明

### app.py

`app.py` 是整个系统的 Web 服务入口，基于 FastAPI 实现。主要功能包括：

- 启动并初始化分拣系统
- 提供 Web 前端页面访问
- 提供系统状态查询接口
- 提供设备扫描接口
- 提供单层分拣参数修改接口
- 提供系统启动、暂停、停止接口
- 提供实时日志接口
- 提供摄像头视频流接口
- 提供 WebSocket 状态推送接口

运行后可以通过浏览器访问系统控制界面。

### zhengti.py

`zhengti.py` 是早期整合版程序，包含摄像头采集、图像预处理、YOLO 模型推理、目标跟踪、颜色识别、触发线判断和 PWM 舵机控制等完整逻辑。

该文件主要用于功能验证和算法调试。

### servo_mg90_pwm*.py

这些文件用于单独测试不同 PWM 通道上的 MG90 / MG90S 舵机，例如：

- `servo_mg90_pwm4.py`
- `servo_mg90_pwm5.py`
- `servo_mg90_pwm7.py`
- `servo_mg90_pwm16.py`

每个测试程序都可以控制舵机转动到指定角度，并在保持一段时间后回到中位，方便确认舵机接线、PWM 通道映射和机械方向。

### run.sh

项目启动脚本，进入当前目录后执行：

```bash
python3 app.py --host 0.0.0.0 --port 8000

## 环境依赖

基础依赖如下：

```text
fastapi
uvicorn[standard]
PyYAML
psutil
```

在 K1 / Bianbu 系统中，`numpy`、`opencv-python`、`onnxruntime`、`spacemit_ort` 等硬件相关环境通常已经适配完成，不建议随意使用普通 `pip` 覆盖安装。

安装 Web 端依赖：

```bash
pip install -r requirements.txt
```

## 模型文件放置

模型文件建议放置在 `models/` 目录下，例如：

```text
models/
└── my_yolov11m/
    ├── model/
    │   └── best_yolov11n_int8_fix.q.onnx
    └── data/
        └── label.txt
```

`label.txt` 中应包含识别类别，例如：

```text
red
yellow
blue
green
```

标签顺序需要与模型训练时的类别顺序保持一致。

## 运行方法

进入项目目录：

```bash
cd project
```

安装依赖：

```bash
pip install -r requirements.txt
```

启动服务：

```bash
bash run.sh
```

或者直接运行：

```bash
python3 app.py --host 0.0.0.0 --port 8000
```

如果 PWM 需要管理员权限，可以使用：

```bash
sudo -E python3 app.py --host 0.0.0.0 --port 8000
```

启动后，在浏览器访问：

```text
http://127.0.0.1:8000
```

同一局域网设备可访问：

```text
http://开发板IP:8000
```

## Web 控制功能

Web 页面支持以下操作：

- 查看系统运行状态
- 查看各层识别与分拣状态
- 扫描摄像头和 PWM 设备
- 设置每层目标颜色
- 设置每层分拣参数
- 启动单层分拣
- 暂停单层分拣
- 停止单层分拣
- 启动全部分拣层
- 暂停全部分拣层
- 停止全部分拣层
- 清零计数
- 查看运行日志
- 查看摄像头实时画面

## 分拣逻辑

系统支持多层独立分拣，每一层可以设置自己的目标颜色。

当摄像头检测到物料经过触发线时：

1. 系统识别物料颜色；
2. 判断该颜色是否为当前层的目标颜色；
3. 如果是目标颜色，舵机执行目标分拣动作；
4. 如果不是目标颜色，则根据配置选择直通或执行非目标动作；
5. 系统更新目标计数、非目标计数和日志。

## 舵机控制说明

系统使用 Linux sysfs PWM 接口控制 MG90 / MG90S 舵机。常用参数包括：

- `period_ns`：PWM 周期
- `init_duty_ns`：初始占空比
- `reset_duty_ns`：复位位置占空比
- `target_duty_ns`：目标颜色分拣占空比
- `other_duty_ns`：非目标颜色分拣占空比
- `hold_seconds`：舵机保持时间

项目中提供了多个单独的 PWM 测试脚本，便于在正式运行前确认每个舵机是否能够正常动作。

## API 接口概览

| 接口 | 方法 | 功能 |
|---|---|---|
| `/` | GET | Web 主界面 |
| `/console` | GET | 控制台页面 |
| `/api/status` | GET | 获取系统状态 |
| `/api/devices` | GET | 获取设备信息 |
| `/api/devices/rescan` | POST | 重新扫描设备 |
| `/api/layers` | GET | 获取所有分拣层状态 |
| `/api/layers/{layer_id}/start` | POST | 启动指定分拣层 |
| `/api/layers/{layer_id}/pause` | POST | 暂停指定分拣层 |
| `/api/layers/{layer_id}/resume` | POST | 恢复指定分拣层 |
| `/api/layers/{layer_id}/stop` | POST | 停止指定分拣层 |
| `/api/system/start` | POST | 启动全部分拣层 |
| `/api/system/pause` | POST | 暂停全部分拣层 |
| `/api/system/stop` | POST | 停止全部分拣层 |
| `/api/logs` | GET | 获取系统日志 |
| `/ws/status` | WebSocket | 实时推送系统状态 |

## 项目特色

本项目相比传统单层分拣系统，具有以下特点：

1. 采用多层分拣结构，提高颜色分类能力；
2. 使用 YOLO 模型完成视觉识别，适应复杂场景；
3. 支持硬件加速推理，提高开发板端运行效率；
4. 使用 Web 控制界面，方便现场调试和展示；
5. 通过模块化设计降低后续维护和扩展难度；
6. 支持多路 PWM 舵机控制，适合实体分拣装置。

## 注意事项

- `.venv/` 虚拟环境目录不建议上传到 GitHub。
- `__pycache__/` 缓存目录不建议上传到 GitHub。
- 模型文件较大时，可以根据比赛要求选择是否上传。
- 如果模型文件较大，建议在 README 中说明模型下载或放置路径。
- 运行前需要确认摄像头、PWM 舵机和模型路径配置正确。
- 如果使用开发板运行，需要确认 `spacemit_ort` 和 ONNX Runtime 环境正常。

## 建议的 .gitignore

```gitignore
.venv/
__pycache__/
*.pyc
*.pyo
*.pyd
*.log
data/*.db
data/*.sqlite
app.py.bak*
.DS_Store
.vscode/
.idea/
```

## 项目状态

当前项目已经完成基础视觉识别、舵机控制、Web 控制界面和多层分拣逻辑。
