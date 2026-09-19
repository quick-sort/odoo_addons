# 开发治理规范（文档 / 质量 / 流程）

> 本文是**元规范**：它约束"文档怎么写、质量怎么把关、开发怎么走"。
> 它本身也遵循它定的规则——是仓库里所有 addon 的共同契约。

## 0. 为什么需要这套规范

addon 越来越多，两个风险在上升：

1. **设计意图丢失**：代码写完了，当初"为什么这么做、不做什么"没有留档，
   后来的 agent 要么猜、要么推翻重来。
2. **质量无门禁**：没有验收标准，改完不知道"怎么算通过"。

这套规范把**设计意图文档化**、把**验收标准前置**、把**门禁自动化**。

---

## 1. 文档是唯一事实来源（Single Source of Truth）

**每一条关于"这个 addon 该是什么样"的要求，只能写在一个地方：`<addon>/docs/`。**

任何其他文件（CLAUDE.md、README、代码注释、PR 描述）都只做**指针**，不复制
要求本身。复制会产生两处真相，改了一处漏了另一处，这是历史 `.kiro/` 目录
被删掉的教训之一——当时设计散落在多个 `.md` 里，互相引用、彼此矛盾。

### 每个 addon 必须有的四个文档入口

```
<addon>/
├── README.rst                # 人类入口：是什么、装什么、怎么用（Odoo 兼容）
├── docs/
│   ├── requirements.md       # 业务需求（最偏业务，回答"为什么"）
│   ├── design.md             # 系统架构（回答"怎么做"，不含实现细节）
│   └── acceptance.md         # 验收标准（回答"怎么算通过"，QC 的唯一依据）
└── tests/                    # 测试实现，与 acceptance.md 一一对应
```

### README 必须用 `.rst`（Odoo 兼容）

README 会显示在 Odoo **Apps 页面**上，这是 addon 的对外门面。已核实 Odoo 19
的读取优先级（`odoo/modules/module.py:200`）：

1. manifest 的 `description` 键（若写了，**覆盖** README）
2. `README.rst` → `README.md` → `README.txt` → `README`

因此两条硬规则：

1. **README 用 `README.rst`**（RST 语法，是最高优先级、且 Odoo 官方文档标准）。
2. **manifest 不写 `description` 键**，让 README 成为唯一门面——否则 Apps 页面
   显示的是 description，README 白写，又出现两处真相。README 就是 description。

README 的内容是**面向使用者的功能说明**（这是什么、解决什么问题、怎么装、
依赖什么、怎么配）。它**不是** requirements/design 的副本——那两处是设计
真相，README 只是入口和概览，详细内容链到 `docs/`。

四者关系，从偏业务到偏实现，层层深入：

```
requirements.md ──→ design.md ──→ acceptance.md ──→ tests/
   为什么              怎么做          怎么验          验了没
```

- **requirements.md**：用户/业务视角。要解决什么问题、范围边界、明确**不做**什么。
  不写技术方案。
- **design.md**：技术视角。数据模型、组件/扩展点、关键取舍、被否决的方案与理由。
  **不写具体实现细节**——实现细节在代码里，写在文档里只会和代码脱节。
- **acceptance.md**：把 requirements 拆成**可验证的功能点**，每个功能点给出
  验收标准。这是 QC 的唯一依据，也是写测试用例的输入。
- **tests/**：acceptance.md 里每个功能点，至少有一个对应的测试。

### 实现细节不写进文档

文档写到"设计"为止。字段怎么算、循环怎么优化、边界怎么处理——这些写进代码，
用注释和测试表达。文档描述**意图**，代码描述**行为**，测试**锁定**行为。

---

## 2. 文档必须能让 coding agent 自动读到

要求写进文档只是第一步；**agent 不会主动去翻**，它只自动加载少数几个入口。
所以每个 addon 需要一个自动加载的入口文件：**`CLAUDE.md`**，内容只做两件事：

1. 指向 `docs/` 的三个文档；
2. 列出**不可违背的红线**（一两条，来自 design.md 的"约束"小节）。

机制：Claude Code 自动加载**根 CLAUDE.md**，并在访问某目录时加载**该目录的
`CLAUDE.md`**（若存在）。所以 `<addon>/CLAUDE.md` 是天然的子级入口。

**入口文件是"指针 + 红线"，不是副本。** 它从不超过约 30 行；详细内容一律
链到 `docs/`。

```markdown
# <addon> — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、模型、扩展点、被否决的方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：
1. ...
2. ...
```

---

## 3. 开发流程：需求 → 设计 → 功能点 → 测试用例 → 测试

按顺序推进，**上一步没定，不进入下一步**。

| 步骤 | 产出 | 落点 |
|---|---|---|
| 1. 确定需求 | 业务需求与边界 | `docs/requirements.md` |
| 2. 细化设计 | 架构、模型、扩展点 | `docs/design.md` |
| 3. 拆功能点 | 可验证的功能点清单 | `docs/acceptance.md` |
| 4. 写测试用例 | 每个功能点的验收标准 | `docs/acceptance.md`（用例）+ `tests/`（实现） |
| 5. 测试驱动实现 | 先写测试，再写代码 | `tests/` 先于 `models/`、`components/` |

关键点：**测试用例在写实现之前定义**。acceptance.md 是"合同"，tests/ 是
"合同执行"。代码是为了让测试通过而写，不是写完了补测试。

---

## 4. 质量门禁（QC）：测试通过才能合并

任何改动走 **PR**，只有 QC 通过才能合并进主分支。

QC 用 **Odoo 自身的测试机制**（`--test-enable --test-tags`），并交由
**GitHub Actions** 执行——最终目标是"QC 过了没"由 CI 机械判定，不靠人判断。

QC 的定义：

1. **acceptance.md 里每个功能点都有测试，且全绿**。
   用 `--test-tags /<addon>` 跑对应 addon 的测试（见根 CLAUDE.md 的命令）。
2. **模块能干净装载**：`-u <addon> --stop-after-init` 退出码 0。
3. **XML well-formed**（每个改动的 XML 过 `xml.dom.minidom`）。
4. **测试不联网**：mock 所有外部调用，无 API key 也能跑。

### GitHub Action 的执行策略（暂不实现，先记录约束）

Action **暂不落地**，但执行策略先定清楚，避免将来实现时走样：

- **只跑受影响模块的测试，不全量跑。** 一个 PR 的代码影响范围是有限的，应
  依据**模块依赖关系**判定哪些 addon 的测试要跑：改动 `A`，则 `A` 及其
  **反向依赖**（depends 链上依赖 A 的 addon）的测试都要跑，其余跳过。
- 判定输入是 PR 变更文件清单 → 映射到 addon → 展开依赖闭包。
- 这一步依赖 `__manifest__.py` 的 `depends` 声明准确，是 §1 单源真相的
  直接受益者。

---

## 5. 新 addon 的强制清单

新建一个 addon，以下必须齐备，否则不许提 PR：

- [ ] `README.rst`（入口，Odoo Apps 门面）
- [ ] `docs/requirements.md`
- [ ] `docs/design.md`
- [ ] `docs/acceptance.md`
- [ ] `CLAUDE.md`（指针 + 红线）
- [ ] `tests/`（与 acceptance.md 对应，导入进 `tests/__init__.py`）
- [ ] `__manifest__.py` 含 `external_dependencies`（若有第三方依赖）

---

## 6. 存量 addon 怎么办

当前 62 个目录里 **24 个无 README**、**仅 1 个有 docs/**。一次性补齐成本高。

采取**"碰到就补"**：新 addon 必须满足 §5；存量 addon 在**下次被改动时**
补齐文档（README + docs/ 三件套 + CLAUDE.md + tests/），不为没在动的 addon
堆砌空文档。改一个 addon 的同时把它纳入治理，存量包袱随维护自然收敛。
