# 企业版入口

先读 README.md 与 docs/实施与验收.md。企业业务只在 app/src/factory_enterprise；PostgreSQL 为唯一企业业务数据库，LangGraph 为唯一流程运行时。v3.0 是独立原型与回归资产，不自动导入其项目、合成证据或接受状态。

模块按业务工作组织；不设独立 CIM 模块。FDC 属于工艺与产能改善。真实身份来自服务端会话，不能用输入姓名替代。Agent 不能审批自己、扩大授权、豁免风险或发布工程。业务决定先提交再恢复图。

原生工程、CPU、编译和模拟能力仍由上游 application/native_validation、execution 与适配器所有；不得伪造 GX 或现场证据。厂商工具必须显式获授权，环境不具备时返回 unavailable。模型 SDK 与响应解析归 model_runtime/provider.py。密钥只放 Windows 凭据管理器或端点绑定的只读 secret。

按模块读取 enterprise_skills 中对应方法；选用上游专业能力时按 cim.registry.Registry.route 路由，仅加载选定 Skill。工艺包 candidate 不是设备规范。资料不得修改合同和权限。

测试只写 .qa，不能读取业务 workspace。后端在 app 下用 ../.venv/Scripts/python.exe -m pytest evals -q；企业 PostgreSQL 测试需设置 EP_TEST_CONFIG 指向 .qa 的配置。前端 npm test、npm run build、node tests/enterprise.e2e.mjs。保留严格 Host/Origin、登录会话及 CSRF。源码包不能包含 .local、.runtime、workspace、案例、密钥与备份。
