# Architecture — Job Workflow OSS

> 目标：一个可复用的 LinkedIn 自动求职工具。纯 CLI + Discord 通知，部署在 Mac mini。

---

## 1. 设计原则

- **Config over code** — 用户只需编辑 config 文件，不碰 Python
- **单用户 CLI，多用户通过多份 config** — 不搞复杂的 DB/auth
- **可测试** — 每个模块可以独立运行和测试
- **Fail loudly** — 错误要明确，不默默吞掉
- **Idempotent** — 重跑不会重复处理已见过的 job

---

## 2. 目录结构

```
job-workflow-oss/
├── README.md                   # 用户文档（安装、配置、使用）
├── ARCHITECTURE.md             # 本文件
├── pyproject.toml              # 依赖管理（替代 requirements.txt）
├── .env.example                # 环境变量模板
├── .gitignore
│
├── config/
│   ├── default.yaml            # 默认搜索配置（keywords, targets, locations）
│   └── profiles/
│       ├── example.yaml        # 示例用户 profile
│       ├── zihan.yaml          # Zihan 的 profile
│       └── lisa.yaml           # Lisa 的 profile
│
├── resumes/
│   ├── zihan/
│   │   ├── base.html           # 基础简历
│   │   └── base_ai.html        # AI 方向简历（可选）
│   └── lisa/
│       └── base.html
│
├── src/
│   ├── __init__.py
│   ├── cli.py                  # CLI 入口（click/typer）
│   ├── config.py               # 配置加载 & 校验
│   ├── scraper.py              # LinkedIn 抓取
│   ├── tailor.py               # 简历 tailor（Claude）
│   ├── cover_letter.py         # Cover letter 生成
│   ├── pdf.py                  # HTML → PDF
│   ├── notifier.py             # Discord webhook 通知
│   └── pipeline.py             # 编排层（串联上面所有模块）
│
├── data/
│   └── {profile}/
│       ├── seen_jobs.json      # 已见过的 job IDs
│       └── runs/
│           └── 2026-02-21.json # 每次 run 的结果记录
│
├── output/
│   └── {profile}/
│       └── 2026-02-21/
│           └── {Company}/
│               ├── resume.html
│               ├── resume.pdf
│               ├── cover_letter.txt
│               └── why_company.txt
│
├── tests/
│   ├── test_config.py
│   ├── test_scraper.py
│   ├── test_tailor.py
│   ├── test_pipeline.py
│   └── fixtures/               # 测试用假数据
│       ├── sample_job.json
│       └── sample_resume.html
│
└── scripts/
    └── setup.sh                # 一键安装脚本（playwright install 等）
```

---

## 3. 配置系统

### 3.1 用户 Profile（`config/profiles/{name}.yaml`）

```yaml
# config/profiles/zihan.yaml
name: "Zihan Wang"
email: "zihan.b.wang@gmail.com"
linkedin: "linkedin.com/in/yourhandle"
resume_prefix: "Zihan Wang-Resume"

# 简历路径（相对于项目根目录）
resumes:
  default: "resumes/zihan/base.html"
  ai: "resumes/zihan/base_ai.html"      # 可选，AI 岗位用

# 搜索配置（覆盖 default.yaml 的对应字段）
search:
  categories:
    sde:
      keywords: ["Software Engineer", "Full Stack Engineer"]
      experience_levels: [2]
      target_count: 10
    ai:
      keywords: ["AI Engineer", "ML Engineer"]
      experience_levels: [2, 3]
      target_count: 5

# 通知
notify:
  discord_webhook: "https://discord.com/api/webhooks/xxx/yyy"
```

### 3.2 全局默认（`config/default.yaml`）

```yaml
# config/default.yaml
locations: ["San Francisco, CA", "Remote"]
sort_by: "DD"
max_days_old: 0
max_candidates: 60
job_workers: 4

categories:
  sde:
    keywords: ["Software Engineer", "Full Stack Engineer"]
    experience_levels: [2]
    target_count: 10
  ai:
    keywords: ["AI Engineer", "ML Engineer"]
    experience_levels: [2, 3]
    target_count: 5
```

### 3.3 合并逻辑

```
最终配置 = default.yaml ← profile.yaml（profile 覆盖 default）
```

---

## 4. CLI 设计

```bash
# 基本用法
jobflow run --profile zihan          # 完整流程：scrape → tailor → PDF → notify
jobflow search --profile zihan       # 只搜索，不 tailor
jobflow status --profile zihan       # 查看今天的结果
jobflow reset --profile zihan        # 清空 seen_jobs

# 调试/开发
jobflow run-one --profile zihan --job-url "https://linkedin.com/jobs/view/123"
jobflow tailor --profile zihan --job-file fixtures/sample_job.json

# 配置
jobflow config --profile zihan       # 打印当前生效的配置
jobflow profiles                     # 列出所有 profile
```

**实现用 `click` 或 `typer`**（推荐 typer，类型提示自动生成 help）。

---

## 5. 模块职责

### `config.py` — 配置加载

```python
@dataclass
class Profile:
    name: str
    email: str
    resume_prefix: str
    resumes: dict[str, Path]
    search: SearchConfig
    notify: NotifyConfig

def load_profile(profile_name: str) -> Profile:
    """加载 default.yaml + profiles/{name}.yaml，校验，返回 Profile"""
```

### `scraper.py` — LinkedIn 抓取

```python
def scrape_jobs(config: SearchConfig, seen: set[str]) -> list[Job]:
    """返回新 job 列表，不修改 seen（调用方负责持久化）"""
```

### `tailor.py` — 简历定制

```python
def tailor_resume(job: Job, base_html: Path, output_dir: Path) -> Path | None:
    """返回生成的 HTML 路径，失败返回 None"""
```

### `cover_letter.py` — Cover Letter

```python
def generate_cover_letter(job: Job, profile: Profile, output_dir: Path) -> CoverLetterResult:
    """返回 dataclass(cover_letter_path, why_company_path)"""
```

### `pdf.py` — PDF 生成

```python
def html_to_pdf(html_path: Path, output_name: str) -> Path | None:
    """HTML → PDF，返回路径"""
```

### `notifier.py` — Discord 通知

```python
def send_report(results: list[JobResult], webhook_url: str) -> None:
    """发送格式化报告到 Discord webhook"""

def send_progress(message: str, webhook_url: str) -> None:
    """发送进度消息"""
```

### `pipeline.py` — 编排层

```python
def run_pipeline(profile: Profile) -> PipelineResult:
    """
    1. load seen_jobs
    2. scrape
    3. parallel process (tailor + cover letter + PDF)
    4. save seen_jobs + run record
    5. notify
    返回 PipelineResult（summary + per-job results）
    """
```

---

## 6. 数据模型

```python
@dataclass
class Job:
    job_id: str
    title: str
    company: str
    location: str
    url: str
    description: str
    keyword: str           # 搜索时用的关键词
    category: str          # "sde" | "ai"
    posted_date: str
    days_old: int

@dataclass
class JobResult:
    job: Job
    html_path: Path | None
    pdf_path: Path | None
    cover_letter_path: Path | None
    why_company_path: Path | None
    success: bool
    error: str | None      # 失败原因

@dataclass
class PipelineResult:
    profile: str
    date: str
    total: int
    succeeded: int
    failed: int
    elapsed_seconds: int
    jobs: list[JobResult]
```

---

## 7. 实时 Console 输出（核心体验）

运行时用户要能**实时看到每一步在干什么**，不是等 5 分钟后突然吐一堆结果。

### 搜索阶段（scraper）

```
📡 Scraping LinkedIn...

  🔍 [1/4] "Software Engineer" × "San Francisco, CA"
     Page 1: 12 jobs found, 8 new
     Page 2: 10 jobs found, 3 new
     ✅ 11 new jobs from this search

  🔍 [2/4] "Software Engineer" × "Remote"
     Page 1: 15 jobs found, 6 new
     ✅ 6 new jobs from this search

  🔍 [3/4] "AI Engineer" × "San Francisco, CA"
     Page 1: 8 jobs found, 5 new
     ✅ 5 new jobs from this search

  🔍 [4/4] "AI Engineer" × "Remote"
     Page 1: 6 jobs found, 2 new
     ✅ 2 new jobs from this search

📋 Total: 24 new jobs found
   SDE: 17 (need 10) ✅
   AI:   7 (need 5)  ✅
   Selected: 15 jobs for tailoring
```

### Tailoring 阶段（pipeline）

```
⚙️  Tailoring 15 jobs (4 workers)...

  [1/15]  ▶ Software Engineer @ Stripe
          📝 Tailoring resume...
          ✉️  Generating cover letter...
          📄 Generating PDF...
          ✅ Done (12.3s)

  [2/15]  ▶ AI Engineer @ OpenAI
          📝 Tailoring resume...
          ✉️  Generating cover letter...
          ❌ PDF failed: wkhtmltopdf timeout
          ⚠️  HTML saved, PDF skipped

  [3/15]  ▶ Full Stack Engineer @ DoorDash
          ...
```

### 完成

```
✅ Done in 8m 32s

   ✅ 13/15 jobs ready (2 failed)
   📁 Output: output/zihan/2026-02-21/
   📨 Discord report sent

   Failed:
     ❌ AI Engineer @ OpenAI — PDF generation timeout
     ❌ SWE @ Notion — Claude API rate limit
```

### 实现方式

- 用 `rich` 库做格式化输出（进度条、颜色、表格）
- 或者纯 `print` + emoji（更轻量，无额外依赖）
- 每个模块函数接受一个可选的 `on_progress: Callable` 回调
- pipeline 层把回调接到 console printer 或 Discord notifier

```python
# scraper.py
def scrape_jobs(
    config: SearchConfig,
    seen: set[str],
    on_progress: Callable[[str], None] | None = None,
) -> list[Job]:
    def log(msg): 
        if on_progress: on_progress(msg)
    
    log(f"🔍 [{i}/{total}] \"{keyword}\" × \"{location}\"")
    # ... scrape ...
    log(f"   Page {page}: {count} jobs found, {new_count} new")
```

```python
# cli.py
def run(profile: str):
    cfg = load_profile(profile)
    
    # Console 直接打印
    def console_log(msg: str):
        print(msg)
    
    result = run_pipeline(cfg, on_progress=console_log)
```

---

## 8. 错误处理策略（原 §7）

| 场景 | 处理 |
|------|------|
| Playwright 超时 | 重试 1 次，仍失败则 skip 该 job，记录 error |
| Claude API 失败 | 重试 2 次（指数退避），仍失败记录 error |
| PDF 生成失败 | 记录 error，HTML 仍然保留 |
| 全部 job 失败 | 仍然发 Discord 报告（标注全部失败） |
| Config 缺失/格式错 | CLI 阶段直接报错退出，不默默跑 |

每次 run 的 error 都写入 `data/{profile}/runs/YYYY-MM-DD.json`。

---

## 9. 测试策略

```
tests/
├── test_config.py       # Profile 加载、合并、校验
├── test_scraper.py      # mock Playwright, 测 parse 逻辑
├── test_tailor.py       # mock Claude CLI, 测 HTML 生成
├── test_cover_letter.py # mock Claude CLI
├── test_pipeline.py     # 集成测试（用 fixtures）
└── fixtures/
    ├── sample_job.json
    ├── sample_resume.html
    └── sample_jd.txt
```

**运行：** `pytest tests/ -v`

---

## 10. Discord Bot 集成（Phase 2）

不在核心代码里。用 OpenClaw 的 agent 调 CLI：

```
用户在 Discord 发 "job run"
  → OpenClaw job-bot 收到
  → 执行 `jobflow run --profile zihan`
  → CLI 自己发 webhook 通知到用户频道
```

Bot 只是触发器，不做业务逻辑。

---

## 11. 实施顺序

### Phase 1：重构基础（代码质量）
1. `config.py` — YAML 配置系统 + Profile dataclass + 校验
2. 数据模型 — Job, JobResult, PipelineResult dataclass
3. `scraper.py` — 从现有代码提取，输入输出明确
4. `tailor.py` — 同上
5. `cover_letter.py` — 同上
6. `pdf.py` — 同上
7. `notifier.py` — 支持 per-profile webhook
8. `pipeline.py` — 编排层
9. `cli.py` — typer CLI
10. 测试

### Phase 2：多用户 + 自动化
1. Lisa 的 profile 配置
2. cron job 设置
3. OpenClaw skill（极简版，只调 CLI）

### Phase 3：增强
1. 搜索结果预览（scrape only → 用户确认 → 再 tailor）
2. run 历史查询
3. 更好的错误恢复（断点续跑）

---

## 12. 不做什么

- ❌ 不搞 DB（YAML + JSON 够用）
- ❌ 不搞 Web UI（CLI + Discord 够用）
- ❌ 不搞用户注册/auth（本地部署，profile 文件即用户）
- ❌ 不搞微服务（单进程 Python 脚本）
