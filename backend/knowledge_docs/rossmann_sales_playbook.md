# 商店销售知识库

本知识库用于 RAG 检索，可随时替换或追加行业文档。

## Rossmann 门店销量

Rossmann 是欧洲连锁药店/日化零售品牌。Kaggle 公开赛题提供：

- `train.csv`：门店 × 日期 的销量事实表（Sales、Customers、Promo、节假日）
- `store.csv`：门店维度（类型、品类、竞品距离、Promo2）
- 关联键：`Store`

## 业务要点

- 零销量通常对应闭店（Open=0），建模时应过滤或单独处理。
- Promo、StateHoliday、SchoolHoliday 对客流影响显著。
- CompetitionDistance 越小，竞争越激烈，可能压低或分流销量。
- Promo2 是持续促销，PromoInterval 表示促销月份。
- 日期可拆成年、月、日、星期，捕捉季节性与周末效应。
- Customers 与 Sales 高度相关，预测未来销量时通常不能使用（标签泄漏）。

## 建模建议

- 回归指标：RMSE、MAE、R2、MAPE、RMSPE（赛题常用）。
- 树模型（XGBoost / LightGBM / CatBoost）在该赛题上表现最好。
- 可对目标做 log1p 变换缓解长尾。
- 特征重要性应结合运营动作解读，而不是只看分数。
