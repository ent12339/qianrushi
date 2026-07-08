# K1 MUSE Pi Pro 多层视觉智能分拣系统

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
