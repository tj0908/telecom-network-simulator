# 简历量化证据表

本表把可写进简历的每个数字钉死到原始数据、公式与适用条件。
数字全部来自阶段三对照实验（`results/eval_matrix_raw.csv` 原始、
`results/eval_matrix_summary.csv` 汇总），可逐项复算。实验条件
（所有数字共享）：ns-3 3.41 仿真；dumbbell 拓扑，接入 10 Mbps/2 ms，
瓶颈时延 10 ms；流量为 2 条 TCP BulkSend + 1 条 UDP OnOff 恒速
4 Mbps（业务 1–11 s）；队列 PfifoFast/FqCoDel 均为 100p、仅施加于
瓶颈出口，设备队列同为 DropTail 100p；5 个种子 = 流启动时刻
[0, 200 ms] 抖动的 5 种相位，数字为其均值 ± 样本标准差。

## 可用数字（可核验）

| # | 数字 | 原始数据 | 计算公式 | 适用条件 |
|---|---|---|---|---|
| 1 | 2 Mbps 下 TCP 总吞吐：FIFO 0.077 ± 0.026 → FqCoDel 1.125 ± 0.074 Mbps | eval_matrix_raw.csv 中 queue/bottleneck 两组各 15 行逐流数据 | 逐流共同窗口速率 = rxBytes×8 / (max lastRx − min firstTx)，两条 TCP 相加后跨种子取均值 | 组 C 混合流量、瓶颈 2 Mbps |
| 2 | 同条件下合计吞吐两策略相同：1.985 vs 1.987 Mbps | 同上 | 三流共同窗口速率之和 | 说明策略改变的是分配而非总量 |
| 3 | 2 Mbps 下 TCP P95 时延：803.2 ± 15.7 → 366.8 ± 21.2 ms（−54.3%） | eval_matrix_raw.csv 的 p95_delay_ms 列 | FlowMonitor 时延直方图（bin 宽 0.5 ms）累计 95% 处 bin 右边界；两条 TCP 先平均再跨种子汇总 | 端到端时延，非排队时延 |
| 4 | 5 Mbps 下 TCP 总吞吐：1.213 ± 0.056 → 2.966 ± 0.188 Mbps（+144.5%）；平均时延 −40.8% | 同 #1 的 5 Mbps 两组 | 同 #1；变化率 = (FqCoDel − FIFO)/FIFO × 100%（按均值） | 瓶颈 5 Mbps |
| 5 | 10 Mbps 下 TCP 吞吐基本持平（+0.6%，小于标准差）、平均时延 −36.0%、P95 −28.8% | 同 #1 的 10 Mbps 两组 | 同上 | 瓶颈 10 Mbps；吞吐差异不可与噪声区分，必须如实写"基本持平" |
| 6 | 公平性稳定性：FIFO 在 2 Mbps 下 jain_tcp 逐种子 0.63–0.96（均值 0.8025），FqCoDel 为 0.9941 ± 小离散 | eval_matrix_raw.csv + scripts/fairness_metrics.py 的 jain() | Jain = (Σx)²/(n·Σx²)，x 为两条 TCP 的共同窗口速率 | 说明单次确定性运行会高估 FIFO 公平性 |
| 7 | 工程规模：30 次对照仿真全自动运行（2 队列 × 3 带宽 × 5 种子），单次墙钟 0.19–1.48 s（各配置均值 0.22–1.37 s），含 4 类自动校验 | eval_matrix_raw.csv / eval_matrix_summary.csv 的 wall_time_s 列；run_bottleneck_matrix.py 输出 | 脚本 perf_counter 计时 | 自动化与可复现性证据 |
| 8 | 口径审计纠正：共同窗口使 C/FIFO 的 jain_tcp 从逐流跨度口径的 0.7093 修正为 0.9987 | results/d7_metrics.csv、d7_unified_window.csv、d7_audit.txt | 见 docs/d7_multiflow.md 的 D7.1 审计一节 | 测量严谨性证据 |

## 不应夸大的内容（红线）

- 不要单独引用"+1353%"描述 2 Mbps 的 TCP 吞吐变化：FIFO 基数
  0.077 接近零，百分比天然爆炸；要写就连同绝对值（0.077→1.125
  Mbps）一起写。
- 不要写"FqCoDel 全面优于 FIFO"：10 Mbps 下 TCP 丢包无改善、
  UDP P95 在 5/10 Mbps 下略差、合计吞吐 −1.2%（离散范围内）。
- 不要写"统计显著"：种子是相位抖动、n=5、非独立样本，只做了
  描述性离散报告。
- 不要把端到端时延写成排队时延，不要把 IP 层吞吐写成应用层
  吞吐/goodput，不要把仿真写成真实网络部署或硬件测量。
- 不要把改善单独归因于 CoDel 或 FQ 任一机制：对照中两机制
  同时变化，未做隔离实验。

## 简历项目描述（真实、可核验，任选）

1. 基于 ns-3 构建 TCP/UDP 混合流量瓶颈竞争仿真系统（dumbbell
   拓扑、FlowMonitor 逐流测量），完成 FIFO 与 FqCoDel 的量化
   对照（2 队列 × 3 带宽 × 5 相位种子共 30 次自动化仿真）：
   2 Mbps 瓶颈下 FqCoDel 使 TCP 总吞吐由 0.077 恢复至
   1.125 Mbps、P95 时延降低 54.3%，且证明合计吞吐不变、
   策略改变的是带宽分配而非总量。
2. 建立可复现的网络性能评估流水线：共同观察窗口吞吐、P95
   时延直方图、Jain 公平性、多层队列计数对账与审计断言；
   通过口径审计发现并修正逐流统计窗口导致的公平性误判
   （Jain 指数 0.7093 → 0.9987），全部结论可追溯至原始 CSV。
3. 对队列管理做多层归因分析：采样证明瓶颈出口是 QueueDisc +
   设备队列两层串联缓冲，FqCoDel 自身队列平均占用仅约 1.3 包
   而设备队列保持约 88 包，定位了 AQM 无法消除的时延地板；
   项目含 14 项回归测试、指标单元测试与完整实验文档。
