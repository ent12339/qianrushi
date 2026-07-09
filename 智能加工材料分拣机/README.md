# K1 MUSE Pi Pro 多层视觉分拣系统（模块化原型）

本项目把原来的单文件 `zhengti.py` 拆成了多层、可配置、可自动扫描设备的结构。K1 直接负责：

- 多路摄像头采集
- YOLOv11 / SpaceMIT 推理
- 每层独立目标跟踪与触发判断
- 多路 Linux PWM 舵机控制
- Web 触控界面、日志和运行信息

外部插电水泵不接入软件控制。

## 1. 核心原则

1. 四层默认分别设置为红、黄、蓝、绿，但这只是初始配置，不是写死逻辑。
2. 每层都可以在界面中独立选择 `red / yellow / blue / green`。
3. 每层都可以独立绑定任意已发现摄像头和任意 PWM 通道。
4. 所有层共享一个 ONNX Runtime 模型会话和一个推理调度线程，避免四路同时争抢 NPU。
5. `non_target_action` 支持：
   - `pass`：非目标颜色直通，舵机不动作，适合多层串联结构。
   - `other`：非目标颜色转到 OTHER 位置，兼容原来的双向分拣逻辑。
6. 摄像头和 PWM 会自动扫描，但不会自动乱配。首次在界面确认绑定，保存后按 UID 自动恢复。

## 2. 目录结构

```text
k1_sorter_multilayer/
├── app.py                    FastAPI 入口
├── config.yaml               四层配置
├── sorter/
│   ├── config.py             配置读取、校验和保存
│   ├── devices.py            摄像头/PWM 自动扫描
│   ├── vision.py             摄像头、预处理、YOLO、跟踪、推理调度
│   ├── servo.py              单路 PWM 舵机控制
│   ├── layer.py              单层状态机和分拣逻辑
│   ├── system.py             四层总管理器
│   └── logstore.py           SQLite 日志
├── web/index.html            MIPI 触摸屏 Web 界面
├── data/sorter.db            首次运行后自动创建
└── deploy/                   systemd 和 kiosk 示例
```

## 3. 放置模型

保持与原程序相同的相对路径：

```text
k1_sorter_multilayer/
└── models/
    └── my_yolov11m/
        ├── model/best_yolov11n_int8_fix.q.onnx
        └── data/label.txt
```

也可以直接修改 `config.yaml` 中的：

```yaml
system:
  model_path: /绝对路径/best_yolov11n_int8_fix.q.onnx
  labels_path: /绝对路径/label.txt
```

标签文件应包含：

```text
red
yellow
blue
green
```

实际顺序必须与模型训练类别顺序一致。

## 4. 安装 Web 端依赖

优先使用开发板当前已经能运行原程序的 Python 环境，不要覆盖 K1 已适配的 OpenCV、ONNX Runtime 和 `spacemit_ort`。

```bash
cd k1_sorter_multilayer
python3 -m pip install -r requirements.txt
```

## 5. 启动

PWM 没有普通用户写权限时，可以先使用：

```bash
sudo -E env \
  DISPLAY=:0 \
  XAUTHORITY=/home/bianbu/.Xauthority \
  python3 app.py --host 0.0.0.0 --port 8000
```

浏览器打开：

```text
http://127.0.0.1:8000
```

同一局域网电脑或手机也可以访问：

```text
http://开发板IP:8000
```

## 6. 首次设备绑定

1. 点击“扫描设备”。
2. 每层选择一个摄像头。
3. 每层选择一个 PWM 通道。
4. 选择该层目标颜色。
5. 多层串联结构将“非目标动作”设为“直通，不动作”。
6. 点击“保存参数”。
7. 在停止或暂停状态下，用“手动目标位 / 舵机复位”确认机械方向。
8. 点击“启动”。

同一个摄像头或 PWM 通道不能同时绑定给两层。

## 7. 为什么不能自动识别“哪个舵机”

普通三线舵机只有电源、地和 PWM 信号，不会向 Linux 返回型号或序列号。程序能扫描 PWM 控制器和通道，但不能判断该通道是否真的接了舵机。因此：

- 摄像头：可扫描、试读、生成 UID。
- PWM：可扫描控制器和通道。
- 舵机物理连接：需要首次人工测试确认。

## 8. 多层运行逻辑

每层配置完全独立：

```yaml
- id: layer_2
  target_color: blue
  camera_uid: camera-xxxx
  pwm_uid: pwm-yyyy
  trigger_line: 285
  control_conf: 0.52
  non_target_action: pass
```

当物料穿过该层触发线：

- 检测颜色等于该层目标颜色：舵机去 `target_duty_ns`，保持后复位。
- 不等于目标颜色且模式为 `pass`：只计数，不驱动舵机。
- 不等于目标颜色且模式为 `other`：舵机去 `other_duty_ns`，保持后复位。

## 9. MIPI 屏幕 kiosk

先确认 Chromium 命令名称：

```bash
which chromium
which chromium-browser
```

手动全屏测试：

```bash
chromium --kiosk --noerrdialogs --disable-infobars http://127.0.0.1:8000
```

`deploy/start-kiosk.sh` 可以按实际 Chromium 命令修改。

## 10. 当前原型的边界

- 已完成 Python 语法检查，但无法在这里验证 K1 的真实摄像头、PWM 权限和 SpaceMIT 推理性能。
- 当前采用单推理线程轮询多层，优先保证稳定性。后续可根据实测 FPS 调整每层 `infer_interval_ms`。
- 自动扫描 `/dev/video*` 时，部分视频节点可能属于编码器或元数据接口。程序会尝试读帧，界面中会标记不可读设备。
- 生产使用应配置 systemd 权限、物理急停和独立舵机电源。软件停止不能替代物理断电急停。
