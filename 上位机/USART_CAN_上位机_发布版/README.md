# USART/CAN/TCP 上位机

一个 Windows PC 桌面端上位机，支持 USART、CAN 和 TCP 数据收发，支持选择 `.bin`、Intel HEX `.hex` 以及文本 HEX 文件发送，并可设置连续数据流发送时的分块延时。

## 运行

1. 安装 Python 3.10 或更高版本。
2. 在本目录双击 `run.bat`，或执行：

```powershell
python -m pip install -r requirements.txt
python main.py
```

## 功能

- USART：串口选择、波特率、数据位、校验位、停止位配置。
- CAN：接口类型、通道、速率、采样点、标准帧/扩展帧、数据帧/远程帧配置；速率用 `500 kbps`、`1 Mbps` 这类带单位选项显示，通道支持刷新并下拉选择检测到的可用设备。
- TCP Client：配置远端 IP/主机名和端口，主动连接 TCP Server。
- TCP Server：配置监听地址和端口，接受一个 TCP Client 连接。
- 连接按钮：同一个按钮在“连接”和“断开”之间自动切换。
- 接收日志：USART/CAN 接收数据都会以 HEX 显示。
- 手动发送：支持按 UTF-8 文本发送或按 HEX 字节发送。
- 文件发送：`.bin` 按原始字节发送，`.hex` 按 Intel HEX 解析后发送，普通文本会优先尝试按 HEX 字节解析。
- 分块延时：例如设置“每 16 字节延时 100 us”或“10 ms”，发送任务会每发送指定字节数后按所选单位等待再继续。

## CAN 说明

CAN 功能依赖 `python-can` 和对应硬件驱动。常见配置示例：

- PCAN-USB：接口 `pcan`，通道 `PCAN_USBBUS1`。
- SLCAN/串口 CAN：接口 `slcan`，通道可从下拉列表选择实际检测到的设备串口名，例如 `COM5`。
- 虚拟 CAN 测试：接口 `virtual`，通道可填写 `test`。

当前实现发送的是经典 CAN 帧，单帧最多 8 字节；文件或长数据会自动拆成 8 字节帧发送。

## 注意

- 如果打开程序后提示未安装 `pyserial` 或 `python-can`，先运行 `python -m pip install -r requirements.txt`。
- 如果系统里的 `python` 是 Microsoft Store 占位程序，需要从 Python 官网安装正式版本，并勾选 “Add python.exe to PATH”。
