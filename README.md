# CEBS - 社区共享器材预约与归还系统

Community Equipment Booking System，一个基于 Django 的社区共享器材预约与归还系统。

## 项目简介

CEBS 是一个功能完善的社区器材预约管理系统，支持器材浏览、在线预约、审批管理、库存追踪、损坏上报等全流程管理。系统采用 Django 框架开发，使用 SQLite 数据库，界面简洁易用。

## 技术栈

- **后端框架**: Django 6.0.6
- **数据库**: SQLite3
- **前端模板**: Django Templates + Bootstrap
- **交互增强**: HTMX
- **语言**: Python 3.x

## 主要功能

### 用户功能
- 用户登录/登出
- 浏览器材列表和详情
- 器材预约（按时段）
- 我的预约记录
- 预约取消
- 损坏上报

### 管理员功能
- 管理后台仪表盘
- 预约审批（批准/拒绝）
- 器材领取登记
- 器材归还登记
- 损坏记录处理
- 库存流水查看
- 审计日志查看
- CSV 数据导出

## 数据模型

- **Equipment (器材)**: 器材名称、描述、库存、状态、分类等
- **Reservation (预约)**: 用户预约记录，支持多种状态流转
- **DamageRecord (损坏记录)**: 器材损坏上报及处理记录
- **StockFlow (库存流水)**: 库存变动明细记录
- **AuditLog (审计日志)**: 系统操作审计记录

## 项目结构

```
cebs/
├── cebs/                    # 项目配置目录
│   ├── __init__.py
│   ├── settings.py          # Django 配置
│   ├── urls.py              # 主路由
│   ├── asgi.py
│   └── wsgi.py
├── equipment/               # 器材管理应用
│   ├── management/          # 自定义管理命令
│   │   └── commands/
│   │       └── initdata.py  # 初始化数据命令
│   ├── migrations/          # 数据库迁移文件
│   ├── templates/           # 模板文件
│   │   └── equipment/
│   │       ├── partials/    # HTMX 部分模板
│   │       ├── base.html
│   │       ├── home.html
│   │       ├── login.html
│   │       ├── equipment_list.html
│   │       ├── equipment_detail.html
│   │       ├── reservation_list.html
│   │       ├── admin_dashboard.html
│   │       └── ...
│   ├── __init__.py
│   ├── admin.py             # 后台管理配置
│   ├── apps.py
│   ├── models.py            # 数据模型
│   ├── services.py          # 业务逻辑层
│   ├── tests.py             # 测试文件
│   ├── urls.py              # 应用路由
│   └── views.py             # 视图函数
├── manage.py                # Django 管理脚本
└── db.sqlite3               # SQLite 数据库文件
```

## 快速开始

### 环境要求

- Python 3.8+
- pip

### 安装步骤

1. **克隆项目**

```bash
git clone <repository-url>
cd cebs
```

2. **创建虚拟环境（推荐）**

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

3. **安装依赖**

```bash
pip install django
```

4. **执行数据库迁移**

```bash
python manage.py migrate
```

5. **创建超级管理员**

```bash
python manage.py createsuperuser
```

6. **初始化测试数据（可选）**

```bash
python manage.py initdata
```

7. **运行开发服务器**

```bash
python manage.py runserver
```

8. **访问系统**

- 前台地址: http://127.0.0.1:8000/
- 后台管理: http://127.0.0.1:8000/admin/

## 路由说明

| 路径 | 说明 | 权限 |
|------|------|------|
| `/login/` | 用户登录 | 公开 |
| `/logout/` | 用户登出 | 登录用户 |
| `/` | 首页 | 登录用户 |
| `/equipments/` | 器材列表 | 登录用户 |
| `/equipment/<id>/` | 器材详情 | 登录用户 |
| `/equipment/<id>/reserve/` | 预约器材 | 登录用户 |
| `/reservations/` | 我的预约 | 登录用户 |
| `/reservation/<id>/cancel/` | 取消预约 | 登录用户 |
| `/management/` | 管理后台 | 管理员 |
| `/damages/` | 损坏记录 | 管理员 |
| `/stock-flows/` | 库存流水 | 管理员 |
| `/audit-logs/` | 审计日志 | 管理员 |

## 开发说明

### 业务逻辑层

所有核心业务逻辑封装在 `equipment/services.py` 中，包括：

- 预约创建、取消、审批、领取、归还
- 库存管理
- 损坏上报与处理
- 审计日志记录
- 逾期检测

### 模板系统

模板采用继承式设计，`base.html` 为基础模板，其他模板继承自它。
部分页面使用 HTMX 实现无刷新交互，相关模板位于 `partials/` 目录下。

### 管理命令

- `python manage.py initdata`: 初始化测试数据

## 测试

项目包含测试文件：

- `test_view.py`: 视图测试
- `test_services.py`: 服务层测试
- `test_htmx_view.py`: HTMX 视图测试
- `test_full.py`: 综合测试

运行测试：

```bash
python manage.py test equipment
```

## 注意事项

1. 本项目使用 SQLite 数据库，适合开发和小规模部署
2. 默认设置中 `DEBUG=True`，生产环境请务必关闭
3. `SECRET_KEY` 请在生产环境中更换为安全的随机字符串
4. 生产环境建议使用 PostgreSQL 或 MySQL 数据库

## 许可证

MIT License
