# Profili.mdb 逆向笔记（SCHEMA.md)

逆向对象为 Profili 2.21（MFC 程序，DAO/ODBC 访问 Jet 4.0 数据库）。
所有结论均经过实测验证（见文末验证记录）。

## 表结构

| 表 | 作用 | 实测行数 |
|---|---|---|
| `Profili` | 翼型主表 | 2202 |
| `Coordinate` | 翼型坐标 | 147,026 |
| `PolariHeader` | 极曲线头（翼型 × Re） | 44,040 |
| `PolariCoordinate` | 极曲线数据点 | 1,258,204 |
| `Librerie` | 翼型库 | 2 |
| `Variabili` | 变量表 | — |

### `Profili` 列

| 列 | 类型/含义 |
|---|---|
| `Id` | 主键（Counter） |
| `Nome` | 翼型名（如 `NACA 2412`、`AG 16`） |
| `Note` | 备注 |
| `MaxWidth` | 最大厚度，**百分比**（如 7.114） |
| `MaxWidthSuCorda` | 最大厚度的弦向位置，**百分比**（如 23.25） |
| `MaxCamber` | 最大弯度，**百分比** |
| `MaxCamberSuCorda` | 最大弯度的弦向位置，**百分比** |
| `CodiceLibreria` | 所属库编号（0 = 默认库） |
| `IdInLibreria` | 库内序号 |

### `Coordinate` 列

| 列 | 含义 |
|---|---|
| `Fk_Id_Profilo` | → `Profili.Id` |
| `FlagSopraSotto` | **0 = 上表面，1 = 下表面** |
| `X`, `Y` | 百分比弦长（100 = 后缘） |

### `PolariHeader` / `PolariCoordinate`

`PolariHeader`：`Id`、`Fk_Id_Profilo`、`Re`。
`PolariCoordinate`：`Fk_Id_Polare`、`Alfa`、`CL`、`CD`、`CM`。

## 数值缩放约定（核心）

| 量 | 库存值 | 还原公式 |
|---|---|---|
| 攻角 alfa | `(alpha_deg + 10) × 10` | `alpha = raw/10 − 10` |
| CL / CD / CM | 真实值 × 10000 | `value = raw/10000` |
| Re | 真实 Re ÷ 1000 | `Re = raw × 1000` |
| 坐标 X/Y | 百分比弦长 | `x = raw/100` |

攻角 +10° 偏移的来源不明（可能是历史库的格式约定），但两个独立验证都精确成立（见下）。

## 写库注意事项（实测踩坑）

通过 ODBC 向 Profili.mdb 写入时，Jet 4.0 驱动有以下约束（均已在本项目代码中处理）：

1. **INSERT 语句的列名必须加方括号**（`INSERT INTO [Profili] ([Nome], ...)`)，
   不加会被驱动程序按关键字解析报 42000 语法错误。
2. `Profili.Note` 字段 `AllowZeroLength=False` —— 空备注必须存空格。
3. `(CodiceLibreria, IdInLibreria)` 有唯一性约束：新翼型的 `IdInLibreria`
   必须取该库内 `MAX+1`。
4. `@@IDENTITY` **不跨连接**：必须在同一条连接上紧跟 INSERT 查询，否则拿到
   空值。bridge 的 `exec` 模式因此同时返回 `affected` 和 `identity`。
5. Jet 不支持多行 `VALUES`，也不允许 `FROM (SELECT ... UNION ALL SELECT ...)`
   常量派生表。本项目的做法：bridge 新增 `batch` 模式，把多条单条 INSERT
   放进一次 PowerShell 调用、一个事务里执行（失败整体回滚）。

## 验证记录

- NACA 2412，Re=400k（库存 `Re=400`），α=0° 处库存 `Alfa=100, CL=2232, CM=-493`：
  还原得 CL=0.2232、CM=−0.0493 —— 与 Abbott《Theory of Wing Sections》的
  NACA 2412 标准值一致。
- 对称翼型 12% JOUKOWSKI，Re=30k：α=−7.5°（库存 25）时 CL=−0.7471、
  CM≈0.007 —— 与零升力角≈0°、升力线斜率≈0.1/° 的对称翼型完全吻合。
- AG 16 厚度：库坐标插值计算 7.11%，与 `Profili.MaxWidth=7.114` 一致。

## XFOIL 集成（程序内嵌配方）

Profili 把当前翼型写成 `A.dat`（名字行 + 上表面后缘→前缘 + 下表面前缘→后缘，
坐标为弦长分数），然后用脚本喂给同目录的 `Xfoil.exe`：

`ScriptXFoil.cmd`（极曲线）：
```
LOAD  A.dat
GDES / CADD / (空行×3) / PANE / [FILT 1.00] / PANE
OPER / VPAR / N <ncrit> / VACC <vacc> / (空行) / TYPE 1
VISC <Re> / MACH <mach> / ITER / <iters>
ALFA <init> / INIT / ALFA <init>
PACC / Dati.pol / (空行)
ASEQ <start> <end> <step>
PACC / (空行) / QUIT
```
`ScriptThCa.cmd`（改厚度/弯度）：`GDES / TSET / <thickness%> / <camber%> / HIGH / <x_t%> / <x_c%> / exec / save new.dat`。

极曲线 dump（`Dati.pol`）列：`alpha CL CDi CDv CD CDf CM Top_Xtr Bot_Xtr`。

## 其他通道

- `Profili.INI`：极线 Re 列表、攻角范围、XFoil 参数（NCrit、Mach、迭代数）等全部 UI 状态。
- 文件格式：`.dat`/`.cor` 坐标、`.dxf` 导入导出、`Cp\*.cp` 压力分布。
- COM/OLE：程序注册了 OLE 嵌入但**无类型库、无 IDispatch**，`/RegServer` 后
  无任何 ProgID —— 脚本自动化此路不通（本项目因此走数据库+XFOIL 通道）。
