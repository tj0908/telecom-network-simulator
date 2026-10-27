# 仓库与实验审计（升级任务阶段一）

审计对象：telecom-network-simulator @ 6e8e55c（master，工作区干净，
与 origin 同步）。审计方式：只读检查源码、配置、已保存数据与已安装
的 ns-3 3.41 头文件/库，并对现有二进制做确定性复跑。审计中未修改
任何代码与数据。

## 1. 环境与入口确认

| 项 | 实际状态 |
|---|---|
| ns-3 | 3.41（apt 系统包，pkg-config 五模块 + flow-monitor/traffic-control 均为 3.41） |
| 程序 | udp_baseline（D1）、tcp_udp_compare（D2）、flow_metrics（D3/D4）、queue_compare（D5）、multiflow_fairness（D7） |
| 自动化 | run_experiments.py（D4）、run_queue_experiments.py（D5）、run_fairness_experiments.py（D7，7 项校验）、audit_d7_metrics.py（D7.1，40+ 断言）、run_regression.sh（14 项回归）、三个绘图脚本 |
| 测试现状 | 14 项回归全 PASS；D7 校验 7/7；D7.1 审计全 PASS（2026-10-26 实测） |
| 单次仿真成本 | D7 一组实测墙钟约 0.38 s（12 s 仿真时长） |

## 2. D7 实际配置（逐项核实自 src/multiflow_fairness.cc）

- 拓扑：3 发送 + 2 路由 + 3 接收的 dumbbell；接入链路 10 Mbps/2 ms；
  **瓶颈在源码中写死为 2 Mbps / 10 ms**（middle 链路），无命令行参数。
- 流量：TCP×2 = BulkSend（MaxBytes=0，SendSize=1024）；UDP = OnOff
  恒速（OnTime 常量 1、OffTime 常量 0），速率由 --group 决定
  （A 无 UDP / B 500 kbps / C 4 Mbps），包长 1024 B。
- 时间：业务统一 1.0 s 启动、11.0 s 停止，仿真 12.0 s 结束。
- 队列：**仅施加于 R0→R1 出口方向**。TrafficControlHelper 先
  Uninstall 再装 PfifoFastQueueDisc 或 FqCoDelQueueDisc，上限同为
  100p；设备队列两边同为默认 DropTail 100p。每组运行都从协议栈
  读回实际配置打印核对。
- 测量：FlowMonitor（IP 层）逐流 tx/rx/lost/rxBytes/delaySum 与
  首末包时刻；瓶颈两层队列的丢弃计数、10 ms 占用采样与结束残留；
  D7.1 已确立共同观察窗口口径并保留逐流跨度口径原始数据。

## 3. 现有能力清单（可直接复用）

1. 完整的单流（D1–D5）与多流（D7）仿真程序及全部原始数据、CSV、
   图表、回归与审计脚本。
2. 指标：IP 层吞吐（双口径）、平均时延、逐流丢包率
   （lostPackets/txPackets）、未接收比例、Jain 公平性（双口径，
   TCP-only 与含 UDP 两种集合）、队列占用/丢弃/残留与结束对账。
3. 工程机制：确定性复跑校验、队列读回核对、多层计数交叉验证、
   审计断言脚本——升级可直接沿用这套验证风格。

## 4. 数据与指标口径问题（审计发现）

1. **当前程序没有任何随机种子机制**。`--rng-run` 不是该程序的
   合法参数；流量成分全部确定性（OnOff 为常数开关、BulkSend 贪婪
   发送、无信道误差模型、静态全局路由）。同参数两次运行输出逐
   字节相同（审计实测）。**结论：按现状跑"5 个种子"只会得到 5 份
   相同结果，属于伪重复，严禁当作独立样本报告离散程度。**
2. **P95 时延当前不可得**：FlowMonitor 只保存了 delaySum（均值）。
   已核实 FlowStats 含 delayHistogram 字段、库中存在 DelayBinWidth
   属性——可通过设置直方图 bin 宽并读取逐流直方图得到 P95
   （bin 分辨率内的近似，须注明 bin 宽），无需改测量层。
3. 逐流跨度吞吐不可加总（D7.1 已修复为共同窗口口径，升级中
   严禁回归）。
4. FIFO vs FqCoDel 的差异**同时包含调度与丢弃逻辑两个机制**，
   本设计内不可分离归因（D5 单流对照为旁证）。
5. 两种策略下都串联着不受控的 100p 设备队列：对照的准确含义是
   "给定共享设备队列时 qdisc 纪律的差异"，不是纯 AQM 对照。
6. 反向 ACK 方向队列未插桩；占用采样含业务前约 1 s 空队列期
   （各组同口径）；TCP 的 lostPackets 为 IP 层计数、因重传而
   高估应用层损失；TCP 报文段为 ns-3 默认 536 B。
7. 瓶颈带宽写死 2 Mbps：5/10 Mbps 对照需要新增参数；且带宽升高
   后 UDP 4 Mbps 的相对过载程度改变，跨带宽结果必须分带宽报告，
   不可合并成单一结论。

## 5. 缺失的指标

| 指标 | 状态 | 补齐方式 |
|---|---|---|
| P95 端到端时延（逐流） | 缺失 | FlowMonitor delayHistogram（bin 宽 0.5 ms，注明近似方式） |
| 统一窗口下的 TCP 总吞吐/UDP 吞吐/合计 | D7 有逐流值，缺聚合与跨配置汇总 | Python 汇总脚本从逐流 rxBytes 与窗口计算 |
| 多种子离散程度 | 不存在（见问题 1） | 新增显式随机因素后才有意义（见最小方案） |
| 每次运行墙钟耗时 | 未记录 | 新运行脚本用 perf_counter 记录并写入 CSV |

## 6. 最小代码修改方案（阶段二执行）

只改 1 个已有文件，新增 4 个文件，不动 D1–D5 与既有 D7 数据：

1. **src/multiflow_fairness.cc（增量）**：
   - 新增 `--bottleneck` 参数（默认 "2Mbps"，保持现行为）；
   - 新增 `--seed` 参数（默认 0 = 旧行为：不触碰 RNG、无抖动，
     旧参数组合的输出保持逐字节不变）；seed ≥ 1 时用
     RngSeedManager 固定 Seed 并以 seed 为 Run 号，为三条流的
     启动时刻抽取 [0, 200 ms] 内的均匀抖动（停止时刻不变），
     抖动值打印到输出——这是本升级**唯一引入的随机因素**，
     其作用是扰动流间相位关系，文档中明确声明；
   - 采集 P95：给 FlowMonitor 设置 DelayBinWidth=0.0005 s，
     逐流从 delayHistogram 计算 P95（累计计数首次达到 95% 时
     所在 bin 的右边界），新增输出行与 CSV 列（追加在末尾，
     旧列名与顺序不变）。
2. **scripts/fairness_metrics.py（新）**：共同窗口速率、Jain、
   均值/标准差、变化率等纯函数，供汇总脚本与单元测试共用。
3. **scripts/test_metrics.py（新）**：标准库单元测试（本环境无
   pytest，已核实）：Jain 边界、共同窗口合计不超容量、均值/
   标准差/变化率公式、P95 直方图算法的 Python 镜像用例。
4. **scripts/run_bottleneck_matrix.py（新）**：阶段三矩阵入口
   （队列 2 × 带宽 3 × seed 1..5，固定组 C 混合流量），记录
   每组墙钟耗时，输出原始 CSV 与汇总 CSV（均值 ± 标准差）。
5. **scripts/plot_bottleneck_matrix.py（新）**：吞吐/P95/丢包率/
   Jain 四张带误差棒的对比图。

矩阵固定组 C 的理由：它是 TCP/UDP 真正竞争的场景（A 无 UDP、
B 的 UDP 只占 25%）；跨带宽时 UDP 速率保持 4 Mbps 不变，
带宽是唯一变化的受控变量，口径在报告中注明。

## 7. 预计运行成本

- 编译：约 10 s（单文件，系统 ns-3 库链接）。
- 矩阵：30 次 × 约 0.4–0.6 s ≈ 20 s 以内（含 Python 开销）。
- 汇总 + 绘图 + 单元测试：数秒。
- 旧体系验证（14 回归 + D7 校验 + D7.1 审计）：约 1 分钟。
- 总执行成本以分钟计；主要成本在分析与文档，而非计算。

## 8. 审计结论

现有 D7 是可靠的对照框架：拓扑、流量、队列位置与参数、共同窗口
口径都已核实无误，可直接作为升级基座。升级的必要增量只有三处：
瓶颈参数化、P95 采集、以及**诚实的多样本机制**（显式抖动种子，
而非把确定性结果冒充重复样本）。除此之外不大动。
