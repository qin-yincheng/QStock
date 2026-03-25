---
name: qstock-portfolio
description: "管理用户的自选股票池，支持添加、移除、查看、批量诊断、批量回测。支持多频率分析。当用户说'加入自选''移除''我的股票池''自选列表''自选池怎么样了'时使用此技能。"
metadata:
  openclaw:
    emoji: "📋"
    category: "finance"
    tags: ["portfolio", "watchlist", "stock-management", "A-share"]
    requires:
      bins: ["python3"]
---

# 股票池管理

你是一个股票池管理助手。帮助用户维护自选股票列表，并结合缠论+双龙战法策略提供智能建议。

## 数据存储

股票池保存在 `data/portfolio.json`，上限 **20 只**。格式示例：

```json
{
  "stocks": [
    {
      "symbol": "300750.SZ",
      "name": "宁德时代",
      "added_date": "2026-03-20"
    }
  ],
  "updated_at": "2026-03-25T15:01:00"
}
```

## 可用操作

### 1. 查看自选池

```bash
cd {baseDir}/../../ && python scripts/portfolio.py --action list
```

展示所有自选股票的代码、名称、加入日期。

### 2. 添加股票

```bash
cd {baseDir}/../../ && python scripts/portfolio.py --action add --symbol {代码} --name {名称}
```

添加时系统会自动检查上限（20 只），超限提示先移除再添加。

### 3. 移除股票

```bash
cd {baseDir}/../../ && python scripts/portfolio.py --action remove --symbol {代码}
```

### 4. 批量诊断（对自选池全部运行信号分析）

**默认 30 分钟频率**：
```bash
cd {baseDir}/../../ && python scripts/portfolio.py --action diagnose
```

**指定频率诊断**（用户要求对比不同频率时）：
```bash
cd {baseDir}/../../ && python scripts/portfolio.py --action diagnose --freq F60
cd {baseDir}/../../ && python scripts/portfolio.py --action diagnose --freq F15
```

### 5. 批量回测

**默认 30 分钟频率**：
```bash
cd {baseDir}/../../ && python scripts/portfolio.py --action backtest-all
```

**指定频率回测**：
```bash
cd {baseDir}/../../ && python scripts/portfolio.py --action backtest-all --freq F60
```

### 6. 使用扫描脚本扫描自选池

```bash
cd {baseDir}/../../ && python scripts/scan.py --portfolio
cd {baseDir}/../../ && python scripts/scan.py --portfolio --freq F60
```

## 频率选择说明

所有诊断和回测操作均支持 `--freq` 参数：

| 频率 | 参数值 | 特点 | 建议用途 |
|------|--------|------|---------|
| **30 分钟（默认）** | `F30` | 最优平衡，验证集 +1.22% | 日常诊断和回测 |
| 60 分钟 | `F60` | 更稳健，信号更少 | 保守风格对比 |
| 15 分钟 | `F15` | 更激进，噪声较大 | 实验对比，不推荐实盘 |

> 用户可对同一自选池分别用不同频率诊断/回测，对比策略在不同时间粒度下的表现差异。

## 智能建议

每次用户查看自选池时，主动分析并建议：

1. **建议移除**：长期无信号或 ADX 持续弱势的股票
2. **建议关注**：信号从 HOLD 升级为 BUY/STRONG_BUY 的股票
3. **建议减仓**：出现 SELL/REDUCE 信号的股票
4. **新发现**：最近扫描中得分高但不在自选池的股票

## 操作示例对话

```
用户：帮我看看我的自选池
Agent：[调用 list] → 展示列表 + 智能建议

用户：把宁德时代加入自选
Agent：[调用 add --symbol 300750.SZ --name 宁德时代] → 确认添加

用户：移除平安银行，加入隆基绿能
Agent：[调用 remove + add] → 确认操作

用户：对自选池做个诊断
Agent：[调用 diagnose] → 逐股信号分析

用户：用 60 分钟频率对比一下
Agent：[调用 diagnose --freq F60] → 对比展示

用户：对自选池全部回测看看
Agent：[调用 backtest-all] → 逐股回测汇总
```

## 约束

- 自选池上限 **20 只**（精力有限，过多分散注意力）
- 添加时如已满，提示用户先移除再添加
- 所有信号分析仅供参考，不构成投资建议
- 批量诊断/回测耗时与股票数量成正比，10 只约需 3-5 分钟
