---
name: qstock-holding
description: "管理用户的股票持仓信息（买入记录、卖出记录、持仓查看）。当用户说'我买了''买入了''记录持仓''卖出了''清仓了''我的持仓''持仓情况'时使用此技能。"
metadata:
  openclaw:
    emoji: "💰"
    category: "finance"
    tags: ["holding", "position", "portfolio", "trade-record", "A-share"]
    requires:
      bins: ["python3"]
---

# 持仓管理

你是一个股票持仓管理助手。帮助用户记录买入/卖出操作，追踪持仓状态，并在扫描时提供持仓感知的差异化建议。

## 核心概念

- **持仓数据**存储在 `data/portfolio.json` 中，与自选池共用同一文件
- 每只股票可以有 `holding: true/false`、`buy_price`、`shares`、`buy_date` 等字段
- **默认未持仓**：没有 `holding` 字段或 `holding: false` 的股票视为未持仓
- 持仓信息会被扫描系统自动读取，生成差异化建议（已持仓 vs 未持仓）

## 可用操作

### 1. 记录买入（更新持仓）

当用户说"我买了XX"、"买入了XX股XX元"时：

```bash
cd {baseDir}/../../ && python scripts/portfolio.py --action update-holding --symbol {代码} --buy-price {价格} --shares {数量}
```

**参数说明**：
- `--symbol`：股票代码（必填），如 `300750.SZ`
- `--buy-price`：买入价格（必填），如 `195.50`
- `--shares`：买入数量（可选），如 `500`
- `--note`：备注（可选），如 `"缠论二买信号入场"`

**示例**：
```bash
cd {baseDir}/../../ && python scripts/portfolio.py --action update-holding --symbol 300750.SZ --buy-price 195.50 --shares 500
cd {baseDir}/../../ && python scripts/portfolio.py --action update-holding --symbol 002594.SZ --buy-price 302.8 --shares 300 --note "BUY_1信号入场"
```

> 如果股票不在自选池中，会自动添加到自选池。

### 2. 记录卖出（清除持仓）

当用户说"卖了XX"、"清仓了XX"、"卖出XX元"时：

```bash
cd {baseDir}/../../ && python scripts/portfolio.py --action clear-holding --symbol {代码} --sell-price {卖出价格}
```

**参数说明**：
- `--symbol`：股票代码（必填）
- `--sell-price`：卖出价格（可选），提供后会自动计算本次交易盈亏

**示例**：
```bash
cd {baseDir}/../../ && python scripts/portfolio.py --action clear-holding --symbol 300750.SZ --sell-price 210.30
```

### 3. 查看所有持仓

当用户说"我的持仓"、"持仓情况"、"我现在持有什么"时：

```bash
cd {baseDir}/../../ && python scripts/portfolio.py --action holdings
```

### 4. 查看自选池（含持仓标记）

```bash
cd {baseDir}/../../ && python scripts/portfolio.py --action list
```

自选池列表现在会标注每只股票是否持仓、买入价、持股数量。

## 持仓与扫描的联动

当用户扫描时（通过 qstock-scanner 技能），扫描系统会自动读取持仓信息，对每只股票给出差异化建议：

| 持仓状态 | 买入信号 | 卖出信号 | 无信号 |
|---------|---------|---------|-------|
| **未持仓** | 给出买入价+止损价+仓位 | 不操作，等待买点 | 继续观望 |
| **已持仓且浮盈** | 可加仓（如信号更强） | 执行卖出，锁定利润 | 继续持有，关注止盈 |
| **已持仓且浮亏** | 不加仓 | 执行止损，减少损失 | 继续持有，关注止损线 |

## 操作示例对话

```
用户：我今天买了500股宁德时代，195.5元买的
Agent：[调用 update-holding --symbol 300750.SZ --buy-price 195.50 --shares 500]
→ 确认记录买入，提示止损价设在 XXX

用户：宁德时代卖了，210块卖的
Agent：[调用 clear-holding --symbol 300750.SZ --sell-price 210]
→ 确认卖出，显示本次盈亏 +7.4%

用户：我现在持有什么股票
Agent：[调用 holdings]
→ 展示所有持仓列表

用户：比亚迪我买了300股，302.8元
Agent：[调用 update-holding --symbol 002594.SZ --buy-price 302.8 --shares 300]
→ 确认记录

用户：扫描一下我的自选池
Agent：[使用 qstock-scanner 技能，扫描结果会自动显示持仓相关建议]
```

## 信息提取指南

用户表达买入/卖出意图时，需要从对话中提取：

| 信息 | 提取方式 | 必须 |
|------|---------|:---:|
| 股票名称/代码 | 用户直接说，或根据名称推断代码 | ✅ |
| 买入/卖出价格 | 用户说"XX元买的""XX块卖出" | ✅ |
| 数量 | 用户说"XX股""XX手"（1手=100股） | 可选 |
| 操作类型 | "买了""买入" → update-holding；"卖了""清仓" → clear-holding | ✅ |

**股票代码对照（常用）**：

| 名称 | 代码 |
|------|------|
| 贵州茅台 | 600519.SH |
| 宁德时代 | 300750.SZ |
| 比亚迪 | 002594.SZ |
| 招商银行 | 600036.SH |
| 中国平安 | 601318.SH |
| 五粮液 | 000858.SZ |
| 东方财富 | 300059.SZ |
| 长江电力 | 600900.SH |
| 隆基绿能 | 601012.SH |

## 约束

- 持仓数据保存在 `data/portfolio.json`，与自选池共用
- 买入价格必须大于 0
- 清除持仓时如果提供卖出价格，会自动计算并展示盈亏
- 同一只股票重复更新持仓会覆盖之前的记录
- 所有操作仅做记录，不执行实际交易
- A 股 T+1 制度，买入当天不能卖出
