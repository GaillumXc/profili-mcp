# profili-mcp

**MCP server for the legacy [Profili 2.x](https://www.profili2.com/) airfoil software** — control the database, the solver, and the app from any MCP-compatible AI agent.

[English abstract](#english-abstract) below.

Profili 是 1995–2015 年间的经典翼型设计软件（内置 2200+ 翼型库、126 万条极曲线数据），作者已将其退役并停止了下载。它没有 COM/OLE 自动化接口，也没有官方 MCP。本项目通过逆向其数据与计算架构，把三条真实存在的通道封装成 14 个 MCP 工具：

```
┌─────────────┐   MCP (stdio)   ┌──────────────────────────────────────┐
│  AI Agent   │ ◄──────────────► │            profili-mcp               │
│ (Kimi Code, │                  │                                      │
│  Cursor…)   │                  │  ┌─ db.py ── 32-bit PowerShell/ODBC ──┼─► Profili.mdb (Jet)
└─────────────┘                  │  ├─ xfoil.py ── Xfoil.exe batch ─────┼─► 极曲线/Cp/改型
                                 │  └─ config.py ── 进程/路径管理 ──────┼─► Profili.exe GUI
                                 └──────────────────────────────────────┘
```

## 功能（14 个工具）

| 工具 | 说明 |
|---|---|
| `get_status` | 探测安装：路径、数据库行数、GUI 是否在运行 |
| `launch_profili` / `close_profili` | 启动 / 关闭 Profili GUI |
| `list_libraries` | 列出翼型库 |
| `search_airfoils` | 按名称（SQL LIKE）/厚度/弯度/库筛选 2200+ 翼型 |
| `get_airfoil_geometry` | 读取翼型元数据 + 上下表面坐标（弦长分数，前缘→后缘） |
| `export_airfoil_dat` | 导出 Profili 格式 `.dat` 坐标文件 |
| `import_airfoil_dat` | 导入 `.dat` 进翼型库（自动备份） |
| `list_polars` | 列出某翼型已有极曲线的雷诺数 |
| `get_polar` | 读取极曲线（攻角-CL/CD/CM，自动换算存储缩放） |
| `find_airfoils_by_polar` | 按气动性能选翼型（某雷诺数、某攻角下的 CL/CD/升阻比门槛） |
| `analyze_airfoil` | 用 Profili 捆绑的 XFOIL 现算极曲线（同 Profili 内部配方），可写回数据库让 GUI 显示 |
| `analyze_naca` | 直接对任意 NACA 4/5 位数翼型算极曲线（不动数据库） |
| `redesign_airfoil` | XFOIL GDES TSET 修改最大厚度/弯度（Profili 的"修改翼型"同款配方），可另存为新翼型 |

## 安装与配置

要求：Windows + 已安装的 Profili 2.x（`Profili.exe` + `Profili.mdb` + `Xfoil.exe` 同目录）。系统需有 32 位 `Microsoft Access Driver (*.mdb)` ODBC 驱动——Win10/11 通常自带；缺失时安装 [MDAC](https://www.microsoft.com/en-us/download/details.aspx?id=5793) 或 Access Database Engine。

```bash
git clone https://github.com/cjl123bili/profili-mcp.git
cd profili-mcp
uv sync                      # 或 pip install .

# 告诉 server Profili 装在哪（也可用工具参数 install_dir 或自动发现）
set PROFILI_DIR=D:\path\to\ProfiliV2

# 全链路自检：数据库 + 数值约定 + XFOIL
python -m profili_mcp --selftest
```

### 接入 MCP 客户端

**Kimi Code**（`mcp` 配置）：

```json
{
  "mcpServers": {
    "profili": {
      "command": "python",
      "args": ["-m", "profili_mcp"],
      "env": { "PROFILI_DIR": "D:\\path\\to\\ProfiliV2" }
    }
  }
}
```

**Claude Desktop / Cursor**：在各自的 MCP 配置中加入同样的 `mcpServers` 条目即可。

## 安全设计

- 所有写数据库的操作（导入翼型、写回极曲线）**默认先自动备份** `Profili.mdb`（时间戳后缀），可用 `backup=False` 关闭。
- Jet 支持共享访问：**Profili 运行时也能读写**，但 GUI 不会自动刷新，写入后建议重启 Profili 再看。
- 极曲线写入遵循与 Profili 自带库导入完全相同的表结构（`PolariHeader` + `PolariCoordinate`）。

## 已破解的存储约定（详见 [docs/SCHEMA.md](docs/SCHEMA.md)）

逆向 + 实测验证的 Profili.mdb 数值编码：

- 攻角库存值 =（真实攻角 + 10）× 10（即 `alpha = raw/10 − 10`）
- CL/CD/CM 库存值 = 真实值 × 10000；Re 库存值 = Re ÷ 1000
- 坐标存百分比弦长；`FlagSopraSotto` 0=上表面、1=下表面
- 验证依据：库中 NACA 2412 @ Re=400k, α=0° 存为 CL=0.2232、CM=−0.0493，与教科书精确吻合

## 实战示例

[examples/](examples/) 目录是用本库完成的真实案例分析（NACA 2412 @ Re=3×10⁵ 极曲线，
含特征参数提取与出图）：`python examples/analysis_compute.py && python examples/analysis_naca2412.py`。
结果与 Profili 自带库存极曲线及 Abbott 经典文献值吻合，见 [examples/README.md](examples/README.md)。

## 已知坑

- **非 ASCII 安装路径 + editable 安装**：CPython 的 `site.py` 用系统 locale（GBK）读 `.pth` 文件，项目路径含中文时 editable 安装会起不来。规避：clone 到纯英文路径，或用 `PYTHONPATH=src python -m profili_mcp` 直接跑。
- 本仓库不附带 Profili 本体（商业软件，已退役），仅与其已安装的副本交互。

## 免责声明

本项目仅用于个人学习与研究。Profili 是 devCAD/Stefano Nardone 的软件，权利归原作者所有；XFOIL 由 Mark Drela 开发并随 Profili 捆绑分发。请勿将本项目用于商业用途。

## 贡献者

- **cjl123bili** — 项目发起人：需求定义、实机验证与测试环境
- **Kimi K2.8**（Moonshot AI 编程助手）— 逆向分析、核心代码、文档与实战示例的主要共同开发者

> 本仓库的提交遵循 [Co-authored-by](https://docs.github.com/pull-requests/committing-changes-to-your-project/creating-and-editing-commits/creating-a-commit-with-multiple-authors) 惯例署名 AI 协作者。

## License

MIT（见 [LICENSE](LICENSE)）。

---

## English abstract

Profili 2.x is a retired airfoil design tool (2200+ airfoil library, 1.26M polar data points) with no automation API. This MCP server reverse-engineers its three real control surfaces — the Jet database (`Profili.mdb`), the bundled `Xfoil.exe` batch engine (using Profili's own script recipes), and the GUI process — and exposes them as 14 MCP tools for AI agents: library search, geometry/polar read-write, NACA analysis, and thickness/camber redesign. All storage scale conventions (alpha offset, CL/Re scaling) were empirically validated against textbook NACA 2412 values. Requires Windows + a Profili installation. MIT licensed.
