# 🌦️ WeatherBet — Powered by Hermes Agent

> **完全自治的预测市场交易机器人** — 基于 ECMWF 天气预报数据在全链上自动寻找错误定价的 Polymarket 市场进行投注，并借助 **Hermes Agent** 框架实现全自动进化学习。

[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/downloads/)
[![Polygon](https://img.shields.io/badge/Chain-Polygon%20137-9B59B6.svg)](https://polygon.technology/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 🤖 为什么选择 Hermes Agent

本项目展示了 **Hermes Agent** 框架在自动化交易领域的强大能力：

| Hermes Agent 特性 | 在本项目中的应用 |
|---|---|
| **自主学习进化 (Self-Learning)** | 机器人从历史交易中自动调整 Kelly 分数和 EV 阈值参数 |
| **全自动化执行 (Autonomous Execution)** | 60 分钟循环扫描市场 → 计算信号 → 自动下单 → 链上结算，全程无需人工干预 |
| **多消息平台接入 (Multi-Platform Gateway)** | 通过 Telegram 实时推送交易通知，手机随时掌控全局 |
| **长期记忆 (Persistent Memory)** | 交易日志 + 学习模型持久化存储，跨会话保留学习成果 |
| **模型无关 (Model Agnostic)** | 可自由切换任意 LLM 提供者进行决策推理 |
| **工具编排 (Tool Orchestration)** | 整合天气预报 API + 链上 CLOB 交易 + Telegram 通知 |

---

## 🎯 这个项目做什么

机器人监控 **6 个美国城市**（纽约、芝加哥、迈阿密、达拉斯、西雅图、亚特兰大）的天气预报，在 **Polymarket 温度预测市场** 中寻找错误定价机会。

**核心逻辑：** 当天气预报预测某温度区间的概率与市场隐含概率不一致时 → 计算期望值 (EV) → EV > 阈值则自动投注。

---

## 🧠 核心技术：Gaussian Bucket Model

### 第一步 — 从 ECMWF 获取真实概率

```python
import math

def norm_cdf(x):
    """标准正态分布累计分布函数"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bucket_prob(forecast_temp, t_low, t_high, sigma=2.0):
    """
    天气预报给出 72°F ± 2σ
    计算实际高温落在 70-75°F 区间的真实概率
    P(t_low ≤ X ≤ t_high) = CDF(z_high) - CDF(z_low)
    """
    z_low  = (t_low  - forecast_temp) / sigma
    z_high = (t_high - forecast_temp) / sigma
    return norm_cdf(z_high) - norm_cdf(z_low)
```

### 第二步 — 计算期望值 (Expected Value)

```python
def calc_ev(true_prob, market_price):
    """
    EV = P(赢) × 收益 - P(输) × 损失
    EV > 0 表示市场定价偏低 → 买入信号
    """
    win  = true_prob * (1 / market_price - 1)
    lose = (1 - true_prob) * 1
    return win - lose
```

**示例：**
- 天气预报：72°F → 70-75°F 区间概率 **75%**
- 市场价格：$0.30（隐含 30% 概率）
- `EV = 0.75 × (1/0.30 - 1) - 0.25 = +1.25` → **强烈买入信号** 📈

### 第三步 — Kelly Criterion 最优投注

```python
def calc_kelly(p, price):
    """Kelly % = (bp - q) / b，使用 1/4 Kelly 保守分数"""
    b = 1.0 / price - 1.0
    f = (p * b - (1.0 - p)) / b
    return round(min(max(f, 0.0) * KELLY_FRAC, 1.0), 4)
```

---

## 🌀 自动进化学习系统

这是 Hermes Agent 框架的核心优势之一 — 机器人**从实战中学习，自动调参**：

```
data/learning/
├── trade_log.json   # 所有交易记录：城市、区间、成本、结果、盈亏
└── model.json       # 每个城市/区间的学习参数
```

**自适应规则：**
-胜率 < 45% → Kelly 分数 ×0.8，EV 阈值 +10%
-胜率 > 55% + 盈利 > $2 → Kelly 分数 ×1.1，EV 阈值 −5%
-按城市追踪胜率，调整各市场置信度
-初始保守（25% Kelly）→ 随着数据积累自动收敛到最优

---

## 📊 系统架构

```
ECMWF 天气预报 API
        ↓
Hermes Agent（自主决策引擎）
    ├── 高斯桶模型 → 真实概率
    ├── calc_ev() → 期望值计算
    ├── calc_kelly() → 最优投注
    └── 自适应学习 → 自动调参
        ↓
Polymarket CLOB（Polygon 链上执行）
        ↓
Telegram（实时推送通知）
```

---

## ⚙️ 快速开始

### 环境要求
- Python 3.13+
- Polygon 钱包 + USDC.e
- Polymarket CLOB 授权
- Polymarket API 凭证

### 安装
```bash
git clone https://github.com/nicolastinkl/hermes_weatherbot.git
cd hermes_weatherbot
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 配置
创建 `.env`：
```env
PK=your_polygon_private_key
WALLET=your_polygon_address
SIG_TYPE=0
```

编辑 `config.json`：
```json
{
  "balance": 0,
  "max_bet": 2.0,
  "min_ev": 0.10,
  "min_volume": 500,
  "scan_interval": 3600,
  "telegram_bot_token": "your_token",
  "telegram_chat_id": "your_chat_id"
}
```

### 运行
```bash
# 单次扫描
python bot_v3.py scan

# 持续交易循环
python bot_v3.py run

# 查看状态
python bot_v3.py status
```

---

## 🛡️ 风险管理

| 参数 | 值 | 说明 |
|---|---|---|
| 最大投注 | $2.00 | 单笔交易上限 |
| Kelly 分数 | 25% | 1/4 Kelly 保守策略 |
| 最低 EV | 10%+ | 只交易正期望值 |
| 最低成交量 | $500 | 避免低流动性市场 |
| 最大价差 | 3% | 避免高滑点 |
| 自适应阈值 | 10-20% | 根据表现自动调整 |

---

## 🔐 交易流程（全自动化）

```
1. 拉取 ECMWF 天气预报（D+0 ~ D+3）
2. 查询 Polymarket 温度区间市场
3. Gaussian 模型计算真实概率（σ=2°F）
4. 与市场价格对比 → 计算 EV
5. EV ≥ 自适应阈值 → 计算 Kelly 投注大小
6. Polymarket CLOB 链上下单（Polygon）
7. 记录交易 → 更新学习模型
8. Telegram 实时通知
9. 每 60 分钟循环
```

---

## 💡 技术栈

- **框架：** Hermes Agent（自主学习 + 多消息平台）
- **语言：** Python 3.13
- **交易：** [py_clob_client](https://github.com/polymarket/py-clob-client) — Polymarket CLOB
- **天气：** ECMWF OpenMETAR / Open-Meteo API
- **链：** Polygon（Chain ID 137）— USDC.e 稳定币
- **通知：** Telegram Bot API
- **学习：** 纯 Python JSON 持久化（零依赖数据库）

---

## ⚠️ 免责声明

本机器人使用真实资金交易真实市场。过去表现不代表未来结果。风险自担。本项目仅供教育和研究目的。

---

*Built with 🐍 + Hermes Agent on Polygon — Autonomous Weather Prediction Trading.*
